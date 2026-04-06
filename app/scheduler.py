import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Job callables
# ---------------------------------------------------------------------------

async def pipeline_job() -> None:
    """Scheduled pipeline: process all pending files then refresh cache."""
    from app.services.pipeline import process_pending_files
    from app.services.cache import write_recent_cache

    logger.info("pipeline_job starting.")
    result = await process_pending_files()
    logger.info(
        "pipeline_job: %d attempted, %d succeeded, %d failed.",
        result["attempted"], result["succeeded"], result["failed"],
    )
    cache_count = await write_recent_cache()
    logger.info("Cache refreshed: %d entries in recent.json.", cache_count)


async def cleanup_job() -> None:
    """Daily cleanup: remove local files past their retention window."""
    from app.services.cleanup import delete_expired_files  # local import avoids cycles

    logger.info("Cleanup job starting.")
    await delete_expired_files()
    logger.info("Cleanup job finished.")


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def _parse_cron(cron_expr: str) -> CronTrigger:
    """Parse a five-field cron expression into an APScheduler CronTrigger."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"SCHEDULE_CRON must be a five-field cron expression, got: '{cron_expr}'"
        )
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


def start_scheduler() -> None:
    """Register jobs and start the AsyncIOScheduler."""
    # Pipeline job — follows SCHEDULE_CRON
    scheduler.add_job(
        pipeline_job,
        trigger=_parse_cron(settings.schedule_cron),
        id="pipeline_job",
        name="Scheduled processing pipeline",
        replace_existing=True,
    )

    # Cleanup job — daily at 04:00
    scheduler.add_job(
        cleanup_job,
        trigger=CronTrigger(hour=4, minute=0),
        id="cleanup_job",
        name="Daily local-file cleanup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. pipeline_job cron='%s', cleanup_job cron='0 4 * * *'.",
        settings.schedule_cron,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
