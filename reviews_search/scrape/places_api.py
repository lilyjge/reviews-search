from __future__ import annotations

import re

import httpx

from reviews_search.models import Place

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.rating,places.userRatingCount,places.googleMapsUri,places.primaryType"
)


def _normalize_place_id(raw_id: str) -> str:
    if raw_id.startswith("places/"):
        return raw_id.removeprefix("places/")
    return raw_id


def discover_places(
    query: str,
    location: str,
    api_key: str,
    max_results: int = 20,
) -> list[Place]:
    """Discover businesses via Google Places API (New) text search."""
    text_query = f"{query} in {location}"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {"textQuery": text_query, "pageSize": min(max_results, 20)}

    places: list[Place] = []
    page_token: str | None = None

    with httpx.Client(timeout=30.0) as client:
        while len(places) < max_results:
            if page_token:
                body["pageToken"] = page_token
            response = client.post(PLACES_SEARCH_URL, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

            for item in data.get("places", []):
                place_id = _normalize_place_id(item.get("id", ""))
                if not place_id:
                    continue
                display = item.get("displayName", {})
                name = display.get("text", "") if isinstance(display, dict) else str(display)
                places.append(
                    Place(
                        place_id=place_id,
                        name=name,
                        address=item.get("formattedAddress", ""),
                        rating=item.get("rating"),
                        review_count=item.get("userRatingCount"),
                        maps_url=item.get("googleMapsUri", ""),
                        category=item.get("primaryType", ""),
                    )
                )
                if len(places) >= max_results:
                    break

            page_token = data.get("nextPageToken")
            if not page_token or len(places) >= max_results:
                break

    return places


def place_id_from_maps_url(url: str) -> str | None:
    """Extract ChIJ... place id from a Google Maps URL when present."""
    match = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", url, re.I)
    if match:
        return match.group(1)
    match = re.search(r"/place/[^/]+/(@[^/]+/)?data=![^!]*!1s([^!]+)", url)
    if match:
        return match.group(2)
    return None
