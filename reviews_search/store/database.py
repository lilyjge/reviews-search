from __future__ import annotations

import json
from pathlib import Path

import duckdb

from reviews_search.config import CORPUS_TABLE, PLACES_TABLE, REVIEWS_TABLE
from reviews_search.models import Place, Review


class ReviewDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PLACES_TABLE} (
                place_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                address VARCHAR,
                rating DOUBLE,
                review_count INTEGER,
                maps_url VARCHAR,
                category VARCHAR,
                scraped_at VARCHAR
            )
            """
        )
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {REVIEWS_TABLE} (
                review_id VARCHAR PRIMARY KEY,
                place_id VARCHAR,
                place_name VARCHAR,
                text VARCHAR,
                rating INTEGER,
                published_date VARCHAR,
                reviewer_name VARCHAR,
                owner_response VARCHAR,
                scraped_at VARCHAR
            )
            """
        )

    def upsert_place(self, place: Place) -> None:
        row = place.to_dict()
        self.conn.execute(
            f"""
            INSERT OR REPLACE INTO {PLACES_TABLE}
            (place_id, name, address, rating, review_count, maps_url, category, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                row["place_id"],
                row["name"],
                row["address"],
                row["rating"],
                row["review_count"],
                row["maps_url"],
                row["category"],
                row["scraped_at"],
            ],
        )

    def upsert_reviews(self, reviews: list[Review]) -> int:
        if not reviews:
            return 0
        rows = [
            (
                r.review_id,
                r.place_id,
                r.place_name,
                r.text,
                r.rating,
                r.published_date,
                r.reviewer_name,
                r.owner_response,
                r.scraped_at,
            )
            for r in reviews
        ]
        self.conn.executemany(
            f"""
            INSERT OR REPLACE INTO {REVIEWS_TABLE}
            (review_id, place_id, place_name, text, rating, published_date,
             reviewer_name, owner_response, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def list_places(self) -> list[dict]:
        rows = self.conn.execute(
            f"SELECT * FROM {PLACES_TABLE} ORDER BY name"
        ).fetchall()
        cols = [
            "place_id",
            "name",
            "address",
            "rating",
            "review_count",
            "maps_url",
            "category",
            "scraped_at",
        ]
        return [dict(zip(cols, row)) for row in rows]

    def get_place_ids(self) -> set[str]:
        rows = self.conn.execute(f"SELECT place_id FROM {PLACES_TABLE}").fetchall()
        return {row[0] for row in rows}

    def review_count(self) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {REVIEWS_TABLE}").fetchone()[0]

    def place_count(self) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {PLACES_TABLE}").fetchone()[0]

    def get_review(self, review_id: str) -> dict | None:
        row = self.conn.execute(
            f"SELECT * FROM {REVIEWS_TABLE} WHERE review_id = ?", [review_id]
        ).fetchone()
        if not row:
            return None
        cols = [
            "review_id",
            "place_id",
            "place_name",
            "text",
            "rating",
            "published_date",
            "reviewer_name",
            "owner_response",
            "scraped_at",
        ]
        return dict(zip(cols, row))

    def export_corpus_jsonl(self, path: Path) -> int:
        rows = self.conn.execute(
            f"""
            SELECT review_id, place_name, rating, published_date, text, owner_response
            FROM {REVIEWS_TABLE}
            WHERE length(trim(text)) > 0
            """
        ).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("w", encoding="utf-8") as f:
            for review_id, place_name, rating, published_date, text, owner_response in rows:
                parts = [place_name]
                if rating is not None:
                    parts.append(f"rating {rating}/5")
                if published_date:
                    parts.append(published_date)
                parts.append(text.strip())
                if owner_response:
                    parts.append(f"owner response: {owner_response}")
                contents = " | ".join(p for p in parts if p)
                f.write(
                    json.dumps({"id": review_id, "contents": contents}, ensure_ascii=False)
                    + "\n"
                )
                count += 1
        return count

    def close(self) -> None:
        self.conn.close()
