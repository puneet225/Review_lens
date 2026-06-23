"""Tests for configuration loading and validation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from review_pulse.agent.config import AppConfig, load_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    "ingestion": {"window_weeks": 12, "max_reviews_per_source": 500},
    "analysis": {"llm_model": "gemini-2.5-flash", "max_tokens_per_run": 50000},
    "delivery": {"mode": "draft"},
    "schedule": {"cron": "0 8 * * MON", "timezone": "Asia/Kolkata"},
}


def _write_yaml(data: dict, path: Path) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False))


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    _write_yaml(VALID_CONFIG, tmp_path / "config.yaml")
    return tmp_path


# ---------------------------------------------------------------------------
# E1.2 — Configuration System
# ---------------------------------------------------------------------------


class TestConfigLoading:
    """E1.2.1–E1.2.5: Config loading and validation."""

    def test_valid_config_loads(self, config_dir: Path) -> None:
        cfg = load_config(config_dir / "config.yaml")
        assert len(cfg.products) == 1
        assert cfg.products[0].name == "groww"
        assert cfg.ingestion.window_weeks == 12

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="config.yaml not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_config(tmp_path / "config.yaml")

    def test_missing_products_raises(self, tmp_path: Path) -> None:
        _write_yaml({"ingestion": {"window_weeks": 8}}, tmp_path / "config.yaml")
        with pytest.raises(ValidationError):
            load_config(tmp_path / "config.yaml")

    def test_empty_products_list_raises(self, tmp_path: Path) -> None:
        data = {**VALID_CONFIG, "products": []}
        _write_yaml(data, tmp_path / "config.yaml")
        with pytest.raises(ValidationError, match="at least"):
            load_config(tmp_path / "config.yaml")

    def test_duplicate_product_names_raises(self, tmp_path: Path) -> None:
        product = VALID_CONFIG["products"][0].copy()
        data = {**VALID_CONFIG, "products": [product, product]}
        _write_yaml(data, tmp_path / "config.yaml")
        with pytest.raises(ValidationError, match="Duplicate"):
            load_config(tmp_path / "config.yaml")

    def test_unknown_fields_ignored(self, tmp_path: Path) -> None:
        data = {**VALID_CONFIG, "future_field": "hello"}
        _write_yaml(data, tmp_path / "config.yaml")
        cfg = load_config(tmp_path / "config.yaml")
        assert len(cfg.products) == 1

    def test_env_override_llm_model(self, config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REVIEW_PULSE_LLM_MODEL", "gpt-4o")
        cfg = load_config(config_dir / "config.yaml")
        assert cfg.analysis.llm_model == "gpt-4o"

    def test_config_is_frozen(self, config_dir: Path) -> None:
        cfg = load_config(config_dir / "config.yaml")
        with pytest.raises(ValidationError):
            cfg.products = []  # type: ignore[misc]

    def test_invalid_email_raises(self, tmp_path: Path) -> None:
        data = {**VALID_CONFIG}
        data["products"] = [
            {**VALID_CONFIG["products"][0], "stakeholder_emails": ["not-an-email"]}
        ]
        _write_yaml(data, tmp_path / "config.yaml")
        with pytest.raises(ValidationError, match="Invalid email"):
            load_config(tmp_path / "config.yaml")

    def test_invalid_window_weeks_raises(self, tmp_path: Path) -> None:
        data = {**VALID_CONFIG, "ingestion": {"window_weeks": 0}}
        _write_yaml(data, tmp_path / "config.yaml")
        with pytest.raises(ValidationError):
            load_config(tmp_path / "config.yaml")

    def test_get_product_found(self, config_dir: Path) -> None:
        cfg = load_config(config_dir / "config.yaml")
        p = cfg.get_product("groww")
        assert p.name == "groww"

    def test_get_product_not_found(self, config_dir: Path) -> None:
        cfg = load_config(config_dir / "config.yaml")
        with pytest.raises(ValueError, match="not found"):
            cfg.get_product("nonexistent")

    def test_product_without_any_source_raises(self, tmp_path: Path) -> None:
        data = {**VALID_CONFIG}
        data["products"] = [
            {"name": "nosource", "doc_title": "Test", "stakeholder_emails": []}
        ]
        _write_yaml(data, tmp_path / "config.yaml")
        with pytest.raises(ValidationError, match="at least one"):
            load_config(tmp_path / "config.yaml")


def test_analysis_config_has_category_threshold_default():
    from review_pulse.agent.config import AnalysisConfig
    cfg = AnalysisConfig()
    assert cfg.category_match_threshold == 0.30
