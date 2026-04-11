from typing import Literal

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Server
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # Paths
    db_path: str = Field(default="data/knowledge.db", alias="DB_PATH")
    cache_dir: str = Field(default="cache", alias="CACHE_DIR")
    input_dir: str = Field(default="input", alias="INPUT_DIR")

    # Retention
    local_retention_days: int = Field(default=7, alias="LOCAL_RETENTION_DAYS")

    # Schedule (cron expression)
    schedule_cron: str = Field(default="0 3 * * *", alias="SCHEDULE_CRON")

    # Background queue (set false in tests to avoid competing drain tasks)
    queue_drain_enabled: bool = Field(default=True, alias="QUEUE_DRAIN_ENABLED")
    # After the first dequeue, wait this long then drain the rest, so sequential
    # uploads in one drop can share one horizontal batch (same as manual process).
    queue_coalesce_debounce_seconds: float = Field(
        default=0.2,
        alias="QUEUE_COALESCE_DEBOUNCE_SECONDS",
        ge=0.0,
    )

    # Nextcloud (WebDAV)
    nextcloud_url: str = Field(default="", alias="NEXTCLOUD_URL")
    nextcloud_user: str = Field(default="", alias="NEXTCLOUD_USER")
    nextcloud_pass: str = Field(default="", alias="NEXTCLOUD_PASS")
    nextcloud_remote_dir: str = Field(default="/Knowledge/Audio", alias="NEXTCLOUD_REMOTE_DIR")

    # LLM (Phase 2)
    llama_server_url: str = Field(default="http://localhost:8080", alias="LLAMA_SERVER_URL")
    llama_model: str = Field(default="gemma-4-e4b", alias="LLAMA_MODEL")

    # Whisper (Phase 2)
    whisper_model: str = Field(default="large-v3", alias="WHISPER_MODEL")
    whisper_device: Literal["auto", "cuda", "cpu"] = Field(
        default="auto",
        alias="WHISPER_DEVICE",
    )
    whisper_batch_size: int = Field(default=8, alias="WHISPER_BATCH_SIZE", ge=1)
    denoise_max_mb: float = Field(default=100.0, alias="DENOISE_MAX_MB")

    # Qdrant (Phase 3)
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="knowledge", alias="QDRANT_COLLECTION")

    # Tailscale
    tailscale_host: str = Field(default="127.0.0.1", alias="TAILSCALE_HOST")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
