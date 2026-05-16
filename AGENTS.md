# Agent Guide

Operational notes for coding agents (and future-me) working in this repo. **Read this first.**

This is **not a Google Maps scraper project** — it's a "find the best place for a specific need in an area" project that happens to use Google Maps reviews as the corpus. The Q&A loop is:

```
1. Pick a service category + location  →  scrape (gosom)
2. Pick the specific need               →  recommend with synonyms
3. Read snippets, pick a place
```

The optometrist / ortho-k example built the codebase; the laptop-keyboard-repair example below shows it generalizing.

---

## Architecture in 30 seconds

```
gosom binary  →  data/gosom/results*.json  →  DuckDB (places + reviews)
                                                  ↓
                                          QuackIR sparse BM25 (same .duckdb)
                                                  ↓
                                        CLI: `recommend` / `search`
```

- `reviews_search/scrape/gosom_runner.py`    — runs gosom (native binary preferred over Docker)
- `reviews_search/scrape/gosom_import.py`    — parses gosom JSON → `places` + `reviews` tables
- `reviews_search/indexer.py` / `search.py`  — QuackIR BM25 wrapper
- `reviews_search/recommend.py`              — **the value-add**: per-place ranking that combines exact substring matches for query variants with BM25
- `reviews_search/__main__.py`               — CLI

DuckDB schema (all in `data/reviews.duckdb`):
- `places(place_id PK, name, address, rating, review_count, maps_url, category, scraped_at)`
- `reviews(review_id PK, place_id, place_name, text, rating, published_date, reviewer_name, owner_response, scraped_at)`
- `reviews_corpus` — QuackIR's FTS table, rebuilt from `reviews` via `python -m reviews_search index`

---

## Standard recipe for a new task

**Task template:** "find the best `<service>` in `<area>` for `<specific need>`"

```bash
conda activate reviews-search
cd /Users/lily/dev/reviews-search

# 1) Scrape a broad query for the service, plus 2-5 targeted queries that pull in
#    specialty providers a generic search would miss. Use multiple queries split by
#    neighborhood / specialty — gosom de-dupes by place_id on import.
cat > /tmp/queries.txt <<'EOF'
laptop repair in Waterloo Ontario
laptop repair in Kitchener Ontario
laptop keyboard replacement Kitchener Waterloo
Apple authorized service provider Kitchener
computer repair shop Cambridge Ontario
EOF

python -m reviews_search scrape-gosom \
  --queries-file /tmp/queries.txt \
  --depth 5 \
  --exit-on-inactivity 3m

# 2) Recommend, passing domain-specific synonyms so we catch all variant
#    spellings/phrasings. The query string + every --variant turns into a
#    LIKE clause and contributes to the per-place "exact hits" score.
python -m reviews_search recommend "laptop keyboard repair" --top 10 --snippets 3 \
  --variant "keyboard replacement" \
  --variant "key replacement" \
  --variant "keycap" \
  --variant "broken key" \
  --variant "liquid damage" \
  --variant "spill damage" \
  --variant "macbook keyboard"
```

That's it. The output ranks shops by how many of their reviews mention the variants, with the supporting review snippets quoted underneath.

---

## How to pick good `--variant` synonyms

Run this *before* the recommend to see what people actually call the thing:

```bash
python <<'EOF'
import duckdb
con = duckdb.connect("data/reviews.duckdb", read_only=True)
# Replace the LIKE patterns with rough guesses for your domain
for term in ["keyboard", "key", "macbook", "liquid", "spill", "battery"]:
    rows = con.execute("""
        SELECT place_name, count(*) FROM reviews
        WHERE lower(text) LIKE ? GROUP BY place_name ORDER BY count(*) DESC LIMIT 5
    """, [f"%{term}%"]).fetchall()
    print(f"\n'{term}':"); [print(" ", r) for r in rows]
EOF
```

Skim a handful of matched reviews; note the **other words** people use ("typed", "stuck", "spilled coffee", "keys fell off", "took it to Apple"). Add those as `--variant`.

---

## Gotchas (these will bite you)

