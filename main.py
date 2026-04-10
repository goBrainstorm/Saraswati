import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import create_db_and_tables
from app.templates_env import templates
from app.queue import drain_queue
from app.routes import entries, models_config as models_config_route, process, prompts, settings as settings_route, status, upload
from app.scheduler import start_scheduler, stop_scheduler
from app.services.model_config import seed_model_configs

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting up Knowledge Base server.")

    # Ensure required directories exist
    for directory in (settings.input_dir, settings.cache_dir, "data"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.info("Directory ready: %s", directory)

    # Initialise database
    create_db_and_tables()

    # Seed default model configs (idempotent)
    seed_model_configs()

    # Start background scheduler
    start_scheduler()

    # Start queue drain coroutine (disabled when QUEUE_DRAIN_ENABLED=false, e.g. tests)
    if settings.queue_drain_enabled:
        asyncio.create_task(drain_queue())

    yield

    # --- Shutdown ---
    logger.info("Shutting down Knowledge Base server.")
    stop_scheduler()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Personal Knowledge Base",
    description="Self-hosted audio ingestion and knowledge pipeline — Phase 2",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(upload.router)
app.include_router(status.router)
app.include_router(entries.router)
app.include_router(process.router)
app.include_router(prompts.router)
app.include_router(models_config_route.router)
app.include_router(settings_route.router)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"active_page": "files"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
