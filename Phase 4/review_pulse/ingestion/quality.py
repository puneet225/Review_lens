"""
Review quality filter — applied during scraping.

Cheap structural checks to drop reviews that carry no analytical signal:

  - too_short      length < MIN_CHARS
  - no_letters     emoji-only, digit-only, or punctuation-only
  - low_entropy    "aaaaaa", "kkkkkkk", "abababab" — character-level mashing
  - no_words       single run-on token, no whitespace separation
  - word_repeated  same token over and over: "asdfg asdfg asdfg"
  - generic_only   only stock praise/criticism: "good good good", "wow nice 👍"

Note on off-topic ("not related to the app") detection:
  Truly semantic relevance needs embeddings, so it is *not* done here.
  Off-topic reviews end up as HDBSCAN noise during analysis and are
  excluded from theme summarisation by `analysis/pipeline.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# ── Tunables ───────────────────────────────────────────────────────────────
MIN_CHARS: Final[int] = 15
MIN_LETTERS: Final[int] = 8
MIN_UNIQUE_CHAR_RATIO: Final[float] = 0.30
MIN_WORDS: Final[int] = 2

# Stock single-word praise/criticism. A review composed entirely of these
# tokens (in any combination, with punctuation/digits/emoji between) is
# treated as content-free.
_GENERIC_TOKENS: Final[str] = (
    "good|nice|ok|okay|okk|okayish|bad|wow|cool|love|loved|hate|hated|"
    "fine|great|greatt|awesome|best|worst|super|excellent|amazing|"
    "poor|fantastic|wonderful|perfect|useless|trash|garbage|crap|"
    "yes|no|nope|yep|hi|hello|thanks|thx|nice1|good1"
)
_GENERIC_ONLY_RE: Final[re.Pattern] = re.compile(
    rf"[\W\d_]*(?:(?:{_GENERIC_TOKENS})[\W\d_]*)+",
    re.IGNORECASE,
)

# Unicode-aware: matches any letter (Latin, Devanagari, etc.), excluding digits/underscore.
_LETTER_RE: Final[re.Pattern] = re.compile(r"[^\W\d_]", re.UNICODE)
_WORD_RE: Final[re.Pattern] = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


@dataclass(frozen=True)
class QualityVerdict:
    keep: bool
    reason: str  # "ok" | one of the rejection reasons listed in the module docstring


_OK = QualityVerdict(True, "ok")


def assess(text: str) -> QualityVerdict:
    """Return a verdict on whether `text` carries enough signal to keep."""
    cleaned = (text or "").strip()

    if len(cleaned) < MIN_CHARS:
        return QualityVerdict(False, "too_short")

    letters = _LETTER_RE.findall(cleaned)
    if len(letters) < MIN_LETTERS:
        return QualityVerdict(False, "no_letters")

    letter_blob = "".join(letters).lower()
    if len(set(letter_blob)) / len(letter_blob) < MIN_UNIQUE_CHAR_RATIO:
        return QualityVerdict(False, "low_entropy")

    words = _WORD_RE.findall(cleaned)
    if len(words) < MIN_WORDS:
        return QualityVerdict(False, "no_words")

    if len({w.lower() for w in words}) == 1:
        return QualityVerdict(False, "word_repeated")

    if _GENERIC_ONLY_RE.fullmatch(cleaned):
        return QualityVerdict(False, "generic_only")

    return _OK
