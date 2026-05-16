"""Ingestion subpackage — app store review scrapers and PII scrubber."""

from review_pulse.ingestion.pipeline import IngestionError, run_ingestion

__all__ = ["run_ingestion", "IngestionError"]
