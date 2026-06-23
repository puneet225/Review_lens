# Fixed-Category Themes — Design Spec

**Date:** 2026-06-23
**Status:** Approved direction, pending spec review
**Area:** `Phase 4/review_pulse/analysis/`, `frontend/app/page.tsx`

## Problem

The current analysis produces **repetitive, disorganized themes**. A single run surfaced
`Trade App`, `User Reviews`, `Groww App`, `Groww Fans`, `Easy App`, `Nice App`, `Good App`,
`App Praise`, `Simple UI`, `Chart Issues` — six of which are the same underlying sentiment
(generic praise) wearing different names.

Two design choices cause this:

1. **HDBSCAN** splits the (mostly positive) reviews into ~12 micro-clusters, several
   semantically identical.
2. The **summariser names each cluster independently** and a prompt rule
   (`summariser.py:45`) *forces* each name to be distinct from the others. So near-identical
   praise clusters are forced into artificially different labels. The de-dup rule is what
   manufactures the duplication.

Separately, the UI shows a **"Tokens Used"** stat that is meaningless to end users.

## Goals

- Replace free-form per-cluster naming with a **small fixed set of aspect categories**, so
  output is organized, targeted, and **comparable run-to-run**.
- Collapse all generic praise into **one** bucket.
- Remove the "Tokens Used" stat from the UI.

## Non-goals

- No change to ingestion, PII scrubbing, delivery (Gmail/Docs), or the fee-explainer's
  curated-facts mechanism.
- No multi-label classification (each review → exactly one category for v1).
- No week-over-week trend storage/visualisation (comparability is enabled, not yet surfaced).

## Approach — embedding classification (approach ①)

Reuse the already-loaded `all-MiniLM-L6-v2` embedder. Each category is defined by a handful
of **seed phrases**. Every review is assigned to its single best-matching category; reviews
that match nothing land in **Other**. The LLM then writes one summary per non-empty category.

This drops UMAP + HDBSCAN + the force-distinct-names rule from the happy path. The existing
TF-IDF fallback is preserved for when embeddings are unavailable.

### Fixed taxonomy (Groww / fintech)

| Key | Display name | Seed phrases (starting set, tunable) |
|---|---|---|
| `loved` | 💚 What Users Love | "easy to use", "clean and simple interface", "best investing app", "smooth experience", "user friendly", "love this app", "great for beginners", "good app" |
| `bugs` | ⚡ App Problems & Bugs | "app keeps crashing", "full of bugs", "very slow and laggy", "app not working", "app freezes", "stopped working after update", "charts not loading", "technical glitch" |
| `fees` | 💸 Fees & Charges | "high brokerage charges", "too many hidden charges", "expensive fees", "account maintenance charge", "DP charges", "charged extra money" |
| `account` | 🔐 Account, Funds & Support | "KYC verification problem", "unable to login", "OTP not received", "withdrawal not working", "my money is stuck", "deposit failed", "no response from customer support", "account opening issue" |
| `other` | 📦 Other | — (catch-all; **hidden when empty**) |

The taxonomy lives as a `DEFAULT_CATEGORIES` constant in `classifier.py`. A future
`data/categories/{product}.yaml` override is out of scope for v1.

### Assignment algorithm

1. Embed all category seed phrases once per run (small, cached for the run). L2-normalise.
2. Embed each review (already produced by the embedder). L2-normalise.
3. For each review, score = `max over each category's seeds of cosine(review, seed)`.
   The review's category = the category owning the best-scoring seed (argmax).
   *(Max-over-seeds, not a single averaged centroid — more forgiving for short reviews.)*
4. If the best score `< category_match_threshold` → assign to `other`.
5. Group: `{category_key: [reviews]}`. Empty categories are not emitted (so empty `Other`
   never reaches the UI).

`category_match_threshold` is a new `AnalysisConfig` field, default **0.30** (MiniLM cosine;
tunable). Documented as the single knob for precision/recall of the `Other` bucket.

