"""Import places + reviews from gosom/google-maps-scraper JSON output."""

from __future__ import annotations

import json
import re
from pathlib import Path

from reviews_search.models import Place, Review
from reviews_search.store.database import ReviewDatabase


def _pick(d: dict, *keys: str, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _normalize_review_obj(r: dict) -> dict:
    """gosom uses Go structs with TitleCase JSON keys by default."""
    return {
        "name": _pick(r, "Name", "name", "reviewer_name", default="") or "",
        "description": _pick(r, "Description", "description", "text", "body", default="") or "",
        "rating": _pick(r, "Rating", "rating"),
        "when": _pick(r, "When", "when", "date", "published_date", default="") or "",
        "response": _pick(r, "OwnerResponse", "owner_response"),
    }


def _place_id_from_entry(entry: dict) -> str:
    for key in ("place_id", "PlaceID", "cid", "Cid"):
        v = entry.get(key)
        if v:
            return str(v)
    link = entry.get("link") or entry.get("Link") or ""
    m = re.search(r"1s(0x[0-9a-f]+:0x[0-9a-f]+)", link, re.I)
    if m:
        return m.group(1)
    slug = link.split("/place/")[-1].split("/")[0] if "/place/" in link else ""
    return f"gosom_{abs(hash(link)) % 10**12}" if link else "unknown"


def entry_to_place(entry: dict) -> Place:
    place_id = _place_id_from_entry(entry)
    title = entry.get("title") or entry.get("Title") or ""
    link = entry.get("link") or entry.get("Link") or ""
    addr = entry.get("address") or entry.get("Address") or ""
    cat = entry.get("category") or entry.get("Category") or ""
    rc = entry.get("review_count") or entry.get("ReviewCount")
    rr = entry.get("review_rating") or entry.get("ReviewRating")
    return Place(
        place_id=place_id,
        name=title,
        address=addr,
        rating=float(rr) if rr is not None else None,
        review_count=int(rc) if rc is not None else None,
        maps_url=link,
        category=cat,
    )


def entry_reviews(entry: dict, place: Place) -> list[Review]:
    raw_lists = []
    for key in ("user_reviews_extended", "UserReviewsExtended", "user_reviews", "UserReviews"):
        chunk = entry.get(key)
        if isinstance(chunk, list) and chunk:
            raw_lists.append(chunk)

    seen: set[str] = set()
    out: list[Review] = []

    for chunk in raw_lists:
        for item in chunk:
            if not isinstance(item, dict):
                continue
            nr = _normalize_review_obj(item)
            text = (nr["description"] or "").strip()
            if not text:
                continue
            rid = Review.make_id(
                place.place_id, text, nr["name"], str(nr["when"])
            )
            if rid in seen:
                continue
            seen.add(rid)
            rating = nr["rating"]
            if rating is not None and not isinstance(rating, int):
                try:
                    rating = int(rating)
                except (TypeError, ValueError):
                    rating = None
            out.append(
                Review(
                    review_id=rid,
                    place_id=place.place_id,
                    place_name=place.name,
                    text=text,
                    rating=rating,
                    published_date=str(nr["when"] or ""),
                    reviewer_name=nr["name"],
                    owner_response=str(nr["response"]) if nr["response"] else None,
                )
            )
    return out


def load_entries(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    raw_stripped = raw.strip()
    if not raw_stripped:
        return []
    try:
        data = json.loads(raw_stripped)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    entries: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            entries.append(row)
    return entries


def import_gosom_json(db_path: Path, json_path: Path) -> dict:
    entries = load_entries(json_path)
    db = ReviewDatabase(db_path)
    n_places = 0
    n_reviews = 0

    for entry in entries:
        place = entry_to_place(entry)
        db.upsert_place(place)
        revs = entry_reviews(entry, place)
        n_reviews += db.upsert_reviews(revs)
        n_places += 1

    db.close()
    return {
        "entries": n_places,
        "reviews_upserted": n_reviews,
        "json_path": str(json_path),
    }
