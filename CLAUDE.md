# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout — important

The repo contains **two parallel copies** of the Python package and **four phase snapshots**:

- `review_pulse/` (top-level) — an early Phase 1/2 snapshot. `analysis/`, `delivery/`, `ingestion/`, and `rendering/` are skeletons (only `__init__.py`). Do **not** treat this as the live codebase.
- `Phase 4/review_pulse/` — the **current, complete** implementation (ingestion, analysis, delivery via Google APIs, store). All real work lands here.
- `Phase 1/`, `Phase 2/`, `Phase 3/`, `Phase 4/` — frozen snapshots at the end of each phase. Treat earlier-phase folders as historical; only edit Phase 4 unless explicitly asked.
- `Phase 4/api.py` — FastAPI server wrapping the orchestrator (the backend the Next.js frontend talks to).
- `frontend/` — Next.js 14 (App Router) UI that calls the FastAPI backend.

Top-level `config.yaml`, `pyproject.toml`, `mcp_servers.sample.json`, and the `data/` directory are the live ones used by the FastAPI server (Phase 4/api.py loads `Phase 4/config.yaml` via `Path(__file__).parent / "config.yaml"`, and `.env` from the project root).

## Common commands

Always work from the project root. The Python virtual env lives in `.venv/`.

```bash
# Activate the venv
source .venv/bin/activate

# Install backend deps (Phase 4 is the source of truth for runtime requirements)
pip install -r "Phase 4/requirements.txt"

# Or editable install of the package (pyproject) — picks up the top-level review_pulse/
pip install -e .

# CLI (entrypoint defined in pyproject.toml -> review_pulse.cli:main)
review-pulse run --product groww                      # current ISO week
review-pulse run --product groww --week 2026-W18 --dry-run
review-pulse backfill --product groww --from-week 2026-W14 --to-week 2026-W18
review-pulse status --product groww --limit 20

# FastAPI backend (serves the Next.js frontend)
cd "Phase 4" && uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# Frontend
cd frontend && npm install && npm run dev            # default API URL: http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev

# Tests (Phase 4 holds the latest suite, organised by phase)
cd "Phase 4" && pytest                                # all phases
cd "Phase 4" && pytest tests/phase3                   # one phase
cd "Phase 4" && pytest tests/phase3/test_analysis.py::TestRunAnalysis -v
cd "Phase 4" && pytest -m "not integration"           # skip live-network tests

# One-time Google OAuth setup (writes gcp_token.json from gcp_oauth.json)
python generate_token.py
```

`pytest` config (root `pyproject.toml` and `Phase 4/pyproject.toml`) sets `asyncio_mode = "auto"` and registers `integration` / `e2e` markers. Use them when adding tests that need network or full Google credentials.

Lint/type tools are declared in the root `pyproject.toml` (`ruff`, `mypy`) but no project script wires them — run directly: `ruff check .`, `mypy review_pulse`.

## Required environment

`.env` at the project root (see `.env.template`):

- `GEMINI_API_KEY` — required for Phase 3+ LLM summarisation (`gemini-2.5-flash` by default).
- `GOOGLE_OAUTH_CREDENTIALS_PATH`, `GOOGLE_OAUTH_TOKEN_PATH` — absolute paths to `gcp_oauth.json` and `gcp_token.json` (both gitignored).
- `GROQ_API_KEYS` — optional fallback LLM keys (used by some analysis paths; see `Phase 4/requirements.txt`).
- `GOOGLE_OAUTH_TOKEN_B64` — only for Render deployment; base64 of `gcp_token.json`. `Phase 4/api.py` decodes this into a temp file on startup.

`gcp_oauth.json` and `gcp_token.json` must never be committed (covered by `.gitignore`).

## Architecture — what spans multiple files

End-to-end flow per (product, ISO week):

