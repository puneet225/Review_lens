"""
FastAPI server wrapping the Review Pulse pipeline.
Exposes REST endpoints for the Next.js frontend.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load .env from project root (one level up from Phase 3/)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Support base64-encoded token for Render deployment
_token_b64 = os.environ.get("GOOGLE_OAUTH_TOKEN_B64", "")
if _token_b64:
    _token_path = Path(tempfile.gettempdir()) / "gcp_token.json"
    _token_path.write_text(base64.b64decode(_token_b64).decode())
    os.environ["GOOGLE_OAUTH_TOKEN_PATH"] = str(_token_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory job store (keyed by job_id)
_jobs: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Review Pulse API starting up")
    yield
    logger.info("👋 Review Pulse API shutting down")


app = FastAPI(
    title="Review Pulse API",
    version="1.0.0",
    lifespan=lifespan,
)

_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "*").strip()
_allow_origins = (
    ["*"] if _cors_env in ("", "*") else [o.strip() for o in _cors_env.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS allow_origins=%s", _allow_origins)


# ── Request / Response models ──────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    product: str = "groww"
    weeks: int = 4          # Rolling window in weeks
    max_reviews: int = 1000  # Max reviews to scrape


class DeliverEmailRequest(BaseModel):
    job_id: str
    recipients: List[str]


class DeliverDocRequest(BaseModel):
    job_id: str


# ── Background pipeline runner ─────────────────────────────────────────────


async def _run_pipeline(job_id: str, product: str, weeks: int, max_reviews: int):
    """Run the full pipeline asynchronously and store results in _jobs."""
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["started_at"] = datetime.utcnow().isoformat()

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        os.environ["PYTHONPATH"] = str(Path(__file__).parent)

        from review_pulse.agent.config import load_config
        from review_pulse.agent.orchestrator import Orchestrator
        from review_pulse.store.run_log import RunLog

        # Override config values via env for this run
        config_path = Path(__file__).parent / "config.yaml"
        config = load_config(config_path)

        # Patch ingestion and window settings inline
        config.ingestion.__dict__["max_reviews_per_source"] = max_reviews
        config.ingestion.__dict__["window_weeks"] = weeks

        run_log = RunLog()
        await run_log.init_db()

        iso_week = datetime.utcnow().strftime("%G-W%V")
        orchestrator = Orchestrator(config=config, run_log=run_log)

        # Run in dry mode first to get themes, then deliver on demand
        record = await orchestrator.run(
            product=product,
            iso_week=iso_week,
            dry_run=True,  # Don't auto-deliver; UI will trigger delivery
        )

        # Store the analysis result for later delivery
        _jobs[job_id].update({
            "status": "done",
            "completed_at": datetime.utcnow().isoformat(),
            "run_id": record.id if record else None,
            "iso_week": iso_week,
            "product": product,
            "themes": _extract_themes(orchestrator),
            "stats": {
                "reviews": getattr(orchestrator, "_last_review_count", 0),
                "themes": getattr(orchestrator, "_last_theme_count", 0),
                "tokens": getattr(orchestrator, "_last_tokens", 0),
            },
            "_analysis": getattr(orchestrator, "_last_analysis", None),
        })

    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)


def _extract_themes(orchestrator) -> List[Dict]:
    """Pull theme data from the orchestrator's last analysis result."""
    analysis = getattr(orchestrator, "_last_analysis", None)
    if not analysis:
        return []
    themes = []
    for t in analysis.themes:
        fee = None
        if t.fee_explainer:
            fee = {
                "title": t.fee_explainer.title,
                "bullets": list(t.fee_explainer.bullets),
                "source_urls": [str(u) for u in t.fee_explainer.source_urls],
                "last_checked": t.fee_explainer.last_checked.isoformat(),
                "is_stale": t.fee_explainer.is_stale,
            }
        themes.append({
            "name": t.name,
            "category_key": t.category_key,
            "description": t.description,
            "sentiment": t.sentiment,
            "review_count": t.review_count,
            "action": t.action,
            "quotes": [
                {"text": q.text, "rating": q.rating, "store": q.store}
                for q in t.quotes
            ],
            "fee_explainer": fee,
        })
    return themes


# ── Endpoints ──────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/analyze")
async def start_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Start a pipeline run and return a job_id to poll."""
    from uuid import uuid4
    job_id = uuid4().hex
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "product": req.product,
        "weeks": req.weeks,
        "max_reviews": req.max_reviews,
        "created_at": datetime.utcnow().isoformat(),
    }
    background_tasks.add_task(
        asyncio.coroutine(_run_pipeline)(job_id, req.product, req.weeks, req.max_reviews)
        if False else _run_pipeline,
        job_id, req.product, req.weeks, req.max_reviews
    )
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Poll the status and results of a pipeline run."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Don't expose internal _analysis object
    return {k: v for k, v in job.items() if not k.startswith("_")}


@app.post("/api/deliver/email")
async def deliver_email(req: DeliverEmailRequest):
    """Send Gmail notification for a completed job."""
    job = _jobs.get(req.job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not ready")

    analysis = job.get("_analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="No analysis data available")

    from review_pulse.delivery.gmail import send_gmail_notification
    msg_id = send_gmail_notification(
        product=job["product"],
        iso_week=job["iso_week"],
        analysis=analysis,
        recipients=req.recipients,
        doc_id=job.get("doc_id"),
    )
    return {"status": "sent", "msg_id": msg_id}


@app.post("/api/deliver/gdoc")
async def deliver_gdoc(req: DeliverDocRequest):
    """Create a Google Doc for a completed job."""
    job = _jobs.get(req.job_id)
    if not job or job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not ready")

    analysis = job.get("_analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="No analysis data available")

    from review_pulse.delivery.google_docs import create_google_doc
    doc_id = create_google_doc(
        product=job["product"],
        iso_week=job["iso_week"],
        analysis=analysis,
    )
    _jobs[req.job_id]["doc_id"] = doc_id
    return {
        "status": "created",
        "doc_id": doc_id,
        "doc_url": f"https://docs.google.com/document/d/{doc_id}",
    }


@app.get("/api/jobs")
def list_jobs():
    """Return all jobs (most recent first)."""
    jobs = sorted(
        [{k: v for k, v in j.items() if not k.startswith("_")} for j in _jobs.values()],
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )
    return {"jobs": jobs}
