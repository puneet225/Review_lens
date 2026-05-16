# Phase 6 — End-to-End Testing & Hardening: Evaluations

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §14, §15

---

## Evaluation Criteria

### E6.1 — E2E: Single Product, Single Week

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Full run completes for `groww` with real data | `python -m review_pulse run --product groww` | Exit 0; `status` → `success` |
| 2 | Google Doc has new section with correct heading | Open doc in browser | Section `"Week {ISO_WEEK}"` at end |
| 3 | Doc contains themes, quotes, actions, metadata | Read doc content | All 4 sub-sections present |
| 4 | Every doc quote exists in a real review | Cross-check against ingested reviews | 100% match |
| 5 | Gmail draft/email created with correct subject | Check Gmail | Subject = `"📊 Groww Review Pulse — Week {ISO_WEEK}"` |
| 6 | Email deep link navigates to correct doc section | Click link | Navigates to heading |
| 7 | Run log fully populated | `python -m review_pulse status` | No `None` in doc_id, gmail_msg_id |
| 8 | Total run time < 5 min | Wall clock | < 300s |

### E6.2 — E2E: Idempotent Re-run

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Re-run same product + week | Re-invoke CLI | "Idempotent skip" message |
| 2 | No duplicate doc section | Open doc | One section for that week |
| 3 | No duplicate email | Check sent folder | One message with matching `X-Pulse-Run-Key` |
| 4 | Run log unchanged | Query DB | `COUNT = 1` for `(product, week)` |
| 5 | Exit code = 0 | `$?` | 0 |

### E6.3 — E2E: Multi-Product Backfill

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | 3 products × 2 weeks = 6 runs | `backfill` command | All 6 logged `success` |
| 2 | Each product has own Google Doc | Check Drive | 3 distinct docs |
| 3 | Each doc has 2 sections | Open docs | 2 sections each |
| 4 | 6 emails sent (2 per product) | Check sent folder | 6 messages |
| 5 | Re-run backfill skips all | Re-invoke | All 6 skipped |

### E6.4 — Error Recovery

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | One ingestion source down | Block App Store | Succeeds with Play Store data only |
| 2 | Both sources down | Block all network | `failed`; no doc/email artifacts |
| 3 | Docs MCP crash mid-append | Kill subprocess | Retry once; clean `failed` if persistent |
| 4 | Gmail MCP crash mid-send | Kill subprocess | Retry once; `partial_success` if Docs OK |
| 5 | LLM quota exceeded | Mock persistent 429 | `failed` after 3 retries |
| 6 | Failed run retryable after recovery | Restore service; re-run | Succeeds normally |

### E6.5 — Performance

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Ingestion < 30s (500 reviews/source) | Timer | < 30s |
| 2 | Embedding < 10s (500 reviews) | Timer | < 10s |
| 3 | UMAP + HDBSCAN < 15s | Timer | < 15s |
| 4 | LLM summarisation < 60s (8 clusters) | Timer | < 60s |
| 5 | MCP delivery < 10s | Timer | < 10s |
| 6 | Peak memory < 2GB | `tracemalloc` | < 2GB |

### E6.6 — Security Audit

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | No creds in codebase | `grep -r "client_secret\|private_key"` | Zero matches |
| 2 | No API keys hardcoded | `grep -r "AIza\|sk-"` | Zero matches |
| 3 | `.gitignore` covers sensitive files | Read file | Includes `*.db`, `.env`, cred patterns |
| 4 | PII scrubbed before external calls | Code trace | Confirmed |
| 5 | Run log has no raw review text | Schema inspection | No `body` column |

### E6.7 — Documentation

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | README has quick-start instructions | Read | Prerequisites + install + run |
| 2 | SETUP has MCP server guide | Read | OAuth + MCP config steps |
| 3 | CLI commands documented | `--help` | All commands have examples |
| 4 | Runbook covers ≥5 failure scenarios | Read | Remediation steps included |

---

## Automated Test Commands

```bash
# Full E2E suite
pytest tests/test_e2e_single_run.py tests/test_e2e_idempotency.py tests/test_e2e_backfill.py -v -m "e2e"

# Error recovery
pytest tests/test_error_recovery.py -v

# Security audit
grep -r "client_secret\|private_key\|AIza\|sk-" review_pulse/ --include="*.py"

# Performance profile
python -m review_pulse run --product groww --week 2026-W18 --profile
```

---

## Acceptance Summary

| Area | Weight | Threshold |
|---|---|---|
| Single-product E2E | 20% | Doc + email created successfully |
| Idempotent re-run | 15% | Zero duplicates |
| Multi-product backfill | 15% | All runs succeed |
| Error recovery | 20% | All failure modes handled |
| Performance | 10% | All phases under time limits |
| Security audit | 15% | Zero credential leaks |
| Documentation | 5% | README + SETUP complete |
