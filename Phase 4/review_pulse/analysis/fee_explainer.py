"""
Fee Explainer — RAG-based.

For each theme produced by the summariser:
    1. Build a query from the theme (name + description + first 3 quotes).
    2. Embed it with Gemini (gemini-embedding-001) and query the ChromaDB
       collection {product}_fees built offline by scripts/index_kb.py.
    3. Gate: if the best chunk's distance is above _MAX_DISTANCE the theme
       isn't about fees — skip, leaving theme.fee_explainer = None.
    4. Pass the surviving chunks verbatim to the LLM and ask it to
       synthesise ≤6 neutral, facts-only bullets grounded ONLY in the
       chunks. The LLM also picks which chunk_ids it relied on.
    5. Source URLs = the top distinct URLs among the cited chunks (1-3).
    6. last_checked = max(scraped_at) across cited chunks.

The runtime never scrapes. It only reads ChromaDB + calls Gemini for query
embeddings + Groq for synthesis. This keeps the Render deploy lightweight.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from review_pulse.analysis.classifier import OTHER_KEY
from review_pulse.store.models import FeeExplainer, Theme

logger = logging.getLogger(__name__)

_CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_base" / "chroma"
_EMBED_MODEL = "models/gemini-embedding-001"
_GROQ_MODEL = "llama-3.3-70b-versatile"

# Cosine distance threshold. Chroma uses distance = 1 - cosine_similarity.
# Tight: only themes that clearly land on fee content survive. A higher
# value over-attaches because every Groww theme shares vocabulary with the
# Groww-only corpus.
_MAX_DISTANCE = 0.32
# Themes whose sentiment isn't NEGATIVE or MIXED don't represent confusion —
# the spec's "1 recurring confusion/pain point related to a fee/charge" rules
# out positive/neutral themes even if their text overlaps the fee corpus.
_GATED_SENTIMENTS = {"NEGATIVE", "MIXED"}
_TOP_K = 6
_STALE_AFTER_DAYS = 90

# Lazy cache of the Chroma collection per product
_collections: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_collection(product: str):
    """Open (and cache) the {product}_fees ChromaDB collection."""
    if product in _collections:
        return _collections[product]
    if not _CHROMA_DIR.exists():
        logger.info("Chroma dir %s missing — fee explainer disabled (run scripts/index_kb.py)", _CHROMA_DIR)
        _collections[product] = None
        return None
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        name = f"{product}_fees"
        col = client.get_collection(name)
        _collections[product] = col
        logger.info("Loaded Chroma collection %r (%d docs)", name, col.count())
        return col
    except Exception as exc:
        logger.warning("Could not open Chroma collection for %s: %s", product, exc)
        _collections[product] = None
        return None


def _theme_query(theme: Theme) -> str:
    """Build the retrieval query for a theme."""
    parts: List[str] = [theme.name or ""]
    if theme.description:
        parts.append(theme.description)
    for q in theme.quotes[:3]:
        if q.text:
            parts.append(q.text)
    return " ".join(p for p in parts if p)


def _embed_query(text: str) -> Optional[List[float]]:
    """Embed query text with Gemini. Returns None on failure."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.debug("GEMINI_API_KEY missing — fee explainer skipped")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        result = genai.embed_content(
            model=_EMBED_MODEL,
            content=text,
            task_type="RETRIEVAL_QUERY",
        )
        return result.get("embedding")
    except Exception as exc:
        logger.warning("Gemini query embedding failed: %s", exc)
        return None


