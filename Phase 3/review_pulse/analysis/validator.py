"""
Quote validator — ensures every quote is an exact substring of a real review.

This is a critical safety layer:
  - Prevents hallucinated quotes from reaching the report
  - Guarantees every published quote can be traced to a real user
"""

from __future__ import annotations

import logging
from typing import List, Optional

from review_pulse.store.models import Review, ValidatedQuote

logger = logging.getLogger(__name__)

# Minimum quote length to avoid trivially short matches
_MIN_QUOTE_LENGTH = 15


def validate_quote(
    candidate: str,
    reviews: List[Review],
) -> Optional[ValidatedQuote]:
    """
    Check if the candidate quote is an exact substring of any review.

    Args:
        candidate: Quote string produced by the LLM.
        reviews: Reviews in the cluster to search within.

    Returns:
        ValidatedQuote if found, None if hallucinated or too short.
    """
    cleaned = candidate.strip()

    if len(cleaned) < _MIN_QUOTE_LENGTH:
        logger.debug("Quote too short (%d chars), skipping: %r", len(cleaned), cleaned)
        return None

    for review in reviews:
        if cleaned in review.body:
            return ValidatedQuote(
                text=cleaned,
                source_review_id=review.review_id,
                store=review.source,
                rating=review.rating,
            )

    logger.debug("Hallucinated quote rejected: %r", cleaned[:60])
    return None


def validate_quotes(
    raw_quotes: List[str],
    reviews: List[Review],
    max_quotes: int = 3,
) -> List[ValidatedQuote]:
    """
    Validate a list of LLM-generated quotes against actual reviews.

    Args:
        raw_quotes: Candidate quotes from the LLM.
        reviews: Reviews in the cluster.
        max_quotes: Maximum number of validated quotes to return.

    Returns:
        List of validated quotes (may be empty if all are hallucinated).
    """
    validated: List[ValidatedQuote] = []
    seen_review_ids: set = set()

    for candidate in raw_quotes:
        if len(validated) >= max_quotes:
            break

        vq = validate_quote(candidate, reviews)
        if vq and vq.source_review_id not in seen_review_ids:
            validated.append(vq)
            seen_review_ids.add(vq.source_review_id)

    if len(validated) < len(raw_quotes):
        hallucinated = len(raw_quotes) - len(validated)
        logger.info(
            "Quote validation: %d/%d valid, %d hallucinated",
            len(validated),
            len(raw_quotes),
            hallucinated,
        )

    return validated
