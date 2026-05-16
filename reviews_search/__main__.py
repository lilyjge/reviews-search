from __future__ import annotations

import argparse
import shlex
import subprocess
import sys

from pathlib import Path

from rich.console import Console
from rich.table import Table

from reviews_search.config import Settings
from reviews_search.pipeline import (
    run_gosom_pipeline,
    run_index,
    run_scrape,
    run_search,
)
from reviews_search.store.database import ReviewDatabase

console = Console()


def cmd_scrape(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    stats = run_scrape(
        settings,
        query=args.query,
        location=args.location,
        max_places=args.max_places,
        max_reviews_per_place=args.max_reviews,
        force=args.force,
    )
    console.print(
        f"[green]Done.[/green] Scraped {stats['places_scraped']} places, "
        f"added {stats['reviews_added']} reviews → {settings.db_path}"
    )
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    try:
        stats = run_index(settings)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(
        f"[green]Indexed[/green] {stats['indexed_docs']} documents "
        f"(from {stats['corpus_docs']} reviews) in {settings.db_path}"
    )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    try:
        results = run_search(settings, args.query, top_n=args.top)
    except Exception as exc:
        if "fts_main" in str(exc).lower() or "does not exist" in str(exc).lower():
            console.print("[red]No search index found. Run: python -m reviews_search index[/red]")
            return 1
        raise

    if not results:
        console.print("[yellow]No matching reviews.[/yellow]")
        return 0

    table = Table(title=f'Results for "{args.query}"')
    table.add_column("Score", justify="right", style="cyan")
    table.add_column("Place", style="bold")
    table.add_column("Rating")
    table.add_column("Snippet", max_width=60)

    for row in results:
        snippet = row["review_text"][:200].replace("\n", " ")
        if len(row["review_text"]) > 200:
            snippet += "…"
        table.add_row(
            f"{row['score']:.3f}",
            row.get("place_name") or "?",
            f"{row['review_rating']}/5" if row.get("review_rating") else "—",
            snippet,
        )

    console.print(table)
    console.print("\n[dim]Full details:[/dim]")
    for i, row in enumerate(results, 1):
        console.print(f"\n[bold]{i}. {row.get('place_name', '?')}[/bold] (score {row['score']:.3f})")
        if row.get("place_address"):
            console.print(f"   {row['place_address']}")
        if row.get("place_maps_url"):
            console.print(f"   {row['place_maps_url']}")
        meta = []
        if row.get("review_rating"):
            meta.append(f"{row['review_rating']}/5")
        if row.get("review_date"):
            meta.append(row["review_date"])
        if row.get("reviewer_name"):
            meta.append(row["reviewer_name"])
        if meta:
            console.print(f"   {' · '.join(meta)}")
        console.print(f"   {row['review_text']}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from reviews_search.demo_data import DEMO_PLACES, DEMO_REVIEWS

    settings = Settings.from_env()
    db = ReviewDatabase(settings.db_path)
    for place in DEMO_PLACES:
        db.upsert_place(place)
    count = db.upsert_reviews(DEMO_REVIEWS)
    db.close()
    console.print(f"[green]Loaded demo data:[/green] {len(DEMO_PLACES)} places, {count} reviews")
    return 0


def cmd_scrape_gosom(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if args.queries_file:
        qpath = Path(args.queries_file)
        if not qpath.is_file():
            console.print(f"[red]Not found: {qpath}[/red]")
            return 1
        queries = [ln.strip() for ln in qpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    elif args.search:
        queries = [args.search.strip()]
    elif args.query and args.location:
        queries = [f"{args.query.strip()} in {args.location.strip()}"]
    else:
        console.print(
            "[red]Use --search \"...\", or --query + --location, or --queries-file PATH[/red]"
        )
        return 1

    extra = shlex.split(args.extra_flags) if args.extra_flags else []

    try:
        stats = run_gosom_pipeline(
            settings,
            queries=queries,
            work_dir=Path(args.work_dir) if args.work_dir else None,
            results_filename=args.results_name,
            depth=args.depth,
            lang=args.lang,
            extra_reviews=not args.no_extra_reviews,
            exit_on_inactivity=args.exit_on_inactivity,
            docker_image=args.docker_image,
            pull=args.pull,
            build_index=not args.no_index,
            email=args.email,
            proxies=args.proxies or None,
            geo=args.geo or None,
            zoom=args.zoom,
            radius=args.radius,
            concurrency=args.concurrency,
            grid_bbox=args.grid_bbox or None,
            grid_cell=args.grid_cell,
            fast_mode=args.fast_mode,
            extra_args=extra or None,
            runner=args.runner,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]google-maps-scraper (Docker) exited with code {exc.returncode}[/red]")
        return exc.returncode or 1
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    console.print(
        f"[green]gosom scrape → DuckDB[/green]: {stats['entries']} listings, "
        f"{stats['reviews_upserted']} reviews ({settings.db_path})"
    )
    if stats.get("runner"):
        console.print(f"[dim]Runner:[/dim] {stats['runner']}")
    if stats.get("json_out"):
        console.print(f"[dim]JSON:[/dim] {stats['json_out']}")
    if stats.get("log_file"):
        console.print(f"[dim]Scrape log:[/dim] {stats['log_file']}")
    idx = stats.get("index")
    if idx:
        console.print(
            f"[green]Indexed[/green] {idx['indexed_docs']} documents from corpus."
        )
    elif not args.no_index:
        console.print("[yellow]Skipped index (no reviews in database).[/yellow]")
    return 0


def cmd_import_gosom(args: argparse.Namespace) -> int:
    from pathlib import Path

    from reviews_search.pipeline import run_index
    from reviews_search.scrape.gosom_import import import_gosom_json

    settings = Settings.from_env()
    path = Path(args.json_file)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        return 1
    stats = import_gosom_json(settings.db_path, path)
    console.print(
        f"[green]Imported[/green] {stats['entries']} listings, "
        f"{stats['reviews_upserted']} review rows → {settings.db_path}"
    )
    if args.index:
        try:
            idx = run_index(settings)
            console.print(
                f"[green]Indexed[/green] {idx['indexed_docs']} documents."
            )
        except RuntimeError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
            return 1
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    from reviews_search.recommend import recommend

    settings = Settings.from_env()
    if not settings.db_path.exists():
        console.print(f"[red]No database at {settings.db_path}.[/red] Run scrape-gosom first.")
        return 1

    extra_variants: list[str] = list(args.variant or [])
    for csv in args.variants or []:
        extra_variants.extend(v.strip() for v in csv.split(",") if v.strip())

    result = recommend(
        settings.db_path,
        args.query,
        variants=extra_variants or None,
        top_places=args.top,
        snippets_per_place=args.snippets,
    )
    places = result["places"]
    if not places:
        console.print("[yellow]No matching places.[/yellow]")
        return 0

    console.print(
        f'[bold]Top places for "{args.query}"[/bold] '
        f'(variants: {", ".join(result["variants"])})\n'
    )

    table = Table(show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Place", style="bold")
    table.add_column("Exact hits", justify="right", style="green")
    table.add_column("BM25 top", justify="right")
    table.add_column("Maps rating", justify="right")
    table.add_column("# reviews", justify="right")
    for i, p in enumerate(places, 1):
        rating = f"{p['rating']:.1f}" if p.get("rating") else "—"
        rc = str(p["review_count"]) if p.get("review_count") else "—"
        table.add_row(
            str(i),
            p["name"],
            str(p["exact_hits"]),
            f"{p['bm25_top']:.2f}",
            rating,
            rc,
        )
    console.print(table)

    for i, p in enumerate(places, 1):
        if not p["snippets"]:
            continue
        console.print(f"\n[bold cyan]{i}. {p['name']}[/bold cyan]")
        if p.get("address"):
            console.print(f"   {p['address']}")
        if p.get("maps_url"):
            console.print(f"   [dim]{p['maps_url']}[/dim]")
        if p["variant_hits"]:
            vh = ", ".join(f"{v}×{c}" for v, c in sorted(p["variant_hits"].items(), key=lambda kv: -kv[1]))
            console.print(f"   [green]Mentions:[/green] {vh}")
        for s in p["snippets"]:
            meta = []
            if s.get("rating") is not None:
                meta.append(f"{s['rating']}/5")
            if s.get("date"):
                meta.append(str(s["date"]))
            if s.get("reviewer"):
                meta.append(s["reviewer"])
            if s.get("score"):
                meta.append(f"bm25 {s['score']:.2f}")
            console.print(f"     [dim]· {' · '.join(meta)}[/dim]")
            console.print(f"     {s['snippet']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if not settings.db_path.exists():
        console.print(f"No database at {settings.db_path}")
        return 0
    db = ReviewDatabase(settings.db_path)
    console.print(f"Database: {settings.db_path}")
    console.print(f"  Places:  {db.place_count()}")
    console.print(f"  Reviews: {db.review_count()}")
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps reviews and search them with QuackIR (DuckDB BM25)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrape_p = sub.add_parser(
        "scrape",
        help="[Legacy] Playwright scrape — prefer scrape-gosom",
    )

    scrape_p.add_argument("--query", required=True, help='e.g. "optometrists"')
    scrape_p.add_argument("--location", required=True, help='e.g. "Waterloo, ON"')
    scrape_p.add_argument("--max-places", type=int, default=15)
    scrape_p.add_argument("--max-reviews", type=int, default=50, dest="max_reviews")
    scrape_p.add_argument("--force", action="store_true", help="Re-scrape known places")
    scrape_p.set_defaults(func=cmd_scrape)

    index_p = sub.add_parser("index", help="Build QuackIR BM25 index from scraped reviews")
    index_p.set_defaults(func=cmd_index)

    search_p = sub.add_parser("search", help="Search review text")
    search_p.add_argument("query", help='e.g. "ortho k lenses"')
    search_p.add_argument("--top", type=int, default=10)
    search_p.set_defaults(func=cmd_search)

    demo_p = sub.add_parser("demo", help="Load sample optometrist reviews (no scraping)")
    demo_p.set_defaults(func=cmd_demo)

    sg = sub.add_parser(
        "scrape-gosom",
        help="Run gosom/google-maps-scraper (native binary or Docker), import + index",
    )
    sg.add_argument(
        "--runner",
        choices=["auto", "binary", "docker"],
        default="auto",
        help="auto picks the native binary if installed, else Docker",
    )
    sg.add_argument(
        "--search",
        help='Single Maps query line, e.g. "optometrists in Waterloo, Ontario"',
    )
    sg.add_argument("--query", help="With --location, builds \"{query} in {location}\"")
    sg.add_argument("--location", help="With --query, builds one search line")
    sg.add_argument(
        "--queries-file",
        help="File with one Google Maps search query per line (see gosom SKILL.md)",
    )
    sg.add_argument(
        "--work-dir",
        help="Defaults to <db-dir>/gosom (queries.txt + results JSON written here)",
    )
    sg.add_argument("--results-name", default="results.json", dest="results_name")
    sg.add_argument("--depth", type=int, default=5, help="Scroll depth (1–10 typical)")
    sg.add_argument("--lang", default="en")
    sg.add_argument(
        "--exit-on-inactivity",
        default="8m",
        help="Docker -exit-on-inactivity (e.g. 3m, 8m)",
    )
    sg.add_argument(
        "--no-extra-reviews",
        action="store_true",
        help="Omit -extra-reviews (faster, fewer review texts)",
    )
    sg.add_argument("--no-index", action="store_true", help="Skip QuackIR index rebuild")
    sg.add_argument("--pull", action="store_true", help="docker pull before run")
    sg.add_argument(
        "--docker-image",
        default="gosom/google-maps-scraper",
    )
    sg.add_argument("--email", action="store_true", help="Enable gosom -email")
    sg.add_argument("--proxies", default="", help="gosom -proxies string")
    sg.add_argument("--geo", default="", help='gosom -geo "lat,lng"')
    sg.add_argument("--zoom", type=int, default=None)
    sg.add_argument("--radius", type=int, default=None)
    sg.add_argument("--concurrency", "-c", type=int, default=None, dest="concurrency")
    sg.add_argument("--grid-bbox", default="", help='gosom -grid-bbox "minLat,minLon,maxLat,maxLon"')
    sg.add_argument("--grid-cell", type=float, default=None)
    sg.add_argument("--fast-mode", action="store_true")
    sg.add_argument(
        "--extra-flags",
        "--docker-extra",
        default="",
        dest="extra_flags",
        help='Extra scraper flags (shell-quoted), e.g. \'-c 8\'',
    )
    sg.set_defaults(func=cmd_scrape_gosom)

    gosom_p = sub.add_parser(
        "import-gosom",
        help="Load JSON from gosom/google-maps-scraper (-json output)",
    )
    gosom_p.add_argument("json_file", help="Path to results JSON or JSONL")
    gosom_p.add_argument(
        "--index",
        action="store_true",
        help="Rebuild QuackIR search index after import",
    )
    gosom_p.set_defaults(func=cmd_import_gosom)

    rec_p = sub.add_parser(
        "recommend",
        help="Rank places by query relevance and show supporting review snippets",
    )
    rec_p.add_argument("query", help='e.g. "ortho k lenses"')
    rec_p.add_argument("--top", type=int, default=10, help="Places to show")
    rec_p.add_argument("--snippets", type=int, default=3, help="Snippets per place")
    rec_p.add_argument(
        "--variant",
        action="append",
        default=[],
        help='Additional synonym to match exactly (repeatable). '
        'e.g. --variant orthokeratology --variant "corneal reshaping"',
    )
    rec_p.add_argument(
        "--variants",
        action="append",
        default=[],
        help="Comma-separated synonyms (alternative to repeating --variant).",
    )
    rec_p.set_defaults(func=cmd_recommend)

    status_p = sub.add_parser("status", help="Show scrape statistics")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
