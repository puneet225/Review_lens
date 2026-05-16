# Phase 1 — Foundation & Data Models: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §3, §9, §10

---

## EC1.1 — Configuration Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC1.1.1 | `config.yaml` file missing entirely | Raise `FileNotFoundError` with message: "config.yaml not found at {path}. Copy config.sample.yaml to get started." | 🔴 Critical |
| EC1.1.2 | `config.yaml` is empty (0 bytes) | Raise `ValidationError`: "Configuration file is empty" | 🔴 Critical |
| EC1.1.3 | YAML syntax error (e.g. unmatched quotes) | Raise `yaml.YAMLError` wrapped in `ConfigError` with line number | 🟡 Medium |
| EC1.1.4 | Product list is empty (`products: []`) | Raise `ValidationError`: "At least one product must be configured" | 🔴 Critical |
| EC1.1.5 | Duplicate product names in config | Raise `ValidationError`: "Duplicate product name: {name}" | 🟡 Medium |
| EC1.1.6 | `appstore_id` or `playstore_id` missing for a product | Allow — partial sources OK; log warning | 🟢 Low |
| EC1.1.7 | `stakeholder_emails` contains invalid email format | Raise `ValidationError` with specific email string | 🟡 Medium |
| EC1.1.8 | `window_weeks` set to 0 or negative | Raise `ValidationError`: "window_weeks must be ≥ 1" | 🟡 Medium |
| EC1.1.9 | `max_tokens_per_run` set absurdly high (e.g. 10M) | Clamp to max allowed (500K) with warning log | 🟢 Low |
| EC1.1.10 | Config file has UTF-8 BOM marker | YAML parser must handle BOM transparently | 🟢 Low |

## EC1.2 — Data Model Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC1.2.1 | `Review.body` is empty string `""` | Accept — some reviews are rating-only; `body` set to `""` | 🟡 Medium |
| EC1.2.2 | `Review.body` contains only emojis (no text) | Accept — will be an outlier in clustering (HDBSCAN noise) | 🟢 Low |
| EC1.2.3 | `Review.rating` is a float `4.5` | Coerce to `int` (round) or reject — depends on source normalisation | 🟡 Medium |
| EC1.2.4 | `Review.date` is in the future | Accept but log warning — clock skew between stores and system | 🟢 Low |
| EC1.2.5 | `Review.review_id` is `None` or empty | Generate a deterministic hash from `(source, product, body, date)` | 🟡 Medium |
| EC1.2.6 | `Review.body` exceeds 10,000 characters | Truncate to 5,000 chars with `[TRUNCATED]` suffix; log warning | 🟡 Medium |
| EC1.2.7 | `RunRecord` fields contain SQL injection attempts | Parameterised queries prevent injection; Pydantic validates types | 🔴 Critical |
| EC1.2.8 | Unicode edge cases in review text (RTL, zero-width chars) | Normalise to NFC form; strip zero-width characters | 🟢 Low |

## EC1.3 — SQLite Run Log Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC1.3.1 | SQLite DB file is locked by another process | Retry 3 times with 1s backoff; then raise `DatabaseLocked` | 🟡 Medium |
| EC1.3.2 | DB file is on a read-only filesystem | Raise `PermissionError` with clear message at startup | 🔴 Critical |
| EC1.3.3 | DB file is corrupted (invalid SQLite header) | Detect corruption; backup corrupt file; create fresh DB; log critical warning | 🔴 Critical |
| EC1.3.4 | Concurrent writes from two scheduler instances | SQLite WAL mode + `UNIQUE` constraint prevents duplicates; second writer waits or fails | 🟡 Medium |
| EC1.3.5 | Very old run log (10,000+ records) | Performance must remain <100ms for `check_run_exists()`; add index on `(product, iso_week)` | 🟢 Low |
| EC1.3.6 | `iso_week` format inconsistency (`2026-W8` vs `2026-W08`) | Normalise to zero-padded format (`2026-W08`) in model validator | 🟡 Medium |

## EC1.4 — CLI Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC1.4.1 | `--week` value is a valid ISO format but in the future | Allow — useful for pre-scheduling; log info | 🟢 Low |
| EC1.4.2 | `--week` value is far in the past (e.g. `2020-W01`) | Allow — backfill use case; warn if no reviews expected | 🟢 Low |
| EC1.4.3 | `--product` name not in config | Raise error: "Product '{name}' not found in config. Available: {list}" | 🟡 Medium |
| EC1.4.4 | Ctrl+C during run | Graceful shutdown; mark run as `interrupted` in log | 🟡 Medium |
| EC1.4.5 | Terminal without UTF-8 support | Degrade emoji in output to ASCII equivalents | 🟢 Low |
