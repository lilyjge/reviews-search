# Reviews Search

Scrape Google Maps reviews for businesses in an area, store them in DuckDB, and search the review text with [QuackIR](https://github.com/castorini/quackir) BM25 full‑text search — all in one DuckDB file.

**Concrete use case:** find optometrists in Waterloo–Kitchener–Cambridge and pick one for **ortho‑k lenses** (the answer is at the bottom of this README — Dr. Sarah Fong).

## Architecture

```
Google Maps  →  gosom/google-maps-scraper (native binary or Docker)
                ↓ JSON (lowercase keys + TitleCase nested reviews)
            import → DuckDB: places + reviews
                ↓ export jsonl
            QuackIR sparse BM25 index → reviews_corpus (same DuckDB)
                ↓
            CLI: search / recommend
```

- **Scraper:** [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper). Run it as a **native Go binary** (recommended on machines without Docker) or via Docker (matches their [agent skill](https://github.com/gosom/google-maps-scraper/blob/main/skills/google-maps-scraper/SKILL.md)). Use `--runner binary|docker|auto`.
- **Storage:** `places` and `reviews` tables in `data/reviews.duckdb`. QuackIR adds a `reviews_corpus` table with the sparse index to the same file.
- **Retrieval:** `search` ranks individual reviews by BM25. `recommend` groups by **place** and combines exact‑substring hits for query variants (e.g. `ortho-k`, `orthok`, `orthokeratology`, `corneal reshaping`) with the BM25 score, so you get an answer to "which business should I pick".

## Install

Requires **Python 3.10+**, a JVM (for the Pyserini Lucene tokenizer used by QuackIR), and **either**:

- the native gosom binary — easiest on macOS / Linux without Docker:
  ```bash
  brew install go     # or: sudo apt install golang
  go install github.com/gosom/google-maps-scraper@latest
  # binary lands at $(go env GOPATH)/bin/google-maps-scraper
  ```
- or **Docker Desktop**, if you'd rather not install Go.

Then:

```bash
git clone --recurse-submodules <this-repo-url>
cd reviews-search
# (or, if you already cloned without --recurse-submodules:)
#   git submodule update --init

conda env create -f environment.yml   # includes openjdk
conda activate reviews-search
pip install -e . --no-deps
playwright install chromium           # only needed for the legacy scraper
cp .env.example .env                  # optional: GOOGLE_PLACES_API_KEY
```

QuackIR is pulled in as a git submodule under `vendor/quackir` and added to `sys.path` by `reviews_search.indexer` / `.search` until it's on PyPI.

## One command (recommended)

```bash
python -m reviews_search scrape-gosom \
  --search "optometrist in Kitchener Waterloo Ontario" \
  --depth 5 \
  --exit-on-inactivity 3m

python -m reviews_search recommend "ortho k lenses" --top 10
```

`scrape-gosom` writes `data/gosom/queries.txt`, `data/gosom/results.json`, and `data/gosom/scrape.log`, then imports + indexes into `data/reviews.duckdb`. `--runner auto` (the default) picks the native binary if it can find it on `$PATH`, in `$GOBIN`, or under `~/go/bin`, otherwise falls back to Docker. Force one with `--runner binary` or `--runner docker`.

Multi‑line queries (split a city into neighborhoods, etc.):

```bash
python -m reviews_search scrape-gosom --queries-file my-queries.txt --depth 5
```

Advanced gosom flags (mirroring the [gosom CLI](https://github.com/gosom/google-maps-scraper)): `--geo`, `--zoom`, `--radius`, `--grid-bbox`, `--grid-cell`, `--proxies`, `--fast-mode`, `--email`, `--concurrency 8`, `--extra-flags '-c 8 -debug'`.

## Commands

| Command | Description |
|---------|-------------|
| `scrape-gosom` | Run [gosom](https://github.com/gosom/google-maps-scraper) (binary or Docker), import reviews, build the BM25 index. **Use this.** |
| `import-gosom FILE` | If you already have a `-json` result file, just import + (optionally) `--index`. |
| `index` | (Re)build the QuackIR sparse BM25 index from whatever's in the `reviews` table. |
| `search QUERY` | BM25 over individual reviews. |
| `recommend QUERY` | Aggregate by **place**: exact‑substring matches for query variants + BM25 top score + Maps rating, with the supporting review snippets. |
| `status` | Place and review counts. |
| `demo` | Load 3 demo places / 6 reviews, no scraping. |
| `scrape` | **Legacy** — direct Playwright scrape, fragile against Maps UI changes. Prefer `scrape-gosom`. |

## Environment

| Variable | Description |
|----------|-------------|
| `GOSOM_BIN` | Explicit path to the gosom binary (auto‑detected otherwise). |
| `GOOGLE_PLACES_API_KEY` | Optional. Used only by the legacy `scrape` discovery path. |
| `REVIEWS_DB_PATH` | DuckDB path (default `data/reviews.duckdb`). |
| `HEADLESS` | `true`/`false` for the legacy Playwright scraper. |

## Inspect the DB directly

Everything is one DuckDB file — you can ad‑hoc SQL it:

```bash
python - <<'EOF'
import duckdb
con = duckdb.connect("data/reviews.duckdb", read_only=True)
for r in con.execute("""
  SELECT place_name, count(*) AS hits
  FROM reviews
  WHERE lower(text) LIKE '%ortho-k%' OR lower(text) LIKE '%orthok%'
  GROUP BY place_name ORDER BY hits DESC
""").fetchall():
    print(r)
EOF
```

## Notes & ethics

- Scraping Google Maps may violate [Google's Terms of Service](https://policies.google.com/terms). Use responsibly and respect rate limits.
- The gosom scraper caps `-extra-reviews` at ~1000 per place; for top‑heavy places (big chains with thousands of reviews) you'll miss some. Specialty terms like "ortho‑k" almost always still show up in the captured slice.
- Re‑run the `scrape-gosom` (or `import-gosom --index`) flow whenever you add new queries to refresh both data and index.

## License

Apache 2.0. QuackIR retains its upstream license.

---

## Concrete answer to "which optometrist for ortho‑k in Waterloo–Kitchener?"

From 13k+ scraped reviews across 89 places in the region (`recommend "ortho k lenses"`):

| Rank | Place | Ortho‑k mentions | Maps rating | Notes |
|------|-------|-----------------:|------------:|-------|
| **1** | **Boardwalk Optical & Optometry — Dr. Sarah Fong** (Cambridge) | **6** | 4.9 ★ (203) | Multiple distinct patients call her out by name for ortho‑k specifically. One says "the go‑to person if you're looking Ortho‑k practice"; another, her first ortho‑k patient, has been with her 16+ years. Treats both adults and kids. |
| 2 | **Innovation Eye Clinic — Dr. Jason Chau OD** (Kitchener) | 3 | 5.0 ★ (132) | One very detailed parent review about Ortho‑K for their son — Dr. Chau replaced the lenses several times until vision was 20/20 and explained orthokeratology thoroughly. 100% 5‑star reviews (small sample). |
| 3 | G&G Eye Doctors (Cambridge) | 2 | 5.0 ★ (239) | One review is just "Great place to get ortho k lenses 😄" — positive but thin. |
| 4 | IRIS Optometrists (Waterloo) | 1 | 4.6 ★ (130) | Single review about starting OrthoK for an 8‑year‑old. Some negative reviews about pricing on the regular optical side. |

**Recommendation:** book with **Dr. Sarah Fong at Boardwalk Optical** if the 25‑minute drive to Cambridge is OK — she clearly has the most ortho‑k volume and consistent praise. If you want to stay in Kitchener proper, **Dr. Jason Chau at Innovation Eye Clinic** is the obvious choice and has perfect ratings.
