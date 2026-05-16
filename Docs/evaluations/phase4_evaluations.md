# Phase 4 — MCP Integration & Delivery: Evaluations

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §5

---

## Evaluation Criteria

### E4.1 — MCP Client Manager

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Connects to a MCP server via stdio | Launch mock MCP server; call `connect()` | Session established; no errors |
| 2 | `list_tools()` returns available tools | Call after connect | Returns non-empty tool list |
| 3 | `call_tool()` invokes a tool and returns result | Call a simple tool | Valid JSON result returned |
| 4 | `disconnect()` cleanly terminates the session | Call disconnect; check subprocess | Subprocess terminated; no zombies |
| 5 | Connection timeout handled | Set 5s timeout; mock server that never responds | `ConnectionTimeout` raised after 5s |
| 6 | Multiple sessions managed concurrently | Connect to 2 servers | Both sessions active simultaneously |
| 7 | Config loaded from `mcp_servers.json` | Parse template config | Both server entries parsed with correct commands |

### E4.2 — Google Docs MCP Delivery

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `ensure_doc_exists()` creates doc on first call | Call for new product | Returns valid `doc_id` |
| 2 | `ensure_doc_exists()` returns existing doc on subsequent calls | Call twice for same product | Same `doc_id` returned both times |
| 3 | `heading_exists()` returns `False` for new week | Query for unseen week | `False` |
| 4 | `append_section()` adds content at end of doc | Call with test payload | Doc contains new section at the end |
| 5 | Section contains correct heading with ISO week | Read doc after append | Heading matches `Week {iso_week}` |
| 6 | `heading_exists()` returns `True` after append | Query same week | `True` |
| 7 | Idempotent: second `append_section()` for same week skips | Call twice | Doc has exactly one section for that week |
| 8 | Returns heading anchor for email deep link | Check return value | Non-empty anchor string |
| 9 | Handles doc with 50+ existing sections | Append to large doc | Completes in <5s |

### E4.3 — Gmail MCP Delivery

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `create_draft()` creates a draft email | Call with test payload | Returns valid `draft_id` |
| 2 | Draft contains correct subject line | Read draft | Subject matches `📊 {Product} Review Pulse — Week {iso_week}` |
| 3 | Draft contains deep link to doc heading | Read draft body | Contains doc URL with anchor |
| 4 | `send_draft()` sends the draft | Call with draft ID | Returns `message_id`; draft no longer exists |
| 5 | `already_sent()` returns `False` before send | Query | `False` |
| 6 | `already_sent()` returns `True` after send | Query | `True` |
| 7 | Idempotent: second send for same week skips | Call send twice | Only 1 message in sent folder for that run key |
| 8 | Email has both HTML and plain-text parts | Read message MIME | `multipart/alternative` with both parts |
| 9 | Custom `X-Pulse-Run-Key` header present | Read message headers | Header exists with value `{product}:{iso_week}` |

### E4.4 — MCP Health Check

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Health check passes when both servers available | Boot agent | Logs "MCP servers ready" |
| 2 | Health check fails fast when Docs server unavailable | Remove Docs server config | Raises `MCPServerUnavailable` within 10s |
| 3 | Health check fails fast when Gmail server unavailable | Remove Gmail server config | Raises `MCPServerUnavailable` within 10s |
| 4 | Partial failure: one server up, one down | Mock one failure | Error names the failed server |

---

## Automated Test Commands

```bash
# Unit tests (with mock MCP servers)
pytest tests/test_mcp_client.py tests/test_docs_delivery.py tests/test_gmail_delivery.py -v

# Integration tests (requires real MCP servers + OAuth)
pytest tests/test_delivery_integration.py -v -m "integration"
```

---

## Acceptance Summary

| Area | Weight | Threshold |
|---|---|---|
| MCP client connects & calls tools | 25% | All connection tests pass |
| Docs append + idempotency | 30% | Append works; duplicate skipped |
| Gmail draft/send + idempotency | 30% | Draft created; send works; duplicate skipped |
| Health check & error handling | 15% | Fail-fast verified |
