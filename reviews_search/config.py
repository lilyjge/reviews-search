from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "reviews.duckdb"
CORPUS_TABLE = "reviews_corpus"
PLACES_TABLE = "places"
REVIEWS_TABLE = "reviews"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    google_places_api_key: str | None
    headless: bool

    @classmethod
    def from_env(cls) -> Settings:
        db_path = Path(os.getenv("REVIEWS_DB_PATH", str(DEFAULT_DB_PATH)))
        return cls(
            db_path=db_path,
            google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY") or None,
            headless=os.getenv("HEADLESS", "true").lower() not in ("0", "false", "no"),
        )
