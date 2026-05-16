"""
SQLite-based run audit log.

Provides async CRUD operations for tracking pipeline runs.
Uses WAL mode for better concurrent read performance.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Union

import aiosqlite

from review_pulse.store.models import RunRecord

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS run_log (
    id              TEXT PRIMARY KEY,
    product         TEXT NOT NULL,
    iso_week        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    reviews_count   INTEGER,
    themes_count    INTEGER,
    doc_id          TEXT,
    doc_heading     TEXT,
    gmail_msg_id    TEXT,
    tokens_used     INTEGER,
    cost_usd        REAL,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    error_message   TEXT,
    UNIQUE(product, iso_week)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_run_log_product_week
ON run_log (product, iso_week);
"""

_DEFAULT_DB_PATH = "data/run_log.db"


class RunLog:
    """Async SQLite-backed run audit log."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        self._db_path = Path(db_path) if db_path else Path(_DEFAULT_DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        """Create the database file and table if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.commit()
        logger.info("Run log database initialised at %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_connected(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("RunLog not initialised. Call init_db() first.")
        return self._db

    # -- CRUD ---------------------------------------------------------------

    async def insert_run(self, record: RunRecord) -> None:
        """Insert a new run record. Raises IntegrityError on duplicate (product, iso_week)."""
        db = self._ensure_connected()
        await db.execute(
            """
            INSERT INTO run_log
                (id, product, iso_week, status, reviews_count, themes_count,
                 doc_id, doc_heading, gmail_msg_id, tokens_used, cost_usd,
                 created_at, completed_at, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.product,
                record.iso_week,
                record.status,
                record.reviews_count,
                record.themes_count,
                record.doc_id,
                record.doc_heading,
                record.gmail_msg_id,
                record.tokens_used,
                record.cost_usd,
                record.created_at.isoformat(),
                record.completed_at.isoformat() if record.completed_at else None,
                record.error_message,
            ),
        )
        await db.commit()
        logger.debug("Inserted run %s for %s / %s", record.id, record.product, record.iso_week)

    async def get_run(self, product: str, iso_week: str) -> Optional[RunRecord]:
        """Fetch a run record by product + iso_week, or None if not found."""
        db = self._ensure_connected()
        cursor = await db.execute(
            "SELECT * FROM run_log WHERE product = ? AND iso_week = ?",
            (product, iso_week),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row, cursor.description)

    async def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        reviews_count: Optional[int] = None,
        themes_count: Optional[int] = None,
        doc_id: Optional[str] = None,
        doc_heading: Optional[str] = None,
        gmail_msg_id: Optional[str] = None,
        tokens_used: Optional[int] = None,
        cost_usd: Optional[float] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update specific fields of a run record."""
        db = self._ensure_connected()
        updates: List[str] = []
        values: List[object] = []

        for field_name, value in [
            ("status", status),
            ("reviews_count", reviews_count),
            ("themes_count", themes_count),
            ("doc_id", doc_id),
            ("doc_heading", doc_heading),
            ("gmail_msg_id", gmail_msg_id),
            ("tokens_used", tokens_used),
            ("cost_usd", cost_usd),
            ("completed_at", completed_at.isoformat() if completed_at else None),
            ("error_message", error_message),
        ]:
            if value is not None:
                updates.append(f"{field_name} = ?")
                values.append(value)

        if not updates:
            return

        values.append(run_id)
        sql = f"UPDATE run_log SET {', '.join(updates)} WHERE id = ?"
        await db.execute(sql, values)
        await db.commit()
        logger.debug("Updated run %s: %s", run_id, ", ".join(updates))

    async def list_runs(
        self,
        product: Optional[str] = None,
        limit: int = 20,
    ) -> List[RunRecord]:
        """List recent run records, optionally filtered by product."""
        db = self._ensure_connected()

        if product:
            cursor = await db.execute(
                "SELECT * FROM run_log WHERE product = ? ORDER BY created_at DESC LIMIT ?",
                (product, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM run_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        rows = await cursor.fetchall()
        return [self._row_to_record(row, cursor.description) for row in rows]

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: tuple, description: tuple) -> RunRecord:
        """Convert a raw SQLite row to a RunRecord."""
        col_names = [d[0] for d in description]
        data = dict(zip(col_names, row))
        # Parse datetime strings back
        if data.get("created_at"):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if data.get("completed_at"):
            data["completed_at"] = datetime.fromisoformat(data["completed_at"])
        return RunRecord.model_validate(data)
