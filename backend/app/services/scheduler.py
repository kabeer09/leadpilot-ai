"""Background schedulers (stdlib only — no extra dependencies).

Hourly jobs share one daemon thread:
- 24h WhatsApp follow-up scan (queues due follow-ups),
- 24h EMAIL follow-up auto-send (fail-closed, capped),
- Gmail reply poll (matches threads, classifies + routes replies),
- Daily auto-send (Gmail quota-aware).

Each run uses its own DB session. The thread never blocks shutdown.
"""
import logging
import threading
import time

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


def _scan_once() -> None:
    from app.database import SessionLocal
    from app.services.outreach import scan_and_queue_followups, poll_gmail_replies

    db = SessionLocal()
    try:
        summary = scan_and_queue_followups(db)
        if summary["due_found"]:
            logger.info(f"Scheduled follow-up scan: {summary}")
    except Exception as e:
        logger.error(f"Scheduled follow-up scan failed: {e}")
    try:
        replies = poll_gmail_replies(db)
        if replies["matched"]:
            logger.info(f"Scheduled reply poll: {replies}")
    except RuntimeError:
        pass  # no Google account connected — nothing to poll
    except Exception as e:
        logger.error(f"Scheduled reply poll failed: {e}")
    # Auto 24h email follow-ups come AFTER the reply poll so a fresh
    # reply always stops its follow-up. Fail-closed inside.
    try:
        if settings.FOLLOWUP_AUTO_SEND_ENABLED:
            from app.services.outreach import send_due_email_followups
            auto_fu = send_due_email_followups(
                db, limit=settings.FOLLOWUP_AUTO_SEND_LIMIT)
            if auto_fu.get("sent"):
                logger.info(f"Scheduled email follow-ups: {auto_fu}")
    except Exception as e:
        logger.error(f"Scheduled email follow-ups failed: {e}")
    try:
        from app.services.outreach import run_auto_send
        auto = run_auto_send(db)
        if auto.get("ran"):
            logger.info(f"Scheduled auto-send: {auto}")
    except Exception as e:
        logger.error(f"Scheduled auto-send failed: {e}")
    finally:
        db.close()


def _run_loop(interval_seconds: float) -> None:
    logger.info(f"Follow-up scheduler started (every {interval_seconds / 60:.0f} min)")
    while not _scheduler_stop.wait(interval_seconds):
        _scan_once()


def start_followup_scheduler() -> threading.Thread | None:
    """Start the daemon follow-up scheduler (idempotent)."""
    global _scheduler_thread
    if not settings.FOLLOWUP_SCHEDULER_ENABLED:
        logger.info("Follow-up scheduler disabled by config")
        return None
    if _scheduler_thread and _scheduler_thread.is_alive():
        return _scheduler_thread
    interval = max(1, settings.FOLLOWUP_SCAN_INTERVAL_MINUTES) * 60.0
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(
        target=_run_loop, args=(interval,), daemon=True, name="followup-scheduler"
    )
    _scheduler_thread.start()
    return _scheduler_thread


def stop_followup_scheduler() -> None:
    """Signal the scheduler thread to stop (used in tests/shutdown)."""
    _scheduler_stop.set()