## Module changes

### New: `analysis/classifier.py`
- `DEFAULT_CATEGORIES`: ordered list of `(key, display_name, [seed_phrases])`.
- `classify_reviews(reviews, embeddings, threshold) -> dict[str, list[Review]]` returning
  reviews grouped by category key, preserving display-name mapping.
- Pure function over already-computed embeddings; no network.

### `analysis/pipeline.py`
- Replace STEP 2 (UMAP) + STEP 3 (HDBSCAN) on the happy path with a single call to
  `classify_reviews(...)`. Keep STEP 1 (embedding) and STEP 4a (TF-IDF fallback when
  embedding fails). `reducer.py` / `clusterer.py` remain in the repo but are no longer wired
  into the main path.
- Iterate categories (sorted by review count desc; `other` always last) instead of clusters.
  Cap by `max_themes` (now effectively ≤5).
- `noise_count` is repurposed to the size of the `Other` bucket (reviews matched to no
  category), keeping the field meaningful.

### `analysis/summariser.py`
- Remove the `existing_theme_names` parameter and the "MUST be distinct" rule.
- New signature carries a **fixed category name**; the LLM no longer names the theme. Prompt
  becomes: "These reviews belong to the '{category}' category. Write a one-line description,
  classify sentiment, pick 2–3 exact-substring quotes, and give one action." The returned
  `name` is overwritten with the fixed display name regardless of LLM output.
- Sentiment / quote / action rules are unchanged. Groq-primary, Gemini-fallback unchanged.

### `store/models.py`
- No schema break. `Theme.name` holds the fixed category display name.
- (Optional, low-risk) add `category_key: Optional[str]` to `Theme` for stable identification
  independent of display string. Include it; defaults to `None` so nothing breaks.

### `frontend/app/page.tsx`
- Remove the `Tokens Used` entry from the stats bar (`page.tsx:458-478`) and change the grid
  from `repeat(3, 1fr)` to `repeat(2, 1fr)`. Backend `stats.tokens` is left intact, just not
  surfaced.
- Theme cards already render `theme.name`; ordering by review count comes from the backend.
  Empty categories never arrive, so no UI guard needed.

## Data flow (new happy path)

```
Reviews
  → Embedder (all-MiniLM-L6-v2, 384-dim)        [unchanged]
  → classify_reviews (cosine vs category seeds) [NEW — replaces UMAP+HDBSCAN]
  → per-category LLM summary (Groq/Gemini)       [name is fixed; no de-dup rule]
  → Validator (exact-substring quotes)           [unchanged]
  → Fee-explainer enrichment                     [unchanged; attaches to Fees & Charges]
  → AnalysisResult (≤5 themes)
```

## Edge cases

- **All reviews positive** → one large `What Users Love` card, others absent. Acceptable.
- **Everything below threshold** → all land in `Other`; if that is the only non-empty
  category, it is shown (the "hide when empty" rule only hides empty buckets).
- **Tie in argmax** → first category in `DEFAULT_CATEGORIES` order wins (deterministic).
- **< 10 reviews or embedding failure** → existing TF-IDF fallback path, unchanged.
- **Token budget exhausted** → remaining categories skipped, `is_partial=True`, unchanged.

## Testing

- `classifier.py` unit tests: synthetic reviews map to the expected category; below-threshold
  → `other`; tie determinism; empty input.
- `pipeline.py` test: produces only names drawn from the fixed taxonomy; ≤5 themes; `Other`
  populated only by unmatched reviews; fallback path still triggers on embedding failure.
- Frontend: visual check that the stats bar shows 2 cards and themes render the fixed names.

## Rollback

Pure analysis-layer + one frontend edit. Reverting `pipeline.py` to call the
clusterer/reducer restores the old behaviour; `reducer.py`/`clusterer.py` are untouched.
