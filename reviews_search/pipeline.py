from __future__ import annotations

from pathlib import Path

from tqdm import tqdm

from reviews_search.config import Settings
from reviews_search.indexer import build_fts_index
from reviews_search.models import Place
from reviews_search.scrape.browser import BrowserScraper
from reviews_search.scrape.gosom_import import import_gosom_json
from reviews_search.scrape.gosom_runner import run_auto
from reviews_search.scrape.places_api import discover_places
from reviews_search.store.database import ReviewDatabase


def run_scrape(
    settings: Settings,
    query: str,
    location: str,
    max_places: int = 20,
    max_reviews_per_place: int = 50,
    force: bool = False,
) -> dict:
    db = ReviewDatabase(settings.db_path)
    existing = db.get_place_ids()

    if settings.google_places_api_key:
        places = discover_places(
            query, location, settings.google_places_api_key, max_results=max_places
        )
    else:
        scraper = BrowserScraper(headless=settings.headless)
        places = scraper.discover_places(query, location, max_places=max_places)

    if not force:
        places = [p for p in places if p.place_id not in existing]

    scraper = BrowserScraper(headless=settings.headless)
    total_reviews = 0

    for place in tqdm(places, desc="Scraping reviews"):
        if not place.maps_url and place.place_id:
            place.maps_url = f"https://www.google.com/maps/place/?q=place_id:{place.place_id}"
        db.upsert_place(place)
        try:
            reviews = scraper.scrape_reviews(
                place,
                max_reviews=max_reviews_per_place,
                location_hint=location,
            )
            total_reviews += db.upsert_reviews(reviews)
        except Exception as exc:
            tqdm.write(f"  skip {place.name}: {exc}")

    places_scraped = len(places)
    db.close()
    return {
        "places_scraped": places_scraped,
        "reviews_added": total_reviews,
    }


def run_gosom_pipeline(
    settings: Settings,
    *,
    queries: list[str],
    work_dir: Path | None = None,
    results_filename: str = "results.json",
    depth: int = 5,
    lang: str = "en",
    extra_reviews: bool = True,
    exit_on_inactivity: str = "8m",
    docker_image: str = "gosom/google-maps-scraper",
    pull: bool = False,
    build_index: bool = True,
    email: bool = False,
    proxies: str | None = None,
    geo: str | None = None,
    zoom: int | None = None,
    radius: int | None = None,
    concurrency: int | None = None,
    grid_bbox: str | None = None,
    grid_cell: float | None = None,
    fast_mode: bool = False,
    extra_args: list[str] | None = None,
    runner: str = "auto",
) -> dict:
    """
    Write queries.txt, run gosom (native binary or Docker), import JSON into DuckDB, FTS index.

    `runner` is one of: "auto" (default), "binary", "docker".
    """
    base = work_dir or (settings.db_path.parent / "gosom")
    base.mkdir(parents=True, exist_ok=True)
    qfile = base / "queries.txt"
    qfile.write_text("\n".join(line.strip() for line in queries if line.strip()) + "\n")
    out_json = base / results_filename
    log_file = base / "scrape.log"

    used = run_auto(
        qfile,
        out_json,
        prefer=runner,
        image=docker_image,
        pull=pull,
        log_file=log_file,
        depth=depth,
        lang=lang,
        extra_reviews=extra_reviews,
        exit_on_inactivity=exit_on_inactivity,
        email=email,
        proxies=proxies,
        geo=geo,
        zoom=zoom,
        radius=radius,
        concurrency=concurrency,
        grid_bbox=grid_bbox,
        grid_cell=grid_cell,
        fast_mode=fast_mode,
        extra_args=extra_args,
    )

    imp = import_gosom_json(settings.db_path, out_json)
    idx: dict | None = None
    if build_index:
        db = ReviewDatabase(settings.db_path)
        nrev = db.review_count()
        db.close()
        if nrev > 0:
            idx = run_index(settings)
    return {
        "queries_file": str(qfile),
        "json_out": str(out_json),
        "log_file": str(log_file),
        "runner": used,
        **imp,
        "index": idx,
    }


def run_index(settings: Settings) -> dict:
    db = ReviewDatabase(settings.db_path)
    corpus_path = settings.db_path.parent / "corpus.jsonl"
    count = db.export_corpus_jsonl(corpus_path)
    db.close()

    if count == 0:
        raise RuntimeError("No reviews in database. Run scrape first.")

    indexed = build_fts_index(settings.db_path, corpus_path)
    return {"corpus_docs": count, "indexed_docs": indexed}


def run_search(settings: Settings, query: str, top_n: int = 10) -> list[dict]:
    from reviews_search.search import search_reviews

    return search_reviews(settings.db_path, query, top_n=top_n)
