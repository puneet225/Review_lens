"""
Google Docs delivery — creates or updates a weekly review pulse document.

Uses the Google Docs API (v1) with OAuth credentials from gcp_token.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from review_pulse.store.models import AnalysisResult

logger = logging.getLogger(__name__)

# Required scopes
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def _get_credentials() -> Credentials:
    """Load and refresh OAuth credentials from gcp_token.json."""
    token_path = os.environ.get(
        "GOOGLE_OAUTH_TOKEN_PATH",
        str(Path(__file__).resolve().parents[3] / "gcp_token.json"),
    )

    if not Path(token_path).exists():
        raise FileNotFoundError(
            f"gcp_token.json not found at {token_path}. "
            "Run `python generate_token.py` to create it."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds.expired and creds.refresh_token:
        logger.info("🔄 Refreshing expired Google OAuth token...")
        creds.refresh(Request())
        # Save refreshed token
        Path(token_path).write_text(creds.to_json())

    return creds


def _build_document_body(
    product: str,
    iso_week: str,
    analysis: AnalysisResult,
) -> list:
    """
    Build the Google Docs API 'requests' list to populate the document.
    Uses a reverse-insertion strategy at index 1 to avoid index drift and
    'grapheme cluster' errors.
    """
    requests = []
    
    # We want the content to appear in this order:
    # 1. Title
    # 2. Stats
    # 3. Themes...
    
    # To achieve this with reverse insertion at index 1, 
    # we process the blocks from BOTTOM to TOP.
    
    blocks = []

    # --- Themes (processed in reverse order for insertion) ---
    for i, theme in reversed(list(enumerate(analysis.themes, 1))):
        # Divider at the end of each theme
        blocks.append({"text": "\n" + "─" * 40 + "\n\n", "style": "NORMAL_TEXT"})
        
        # Action
        if theme.action:
            blocks.append({"text": f"✅ Recommended Action: {theme.action}\n", "style": "NORMAL_TEXT"})
            
        # Quotes
        if theme.quotes:
            for q in reversed(theme.quotes):
                blocks.append({"text": f"  • \"{q.text}\" — ★{q.rating} ({q.store})\n", "style": "NORMAL_TEXT"})
            blocks.append({"text": "💬 Supporting Quotes:\n", "style": "HEADING_3"})

        # Review count
        blocks.append({"text": f"📊 Reviews in cluster: {theme.review_count}\n", "style": "NORMAL_TEXT"})
        
        # Description
        blocks.append({"text": f"{theme.description}\n", "style": "NORMAL_TEXT"})
        
        # Theme heading
        blocks.append({"text": f"Theme {i}: {theme.name}\n", "style": "HEADING_2"})

    # --- Header Info ---
    blocks.append({
        "text": f"\nWeek: {iso_week} | Reviews Analyzed: {analysis.total_reviews} | "
                f"Themes Found: {len(analysis.themes)} | Tokens Used: {analysis.tokens_used}\n\n",
        "style": "SUBTITLE",
    })
    
    blocks.append({
        "text": f"Weekly Review Pulse — {product.title()}\n",
        "style": "HEADING_1",
    })

    # --- Create Requests ---
    for block in blocks:
        text = block["text"]
        # Always insert at index 1
        requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": text,
            }
        })
        # Style the text we just inserted. 
        # Note: In batchUpdate, these are applied sequentially.
        # But styling by index 1 to 1+len(text) is safer here.
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": 1 + len(text)},
                "paragraphStyle": {"namedStyleType": block["style"]},
                "fields": "namedStyleType",
            }
        })

    return requests


def create_google_doc(
    product: str,
    iso_week: str,
    analysis: AnalysisResult,
) -> str:
    """
    Create a new Google Doc with the weekly review pulse report.

    Args:
        product: Product name.
        iso_week: ISO week string (e.g. '2026-W18').
        analysis: The analysis result to render.

    Returns:
        The Google Doc ID.
    """
    creds = _get_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    title = f"Review Pulse — {product.title()} — {iso_week}"

    # 1. Create empty document
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    logger.info("📄 Created Google Doc: %s (id=%s)", title, doc_id)

    # 2. Populate with content
    body_requests = _build_document_body(product, iso_week, analysis)
    if body_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": body_requests},
        ).execute()
        logger.info("📝 Populated doc with %d themes", len(analysis.themes))

    # 3. Make it accessible via link (anyone with link can view)
    try:
        drive_service.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()
        logger.info("🔗 Doc shared: https://docs.google.com/document/d/%s", doc_id)
    except Exception as e:
        logger.warning("Could not set sharing permissions: %s", e)

    return doc_id
