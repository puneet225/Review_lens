# Phase 2 — Review Ingestion Pipeline: Evaluations

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §6

---

## Evaluation Criteria

### E2.1 — App Store Scraper

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Fetches reviews for a valid `appstore_id` | Integration test (live) | Returns ≥1 `Review` objects |
| 2 | Returned reviews conform to `Review` schema | Validate each against Pydantic model | Zero validation errors |
| 3 | `rating` values are in range [1, 5] | Assertion on all returned reviews | All pass |
| 4 | `date` field is parseable and within the window | Compare dates against `(now - window_weeks)` | All dates ≥ window start |
| 5 | Reviews cached to fixture file for offline tests | Write to `tests/fixtures/appstore_groww.json` | File written; re-loadable |
| 6 | Performance: fetch ≤500 reviews in <30 seconds | Timed integration test | Elapsed < 30s |

### E2.2 — Play Store Scraper

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Fetches reviews for a valid `playstore_id` | Integration test (live) | Returns ≥1 `Review` objects |
| 2 | Returned reviews conform to `Review` schema | Pydantic validation | Zero validation errors |
| 3 | `review_id` is unique within returned set | `len(set(ids)) == len(ids)` | True |
| 4 | Handles apps with very few reviews (<5) | Test with niche app ID | Returns available reviews without error |
| 5 | `continuation_token` / pagination works | Request >100 reviews | All pages fetched up to `max_reviews_per_source` |

### E2.3 — PII Scrubber

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Email addresses replaced with `[EMAIL]` | Test with `user@example.com` in body | Body contains `[EMAIL]`, not original |
| 2 | Phone numbers replaced with `[PHONE]` | Test with `+91-9876543210` | Body contains `[PHONE]` |
| 3 | Aadhaar-like patterns replaced with `[AADHAAR]` | Test with `1234 5678 9012` | Replaced correctly |
| 4 | PAN number patterns replaced with `[PAN]` | Test with `ABCDE1234F` | Replaced correctly |
| 5 | Non-PII text is unaltered | Test with clean review text | Text unchanged |
| 6 | Multiple PII items in one review | Test with email + phone combined | Both replaced |
| 7 | `raw_body` preserved before scrubbing | Check `Review.raw_body` field | Equals original text |
| 8 | Scrubber performance: 1000 reviews in <2s | Timed test | Elapsed < 2s |

### E2.4 — Deduplication

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Duplicate `review_id` entries removed | Feed 2 reviews with same `review_id` | Output has 1 review |
| 2 | Cross-source duplicates preserved | Same text from App Store + Play Store (different IDs) | Both kept (different sources) |
| 3 | Order preserved after dedup | Feed ordered list with dups | First occurrence kept; order stable |

### E2.5 — Graceful Degradation

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | App Store down → Play Store results still returned | Mock App Store raising `ConnectionError` | Returns Play Store reviews only; warning logged |
| 2 | Play Store down → App Store results still returned | Mock Play Store raising `ConnectionError` | Returns App Store reviews only; warning logged |
| 3 | Both sources down → run fails cleanly | Mock both sources failing | `IngestionError` raised with both errors listed |
| 4 | Partial timeout on one source | Mock timeout after 50% of pages fetched | Returns partial results; log warning |

---

## Automated Test Commands

```bash
# Unit tests (with fixtures)
pytest tests/test_appstore.py tests/test_playstore.py tests/test_pii_scrubber.py tests/test_dedup.py -v

# Integration tests (live, optional — requires network)
pytest tests/test_ingestion_live.py -v -m "integration"
```

---

## Acceptance Summary

| Area | Weight | Threshold |
|---|---|---|
| App Store scraper returns valid reviews | 25% | ≥1 review for each test product |
| Play Store scraper returns valid reviews | 25% | ≥1 review for each test product |
| PII scrubber catches all seeded PII | 25% | 100% detection on test corpus |
| Deduplication & graceful degradation | 25% | All unit tests pass |
