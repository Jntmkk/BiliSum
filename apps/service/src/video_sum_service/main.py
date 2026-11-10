import logging
import os

from uvicorn import run as uvicorn_run

from video_sum_infra.logging import configure_logging
from video_sum_infra.paths import ensure_directory
from video_sum_service.app import app, settings_manager

logger = logging.getLogger("video_sum_service.main")


def run() -> None:
    settings = settings_manager.current
    configure_logging()
    # Allow overriding worker count via env (e.g. WEB_CONCURRENCY=2) without
    # code changes — useful for Docker deployments where CPU cores vary.
    workers = int(os.environ.get("WEB_CONCURRENCY", settings.workers))
    logger.info(
        "starting service host=%s port=%s workers=%s data_dir=%s cache_dir=%s tasks_dir=%s runtime_channel=%s",
        settings.host,
        settings.port,
        workers,
        settings.data_dir,
        settings.cache_dir,
        settings.tasks_dir,
        settings.runtime_channel,
    )
    ensure_directory(settings.data_dir)
    ensure_directory(settings.cache_dir)
    ensure_directory(settings.tasks_dir)
    uvicorn_run(
        "video_sum_service.app:app",
        host=settings.host,
        port=settings.port,
        workers=workers,
        access_log=False,
    )
