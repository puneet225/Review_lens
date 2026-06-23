"""
Pydantic data models for the Review Pulse system.

Defines the core data structures that flow through the pipeline:
    Review → (clustering) → Theme → AnalysisResult → RunRecord
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from typing import Literal, Optional, List, Union
from uuid import uuid4

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class Review(BaseModel):
    """A single normalised app store review."""

    source: Literal["appstore", "playstore"]
    product: str
    rating: int = Field(..., ge=1, le=5, description="Star rating 1–5")
    title: Optional[str] = Field(None, description="Review title (App Store only)")
    body: str = Field("", description="Review body text (scrubbed)")
    date: datetime
    review_id: str = Field("", description="Unique ID from store; auto-generated if empty")
    version: Optional[str] = Field(None, description="App version the review refers to")
    raw_body: str = Field("", description="Original body before PII scrubbing — never sent to LLM")

    @field_validator("body", "raw_body", mode="before")
    @classmethod
    def normalise_text(cls, v: Optional[str]) -> str:
        """Normalise Unicode to NFC, strip control characters."""
        if v is None:
            return ""
        text = unicodedata.normalize("NFC", v)
        # Strip zero-width and control chars (keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202f\ufeff]", "", text)
        return text

    @field_validator("rating", mode="before")
    @classmethod
    def coerce_rating(cls, v: Union[int, float]) -> int:
        """Coerce float ratings to int."""
        if isinstance(v, float):
            return round(v)
        return v

    @model_validator(mode="after")
    def ensure_review_id(self) -> "Review":
        """Generate a deterministic review_id if not provided by the store."""
        if not self.review_id:
            seed = f"{self.source}:{self.product}:{self.body}:{self.date.isoformat()}"
            object.__setattr__(self, "review_id", hashlib.sha256(seed.encode()).hexdigest()[:16])
        return self

    @field_validator("body", mode="after")
    @classmethod
    def truncate_long_body(cls, v: str) -> str:
        """Truncate extremely long reviews (>5000 chars)."""
        max_len = 5000
        if len(v) > max_len:
            return v[:max_len] + " [TRUNCATED]"
        return v


# ---------------------------------------------------------------------------
# Analysis output
# ---------------------------------------------------------------------------


class ValidatedQuote(BaseModel):
    """A quote that has been verified as an exact substring of a source review."""

    text: str = Field(..., min_length=1, description="The exact quote text")
    source_review_id: str = Field(..., description="ID of the review this quote comes from")
    store: Literal["appstore", "playstore"]
    rating: int = Field(..., ge=1, le=5)


Sentiment = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"]


class FeeExplainer(BaseModel):
    """Curated fact card attached to themes that match a known fee/charges topic.

    Bullets and source URLs come from the curated YAML in data/fee_facts/{product}.yaml.
    The LLM never generates these — it only picks the matching topic_id.
    """

    topic_id: str = Field(..., description="Matching topic_id from the fee_facts YAML")
    title: str = Field(..., description="Fact card title from YAML")
    bullets: List[str] = Field(..., min_length=1, max_length=6, description="≤6 neutral facts")
    source_urls: List[AnyHttpUrl] = Field(..., min_length=1, max_length=3, description="1–3 official sources (target: 2)")
    last_checked: date = Field(..., description="When the curator last verified the facts")
    is_stale: bool = Field(False, description="True if last_checked is older than 90 days")


class Theme(BaseModel):
    """A named cluster theme with supporting evidence."""

    name: str = Field(..., min_length=1, max_length=60, description="Short theme name (≤6 words)")
    description: str = Field("", description="One-line theme description")
    sentiment: Optional[Sentiment] = Field(None, description="POSITIVE/NEGATIVE/MIXED/NEUTRAL")
    quotes: List[ValidatedQuote] = Field(default_factory=list, description="2–3 validated quotes")
    action: Optional[str] = Field(None, description="One actionable recommendation, or None for NEUTRAL clusters")
    review_count: int = Field(0, ge=0, description="Number of reviews in this cluster")
    category_key: Optional[str] = Field(None, description="Stable category key (e.g. 'fees'); None for fallback themes")
    fee_explainer: Optional[FeeExplainer] = Field(None, description="Attached when theme matches a curated fee topic")


class AnalysisResult(BaseModel):
    """Complete output of the analysis pipeline for a single run."""

    themes: List[Theme] = Field(default_factory=list)
    total_reviews: int = Field(0, ge=0)
    noise_count: int = Field(0, ge=0, description="Reviews not assigned to any cluster")
    tokens_used: int = Field(0, ge=0, description="Total LLM tokens consumed")
    is_partial: bool = Field(False, description="True if analysis was truncated (e.g. token budget)")
    fallback_used: bool = Field(False, description="True if TF-IDF fallback was used instead of clustering")


# ---------------------------------------------------------------------------
# Run record (audit log)
# ---------------------------------------------------------------------------


class RunRecord(BaseModel):
    """Audit record for a single pipeline execution."""

    id: str = Field(default_factory=lambda: uuid4().hex, description="Run UUID")
    product: str
    iso_week: str = Field(..., pattern=r"^\d{4}-W\d{2}$", description="ISO week e.g. 2026-W18")
    status: Literal["pending", "success", "failed", "partial_success", "interrupted", "dry_run"] = "pending"
    reviews_count: Optional[int] = None
    themes_count: Optional[int] = None
    doc_id: Optional[str] = None
    doc_heading: Optional[str] = None
    gmail_msg_id: Optional[str] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    @field_validator("iso_week", mode="before")
    @classmethod
    def normalise_iso_week(cls, v: str) -> str:
        """Normalise ISO week to zero-padded format (2026-W8 → 2026-W08)."""
        match = re.match(r"^(\d{4})-W(\d{1,2})$", v)
        if not match:
            raise ValueError(f"Invalid ISO week format: {v!r}. Expected format: 2026-W18")
        year, week = match.groups()
        week_num = int(week)
        if week_num < 1 or week_num > 53:
            raise ValueError(f"ISO week number must be 1–53, got {week_num}")
        return f"{year}-W{week_num:02d}"
