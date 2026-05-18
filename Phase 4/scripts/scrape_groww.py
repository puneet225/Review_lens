"""
Scrape Groww fee/help pages into a JSONL knowledge base.

This is an OFFLINE / build-time tool. It is not invoked at request time on
Render — the runtime only reads the prebuilt ChromaDB persistence files.

Usage:
    python scripts/scrape_groww.py URL [URL ...] [--out FILE]

    # From a file (one URL per line, '#' for comments)
    python scripts/scrape_groww.py --url-file scripts/urls/groww.txt

Output rows (JSONL at data/knowledge_base/groww.jsonl):
    {
      "chunk_id":     "abc123…",        # stable hash of url + chunk_idx
      "url":          "https://...",
      "section_path": "Charges > Stocks > Brokerage",
      "content":      "Charges > Stocks > Brokerage: <chunk text>",
      "scraped_at":   "2026-05-17T10:30:00Z",
      "chunk_idx":    0,
      "prev_chunk_id": null,
      "next_chunk_id": "def456…"
    }

Strategy: static-first (httpx + BeautifulSoup). If a page comes back with
very little visible text (likely JS-rendered SPA), the script logs a clear
warning and skips it — by design, since Playwright/Chromium can't run on
Render. For dynamic pages, run the just-scrape skill manually and append
its output to the JSONL.

Chunking:
    - Section-aware: each leaf heading (h1-h4) starts a new section.
    - Per section: sentence-boundary splits, sliding window with overlap.
    - Each chunk's content is prefixed with its breadcrumb path so retrieval
      gets parent context even when fetching a deep chunk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("scrape_groww")

_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "knowledge_base" / "groww.jsonl"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# ~500 tokens per chunk @ 4 chars/token; ~200 tokens overlap
_TARGET_CHARS = 2000
_OVERLAP_CHARS = 800
_MIN_STATIC_CHARS = 600
_REQUEST_TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _fetch_static(url: str) -> Optional[str]:
    """Fetch URL with httpx; retries on transient errors. None on hard failure."""
    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"}
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=headers, timeout=_REQUEST_TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return r.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("static fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
            time.sleep(1.5 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _clean_soup(soup: BeautifulSoup) -> None:
    """Strip non-content tags in place."""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "form", "iframe"]):
        tag.decompose()


def _visible_text_len(html: str) -> int:
    s = BeautifulSoup(html, "html.parser")
    _clean_soup(s)
    return len(s.get_text(strip=True))


def _walk_sections(soup: BeautifulSoup) -> List[Tuple[List[str], str]]:
    """Walk the DOM in document order and return list of (heading_path, text).

    `heading_path` is a list of ancestor heading texts (h1..h4) above the
    current content node, deepest last. Sections without explicit headings
    inherit the page title.
    """
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else "(Untitled)"

    heading_stack: List[Tuple[int, str]] = [(0, page_title)]  # (level, text)
    sections: List[Tuple[List[str], List[str]]] = []
    current_path: List[str] = [page_title]
    current_buffer: List[str] = []

    def current_section_path() -> List[str]:
        return [h for _, h in heading_stack]

    def flush() -> None:
        if current_buffer:
            sections.append((current_section_path(), list(current_buffer)))
            current_buffer.clear()

    body = soup.body or soup
    for node in body.descendants:
        if not isinstance(node, Tag):
            continue
        name = node.name.lower()

        if name in {"h1", "h2", "h3", "h4"}:
            flush()
            level = int(name[1])
            # Pop the stack to the parent of this level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_text = node.get_text(" ", strip=True) or f"(h{level})"
            heading_stack.append((level, heading_text))
        elif name in {"p", "li", "td", "th", "dt", "dd", "blockquote", "summary"}:
            text = node.get_text(" ", strip=True)
            if text:
                current_buffer.append(text)

    flush()
    # Collapse buffers into text per section
    return [(path, "\n".join(lines)) for path, lines in sections]


# ---------------------------------------------------------------------------
# Chunking — sentence-aware sliding window with overlap, breadcrumb-prefixed
# ---------------------------------------------------------------------------


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9₹])")


def _split_sentences(text: str) -> List[str]:
    if not text.strip():
        return []
    parts = _SENTENCE_SPLIT.split(text)
    # Trim each, drop empties
    return [p.strip() for p in parts if p.strip()]


def _sliding_chunks(
    text: str,
    target: int = _TARGET_CHARS,
    overlap: int = _OVERLAP_CHARS,
) -> List[str]:
    """Sentence-aware sliding window. Each chunk ≤ target chars, with
    `overlap` chars of trailing context carried into the next chunk.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []
    if sum(len(s) for s in sentences) <= target:
        return [" ".join(sentences)]

    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for s in sentences:
        if buf and buf_len + len(s) + 1 > target:
            chunks.append(" ".join(buf).strip())
            # Build overlap window from the tail of the previous chunk
            tail: List[str] = []
            tail_len = 0
            for prev in reversed(buf):
                if tail_len + len(prev) + 1 > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            buf = list(tail)
            buf_len = tail_len
        buf.append(s)
        buf_len += len(s) + 1

    if buf:
        chunks.append(" ".join(buf).strip())
    return [c for c in chunks if c]


