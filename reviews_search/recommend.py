"""Rank places by relevance to a query (e.g. 'ortho k lenses') and summarize matching reviews.

Combines:
  • exact substring matches for query variants (high precision)
  • BM25 scores from QuackIR (recall over the corpus)

The output is intended to answer 'which optometrist should I pick for X?'.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb

from reviews_search.config import REVIEWS_TABLE, PLACES_TABLE
from reviews_search.search import search_reviews


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _expand_variants(query: str) -> list[str]:
    """
    Generate substring variants to catch typos / hyphenation.
    'ortho k lenses' -> ['ortho-k', 'ortho k', 'orthok', 'orthokeratology', 'corneal reshaping', ...]
    Keeps the original tokens as a fallback.
    """
    q = _normalize(query)
    variants = {q}

    tokens = q.split()
    if "ortho" in q or "orthok" in q or "orthokeratology" in q:
        variants.update(
            {
                "ortho-k",
                "ortho k",
                "orthok",
                "orthokeratology",
                "corneal reshaping",
                "overnight lens",
                "overnight lenses",
                "myopia control",
                "myopia management",
                "misight",
            }
        )

    if len(tokens) >= 2:
        for sep in (" ", "-", ""):
            variants.add(sep.join(tokens))

    return sorted({v for v in variants if v})


def _place_match_counts(
    conn: duckdb.DuckDBPyConnection,
    variants: list[str],
) -> dict[str, dict]:
    """For each variant, count per-place hits via LIKE on the lowered review text."""
    by_place: dict[str, dict] = {}
    for v in variants:
        rows = conn.execute(
            f"""
            SELECT r.place_id, COALESCE(p.name, r.place_name) AS name, COUNT(*) cnt
            FROM {REVIEWS_TABLE} r
            LEFT JOIN {PLACES_TABLE} p ON p.place_id = r.place_id
            WHERE lower(r.text) LIKE ?
            GROUP BY r.place_id, COALESCE(p.name, r.place_name)
            """,
            [f"%{v}%"],
        ).fetchall()
        for pid, name, cnt in rows:
            slot = by_place.setdefault(
                pid, {"place_id": pid, "name": name, "variants": {}, "total_hits": 0}
            )
            slot["variants"][v] = cnt
            slot["total_hits"] += cnt
    return by_place


def _quoted_snippet(text: str, variants: list[str], width: int = 220) -> str:
    """Show ±width chars around the first variant match."""
    lower = text.lower()
    hit = -1
    chosen = ""
    for v in variants:
        idx = lower.find(v)
        if idx >= 0 and (hit < 0 or idx < hit):
            hit = idx
            chosen = v
    if hit < 0:
        return text.strip().replace("\n", " ")[: width * 2] + (
            "…" if len(text) > width * 2 else ""
        )
    start = max(0, hit - width)
    end = min(len(text), hit + len(chosen) + width)
    snippet = text[start:end].strip().replace("\n", " ")
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def recommend(
    db_path: Path,
    query: str,
    *,
    top_places: int = 10,
    snippets_per_place: int = 3,
    bm25_top_n: int = 50,
) -> dict:
    """
    Returns:
        {
          "query": str,
          "variants": [str, ...],
          "places": [
            {
              "place_id", "name", "address", "rating", "review_count", "maps_url",
              "exact_hits": int,
              "variant_hits": {variant: count},
              "bm25_top": float,    # best BM25 score among this place's reviews
              "score": float,       # combined ranking score
              "snippets": [
                  {"review_id", "rating", "date", "reviewer", "score", "text"},
                  ...
              ]
            },
            ...
          ]
        }
    """
    conn = duckdb.connect(str(db_path), read_only=True)

    variants = _expand_variants(query)
    exact = _place_match_counts(conn, variants)

    try:
        bm25 = search_reviews(db_path, query, top_n=bm25_top_n)
    except Exception:
        bm25 = []

    bm25_by_place_best: dict[str, float] = {}
    bm25_reviews_by_place: dict[str, list[dict]] = {}
    for hit in bm25:
        pid_row = conn.execute(
            f"SELECT place_id FROM {REVIEWS_TABLE} WHERE review_id = ?",
            [hit["review_id"]],
        ).fetchone()
        if not pid_row:
            continue
        pid = pid_row[0]
        prev = bm25_by_place_best.get(pid, 0.0)
        if hit["score"] > prev:
            bm25_by_place_best[pid] = hit["score"]
        bm25_reviews_by_place.setdefault(pid, []).append(hit)

    all_pids = set(exact.keys()) | set(bm25_by_place_best.keys())
    places: list[dict] = []
    for pid in all_pids:
        meta_row = conn.execute(
            f"""
            SELECT name, address, rating, review_count, maps_url
            FROM {PLACES_TABLE} WHERE place_id = ?
            """,
            [pid],
        ).fetchone()
        name = (meta_row[0] if meta_row else None) or (
            exact.get(pid, {}).get("name") or "?"
        )
        address = meta_row[1] if meta_row else ""
        rating = meta_row[2] if meta_row else None
        review_count = meta_row[3] if meta_row else None
        maps_url = meta_row[4] if meta_row else ""

        ex = exact.get(pid, {"total_hits": 0, "variants": {}})
        bm = bm25_by_place_best.get(pid, 0.0)
        score = ex["total_hits"] * 10.0 + bm

        place_review_hits = bm25_reviews_by_place.get(pid, [])
        place_review_hits.sort(key=lambda h: -h["score"])

        seen_text: set[str] = set()
        snippets: list[dict] = []

        for hit in place_review_hits:
            text = hit["review_text"]
            key = text[:120]
            if key in seen_text:
                continue
            seen_text.add(key)
            snippets.append(
                {
                    "review_id": hit["review_id"],
                    "rating": hit.get("review_rating"),
                    "date": hit.get("review_date"),
                    "reviewer": hit.get("reviewer_name"),
                    "score": hit["score"],
                    "text": text,
                }
            )
            if len(snippets) >= snippets_per_place:
                break

        if len(snippets) < snippets_per_place and ex["total_hits"]:
            rows = conn.execute(
                f"""
                SELECT review_id, rating, published_date, reviewer_name, text
                FROM {REVIEWS_TABLE}
                WHERE place_id = ? AND ({" OR ".join(["lower(text) LIKE ?"] * len(variants))})
                """,
                [pid, *[f"%{v}%" for v in variants]],
            ).fetchall()
            for review_id, r_rating, pub, reviewer, text in rows:
                key = text[:120]
                if key in seen_text:
                    continue
                seen_text.add(key)
                snippets.append(
                    {
                        "review_id": review_id,
                        "rating": r_rating,
                        "date": pub,
                        "reviewer": reviewer,
                        "score": 0.0,
                        "text": text,
                    }
                )
                if len(snippets) >= snippets_per_place:
                    break

        for s in snippets:
            s["snippet"] = _quoted_snippet(s["text"], variants)

        places.append(
            {
                "place_id": pid,
                "name": name,
                "address": address,
                "rating": rating,
                "review_count": review_count,
                "maps_url": maps_url,
                "exact_hits": ex["total_hits"],
                "variant_hits": ex["variants"],
                "bm25_top": bm,
                "score": score,
                "snippets": snippets,
            }
        )

    places.sort(
        key=lambda p: (-p["exact_hits"], -p["bm25_top"], -(p.get("rating") or 0))
    )
    places = places[:top_places]

    conn.close()
    return {"query": query, "variants": variants, "places": places}
