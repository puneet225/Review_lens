# Phase 2 — Review Ingestion Pipeline: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §6

---

## EC2.1 — App Store Scraper Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC2.1.1 | Invalid `appstore_id` (non-existent app) | Raise `AppNotFoundError` with the ID; skip this source | 🟡 Medium |
| EC2.1.2 | App exists but has zero reviews | Return empty list; log info "No App Store reviews found for {product}" | 🟢 Low |
| EC2.1.3 | Apple rate-limits the request (HTTP 429) | Retry with exponential backoff (3 attempts, 2s/4s/8s); then fail gracefully | 🟡 Medium |
| EC2.1.4 | RSS feed returns XML with unexpected schema changes | Parse defensively; log warning for missing fields; skip malformed entries | 🟡 Medium |
| EC2.1.5 | Review body contains HTML entities (`&amp;`, `&lt;`) | Decode to plain text during normalisation | 🟢 Low |
| EC2.1.6 | Review written in non-English language (Hindi, mixed scripts) | Accept as-is — clustering handles multilingual embeddings | 🟢 Low |
| EC2.1.7 | App Store web page structure changes (scraper breakage) | Catch `ScrapeError`; log critical; fall back to RSS if available | 🔴 Critical |
| EC2.1.8 | Review date is in non-standard timezone format | Parse with `dateutil.parser`; default to UTC if ambiguous | 🟢 Low |
| EC2.1.9 | Network timeout after partial fetch | Return reviews fetched so far; log warning with count | 🟡 Medium |

## EC2.2 — Play Store Scraper Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC2.2.1 | Invalid `playstore_id` (package doesn't exist) | Raise `AppNotFoundError`; skip this source | 🟡 Medium |
| EC2.2.2 | Play Store returns reviews with `None` body (rating only) | Set `body = ""`; mark as rating-only in metadata | 🟢 Low |
| EC2.2.3 | Play Store pagination returns duplicate reviews across pages | Dedup by `review_id` after all pages fetched | 🟡 Medium |
| EC2.2.4 | `google-play-scraper` library throws unhandled exception | Catch broad exception; log stack trace; degrade gracefully | 🟡 Medium |
| EC2.2.5 | Review `date` is `None` (missing timestamp) | Use current date as fallback; log warning | 🟢 Low |
| EC2.2.6 | Review body >10,000 characters (lengthy diatribe) | Truncate at 5,000 chars with `[TRUNCATED]` marker | 🟢 Low |
| EC2.2.7 | Review contains control characters (`\x00`, `\r`) | Strip control chars during normalisation | 🟢 Low |
| EC2.2.8 | Google CAPTCHA blocks scraper | Detect CAPTCHA response; log critical; fail source gracefully | 🔴 Critical |

## EC2.3 — PII Scrubber Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC2.3.1 | Email-like string that isn't a real email (`user@domain`) | Conservative: treat as PII and replace with `[EMAIL]` | 🟢 Low |
| EC2.3.2 | Phone number embedded in running text (`call me at 9876543210 asap`) | Pattern matches 10-digit sequence; replaces with `[PHONE]` | 🟡 Medium |
| EC2.3.3 | Number that looks like a phone but is an order ID (`ORD9876543210`) | Avoid false positive — require standalone digit sequence or known prefix | 🟡 Medium |
| EC2.3.4 | Review body is entirely PII (just a phone number) | Result is `[PHONE]` — valid but review becomes uninformative; clustering will likely mark as noise | 🟢 Low |
| EC2.3.5 | Presidio NER model is unavailable / not installed | Fall back to regex-only scrubbing; log warning | 🟡 Medium |
| EC2.3.6 | Non-Indian PII patterns (US SSN, UK NIN) | Not covered in v1; accept as-is; documented as known gap | 🟢 Low |
| EC2.3.7 | PII in review title (App Store) | Scrub both `title` and `body` fields | 🟡 Medium |
| EC2.3.8 | Multiple PII types adjacent (`email: a@b.com phone: 1234567890`) | Both detected and replaced in single pass | 🟡 Medium |

## EC2.4 — Cross-Cutting Ingestion Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC2.4.1 | `window_weeks = 1` (very narrow window) | May return 0 reviews for low-volume apps; run proceeds with warning | 🟡 Medium |
| EC2.4.2 | `max_reviews_per_source = 1` | Returns exactly 1 review per source; analysis will likely fail; warn user | 🟡 Medium |
| EC2.4.3 | Total reviews across both sources = 0 | Abort run with `InsufficientDataError`; log to run log with `failed` status | 🔴 Critical |
| EC2.4.4 | 100% duplicate reviews (App Store and Play Store somehow overlap) | Dedup by `review_id` preserves both (different source); if same source, keeps one | 🟢 Low |
| EC2.4.5 | System clock is wrong (reviews appear "from the future") | Log warning; don't filter out — might be legitimate timezone offset | 🟢 Low |
| EC2.4.6 | DNS resolution failure (no internet) | Both sources fail; `IngestionError` with network hint message | 🔴 Critical |
