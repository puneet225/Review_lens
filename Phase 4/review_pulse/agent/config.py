"""
Application configuration — loads and validates config.yaml.

Uses Pydantic v2 for schema validation with environment variable overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional, List, Dict, Union

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ProductConfig(BaseModel):
    """Configuration for a single tracked product."""

    name: str = Field(..., min_length=1, description="Unique product identifier (lowercase slug)")
    appstore_id: Optional[str] = Field(None, description="Apple App Store numeric ID")
    playstore_id: Optional[str] = Field(None, description="Google Play package name")
    doc_title: str = Field(..., min_length=1, description="Title of the running Google Doc")
    stakeholder_emails: List[str] = Field(default_factory=list, description="Email recipients for the pulse")

    @field_validator("stakeholder_emails", mode="before")
    @classmethod
    def validate_emails(cls, v: List[str]) -> List[str]:
        """Basic email format validation."""
        import re

        pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        for email in v:
            if not pattern.match(email):
                raise ValueError(f"Invalid email format: {email!r}")
        return v

    @model_validator(mode="after")
    def at_least_one_source(self) -> "ProductConfig":
        """Ensure at least one store source is configured."""
        if not self.appstore_id and not self.playstore_id:
            raise ValueError(f"Product '{self.name}' must have at least one of appstore_id or playstore_id")
        return self


class IngestionConfig(BaseModel):
    """Settings for the review ingestion pipeline."""

    window_weeks: int = Field(12, ge=1, le=52, description="Rolling window in weeks")
    max_reviews_per_source: int = Field(500, ge=1, le=10000, description="Cap per store source")


class AnalysisConfig(BaseModel):
    """Settings for the clustering and LLM analysis pipeline."""

    embedding_model: str = Field("all-MiniLM-L6-v2", description="Sentence-Transformers model name")
    umap_n_components: int = Field(15, ge=2, le=100)
    umap_n_neighbors: int = Field(20, ge=2, le=200)
    umap_min_dist: float = Field(0.0, ge=0.0, le=1.0)
    umap_metric: str = Field("cosine")
    hdbscan_min_cluster_size: int = Field(5, ge=2, le=100)
    hdbscan_min_samples: int = Field(3, ge=1, le=50)
    llm_model: str = Field("gemini-2.5-flash", description="LLM model identifier")
    max_tokens_per_run: int = Field(50_000, ge=100, le=500_000)
    max_themes: int = Field(8, ge=1, le=20)
    category_match_threshold: float = Field(0.30, ge=0.0, le=1.0, description="Min cosine sim to assign a review to a fixed category; below → Other")


class DeliveryConfig(BaseModel):
    """Settings for MCP-based delivery."""

    mode: Literal["draft", "send"] = Field("draft", description="Email delivery mode")
    mcp_config_path: str = Field("./mcp_servers.json", description="Path to MCP server config")


class ScheduleConfig(BaseModel):
    """Settings for the cron scheduler."""

    cron: str = Field("0 8 * * MON", description="Cron expression for scheduled runs")
    timezone: str = Field("Asia/Kolkata", description="IANA timezone")


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------


class AppConfig(BaseSettings):
    """
    Root application configuration.

    Immutable after construction (frozen=True). Loaded from config.yaml
    with optional environment variable overrides.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    products: List[ProductConfig] = Field(..., min_length=1, description="At least one product required")
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)

    @field_validator("products", mode="after")
    @classmethod
    def unique_product_names(cls, v: List[ProductConfig]) -> List[ProductConfig]:
        """Ensure no duplicate product names."""
        names = [p.name for p in v]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise ValueError(f"Duplicate product name: {name!r}")
            seen.add(name)
        return v

    def get_product(self, name: str) -> ProductConfig:
        """Look up a product by name, raising ValueError if not found."""
        for p in self.products:
            if p.name == name:
                return p
        available = [p.name for p in self.products]
        raise ValueError(f"Product {name!r} not found in config. Available: {available}")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = "config.yaml"


def _apply_env_overrides(raw: Dict) -> Dict:
    """Apply manual overrides if needed (BaseSettings handles .env and process env)."""
    return raw


def load_config(path: Optional[Union[str, Path]] = None) -> AppConfig:
    """
    Load and validate configuration from a YAML file.

    Args:
        path: Path to config.yaml. Defaults to ./config.yaml.

    Returns:
        Validated, frozen AppConfig instance.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the file contains invalid YAML.
        pydantic.ValidationError: If the config fails schema validation.
    """
    config_path = Path(path) if path else Path(_DEFAULT_CONFIG_PATH)

    if not config_path.exists():
        raise FileNotFoundError(
            f"config.yaml not found at {config_path.resolve()}. "
            "Copy config.sample.yaml to get started."
        )

    text = config_path.read_text(encoding="utf-8-sig")  # Handles BOM

    if not text.strip():
        raise ValueError("Configuration file is empty")

    raw = yaml.safe_load(text)

    if not isinstance(raw, dict):
        raise ValueError("Configuration file must contain a YAML mapping (dict)")

    raw = _apply_env_overrides(raw)

    config = AppConfig.model_validate(raw)

    # Export GEMINI_API_KEY specifically if it was loaded from .env/process-env
    # so downstream analysis modules can see it via os.environ.
    if hasattr(config, "analysis") and config.analysis.llm_model:
        # Pydantic Settings handles the .env lookup; we just sync it to process env
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key

    return config
