"""Analysis subpackage — embeddings, clustering, LLM summarisation, and validation."""

from review_pulse.analysis.pipeline import AnalysisError, run_analysis

__all__ = ["run_analysis", "AnalysisError"]
