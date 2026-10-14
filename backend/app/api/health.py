"""Health check endpoint."""
from fastapi import APIRouter
from sqlalchemy import text
from app.database import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """Basic health check — verifies app is running and DB is reachable."""
    db_status = "ok"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception:
        db_status = "unreachable"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "service": "leadpilot-ai",
    }
