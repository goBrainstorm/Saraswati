import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Job callables
# ---------------------------------------------------------------------------

async def cleanup_job() -> None:
    """Daily cleanup: remove local files past their retention window."""
    from app.services.cleanup import delete_expired_files

    logger.info("Cleanup job starting.")
    await delete_expired_files()
    logger.info("Cleanup job finished.")


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Register jobs and start the AsyncIOScheduler."""
    # Cleanup job — daily at 04:00
    scheduler.add_job(
        cleanup_job,
        trigger=CronTrigger(hour=4, minute=0),
        id="cleanup_job",
        name="Daily local-file cleanup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started. cleanup_job cron='0 4 * * *'.")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
