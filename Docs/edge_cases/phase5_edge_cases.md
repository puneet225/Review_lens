# Phase 5 — Rendering, Orchestrator & CLI: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §8, §4, §10

---

## EC5.1 — Doc Renderer Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC5.1.1 | `AnalysisResult` has 0 themes (fallback scenario) | Render section with "No significant themes identified this week." message | 🟡 Medium |
| EC5.1.2 | Theme name contains special Docs API characters (newlines, tabs) | Strip/replace control chars before inserting into JSON payload | 🟡 Medium |
| EC5.1.3 | Quote text contains double quotes (`"`) | Properly escape for JSON string embedding; Docs API handles display | 🟢 Low |
| EC5.1.4 | Action idea text is extremely long (>500 chars) | Truncate at 500 chars with `…` suffix | 🟢 Low |
| EC5.1.5 | `date_range` spans across year boundary (e.g., Dec 2025 – Feb 2026) | Format correctly: "2025-12-01 – 2026-02-15" | 🟢 Low |
| EC5.1.6 | Product name contains Unicode (e.g., emoji in product config) | Docs API accepts Unicode; render as-is | 🟢 Low |
| EC5.1.7 | `batchUpdate` payload exceeds Docs API 10MB limit | Extremely unlikely for text report; guard with size check; truncate themes if needed | 🟢 Low |
| EC5.1.8 | Jinja2 template file missing or corrupted | Raise `TemplateNotFoundError` with path; fail run before MCP call | 🔴 Critical |
| EC5.1.9 | Run ID (UUID) is `None` due to bug | Use placeholder `"unknown-run-id"` in metadata; log error | 🟡 Medium |

## EC5.2 — Email Renderer Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC5.2.1 | `doc_heading_link` is `None` (doc delivery failed) | Email still renders but "Read full report" links to doc root URL without anchor | 🟡 Medium |
| EC5.2.2 | Theme names contain HTML-unsafe characters (`<script>`, `&`) | HTML-escape in template: `{{ theme_name | e }}` | 🔴 Critical |
| EC5.2.3 | Stakeholder email list has 1 entry | `To:` field has single recipient; no `Cc:`/`Bcc:` | 🟢 Low |
| EC5.2.4 | Stakeholder email list has 50+ entries | All in `To:` field; warn if >20 to consider `Bcc:` for privacy | 🟡 Medium |
| EC5.2.5 | Emoji in subject line (`📊`) not supported by recipient email client | Degrade gracefully; emoji is decorative only | 🟢 Low |
| EC5.2.6 | Plain-text fallback doesn't match HTML content | Generate plain text from same data, not from HTML stripping | 🟡 Medium |
| EC5.2.7 | HTML template references CSS that's stripped by Gmail | Use inline CSS only; no `<style>` blocks or external stylesheets | 🟡 Medium |
| EC5.2.8 | Email body contains user-controlled text (review quotes) | Quotes are HTML-escaped in template; no raw insertion | 🔴 Critical |

## EC5.3 — Orchestrator Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC5.3.1 | Orchestrator invoked with a product not in config | Raise `ProductNotFoundError`: "Product '{name}' not in config. Available: [...]" | 🟡 Medium |
| EC5.3.2 | Orchestrator receives `KeyboardInterrupt` (Ctrl+C) during analysis | Catch signal; mark run as `interrupted` in log; clean up MCP sessions | 🟡 Medium |
| EC5.3.3 | Orchestrator receives `KeyboardInterrupt` during MCP delivery | More critical — Docs section may be partially appended; log as `interrupted`; next run's idempotency check handles partial state | 🔴 Critical |
| EC5.3.4 | Multiple orchestrator instances running for same product+week | First completes; second hits idempotency check and skips | 🟡 Medium |
| EC5.3.5 | Run log DB is locked when orchestrator tries to write | Retry 3 times with 1s delay; then fail run with `DatabaseLocked` | 🟡 Medium |
| EC5.3.6 | Analysis produces 1 theme only | Valid run; report has single theme section; no special handling needed | 🟢 Low |
| EC5.3.7 | Analysis takes >5 minutes (performance regression) | Log warning at 3-minute mark; no hard timeout (LLM calls can be slow) | 🟡 Medium |
| EC5.3.8 | Dry-run with `--dry-run` flag but MCP servers are not configured | Should succeed — dry-run never touches MCP; don't validate MCP config in dry-run | 🟡 Medium |
| EC5.3.9 | Orchestrator called with `week` = current partial week (mid-week) | Allow — rolling window ingestion still works; reviews may be fewer | 🟢 Low |

## EC5.4 — CLI Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC5.4.1 | `backfill --from-week 2026-W18 --to-week 2026-W15` (reversed range) | Raise error: "from-week must be ≤ to-week" | 🟡 Medium |
| EC5.4.2 | `backfill` spanning >52 weeks | Allow but warn: "Backfilling {n} weeks — this may take a long time" | 🟡 Medium |
| EC5.4.3 | `backfill` with a week format that doesn't match ISO (`2026-18` instead of `2026-W18`) | Raise error with correct format hint | 🟡 Medium |
| EC5.4.4 | `status` when run log DB is empty | Show "No runs recorded yet." instead of empty table | 🟢 Low |
| EC5.4.5 | `status` with very wide terminal (>200 cols) | Table stretches but remains readable | 🟢 Low |
| EC5.4.6 | `status` with narrow terminal (<80 cols) | Truncate long fields (doc_id, error_message) with `…` | 🟢 Low |
| EC5.4.7 | Multiple `--product` flags for batch run | If supported, run sequentially; if not, show "Use backfill for multiple products" | 🟢 Low |
| EC5.4.8 | `run` called without `--week` flag | Default to current ISO week; log info "Using current week: {week}" | 🟡 Medium |

## EC5.5 — Scheduler Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC5.5.1 | System clock changed (NTP sync) while scheduler is running | APScheduler handles clock adjustments; next fire recalculated | 🟢 Low |
| EC5.5.2 | Scheduler missed a fire time (system was off on Monday) | APScheduler's `misfire_grace_time` config; if within grace period, run immediately on wake; otherwise skip with log | 🟡 Medium |
| EC5.5.3 | Scheduler running in Docker container with UTC timezone | Config specifies `Asia/Kolkata`; APScheduler converts correctly | 🟡 Medium |
| EC5.5.4 | Scheduler crashes mid-run for one product | Other products not affected (sequential execution); crashed product logged as `failed` | 🟡 Medium |
| EC5.5.5 | Daylight saving time transition (India doesn't have DST, but consideration for future locales) | Use `pytz` / `zoneinfo` for proper timezone handling | 🟢 Low |
| EC5.5.6 | Two scheduler instances started accidentally | Both fire runs; idempotency check in orchestrator prevents duplicate work | 🟡 Medium |
