from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Place:
    place_id: str
    name: str
    address: str = ""
    rating: float | None = None
    review_count: int | None = None
    maps_url: str = ""
    category: str = ""
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Review:
    review_id: str
    place_id: str
    place_name: str
    text: str
    rating: int | None = None
    published_date: str = ""
    reviewer_name: str = ""
    owner_response: str | None = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @staticmethod
    def make_id(place_id: str, text: str, reviewer_name: str, published_date: str) -> str:
        digest = hashlib.sha256(
            f"{place_id}|{reviewer_name}|{published_date}|{text[:500]}".encode()
        ).hexdigest()[:16]
        return f"{place_id}::{digest}"

    def corpus_contents(self) -> str:
        """Text indexed for BM25 search (place context + review body)."""
        parts = [self.place_name]
        if self.rating is not None:
            parts.append(f"rating {self.rating}/5")
        if self.published_date:
            parts.append(self.published_date)
        parts.append(self.text.strip())
        if self.owner_response:
            parts.append(f"owner response: {self.owner_response}")
        return " | ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)
