"""
CLI entry point for the Review Pulse agent.

Commands:
    run       — Execute a single pipeline run
    backfill  — Run for a range of ISO weeks
    status    — Show recent run records
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Optional, List, Union

import click

from review_pulse.agent.config import load_config
from review_pulse.agent.orchestrator import Orchestrator
from review_pulse.store.run_log import RunLog

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# ISO week helpers
# ---------------------------------------------------------------------------

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")


def _validate_iso_week(ctx: click.Context, param: click.Parameter, value: Optional[str]) -> Optional[str]:
    """Validate and normalise an ISO week string."""
    if value is None:
        return None
    match = _ISO_WEEK_RE.match(value)
    if not match:
        raise click.BadParameter(f"Invalid ISO week format: {value!r}. Expected: 2026-W18")
    year, week = int(match.group(1)), int(match.group(2))
    if week < 1 or week > 53:
        raise click.BadParameter(f"ISO week must be 1–53, got {week}")
    return f"{year}-W{week:02d}"


def _current_iso_week() -> str:
    """Return the current ISO week as a string like '2026-W18'."""
    now = datetime.now()
    iso_cal = now.isocalendar()
    return f"{iso_cal[0]}-W{iso_cal[1]:02d}"


def _iso_week_range(from_week: str, to_week: str) -> List[str]:
    """Generate a list of ISO week strings from from_week to to_week inclusive."""
    from_match = _ISO_WEEK_RE.match(from_week)
    to_match = _ISO_WEEK_RE.match(to_week)
    if not from_match or not to_match:
        raise ValueError("Invalid ISO week format")

    # Convert to dates (Monday of each week)
    from_date = datetime.strptime(from_week + "-1", "%G-W%V-%u")
    to_date = datetime.strptime(to_week + "-1", "%G-W%V-%u")

    if from_date > to_date:
        raise click.BadParameter(f"from-week ({from_week}) must be ≤ to-week ({to_week})")

    weeks: List[str] = []
    current = from_date
    while current <= to_date:
        iso_cal = current.isocalendar()
        weeks.append(f"{iso_cal[0]}-W{iso_cal[1]:02d}")
        current += timedelta(weeks=1)

    return weeks


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config.yaml")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def main(ctx: click.Context, config_path: Optional[str], verbose: bool) -> None:
    """Review Pulse — Weekly Product Review Pulse Agent."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["verbose"] = verbose


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--product", "-p", required=True, help="Product name from config")
@click.option("--week", "-w", default=None, callback=_validate_iso_week, help="ISO week (e.g. 2026-W18)")
@click.option("--dry-run", is_flag=True, help="Run pipeline but skip MCP delivery")
@click.pass_context
def run(ctx: click.Context, product: str, week: Optional[str], dry_run: bool) -> None:
    """Execute a single pipeline run for a product and week."""
    if week is None:
        week = _current_iso_week()
        click.echo(f"ℹ️  Using current week: {week}")

    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"❌ Config error: {e}", err=True)
        sys.exit(1)

    try:
        config.get_product(product)
    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)

    async def _run() -> None:
        run_log = RunLog()
        await run_log.init_db()
        try:
            orch = Orchestrator(config, run_log)
            result = await orch.run(product, week, dry_run=dry_run)
            click.echo(f"\n{'=' * 50}")
            click.echo(f"Run result: {result.status}")
            click.echo(f"Product:    {result.product}")
            click.echo(f"Week:       {result.iso_week}")
            click.echo(f"Run ID:     {result.id}")
            if result.error_message:
                click.echo(f"Error:      {result.error_message}")
            click.echo(f"{'=' * 50}")
        finally:
            await run_log.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# backfill command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--product", "-p", required=True, help="Product name from config")
@click.option("--from-week", required=True, callback=_validate_iso_week, help="Start ISO week (inclusive)")
@click.option("--to-week", required=True, callback=_validate_iso_week, help="End ISO week (inclusive)")
@click.option("--dry-run", is_flag=True, help="Run pipeline but skip MCP delivery")
@click.pass_context
def backfill(ctx: click.Context, product: str, from_week: str, to_week: str, dry_run: bool) -> None:
    """Run the pipeline for a range of ISO weeks."""
    config_path = ctx.obj.get("config_path")

    try:
        config = load_config(config_path)
        config.get_product(product)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)

    try:
        weeks = _iso_week_range(from_week, to_week)
    except (ValueError, click.BadParameter) as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)

    if len(weeks) > 52:
        click.echo(f"⚠️  Backfilling {len(weeks)} weeks — this may take a long time")

    async def _backfill() -> None:
        run_log = RunLog()
        await run_log.init_db()
        try:
            orch = Orchestrator(config, run_log)
            results = {"success": 0, "skipped": 0, "failed": 0}
            for w in weeks:
                click.echo(f"\n--- {product} / {w} ---")
                result = await orch.run(product, w, dry_run=dry_run)
                if result.status in ("success", "dry_run"):
                    results["success"] += 1
                elif result.status == "failed":
                    results["failed"] += 1
                else:
                    results["skipped"] += 1

            click.echo(f"\n{'=' * 50}")
            click.echo(f"Backfill complete: {len(weeks)} weeks")
            click.echo(f"  ✅ Success:  {results['success']}")
            click.echo(f"  ⏭️  Skipped:  {results['skipped']}")
            click.echo(f"  ❌ Failed:   {results['failed']}")
            click.echo(f"{'=' * 50}")
        finally:
            await run_log.close()

    asyncio.run(_backfill())


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--product", "-p", default=None, help="Filter by product name")
@click.option("--limit", "-n", default=20, help="Max rows to show")
@click.pass_context
def status(ctx: click.Context, product: Optional[str], limit: int) -> None:
    """Show recent pipeline runs."""

    async def _status() -> None:
        run_log = RunLog()
        await run_log.init_db()
        try:
            records = await run_log.list_runs(product=product, limit=limit)
        finally:
            await run_log.close()

        if not records:
            click.echo("No runs recorded yet.")
            return

        # Header
        header = f"{'Product':<15} {'Week':<10} {'Status':<16} {'Reviews':>8} {'Themes':>7} {'Doc ID':<20} {'Gmail ID':<20} {'Completed':<20}"
        click.echo(header)
        click.echo("─" * len(header))

        for r in records:
            doc_id = (r.doc_id or "—")[:18]
            gmail_id = (r.gmail_msg_id or "—")[:18]
            completed = r.completed_at.strftime("%Y-%m-%d %H:%M") if r.completed_at else "—"
            reviews = str(r.reviews_count) if r.reviews_count is not None else "—"
            themes = str(r.themes_count) if r.themes_count is not None else "—"

            click.echo(
                f"{r.product:<15} {r.iso_week:<10} {r.status:<16} {reviews:>8} {themes:>7} {doc_id:<20} {gmail_id:<20} {completed:<20}"
            )

    asyncio.run(_status())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
