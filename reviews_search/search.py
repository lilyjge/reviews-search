from __future__ import annotations

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "quackir"
if _VENDOR.exists() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from quackir import SearchType  # noqa: E402
from quackir.search import DuckDBSearcher  # noqa: E402

from reviews_search.config import CORPUS_TABLE
from reviews_search.store.database import ReviewDatabase


def search_reviews(
    db_path: Path,
    query: str,
    top_n: int = 10,
) -> list[dict]:
    searcher = DuckDBSearcher(db_path=str(db_path))
    hits = searcher.search(
        SearchType.SPARSE,
        query_string=query,
        table_names=[CORPUS_TABLE],
        top_n=top_n,
    )
    searcher.close()

    db = ReviewDatabase(db_path)
    results = []
    for review_id, score in hits:
        review = db.get_review(review_id)
        if not review:
            continue
        place_rows = db.conn.execute(
            "SELECT name, address, maps_url, rating FROM places WHERE place_id = ?",
            [review["place_id"]],
        ).fetchone()
        place_info = {}
        if place_rows:
            place_info = {
                "place_name": place_rows[0],
                "place_address": place_rows[1],
                "place_maps_url": place_rows[2],
                "place_rating": place_rows[3],
            }
        results.append(
            {
                "review_id": review_id,
                "score": float(score),
                "review_text": review["text"],
                "review_rating": review["rating"],
                "review_date": review["published_date"],
                "reviewer_name": review["reviewer_name"],
                **place_info,
            }
        )
    db.close()
    return results