1. **Orchestrator** (`Phase 4/review_pulse/agent/orchestrator.py`) — single entry point. Checks idempotency (unique `(product, iso_week)` in SQLite run log), then runs the four stages and updates the audit row at each step. The orchestrator stashes the last `AnalysisResult`, review/theme counts, and token usage on `self._last_*` so the API layer can deliver on demand without re-running the pipeline.
2. **Ingestion** (`ingestion/`) — `pipeline.run_ingestion(product_config, ingestion_config)` fans out to `appstore.py` (app-store-web-scraper) and `playstore.py` (google-play-scraper), then runs `scrubber.py` (Presidio) for PII removal. Returns deduplicated `Review` objects within the rolling `window_weeks`. Each scraper drops low-signal reviews **at scrape time** via `quality.assess()` (too short, emoji/digit/punct only, low character entropy, repeated-word gibberish, generic praise like "good good good"); rejection counts are logged per source. Off-topic reviews are *not* filtered here — that's handled implicitly by HDBSCAN noise during analysis.
3. **Analysis** (`analysis/pipeline.py`) — embeddings (Sentence-Transformers `all-MiniLM-L6-v2`) → UMAP reduction → HDBSCAN clustering → Gemini per-cluster summarisation → quote validator (exact-substring grounding check). Has a **TF-IDF fallback** (`fallback.py`) that activates whenever any heavy step fails, fewer than `_MIN_REVIEWS_FOR_CLUSTERING` (10) reviews are present, or HDBSCAN finds only noise. Imports of optional libs are wrapped in try/except so a missing dep degrades gracefully into fallback mode — keep that pattern when editing.
4. **Delivery** (`delivery/google_docs.py`, `delivery/gmail.py`) — uses `google-api-python-client` directly (OAuth via `gcp_token.json`). Note: the `Docs/architecture.md` design document describes an **MCP-based** delivery layer, but the implemented path in Phase 4 calls the Google APIs directly. Trust the code, not the architecture doc, when they disagree.

**Run audit log** (`store/run_log.py`): async SQLite at `data/run_log.db` (WAL mode). Schema enforces `UNIQUE(product, iso_week)` — this is the idempotency primitive. `agent/idempotency.py` queries it before each run. The `Orchestrator` updates the row incrementally (reviews_count → themes_count + tokens_used → doc_id/gmail_msg_id → status/completed_at) so partial runs are diagnosable via `review-pulse status`.

**Two-mode delivery from the API**: `Phase 4/api.py` always runs the pipeline with `dry_run=True` and stashes the result; the frontend then triggers `POST /api/deliver/email` and `POST /api/deliver/gdoc` separately, which read the stashed `_analysis` from the in-memory `_jobs` dict. This means jobs are not durable across server restarts — by design for the current UX.

**Config model** (`agent/config.py`): Pydantic v2 + pydantic-settings. `AppConfig.model_validate` enforces unique product names and at least one of `appstore_id` / `playstore_id` per product. `load_config()` reads YAML with BOM-tolerant decoding and syncs `GEMINI_API_KEY` from `.env` into `os.environ` so analysis modules pick it up. The API layer mutates `config.ingestion.__dict__` per request to inject UI-supplied `weeks` and `max_reviews` — be careful when refactoring `IngestionConfig` to keep that escape hatch working.

## Deployment

- **Render** (`render.yaml`): builds from `rootDir: Phase 3` with `pip install -r requirements.txt` and `uvicorn api:app`. ⚠️ The latest `api.py`, `requirements.txt`, and `Procfile` live in **Phase 4/**, not Phase 3 — `render.yaml` is stale. Update `rootDir` to `Phase 4` before the next deploy, or sync the two folders.
- Health check: `GET /api/health`.
- The Render deploy expects `GOOGLE_OAUTH_TOKEN_B64` (base64 of `gcp_token.json`) instead of a file on disk.

## Conventions worth keeping

- **ISO week format**: `YYYY-Www` (e.g. `2026-W18`). The CLI validates with the regex in `cli.py`. Always pass through `_validate_iso_week` or `_current_iso_week` rather than hand-formatting.
- **Idempotency key**: always `(product, iso_week)`. Don't add other dedup logic; let the SQLite uniqueness constraint and `check_run_exists` do their job.
- **Graceful degradation in analysis**: every heavy import (`sentence-transformers`, `umap-learn`, `hdbscan`, `google-generativeai`) is wrapped so missing deps fall back to TF-IDF. Preserve this when adding new analysis steps.
- **Token budgeting**: `AnalysisConfig.max_tokens_per_run` is enforced inside `run_analysis` per cluster; if the budget is exhausted the result is marked `is_partial=True`. Don't bypass this.
