# Phase 6 — End-to-End Testing & Hardening: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §14, §15

---

## EC6.1 — End-to-End Run Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC6.1.1 | First-ever run for a product (no existing Google Doc) | `ensure_doc_exists()` creates doc; first section appended; email sent | 🟢 Low |
| EC6.1.2 | Run for a product with only App Store ID (no Play Store) | Ingests from App Store only; analysis proceeds normally | 🟡 Medium |
| EC6.1.3 | Run for a product with only Play Store ID (no App Store) | Ingests from Play Store only; analysis proceeds normally | 🟡 Medium |
| EC6.1.4 | Run during App Store maintenance window | App Store source fails; Play Store used; partial data warning | 🟡 Medium |
| EC6.1.5 | Run produces analysis with 1 theme and 1 quote | Valid report; single theme section in doc; single bullet in email | 🟢 Low |
| EC6.1.6 | Run with `max_themes=1` in config | Only top cluster summarised; others discarded | 🟢 Low |

## EC6.2 — Idempotency Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC6.2.1 | Previous run marked `failed` — re-run should proceed | Idempotency check only blocks on `success`; failed runs are retryable | 🟡 Medium |
| EC6.2.2 | Previous run marked `interrupted` — re-run should proceed | Same as failed; interrupted is retryable | 🟡 Medium |
| EC6.2.3 | Previous run marked `partial_success` (Docs OK, Gmail failed) | Re-run should detect existing doc section; skip Docs append; retry Gmail only | 🔴 Critical |
| EC6.2.4 | Doc heading was manually edited by a human after agent wrote it | Heading text no longer matches expected pattern; agent may re-append duplicate | 🔴 Critical |
| EC6.2.5 | Run log DB deleted between runs | Agent has no local memory of past runs; checks doc headings as backup idempotency layer | 🟡 Medium |
| EC6.2.6 | Clock rollback: system time goes backwards between runs | ISO week computation may repeat; idempotency prevents duplicate | 🟡 Medium |

## EC6.3 — Multi-Product Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC6.3.1 | One product fails mid-backfill | Failed product logged; remaining products continue | 🟡 Medium |
| EC6.3.2 | LLM quota exhausted partway through multi-product backfill | Current product fails; remaining products also fail with same quota error; log all failures | 🔴 Critical |
| EC6.3.3 | MCP server OAuth token valid for one Google account but products' docs are in different accounts | Docs in unauthorized account fail with `PERMISSION_DENIED`; agent reports which products failed | 🔴 Critical |
| EC6.3.4 | Config has 50 products (stress test) | System should handle; scheduler runs sequentially; total time = 50 × single run time | 🟡 Medium |

## EC6.4 — System-Level Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC6.4.1 | Disk full — SQLite can't write | `run_log.py` catches `sqlite3.OperationalError`; logs to stderr; run fails | 🔴 Critical |
| EC6.4.2 | Disk full — sentence-transformers can't download model | Clear error: "Insufficient disk space for model download" | 🔴 Critical |
| EC6.4.3 | Python process killed by OOM killer (large dataset) | No graceful handling possible; next run retries; idempotency covers partial state | 🔴 Critical |
| EC6.4.4 | System timezone changed between scheduler config and runtime | APScheduler uses explicit `timezone` from config; immune to system TZ changes | 🟢 Low |
| EC6.4.5 | Agent runs in Docker container with no persistent volume | SQLite DB lost on restart; run log history lost; doc-level idempotency still works via heading check | 🟡 Medium |
| EC6.4.6 | Agent runs behind corporate proxy that blocks npm registry | `npx -y` for MCP servers fails; clear error with proxy configuration hint | 🟡 Medium |
| EC6.4.7 | Agent runs on machine with no GPU and 2GB RAM | CPU-only embedding; UMAP/HDBSCAN may be slow; reduce `max_reviews_per_source` | 🟡 Medium |
| EC6.4.8 | Log directory is not writable | Fall back to stdout logging; warn user | 🟢 Low |

## EC6.5 — Data Quality Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC6.5.1 | All reviews are 5-star positive with no complaints | Clustering finds positive themes; report reflects "all positive"; actions section may be empty or contain enhancement ideas | 🟢 Low |
| EC6.5.2 | All reviews are 1-star negative with same complaint | Single dominant cluster; report highlights the one issue prominently | 🟢 Low |
| EC6.5.3 | Reviews are evenly split (50/50 positive/negative) | HDBSCAN should find ≥2 clusters; report shows both sides | 🟢 Low |
| EC6.5.4 | Reviews contain spam/bot content | HDBSCAN marks repetitive spam as noise (or a "spam" cluster); LLM may name the theme "Spam/Bot Reviews" | 🟡 Medium |
| EC6.5.5 | Reviews are all very short (<10 words each) | Embeddings are less informative; clusters may be noisy; fallback may trigger | 🟡 Medium |
| EC6.5.6 | Reviews contain competitor mentions ("Groww is better than INDMoney") | Accepted as valid feedback; LLM summarises naturally; no special handling | 🟢 Low |
| EC6.5.7 | Window period (12 weeks) yields 10,000+ reviews | `max_reviews_per_source` caps at 500 per source (1000 total); most recent reviews sampled | 🟡 Medium |