def _format_path(path: List[str]) -> str:
    """Render heading breadcrumb. Dedupes consecutive repeats."""
    out: List[str] = []
    for p in path:
        if not out or out[-1] != p:
            out.append(p)
    return " > ".join(out)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _chunk_id(url: str, idx: int) -> str:
    return hashlib.sha1(f"{url}#{idx}".encode("utf-8")).hexdigest()[:16]


def scrape_one(url: str) -> List[dict]:
    """Fetch + parse + chunk one URL."""
    html = _fetch_static(url)
    if not html:
        logger.error("%s: fetch failed", url)
        return []

    visible_len = _visible_text_len(html)
    if visible_len < _MIN_STATIC_CHARS:
        logger.warning(
            "%s: visible text %d chars < %d — likely JS-rendered. "
            "Skipping (run just-scrape skill manually and append output).",
            url, visible_len, _MIN_STATIC_CHARS,
        )
        return []

    soup = BeautifulSoup(html, "html.parser")
    _clean_soup(soup)
    sections = _walk_sections(soup)
    if not sections:
        logger.warning("%s: parsed 0 sections", url)
        return []

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    records: List[dict] = []
    for path, content in sections:
        chunks = _sliding_chunks(content)
        breadcrumb = _format_path(path)
        for chunk_text in chunks:
            idx = len(records)
            cid = _chunk_id(url, idx)
            records.append({
                "chunk_id": cid,
                "url": url,
                "section_path": breadcrumb,
                # Prefix with breadcrumb so embeddings carry parent context
                "content": f"{breadcrumb}\n\n{chunk_text}",
                "raw_text": chunk_text,
                "scraped_at": now,
                "chunk_idx": idx,
                "prev_chunk_id": None,
                "next_chunk_id": None,
            })

    # Link neighbours within the same URL
    for i, r in enumerate(records):
        if i > 0:
            r["prev_chunk_id"] = records[i - 1]["chunk_id"]
        if i < len(records) - 1:
            r["next_chunk_id"] = records[i + 1]["chunk_id"]

    logger.info("%s: %d sections → %d chunks (visible=%d chars)", url, len(sections), len(records), visible_len)
    return records


def _load_url_file(path: Path) -> List[str]:
    urls: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Groww fee/help pages into a JSONL KB.")
    parser.add_argument("urls", nargs="*", help="URLs to scrape")
    parser.add_argument("--url-file", type=Path, help="File with one URL per line")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output JSONL path")
    parser.add_argument("--append", action="store_true", help="Append instead of overwriting")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    urls: List[str] = list(args.urls)
    if args.url_file:
        urls.extend(_load_url_file(args.url_file))
    urls = list(dict.fromkeys(urls))  # dedupe, preserve order

    if not urls:
        parser.error("Provide URLs as args or via --url-file")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"

    total_chunks = 0
    with args.out.open(mode, encoding="utf-8") as fh:
        for url in urls:
            for rec in scrape_one(url):
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total_chunks += 1

    logger.info("wrote %d chunks from %d URLs to %s", total_chunks, len(urls), args.out)
    return 0 if total_chunks > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
