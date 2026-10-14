"""LeadPilot AI — FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from datetime import datetime

# App-level logging (crawler, enrichment, pipeline)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from app.config import settings
from app.database import Base, engine
from app.api import health, sources, companies, leads, analytics, outreach, meetings, webhooks, settings as settings_api, auth_google, data_quality, automation
# Register additive models before create_all (some are imported lazily elsewhere)
from app.models import contact_item as _models_contact_item  # noqa: F401
from app.models import suppression as _models_suppression  # noqa: F401

logger = logging.getLogger(__name__)

# Create tables on startup (for MVP; Alembic migrations in production)
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
except Exception as e:
    logger.warning(f"Could not create tables (DB may not be ready): {e}")

app = FastAPI(
    title="LeadPilot AI",
    description="AI-Powered B2B Lead Intelligence, Outreach & Meeting Automation Platform",
    version="0.1.0",
)


@app.on_event("startup")
def start_background_schedulers():
    """Start daemon schedulers (WhatsApp follow-up scan)."""
    try:
        from app.services.scheduler import start_followup_scheduler
        start_followup_scheduler()
    except Exception as e:
        logger.warning(f"Could not start follow-up scheduler: {e}")


@app.on_event("startup")
def recover_stale_crawls():
    """Mark CRAWLING jobs/sources as FAILED on boot.

    A fresh process owns no crawl threads, so any CRAWLING row is stale
    (backend restarted mid-run). Saved companies are intact (incremental
    persistence); FAILED unlocks the Retry button for an idempotent resume.
    """
    try:
        from sqlalchemy.orm import Session as _Session
        from app.database import SessionLocal
        from app.models.crawl_job import CrawlJob
        from app.models.source import Source, SourceStatus
        db = SessionLocal()
        try:
            stale_jobs = db.query(CrawlJob).filter(
                CrawlJob.status == "CRAWLING").all()
            for job in stale_jobs:
                job.status = "FAILED"
                job.finished_at = datetime.utcnow()
                errs = list(job.errors or [])
                errs.append("Backend restarted mid-run; job did not finish.")
                job.errors = errs[-20:]
            stale_sources = db.query(Source).filter(
                Source.status == SourceStatus.CRAWLING).all()
            for source in stale_sources:
                source.status = SourceStatus.FAILED
            db.commit()
            if stale_jobs or stale_sources:
                logger.info(f"Recovered {len(stale_jobs)} stale jobs, "
                            f"{len(stale_sources)} stale sources as FAILED")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Stale crawl recovery failed: {e}")


@app.on_event("shutdown")
def stop_background_schedulers():
    try:
        from app.services.scheduler import stop_followup_scheduler
        stop_followup_scheduler()
    except Exception:
        pass

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(sources.router)
app.include_router(companies.router)
app.include_router(leads.router)
app.include_router(analytics.router)
app.include_router(outreach.router)
app.include_router(meetings.router)
app.include_router(webhooks.router)
app.include_router(auth_google.router)
app.include_router(settings_api.router)
app.include_router(data_quality.router)
app.include_router(automation.router)


@app.get("/")
def root():
    return {
        "name": "LeadPilot AI",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
