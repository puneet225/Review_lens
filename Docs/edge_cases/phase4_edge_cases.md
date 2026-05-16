# Phase 4 — MCP Integration & Delivery: Edge Cases

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §5

---

## EC4.1 — MCP Client Manager Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC4.1.1 | `mcp_servers.json` file missing | Raise `FileNotFoundError`: "MCP server config not found at {path}" | 🔴 Critical |
| EC4.1.2 | `mcp_servers.json` has invalid JSON syntax | Raise `JSONDecodeError` with line/column info | 🔴 Critical |
| EC4.1.3 | Server command (`npx`) not found on `$PATH` | Raise `MCPServerError`: "Command 'npx' not found. Install Node.js." | 🔴 Critical |
| EC4.1.4 | MCP server process crashes immediately after spawn | Detect exit code ≠ 0; raise `MCPServerCrash` with stderr output | 🔴 Critical |
| EC4.1.5 | MCP server hangs during `initialize()` handshake | Timeout after 30s; kill subprocess; raise `MCPHandshakeTimeout` | 🟡 Medium |
| EC4.1.6 | MCP server sends malformed JSON-RPC response | Catch `JSONDecodeError`; retry once; then raise `MCPProtocolError` | 🟡 Medium |
| EC4.1.7 | MCP session dropped mid-operation (server OOM) | Detect broken pipe; attempt reconnect once; if failed, abort run | 🔴 Critical |
| EC4.1.8 | Two agents running simultaneously try to spawn same MCP server | Each gets its own subprocess; no conflict (stdio is per-process) | 🟢 Low |
| EC4.1.9 | Environment variables in MCP config contain unexpanded `$HOME` | Expand env vars before passing to subprocess | 🟡 Medium |
| EC4.1.10 | MCP server npm package not yet installed (first run) | `npx -y` auto-installs; may take 30-60s; don't timeout prematurely | 🟡 Medium |

## EC4.2 — Google Docs MCP Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC4.2.1 | OAuth token expired and MCP server can't refresh | MCP server returns auth error; agent logs "OAuth token expired — re-authenticate in MCP server config"; abort delivery | 🔴 Critical |
| EC4.2.2 | User doesn't have edit permission on the target doc | MCP returns `PERMISSION_DENIED`; raise `DeliveryError` with doc ID and required permission | 🔴 Critical |
| EC4.2.3 | Doc was deleted between `ensure_doc_exists()` and `append_section()` | `append_section()` gets `NOT_FOUND`; re-create doc and retry append | 🟡 Medium |
| EC4.2.4 | Google Docs API rate limit hit (HTTP 429) | MCP server may retry internally; if error propagated, agent retries with backoff | 🟡 Medium |
| EC4.2.5 | `batchUpdate` payload exceeds Docs API max request size (10 MB) | Split content into multiple batch requests; or truncate long reports | 🟡 Medium |
| EC4.2.6 | Heading anchor format changes in future Docs API versions | Anchor extraction logic must be resilient; fall back to doc URL without anchor | 🟢 Low |
| EC4.2.7 | Doc title contains special characters (e.g., `Pulse — Groww (v2)`) | Ensure proper escaping in search/create calls | 🟢 Low |
| EC4.2.8 | Concurrent runs try to append to same doc simultaneously | Docs API handles concurrent edits (last-write-wins for different sections); unlikely to conflict since sections are distinct headings | 🟡 Medium |
| EC4.2.9 | Google Docs MCP server doesn't expose expected tool name | List tools at connect; validate required tools exist; fail with helpful error listing available tools | 🔴 Critical |
| EC4.2.10 | Very large doc (100+ weekly sections, ~1MB) | `documents.get` for heading scan may be slow; consider caching doc structure or reading only headings | 🟡 Medium |

## EC4.3 — Gmail MCP Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC4.3.1 | OAuth token expired for Gmail | Same as Docs — auth error; abort with clear message | 🔴 Critical |
| EC4.3.2 | Stakeholder email address is invalid (e.g., `user@invalid`) | Gmail API rejects; `create_draft()` fails; log the invalid address; skip that recipient | 🟡 Medium |
| EC4.3.3 | Stakeholder email list is empty in config | Skip email delivery entirely; log warning "No stakeholders configured for {product}" | 🟡 Medium |
| EC4.3.4 | Email body exceeds Gmail size limit (25 MB) | Practically impossible for text-only pulse; but guard with size check | 🟢 Low |
| EC4.3.5 | `X-Pulse-Run-Key` header stripped by Gmail | Idempotency check via `messages.list` fails; fall back to subject-line search | 🟡 Medium |
| EC4.3.6 | Draft created but `send_draft()` fails (e.g., network glitch) | Draft persists in Gmail; next run's `already_sent()` won't find a *sent* message; run will re-create draft, resulting in 2 drafts | 🟡 Medium |
| EC4.3.7 | Delivery mode is `draft` but someone manually sends the draft before next run | `already_sent()` finds the sent message; idempotency works correctly | 🟢 Low |
| EC4.3.8 | Gmail MCP server exposes different tool names than expected | Same as Docs — validate at connect; fail with available tools list | 🔴 Critical |
| EC4.3.9 | Email sent to 50+ recipients (large stakeholder list) | Gmail may apply per-message recipient limits; batch if needed | 🟡 Medium |
| EC4.3.10 | Deep link to doc heading is invalid/broken | Email still sends with doc-level link (no anchor); log warning | 🟢 Low |

## EC4.4 — Cross-Cutting Delivery Edge Cases

| ID | Edge Case | Expected Behaviour | Severity |
|---|---|---|---|
| EC4.4.1 | Docs delivery succeeds but Gmail delivery fails | Run logged as `partial_success`; run log records doc delivery but null Gmail fields | 🟡 Medium |
| EC4.4.2 | Gmail delivery succeeds but Docs delivery failed | Should never happen — Docs is attempted first; if Docs fails, Gmail not attempted | 🟢 Low |
| EC4.4.3 | Both deliveries fail | Run logged as `failed`; both error messages recorded | 🔴 Critical |
| EC4.4.4 | Agent loses network connectivity mid-delivery | MCP server subprocess may buffer; if server also loses connection, both deliveries fail; run fails cleanly | 🔴 Critical |
| EC4.4.5 | Dry-run mode — no MCP calls made | Rendering succeeds; delivery skipped; run logged as `dry_run` | 🟢 Low |
