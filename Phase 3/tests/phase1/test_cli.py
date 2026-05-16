"""Tests for the CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from review_pulse.cli import main

VALID_CONFIG = {
    "products": [
        {
            "name": "groww",
            "appstore_id": "1404684442",
            "playstore_id": "com.nextbillion.groww",
            "doc_title": "Weekly Review Pulse — Groww",
            "stakeholder_emails": ["team@example.com"],
        }
    ],
}


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(VALID_CONFIG))
    return p


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "backfill" in result.output
        assert "status" in result.output

    def test_run_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--product" in result.output
        assert "--week" in result.output
        assert "--dry-run" in result.output

    def test_run_invalid_week_format(self, config_file: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(config_file), "run", "-p", "groww", "-w", "2026-W99"])
        assert result.exit_code != 0
        assert "1–53" in result.output or "Invalid" in result.output

    def test_run_missing_config(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(tmp_path / "nope.yaml"), "run", "-p", "groww", "-w", "2026-W18"])
        assert result.exit_code != 0
        assert "Config error" in result.output or "not found" in result.output

    def test_run_unknown_product(self, config_file: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(config_file), "run", "-p", "unknown", "-w", "2026-W18"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_run_dry_run_succeeds(self, config_file: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--config", str(config_file), "run", "-p", "groww", "-w", "2026-W18", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "dry_run" in result.output or "Run result" in result.output

    def test_status_empty_db(self, config_file: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(config_file), "status"])
        assert result.exit_code == 0
        assert "No runs" in result.output or "Product" in result.output

    def test_backfill_reversed_range(self, config_file: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--config", str(config_file), "backfill", "-p", "groww", "--from-week", "2026-W18", "--to-week", "2026-W15"],
        )
        assert result.exit_code != 0
