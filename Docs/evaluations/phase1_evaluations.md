# Phase 1 — Foundation & Data Models: Evaluations

> **Ref:** [implementationPlan.md](../implementationPlan.md) · [architecture.md](../architecture.md) §3, §9, §10

---

## Evaluation Criteria

### E1.1 — Project Scaffold Integrity

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `pyproject.toml` declares all required dependencies | `pip install -e .` in clean venv | Install completes with zero missing-dep errors |
| 2 | Directory structure matches architecture §3.1 | Automated script comparing dirs | Every module directory exists with `__init__.py` |
| 3 | Linting passes on scaffold | `ruff check .` + `mypy .` | Zero errors |
| 4 | Python version gate | `python --version` check in CLI entry point | Fails gracefully on Python < 3.11 |

### E1.2 — Configuration System

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Valid `config.yaml` loads into `AppConfig` | Unit test | All 5 products loaded; types correct |
| 2 | Missing required field raises `ValidationError` | Unit test with partial YAML | Pydantic error with clear field name |
| 3 | Unknown fields are ignored (forward-compatible) | Unit test with extra keys | No error; extra keys discarded |
| 4 | Environment variable overrides work | `REVIEW_PULSE_LLM_MODEL=gpt-4o` override test | Config reflects env value |
| 5 | Config is immutable after load | Attempt to mutate `AppConfig` field | Raises `FrozenInstanceError` |

### E1.3 — Pydantic Data Models

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `Review` model validates all fields | Unit test with valid data | Object created successfully |
| 2 | `Review` rejects invalid rating (0 or 6) | Unit test | `ValidationError` raised |
| 3 | `Review` serialises to JSON and back | `model_dump_json()` → `model_validate_json()` | Round-trip equality |
| 4 | `Theme` model holds theme name, quotes list, action | Unit test | All fields accessible |
| 5 | `RunRecord` captures all audit fields from §9.2 | Compare model fields against SQL schema | 1:1 mapping |

### E1.4 — SQLite Run Log

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | Table creation is idempotent | Call `init_db()` twice | No error; table unchanged |
| 2 | Insert a new run record | `insert_run()` | Row exists with correct fields |
| 3 | Duplicate `(product, iso_week)` insert fails | Insert same key twice | `IntegrityError` raised |
| 4 | Query by product + week returns correct record | `get_run()` | Matching `RunRecord` returned |
| 5 | Update run status (pending → success) | `update_run()` | Status field updated; `completed_at` set |
| 6 | List recent runs with pagination | `list_runs(limit=10)` | Returns ≤10 records, newest first |

### E1.5 — Idempotency Checker

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `check_run_exists()` returns `False` for new run | Unit test | `False` |
| 2 | After `mark_run_complete()`, check returns `True` | Unit test | `True` |
| 3 | Failed runs do not block re-runs | Insert failed run, then check | `False` (only `success` blocks) |

### E1.6 — CLI Skeleton

| # | Check | Method | Pass Condition |
|---|---|---|---|
| 1 | `--help` shows all commands | `python -m review_pulse --help` | `run`, `status` listed |
| 2 | `run --product groww --week 2026-W18` parses args | CLI invocation | Logs "Starting run for groww / 2026-W18" |
| 3 | Invalid ISO week format rejected | `--week 2026-W99` | Clear error message |
| 4 | Missing `--product` flag shows error | Omit flag | Click error with usage hint |

---

## Automated Test Commands

```bash
# Run all Phase 1 tests
pytest tests/test_config.py tests/test_models.py tests/test_run_log.py tests/test_idempotency.py tests/test_cli.py -v

# Lint check
ruff check review_pulse/ && mypy review_pulse/
```

---

## Acceptance Summary

| Area | Weight | Threshold |
|---|---|---|
| Config loads & validates | 20% | 100% of tests pass |
| Data models round-trip | 20% | 100% of tests pass |
| Run log CRUD | 25% | 100% of tests pass |
| Idempotency logic | 20% | 100% of tests pass |
| CLI skeleton | 15% | All commands parse correctly |
