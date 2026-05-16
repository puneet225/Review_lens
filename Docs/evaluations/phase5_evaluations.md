# Phase 5 — Rendering, Orchestrator & CLI: Evaluations

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §8, §4, §10

---

## Evaluation Criteria

### E5.1 — Google Doc Renderer

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Produces valid Docs `batchUpdate` JSON payload | Render with fixture `AnalysisResult`; validate JSON schema | Valid structure matching Docs API spec |
| 2 | Heading contains product name and ISO week | Inspect rendered payload | Heading = `"{Product} — Weekly Review Pulse"` + sub-heading `"Week {ISO_WEEK} · {date_range}"` |
| 3 | Themes section lists all themes as numbered items | Count items | Matches `len(result.themes)` |
| 4 | Quotes section uses blockquote formatting | Check formatting requests in payload | Each quote has `BLOCK_QUOTE` style or indent |
| 5 | Action ideas section uses bullet points | Check formatting | Bullet list style applied |
| 6 | Metadata footer includes review count, sources, window, run ID | Inspect payload text | All 4 metadata fields present |
| 7 | Template renders without error when 0 themes | Pass empty themes list | Produces section with "No themes identified" notice |
| 8 | Template renders without error when 0 quotes | Pass themes with empty quotes | Produces "No validated quotes" notice per theme |
| 9 | Special characters in review text escaped for Docs API | Include `"quotes"`, `&`, `<` in fixture data | Characters escaped correctly in JSON |

### E5.2 — Email Renderer

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | HTML email rendered from Jinja2 template | Render with fixture data | Valid HTML string |
| 2 | Plain-text fallback rendered | Render with fixture data | Clean text without HTML tags |
| 3 | Subject line matches format | Check `EmailPayload.subject` | `"📊 {Product} Review Pulse — Week {ISO_WEEK}"` |
| 4 | Top themes listed as bullet points | Inspect HTML body | `<li>` elements for each theme |
| 5 | Deep link to doc heading present | Inspect HTML body | `<a href="{doc_url}#heading=...">` |
| 6 | `X-Pulse-Run-Key` header set in payload | Check `EmailPayload.custom_headers` | `{"X-Pulse-Run-Key": "{product}:{iso_week}"}` |
| 7 | HTML renders correctly in email clients | Visual inspection or Litmus test | No broken layout in Gmail web |
| 8 | Stakeholder email list populated from config | Check `EmailPayload.to` | Matches `config.products[product].stakeholder_emails` |
| 9 | Email body length reasonable (<50KB) | Check `len(payload.html_body)` | < 50,000 chars |

### E5.3 — Orchestrator Main Loop

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Full pipeline executes: ingest → analyse → render → deliver | Integration test with mocked MCP | `RunRecord` with status `success` |
| 2 | Idempotency check runs before ingestion | Mock existing run; verify no ingestion call | Ingestion module not invoked |
| 3 | Failed ingestion aborts pipeline cleanly | Mock `IngestionError` | Run logged as `failed`; no delivery attempted |
| 4 | Failed analysis aborts pipeline cleanly | Mock `AnalysisError` | Run logged as `failed`; no delivery attempted |
| 5 | Failed delivery logged correctly | Mock `DeliveryError` from Docs MCP | Run logged as `failed`; error message recorded |
| 6 | Partial delivery (Docs OK, Gmail fail) logged | Mock Gmail failure only | Run logged as `partial_success` |
| 7 | Dry-run mode skips MCP calls | Pass `--dry-run` | No MCP tool calls; rendered output printed to stdout |
| 8 | Token usage and cost recorded in run log | Check `RunRecord` after successful run | `tokens_used > 0`, `cost_usd >= 0` |
| 9 | Run duration tracked | Check `created_at` vs `completed_at` | Positive duration |
| 10 | Orchestrator logs structured events at each stage | Capture log output | INFO logs for each stage transition |

### E5.4 — CLI Commands

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `run --product groww --week 2026-W18` triggers full pipeline | CLI invocation | Exits 0 with success message |
| 2 | `run --product groww --week 2026-W18 --dry-run` skips delivery | CLI invocation | Exits 0; output includes rendered report; no MCP calls |
| 3 | `backfill --product groww --from-week 2026-W15 --to-week 2026-W18` runs 4 weeks | CLI invocation | 4 runs logged; sequential execution |
| 4 | `backfill` skips already-completed weeks | Pre-seed 2 successful runs | Only 2 new runs executed |
| 5 | `status` shows formatted table of recent runs | CLI invocation | Table with columns: product, week, status, doc_id, gmail_msg_id, timestamp |
| 6 | `status --product groww` filters by product | CLI invocation | Only Groww runs shown |
| 7 | `status --limit 5` limits output | CLI invocation | ≤5 rows |
| 8 | Exit codes correct: 0=success, 1=failure, 2=partial | Check `$?` after CLI | Matches expected code |

### E5.5 — Scheduler

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Cron expression `0 8 * * MON` fires on Monday 08:00 IST | APScheduler simulation | Next fire time is next Monday 08:00 IST |
| 2 | Scheduler triggers run for each configured product | Mock orchestrator; count calls | Called once per product |
| 3 | Scheduler computes correct ISO week for current date | Check passed `--week` arg | Matches `datetime.now().isocalendar()` |
| 4 | Scheduler handles timezone correctly | Set TZ to Asia/Kolkata; verify fire time | Correct in IST |
| 5 | Scheduler logs next fire time at startup | Capture log | "Next run scheduled for {datetime}" |

---

## Automated Test Commands

```bash
# Unit tests
pytest tests/test_doc_renderer.py tests/test_email_renderer.py tests/test_orchestrator.py tests/test_cli_full.py tests/test_scheduler.py -v

# Integration test (dry-run mode, no MCP needed)
python -m review_pulse run --product groww --week 2026-W18 --dry-run
```

---

## Acceptance Summary

| Area | Weight | Threshold |
|---|---|---|
| Doc renderer produces valid payloads | 20% | All schema tests pass |
| Email renderer produces valid HTML + text | 15% | Subject, body, headers correct |
| Orchestrator pipeline end-to-end | 30% | Full loop with mocked MCP succeeds |
| CLI commands all functional | 20% | All commands parse and execute correctly |
| Scheduler fires at correct time | 15% | Cron + timezone verified |
