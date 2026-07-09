import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _refresh_recent_cache() -> None:
    """Scheduled job: rebuild the recent-entries JSON cache."""
    from app.services.cache import write_recent_cache

    count = await write_recent_cache()
    logger.info("Scheduled cache refresh wrote %d entries.", count)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Start the AsyncIOScheduler and register the periodic cache refresh.

    The refresh job is only added when ``CACHE_REFRESH_INTERVAL_MINUTES`` > 0;
    otherwise the scheduler starts with no jobs (the cache is still refreshed on
    every manual ``POST /api/process``).
    """
    interval = settings.cache_refresh_interval_minutes
    if interval > 0:
        scheduler.add_job(
            _refresh_recent_cache,
            trigger="interval",
            minutes=interval,
            id="refresh_recent_cache",
            replace_existing=True,
        )
        logger.info("Scheduler started (cache refresh every %d min).", interval)
    else:
        logger.info("Scheduler started (no scheduled jobs).")
    scheduler.start()


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