def _retrieve(theme: Theme, collection) -> List[Dict[str, Any]]:
    """Retrieve top-k chunks for a theme. Returns list of dicts with
    {id, distance, document, metadata}."""
    query = _theme_query(theme)
    vec = _embed_query(query)
    if not vec:
        return []

    try:
        res = collection.query(
            query_embeddings=[vec],
            n_results=_TOP_K,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Chroma query failed: %s", exc)
        return []

    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    chunks: List[Dict[str, Any]] = []
    for i, cid in enumerate(ids):
        d = dists[i] if i < len(dists) else 1.0
        if d > _MAX_DISTANCE:
            continue
        chunks.append({
            "chunk_id": cid,
            "distance": d,
            "document": docs[i] if i < len(docs) else "",
            "metadata": metas[i] if i < len(metas) else {},
        })
    return chunks


# ---------------------------------------------------------------------------
# LLM synthesis — strictly grounded
# ---------------------------------------------------------------------------


_SYNTH_SYSTEM = (
    "You synthesise neutral, facts-only fee explainers for a fintech product reviewer.\n"
    "You will receive a user-review theme plus numbered fact chunks scraped from the\n"
    "product's official pages. Your output MUST be a JSON object that follows the schema below.\n"
    "\n"
    "STRICT RULES:\n"
    "- Each bullet MUST be derivable from the provided chunks. Do NOT introduce facts\n"
    "  that are not in the chunks. If a fact is not in the chunks, leave it out.\n"
    "- Tone: neutral, third-person, no marketing adjectives, no superlatives, no\n"
    "  comparisons to other products. Just facts and numbers.\n"
    "- ≤6 bullets, each a single sentence.\n"
    "- 'used_chunk_ids' must list ONLY chunk_ids you actually relied on for the bullets.\n"
    "- 'title' is a short noun phrase that summarises the topic (≤8 words).\n"
    "- Reply ONLY with valid JSON. No markdown, no commentary.\n"
    "\n"
    "JSON schema:\n"
    "{\n"
    '  "title": "string (≤8 words)",\n'
    '  "bullets": ["string", ...],\n'
    '  "used_chunk_ids": ["chunk_id_1", "chunk_id_2", ...]\n'
    "}"
)


def _synthesise(theme: Theme, chunks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ask the LLM to write the structured explainer from retrieved chunks."""
    try:
        from groq import Groq
    except ImportError:
        logger.debug("Groq SDK unavailable — fee explainer synthesis skipped")
        return None

    keys = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]
    if not keys:
        logger.debug("No Groq keys — fee explainer synthesis skipped")
        return None

    fact_lines: List[str] = []
    for c in chunks:
        meta = c.get("metadata") or {}
        fact_lines.append(
            f"chunk_id: {c['chunk_id']}\n"
            f"section: {meta.get('section_path','')}\n"
            f"source: {meta.get('url','')}\n"
            f"content: {c.get('document','')}\n"
            f"---"
        )
    quotes_blob = " | ".join(q.text for q in theme.quotes[:3])
    user_prompt = (
        f"Theme name: {theme.name}\n"
        f"Theme description: {theme.description}\n"
        f"Sample user quotes (verbatim review snippets): {quotes_blob}\n\n"
        f"Fact chunks (numbered, with sources):\n\n"
        + "\n".join(fact_lines)
        + "\n\nGenerate the JSON explainer per the schema."
    )

    try:
        client = Groq(api_key=keys[0])
        resp = client.chat.completions.create(
            messages=[
                {"role": "system", "content": _SYNTH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=_GROQ_MODEL,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.warning("Fee synthesis LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Assemble FeeExplainer from synthesis + chunks
# ---------------------------------------------------------------------------


def _pick_sources(used_chunks: List[Dict[str, Any]]) -> List[str]:
    """Pick up to 3 distinct URLs from the used chunks, ordered by relevance."""
    seen: List[str] = []
    for c in used_chunks:
        url = (c.get("metadata") or {}).get("url")
        if url and url not in seen:
            seen.append(url)
        if len(seen) >= 3:
            break
    return seen


def _max_last_checked(used_chunks: List[Dict[str, Any]]) -> date:
    """Most recent scraped_at across used chunks, as a date."""
    best: Optional[date] = None
    for c in used_chunks:
        ts = (c.get("metadata") or {}).get("scraped_at", "")
        try:
            d = datetime.fromisoformat(ts).date()
        except (ValueError, TypeError):
            continue
        if best is None or d > best:
            best = d
    return best or date.today()


def _build_explainer(
    theme: Theme,
    chunks: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
) -> Optional[FeeExplainer]:
    """Validate the LLM output and build a FeeExplainer."""
    title = (synthesis.get("title") or "").strip()
    bullets = [b.strip() for b in (synthesis.get("bullets") or []) if isinstance(b, str) and b.strip()]
    used_ids = synthesis.get("used_chunk_ids") or []

    if not bullets:
        logger.info("Theme %r: synthesis returned no bullets — skipping explainer", theme.name)
        return None
    if not title:
        title = theme.name or "Fee details"
    bullets = bullets[:6]

    chunk_by_id = {c["chunk_id"]: c for c in chunks}
    used_chunks = [chunk_by_id[i] for i in used_ids if i in chunk_by_id]
    if not used_chunks:
        # LLM didn't cite — fall back to the top-ranked chunks.
        used_chunks = chunks[:3]

    sources = _pick_sources(used_chunks)
    if not sources:
        logger.info("Theme %r: no source URLs in cited chunks — skipping explainer", theme.name)
        return None

    last_checked = _max_last_checked(used_chunks)
    is_stale = (date.today() - last_checked).days > _STALE_AFTER_DAYS

    try:
        return FeeExplainer(
            topic_id="rag:" + (used_chunks[0]["metadata"] or {}).get("section_path", "unknown")[:60],
            title=title[:80],
            bullets=bullets,
            source_urls=sources,
            last_checked=last_checked,
            is_stale=is_stale,
        )
    except Exception as exc:
        logger.warning("Theme %r: FeeExplainer validation failed: %s", theme.name, exc)
        return None


# ---------------------------------------------------------------------------
# Public entry point — matches the previous signature so pipeline.py is unchanged
# ---------------------------------------------------------------------------


def enrich_themes(themes: List[Theme], product: str) -> List[Theme]:
    """Attach a RAG-derived FeeExplainer to each theme that has a strong match
    in the {product}_fees Chroma collection.

    Mutates and returns the input list. Themes without a strong retrieval match
    keep fee_explainer = None (no fabrication).
    """
    collection = _get_collection(product)
    if collection is None:
        return themes

    for theme in themes:
        # Category gate: the residual Other bucket is a grab-bag of unclassified
        # reviews and must never receive curated fee guidance, even if its text
        # happens to be semantically close to the fee corpus.
        if theme.category_key == OTHER_KEY:
            logger.debug(
                "Theme %r: category_key=%r is the Other bucket — skipping fee explainer",
                theme.name, OTHER_KEY,
            )
            continue
        # Sentiment gate: confusion themes only.
        if theme.sentiment not in _GATED_SENTIMENTS:
            logger.debug(
                "Theme %r: sentiment=%s not in %s — skipping fee explainer",
                theme.name, theme.sentiment, _GATED_SENTIMENTS,
            )
            continue
        chunks = _retrieve(theme, collection)
        if not chunks:
            logger.info(
                "Theme %r: no chunks under distance %.2f — not a fee topic",
                theme.name, _MAX_DISTANCE,
            )
            continue
        synthesis = _synthesise(theme, chunks)
        if not synthesis:
            continue
        explainer = _build_explainer(theme, chunks, synthesis)
        if explainer:
            theme.fee_explainer = explainer
            logger.info(
                "Fee explainer attached: theme=%r → %d bullets, %d sources, top_distance=%.3f%s",
                theme.name,
                len(explainer.bullets),
                len(explainer.source_urls),
                chunks[0]["distance"],
                " [STALE]" if explainer.is_stale else "",
            )

    return themes
