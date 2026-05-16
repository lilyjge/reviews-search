from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from reviews_search.models import Place, Review
from reviews_search.scrape.places_api import place_id_from_maps_url


@dataclass
class BrowserScraper:
    headless: bool = True
    slow_mo_ms: int = 0

    def _launch(self, playwright: Playwright) -> Browser:
        return playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo_ms,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
            ],
        )

    def _new_context_page(self, browser: Browser) -> tuple[BrowserContext, Page]:
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-CA",
            timezone_id="America/Toronto",
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """
        )
        return context, context.new_page()

    @staticmethod
    def _normalize_maps_href(href: str) -> str:
        href = (href or "").strip()
        if not href:
            return href
        if href.startswith("/"):
            href = urllib.parse.urljoin("https://www.google.com", href)
        return href

    def discover_places(
        self,
        query: str,
        location: str,
        max_places: int = 20,
    ) -> list[Place]:
        search_q = urllib.parse.quote_plus(f"{query} {location}")
        url = f"https://www.google.com/maps/search/{search_q}"
        places: list[Place] = []
        seen_urls: set[str] = set()

        with sync_playwright() as p:
            browser = self._launch(p)
            context, page = self._new_context_page(browser)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                self._dismiss_consent(page)
                time.sleep(2.5)
                try:
                    page.wait_for_selector('a[href*="/maps/place/"]', timeout=15_000)
                except Exception:
                    pass

                feed = page.locator('div[role="feed"]').first
                stale = 0
                while len(places) < max_places and stale < 6:
                    links = page.locator('a[href*="/maps/place/"]').all()
                    for link in links:
                        raw_href = link.get_attribute("href") or ""
                        href = self._normalize_maps_href(raw_href)
                        if not href or href in seen_urls:
                            continue
                        seen_urls.add(href)
                        name = (
                            link.get_attribute("aria-label") or link.inner_text() or ""
                        ).strip()
                        name = re.sub(
                            r"\s*\d+(\.\d+)?\s*stars?.*$",
                            "",
                            name,
                            flags=re.I,
                        ).strip()
                        if not name:
                            continue
                        place_id = place_id_from_maps_url(href) or self._slug_id(href)
                        places.append(
                            Place(
                                place_id=place_id,
                                name=name,
                                maps_url=href,
                            )
                        )
                        if len(places) >= max_places:
                            break

                    if len(places) >= max_places:
                        break
                    prev = len(seen_urls)
                    try:
                        feed.evaluate("el => el.scrollTop += 900")
                    except Exception:
                        page.mouse.wheel(0, 900)
                    time.sleep(1.3)
                    if len(seen_urls) == prev:
                        stale += 1
                    else:
                        stale = 0
            finally:
                context.close()
                browser.close()
        return places

    def _open_place_from_search(self, page: Page, place: Place, location_hint: str) -> None:
        query = self._compact_search_query(place.name, location_hint)
        url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(query)}"
        page.goto(url, wait_until="load", timeout=90_000)
        self._dismiss_consent(page)
        time.sleep(2)
        page.wait_for_selector(
            'a[href*="/maps/place/"]', timeout=45_000, state="attached"
        )
        time.sleep(0.5)
        self._click_matching_place_link(page, place)

    @staticmethod
    def _compact_search_query(name: str, location_hint: str) -> str:
        n = (name or "").strip()
        for sep in ("·", " • ", " | ", " - "):
            if sep in n:
                n = n.split(sep)[0].strip()
        words = n.split()
        if len(words) > 3:
            n = " ".join(words[:3])
        parts = [n] if n else []
        if location_hint:
            parts.append(location_hint.strip())
        return " ".join(parts)

    def _click_matching_place_link(self, page: Page, place: Place) -> None:
        feed_links = page.locator('div[role="feed"] a[href*="/maps/place/"]').all()
        links = feed_links or page.locator('a[href*="/maps/place/"]').all()
        if not links:
            raise RuntimeError("No place links in Maps search results")

        normalized_target = self._normalize_maps_href(place.maps_url or "")
        target_base = normalized_target.split("?")[0].rstrip("/") if normalized_target else ""
        name_key = re.sub(r"[^a-z0-9]", "", place.name.lower())

        for link in links:
            href = self._normalize_maps_href(link.get_attribute("href") or "")
            if target_base and href.split("?")[0].rstrip("/") == target_base:
                link.scroll_into_view_if_needed()
                link.click(timeout=15_000)
                return
            if place.place_id and place.place_id in href:
                link.scroll_into_view_if_needed()
                link.click(timeout=15_000)
                return

        best = None
        best_score = 0
        for link in links:
            label = (link.get_attribute("aria-label") or link.inner_text() or "").lower()
            label_key = re.sub(r"[^a-z0-9]", "", label.split(",")[0])
            if not label_key or not name_key:
                continue
            overlap = min(len(name_key), len(label_key))
            score = 0
            for size in (12, 10, 8):
                if size <= overlap and (
                    name_key[:size] in label_key or label_key[:size] in name_key
                ):
                    score = size
                    break
            if score > best_score:
                best_score = score
                best = link

        chosen = best if best_score > 0 else links[0]
        chosen.scroll_into_view_if_needed()
        chosen.click(timeout=15_000)

    def scrape_reviews(
        self,
        place: Place,
        max_reviews: int = 100,
        sort_by: str = "newest",
        location_hint: str = "",
    ) -> list[Review]:
        if not place.name:
            raise ValueError(f"No name for place {place.place_id}")

        reviews: list[Review] = []
        sort_options = {
            "relevant": 0,
            "newest": 1,
            "highest_rating": 2,
            "lowest_rating": 3,
        }

        with sync_playwright() as p:
            browser = self._launch(p)
            context, page = self._new_context_page(browser)
            try:
                self._open_place_from_search(page, place, location_hint)
                time.sleep(2.8)

                try:
                    page.wait_for_selector(
                        'div[role="main"], [data-review-id], [role="tab"]',
                        timeout=20_000,
                    )
                except Exception:
                    pass

                opened = self._open_reviews_tab(page)
                if not opened:
                    time.sleep(1)
                    self._open_reviews_tab(page)

                self._sort_reviews(page, sort_options.get(sort_by, 1))
                time.sleep(1)

                try:
                    page.wait_for_selector("[data-review-id]", timeout=20_000)
                except Exception:
                    pass

                scrollable = self._reviews_scroll_container(page)
                collected = 0
                last_count = 0
                stale_iterations = 0
                seen_ids: set[str] = set()
                synthetic = 0

                while collected < max_reviews and stale_iterations < 25:
                    review_elements = page.locator("[data-review-id]").all()
                    n_el = len(review_elements)

                    for element in review_elements:
                        data_id = element.get_attribute("data-review-id") or ""
                        if not data_id:
                            synthetic += 1
                            data_id = f"gen_{synthetic}"
                        if data_id in seen_ids:
                            continue
                        seen_ids.add(data_id)

                        try:
                            more_btn = element.locator(
                                'button[jsname="gxjVle"], '
                                'button[aria-label*="See more"], '
                                'button[aria-label*="more"]'
                            ).first
                            if more_btn.is_visible(timeout=400):
                                more_btn.click(timeout=1500)
                                time.sleep(0.2)
                        except Exception:
                            pass

                        reviewer_name = self._extract_reviewer_name(element)
                        rating = self._parse_rating(element)
                        text = self._extract_review_text(element)
                        published_date = self._extract_date(element)
                        owner_response = self._extract_owner_response(element)

                        if not text.strip():
                            continue

                        review_id = f"{place.place_id}::{data_id}"
                        reviews.append(
                            Review(
                                review_id=review_id,
                                place_id=place.place_id,
                                place_name=place.name,
                                text=text.strip(),
                                rating=rating,
                                published_date=published_date,
                                reviewer_name=reviewer_name,
                                owner_response=owner_response,
                            )
                        )
                        collected += 1
                        if collected >= max_reviews:
                            break

                    if n_el == last_count:
                        stale_iterations += 1
                    else:
                        stale_iterations = 0
                        last_count = n_el

                    if collected >= max_reviews:
                        break

                    try:
                        scrollable.evaluate("el => { el.scrollTop += 1400; }", timeout=5000)
                    except Exception:
                        try:
                            page.mouse.wheel(0, 1200)
                        except Exception:
                            pass
                    time.sleep(1.1)

            finally:
                context.close()
                browser.close()

        return reviews

    def _reviews_scroll_container(self, page: Page):
        selectors = [
            'div[role="region"][aria-label*="Reviews for"]',
            'div[role="region"][aria-label*="reviews"]',
            'div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
            'div.m6QErb.DxyBCb',
            'div[class*="m6QErb"][class*="DxyBCb"]',
        ]
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.is_visible(timeout=1200):
                    return loc
            except Exception:
                continue
        return page.locator("div[role='main']").first

    @staticmethod
    def _open_reviews_tab(page: Page) -> bool:
        try:
            tab = page.get_by_role("tab", name=re.compile(r"review", re.I))
            if tab.count() > 0 and tab.first.is_visible(timeout=2500):
                tab.first.click(timeout=5000)
                time.sleep(1.8)
                return True
        except Exception:
            pass

        for pattern in (
            "Reviews",
            "reviews",
        ):
            try:
                btn = page.get_by_role("button", name=re.compile(rf".*{pattern}.*", re.I))
                if btn.count() > 0 and btn.first.is_visible(timeout=1500):
                    btn.first.click(timeout=4000)
                    time.sleep(1.8)
                    return True
            except Exception:
                continue

        for selector in (
            'button[data-tab-index="1"]',
            'div[role="tab"][data-tab-index="1"]',
            'button[aria-label*="Reviews"]',
        ):
            try:
                tab = page.locator(selector).first
                if tab.is_visible(timeout=1500):
                    tab.click(timeout=4000)
                    time.sleep(1.8)
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _sort_reviews(page: Page, option_index: int) -> None:
        try:
            sort_btn = page.locator(
                'button[aria-label*="Sort reviews"], button[aria-label*="Sort"]'
            ).first
            if not sort_btn.is_visible(timeout=2500):
                return
            sort_btn.click(timeout=5000)
            time.sleep(0.7)
            items = page.locator('[role="menuitemradio"], [role="option"]').all()
            if len(items) > option_index:
                items[option_index].click(timeout=5000)
                time.sleep(1.2)
        except Exception:
            pass

    def _extract_reviewer_name(self, element) -> str:
        for sel in (
            '[class*="d4r55"]',
            'div[class*="fontBodyMedium"] span',
            'div[class*="fontBodyMedium"]',
        ):
            t = self._safe_text(element, sel)
            if t and len(t) < 120 and not re.match(r"^\d", t):
                return t
        return ""

    def _extract_review_text(self, element) -> str:
        for sel in (
            "span.wiI7pd",
            '[class*="wiI7pd"]',
            "span.MyEned",
            '[class*="review-full-text"]',
        ):
            t = self._safe_text(element, sel)
            if len(t.strip()) > 2:
                return t

        try:
            spans = element.locator("span").all()
            best = ""
            for s in spans[:40]:
                tx = (s.text_content() or "").strip()
                if len(tx) > len(best) and len(tx) > 15:
                    low = tx.lower()
                    if any(
                        x in low
                        for x in (
                            "photo",
                            "local guide",
                            "reviews",
                            "star",
                            "more",
                        )
                    ):
                        continue
                    best = tx
            if best:
                return best
        except Exception:
            pass
        return ""

    def _extract_date(self, element) -> str:
        for sel in ('[class*="rsqaWe"]', "span[class*='date']"):
            t = self._safe_text(element, sel)
            if t and len(t) < 80:
                return t
        return ""

    def _extract_owner_response(self, element) -> str | None:
        for sel in ('[class*="CDe7pd"]', '[class*="Fam1ne"]'):
            t = self._safe_text(element, sel)
            if t:
                return t
        return None

    @staticmethod
    def _slug_id(maps_url: str) -> str:
        slug = maps_url.split("/place/")[-1].split("/")[0]
        slug = urllib.parse.unquote(slug).replace("+", " ")[:80]
        digest = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_").lower()
        return f"slug_{digest[:48]}"

    @staticmethod
    def _dismiss_consent(page: Page) -> None:
        for label in ("Accept all", "Reject all", "I agree", "Accept"):
            try:
                btn = page.get_by_role("button", name=re.compile(re.escape(label), re.I))
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=3000)
                    time.sleep(0.8)
                    return
            except Exception:
                continue

    @staticmethod
    def _safe_text(element, selector: str) -> str:
        try:
            loc = element.locator(selector).first
            if loc.is_visible(timeout=500):
                return (loc.text_content() or "").strip()
        except Exception:
            pass
        try:
            loc = element.locator(selector).first
            return (loc.text_content() or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_rating(element) -> int | None:
        for sel in ('[role="img"][aria-label*="star"]', '[aria-label*="star"]'):
            try:
                stars = element.locator(sel).first
                if stars.is_visible(timeout=300):
                    aria = stars.get_attribute("aria-label") or ""
                    match = re.search(r"(\d+)", aria)
                    if match:
                        return int(match.group(1))
            except Exception:
                continue
        return None