### 1. Star-only reviews are dropped on import
~18% of reviews on Maps are stars-only (no text). `gosom_import.py` skips them because they're useless to BM25. So `places.review_count` (the Maps total) is always ≥ `count(*) from reviews`. This is fine for picking a place; just don't get confused comparing counts.

### 2. Google caps pagination at ~25 pages (~500 reviews/place)
`gmaps/reviews.go:148` has a 50-page hard cap (1000 reviews), but **Google itself usually stops handing out `next_page_token` around page 25**. Three independent runs return the *exact same set* — Google's RPC is deterministic. So for any listing with >500 reviews, you'll see ~85% of Maps' stated total at best. No flag fixes this in gosom v1.12.1. For small specialty clinics/shops (<300 reviews) you get 100%.

### 3. The native gosom binary is preferred over Docker
We install it with `go install github.com/gosom/google-maps-scraper@latest` → `~/go/bin/google-maps-scraper`. The pipeline auto-detects it (`$PATH`, `$GOBIN`, `~/go/bin`). Docker is the fallback. If neither is available the run fails clearly.

### 4. Don't trust raw BM25 alone for ranking *places*
`python -m reviews_search search QUERY` ranks individual reviews and is dominated by common words (e.g. "lenses" in optometry, "fix" in repair). Always use `recommend` for "which place should I pick" — it weights exact-variant hits 10× the BM25 score.

### 5. Re-running with the same place doesn't get more reviews
The review_id is `sha256(place_id + reviewer_name + when + text[:500])`, so duplicate imports are idempotent. To force-refresh: `rm data/reviews.duckdb` and rescrape.

### 6. Reviewer PII is in `data/`
13k+ reviews × real reviewer names + personal stories. `.gitignore` excludes `data/` — keep it that way before pushing anywhere.

---

## Useful ad-hoc SQL

```bash
python <<'EOF'
import duckdb
con = duckdb.connect("data/reviews.duckdb", read_only=True)

# Which place mentions term X most?
for r in con.execute("""
  SELECT place_name, count(*) hits, avg(rating) avg_rating
  FROM reviews
  WHERE lower(text) LIKE '%term-here%'
  GROUP BY place_name ORDER BY hits DESC LIMIT 10
""").fetchall(): print(r)

# All hits with full text (for term X)
for r in con.execute("""
  SELECT place_name, rating, reviewer_name, text
  FROM reviews WHERE lower(text) LIKE '%term-here%'
  ORDER BY rating DESC LIMIT 20
""").fetchall():
    print(f"\n[{r[1]}/5 — {r[2]} — {r[0]}]\n{r[3]}")

# Rating distribution per shortlisted place
for name in ["Place A", "Place B"]:
    rows = con.execute("""
      SELECT rating, count(*) FROM reviews WHERE place_name = ?
      GROUP BY rating ORDER BY rating DESC NULLS LAST
    """, [name]).fetchall()
    print(name, rows)
EOF
```

---

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| `Indexed 0 documents` | No reviews in DB (only places) | Check `data/gosom/scrape.log` — gosom probably ran but every entry had `user_reviews_extended: null`. Re-scrape with `--depth 5 --exit-on-inactivity 3m` and `-extra-reviews` (which `scrape-gosom` sets by default). |
| `Neither native gosom nor Docker is available` | Fresh machine | `brew install go && go install github.com/gosom/google-maps-scraper@latest` |
| Recommend returns nothing | Your `--variant`s don't match any text | Run the SQL probe above with looser LIKE patterns |
| Search returns "No search index found" | Forgot to index after import-gosom | `python -m reviews_search index` |
| Pyserini error about `jvm.dll` / no JVM | conda env's openjdk isn't active | `conda activate reviews-search` |

---

## Don'ts

- **Don't** scrape into a public repo's history. `data/` and `*.log` are gitignored — keep it that way.
- **Don't** raise `-depth` past 10 unless you really want a lot of irrelevant places.
- **Don't** add domain-specific synonyms to `_expand_variants` in `recommend.py`. Pass them via `--variant` from the CLI instead — that function is meant to stay generic.
- **Don't** use the legacy `scrape` subcommand (built-in Playwright). It's left in tree as fallback but the Maps selectors break every few months. Always prefer `scrape-gosom`.
