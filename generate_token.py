"""
One-time script to generate gcp_token.json from gcp_oauth.json.

Usage:
    python generate_token.py

This will open your browser, ask you to log in to Google,
and save the token to gcp_token.json.
"""

import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# ALL scopes needed for Google Docs, Drive, and Gmail
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

CREDENTIALS_PATH = Path("gcp_oauth.json")
TOKEN_PATH = Path("gcp_token.json")


def main():
    if not CREDENTIALS_PATH.exists():
        print(f"❌ {CREDENTIALS_PATH} not found!")
        print("   Download it from GCP Console > APIs & Services > Credentials")
        return

    # Always delete the old token to force a fresh login with the new scopes
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print("🗑️  Deleted old gcp_token.json (scopes have changed — need fresh login)")

    print("🌐 Opening browser for Google login...")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES
    )
    creds = flow.run_local_server(port=0)

    # Save the token
    TOKEN_PATH.write_text(creds.to_json())
    print(f"✅ Token saved to {TOKEN_PATH}")
    print(f"   Scopes granted: {', '.join(creds.scopes or SCOPES)}")


if __name__ == "__main__":
    main()
