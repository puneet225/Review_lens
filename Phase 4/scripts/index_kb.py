"""
Build the ChromaDB index from a JSONL knowledge base.

Reads:   data/knowledge_base/{product}.jsonl
Writes:  data/knowledge_base/chroma/   (persistent ChromaDB)

Embeddings come from Gemini's `text-embedding-004` (768-dim). The collection
is named `{product}_fees`. Re-running this script is idempotent — it drops
and recreates the collection so any chunks deleted from the JSONL are
removed from the index.

Usage:
    python scripts/index_kb.py --product groww
    python scripts/index_kb.py --product groww --jsonl path/to/other.jsonl

This is an OFFLINE / build-time tool. The runtime on Render only READS the
persistent chroma directory — it doesn't run this script.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("index_kb")

_KB_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"
_CHROMA_DIR = _KB_DIR / "chroma"
_EMBED_MODEL = "models/gemini-embedding-001"  # Gemini, 3072-dim
_BATCH_SIZE = 16


def _load_env() -> None:
    """Load .env from project root if dotenv is available."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=False)


def _embed_batch(client, texts: List[str], task: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
    """Embed a batch via Gemini.

    Args:
        client: the configured `google.generativeai` module.
        texts:  list of strings to embed.
        task:   "RETRIEVAL_DOCUMENT" for indexing, "RETRIEVAL_QUERY" for queries.
    """
    # text-embedding-004 supports batch via embed_content with a list input
    result = client.embed_content(
        model=_EMBED_MODEL,
        content=texts,
        task_type=task,
    )
    # SDK returns {"embedding": [[...], [...]]} for a list input
    embeddings = result.get("embedding")
    if not embeddings or len(embeddings) != len(texts):
        raise RuntimeError(f"Embedding response shape mismatch: got {len(embeddings or [])}, expected {len(texts)}")
    return embeddings


def index(product: str, jsonl_path: Path, chroma_dir: Path) -> int:
    """Index one JSONL file into ChromaDB. Returns the chunk count."""
    if not jsonl_path.exists():
        logger.error("JSONL not found: %s — run scrape_groww.py first", jsonl_path)
        return 0

    chunks: List[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("skipping malformed line %d: %s", i, exc)

    if not chunks:
        logger.error("%s: no chunks to index", jsonl_path)
        return 0

    # --- Gemini client ---
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set in environment")
        return 0
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # --- Chroma persistent client ---
    import chromadb
    chroma_dir.mkdir(parents=True, exist_ok=True)
    chroma = chromadb.PersistentClient(path=str(chroma_dir))
    collection_name = f"{product}_fees"

    # Drop + recreate so deletes propagate
    try:
        chroma.delete_collection(collection_name)
        logger.info("Dropped existing collection %r", collection_name)
    except (ValueError, Exception):
        pass
    collection = chroma.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    # --- Embed in batches ---
    logger.info("Embedding %d chunks with %s …", len(chunks), _EMBED_MODEL)
    for start in range(0, len(chunks), _BATCH_SIZE):
        batch = chunks[start:start + _BATCH_SIZE]
        texts = [c["content"] for c in batch]
        for attempt in range(4):
            try:
                vectors = _embed_batch(genai, texts, task="RETRIEVAL_DOCUMENT")
                break
            except Exception as exc:
                wait = 2 * (attempt + 1)
                logger.warning("embed batch %d-%d failed: %s — retry in %ds", start, start + len(batch), exc, wait)
                time.sleep(wait)
        else:
            logger.error("giving up on batch starting at %d", start)
            continue

        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=texts,
            embeddings=vectors,
            metadatas=[
                {
                    "url": c["url"],
                    "section_path": c["section_path"],
                    "scraped_at": c["scraped_at"],
                    "chunk_idx": c["chunk_idx"],
                    "prev_chunk_id": c.get("prev_chunk_id") or "",
                    "next_chunk_id": c.get("next_chunk_id") or "",
                    "raw_text": c.get("raw_text", c["content"]),
                }
                for c in batch
            ],
        )
        logger.info("indexed %d/%d", min(start + _BATCH_SIZE, len(chunks)), len(chunks))

    final_count = collection.count()
    logger.info("done. collection %r now has %d documents at %s", collection_name, final_count, chroma_dir)
    return final_count


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Index a knowledge-base JSONL into ChromaDB.")
    parser.add_argument("--product", default="groww", help="Product slug (default: groww)")
    parser.add_argument("--jsonl", type=Path, help="Path to JSONL (default: data/knowledge_base/{product}.jsonl)")
    parser.add_argument("--chroma-dir", type=Path, default=_CHROMA_DIR)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _load_env()
    jsonl_path = args.jsonl or (_KB_DIR / f"{args.product}.jsonl")
    count = index(args.product, jsonl_path, args.chroma_dir)
    return 0 if count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
