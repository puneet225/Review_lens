"""
PII scrubber for review body text.

Uses regex patterns to detect and redact personally identifiable information
before review text is sent to any LLM or external service.

Patterns covered:
  - Phone numbers (Indian + international formats)
  - Email addresses
  - UPI IDs
  - Aadhaar-like 12-digit numbers
  - PAN card numbers (Indian)
  - URLs (with personal tokens)

The scrubbed text is stored in Review.body while the original is preserved
in Review.raw_body (never sent outside the system).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

@dataclass
class PiiPattern:
    name: str
    pattern: re.Pattern
    replacement: str


_PII_PATTERNS: List[PiiPattern] = [
    # Indian mobile numbers: 10-digit starting with 6-9, with or without +91/0
    PiiPattern(
        name="indian_phone",
        pattern=re.compile(
            r"(?<!\d)(?:\+91|0)?[6-9]\d{9}(?!\d)",
            re.IGNORECASE,
        ),
        replacement="[PHONE]",
    ),
    # Generic international phone: +CC followed by 7–14 digits
    PiiPattern(
        name="intl_phone",
        pattern=re.compile(
            r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}",
            re.IGNORECASE,
        ),
        replacement="[PHONE]",
    ),
    # Email addresses
    PiiPattern(
        name="email",
        pattern=re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b",
        ),
        replacement="[EMAIL]",
    ),
    # UPI IDs: anything@upi, anything@okaxis, etc.
    PiiPattern(
        name="upi_id",
        pattern=re.compile(
            r"\b[A-Za-z0-9.\-_+]+@(?:upi|okaxis|oksbi|okhdfcbank|okicici|paytm|ybl|axl|ibl|upi)\b",
            re.IGNORECASE,
        ),
        replacement="[UPI_ID]",
    ),
    # Aadhaar: 12-digit number (4-4-4 groups or continuous)
    PiiPattern(
        name="aadhaar",
        pattern=re.compile(
            r"(?<!\d)(?:\d{4}[\s\-]){2}\d{4}(?!\d)"
            r"|(?<!\d)\d{12}(?!\d)",
        ),
        replacement="[AADHAAR]",
    ),
    # PAN card: AAAAA0000A format (5 letters, 4 digits, 1 letter)
    PiiPattern(
        name="pan_card",
        pattern=re.compile(
            r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        ),
        replacement="[PAN]",
    ),
    # URLs — may contain personal tokens or session IDs
    PiiPattern(
        name="url",
        pattern=re.compile(
            r"https?://\S+",
            re.IGNORECASE,
        ),
        replacement="[URL]",
    ),
]


# ---------------------------------------------------------------------------
# Main scrubber function
# ---------------------------------------------------------------------------


def scrub_pii(text: str) -> Tuple[str, List[str]]:
    """
    Scrub PII from review text.

    Args:
        text: Raw review text.

    Returns:
        A tuple of (scrubbed_text, list_of_detected_pattern_names).
    """
    if not text:
        return text, []

    scrubbed = text
    detected: List[str] = []

    for pii in _PII_PATTERNS:
        new_text, count = pii.pattern.subn(pii.replacement, scrubbed)
        if count > 0:
            detected.append(pii.name)
            scrubbed = new_text
            logger.debug("PII pattern '%s' matched %d time(s)", pii.name, count)

    return scrubbed, detected


def scrub_review_body(body: str) -> str:
    """Convenience wrapper — returns only the scrubbed text."""
    scrubbed, _ = scrub_pii(body)
    return scrubbed
