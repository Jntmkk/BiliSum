"""Shared artifact file storage for multi-instance deployments.

Full executor nodes upload task artifact files (transcript, summary,
knowledge note, mindmap, visual notes, covers, uploads) to OSS after a
task completes; any instance can then serve the file by downloading it
to its local disk on first access (local-first, OSS fallback).

Only files living under the instance's managed ``tasks_dir`` /
``cache_dir`` are shared. Export artifacts written to a user-configured
``output_dir`` (desktop workflows) stay local by design.

Storage layout on OSS::

    <prefix>/tasks/<task_id>/<relative path>        task artifacts
    <prefix>/covers/<file name>                      video cover cache
    <prefix>/uploads/<file name>                    local media uploads

The object prefix is ``artifact-store`` and is not configurable.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from video_sum_infra.config import ServiceSettings

logger = logging.getLogger("video_sum_service.app")

OSS_KEY_PREFIX = "artifact-store"

# Download URL TTL for private buckets. Public buckets ignore signing.
SIGNED_URL_EXPIRES_SECONDS = 3600

_OSS_CLIENT_CACHE: dict[tuple[str, str, str, str], Any] = {}

# Extensions considered shareable artifacts. Audio/video sources are
# excluded on purpose: they are transient inputs and can be large.
_ARTIFACT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".markdown",
}

_COVER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def oss_share_config(current: object) -> tuple[str, str, str, str] | None:
    """Return (bucket, endpoint, ak, sk); None when OSS is not fully configured."""
    bucket = str(getattr(current, "oss_bucket", "") or "").strip()
    endpoint = str(getattr(current, "oss_endpoint", "") or "").strip()
    ak = str(getattr(current, "oss_access_key_id", "") or "").strip()
    sk = str(getattr(current, "oss_access_key_secret", "") or "").strip()
    if not (bucket and endpoint and ak and sk):
        return None
    return bucket, endpoint, ak, sk


def oss_share_available(current: object) -> bool:
    return oss_share_config(current) is not None


def _oss_bucket_client(config: tuple[str, str, str, str]):
    try:
        import oss2  # type: ignore[import-not-found]
    except ImportError:
        return None
    bucket_name, endpoint, ak, sk = config
    client_key = (bucket_name, endpoint, ak, sk)
    bucket = _OSS_CLIENT_CACHE.get(client_key)
    if bucket is None:
        bucket = oss2.Bucket(oss2.Auth(ak, sk), f"https://{endpoint}", bucket_name)
        _OSS_CLIENT_CACHE[client_key] = bucket
    return bucket


def _object_key_for(relative_path: str) -> str:
    parts = [part for part in Path(relative_path).parts if part not in {"", ".", ".."}]
    return "/".join([OSS_KEY_PREFIX, *parts])


def _relative_under(path: Path, root: Path) -> str | None:
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
            return None
        return resolved_path.relative_to(resolved_root).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _is_shareable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() not in _ARTIFACT_SUFFIXES and path.suffix.lower() not in _COVER_SUFFIXES:
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def upload_task_artifacts(current_settings: ServiceSettings, task_id: str) -> int:
    """Upload all shareable files of one task directory to OSS. Best effort."""
    config = oss_share_config(current_settings)
    if config is None:
        return 0
    bucket = _oss_bucket_client(config)
    if bucket is None:
        logger.warning("artifact share: oss2 SDK unavailable, skip upload task_id=%s", task_id)
        return 0

    task_dir = Path(current_settings.tasks_dir) / task_id
    uploaded = 0
    try:
        files = [path for path in task_dir.rglob("*") if _is_shareable_file(path)]
    except OSError:
        return 0
    for path in files:
        relative = _relative_under(path, Path(current_settings.tasks_dir))
        if relative is None:
            continue
        object_key = _object_key_for(f"tasks/{relative}")
        try:
            bucket.put_object(object_key, path.read_bytes())
            uploaded += 1
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响其余文件
            logger.warning("artifact share: upload failed key=%s error=%s", object_key, exc)
    if uploaded:
        logger.info("artifact share: uploaded task_id=%s files=%d", task_id, uploaded)
    return uploaded


def upload_cache_file(current_settings: ServiceSettings, path: Path, cache_kind: str) -> bool:
    """Upload a single cache file (covers/ or uploads/) to OSS."""
    config = oss_share_config(current_settings)
    if config is None or cache_kind not in {"covers", "uploads"}:
        return False
    bucket = _oss_bucket_client(config)
    if bucket is None or not _is_shareable_file(path):
        return False
    object_key = _object_key_for(f"{cache_kind}/{path.name}")
    try:
        bucket.put_object(object_key, path.read_bytes())
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("artifact share: cache upload failed key=%s error=%s", object_key, exc)
        return False


def ensure_artifact_file(current_settings: ServiceSettings, path: Path) -> Path:
    """Return a locally readable path, downloading from OSS on cache miss.

    Falls back to the original (possibly missing) path when OSS is not
    configured or the object does not exist — callers keep their current
    error handling.
    """
    if path.is_file():
        return path
    config = oss_share_config(current_settings)
    if config is None:
        return path
    bucket = _oss_bucket_client(config)
    if bucket is None:
        return path

    cache_root = Path(current_settings.cache_dir)
    tasks_root = Path(current_settings.tasks_dir)
    relative = _relative_under(path, tasks_root)
    if relative is None:
        relative = _relative_under(path, cache_root)
    if relative is None:
        return path

    object_key = _object_key_for(relative)
    try:
        result = bucket.get_object(object_key)
        content = result.read()
    except Exception:  # noqa: BLE001 - 对象不存在/权限问题都按未共享处理
        return path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        logger.info("artifact share: downloaded key=%s -> %s", object_key, path)
    except OSError as exc:
        logger.warning("artifact share: cache write failed path=%s error=%s", path, exc)
        return path
    return path


def artifact_media_url(current_settings: ServiceSettings, path: Path) -> str | None:
    """Public URL or signed URL for a shared artifact; None when unavailable.

    Used by media-serving endpoints so file downloads do not have to be
    proxied through this instance's disk.
    """
    config = oss_share_config(current_settings)
    if config is None:
        return None
    bucket = _oss_bucket_client(config)
    if bucket is None:
        return None

    cache_root = Path(current_settings.cache_dir)
    tasks_root = Path(current_settings.tasks_dir)
    relative = _relative_under(path, tasks_root)
    if relative is None:
        relative = _relative_under(path, cache_root)
    if relative is None:
        return None

    object_key = _object_key_for(relative)
    try:
        public_base = str(getattr(current_settings, "oss_public_base_url", "") or "").strip().rstrip("/")
        if public_base:
            return f"{public_base}/{object_key}"
        return bucket.sign_url("GET", object_key, SIGNED_URL_EXPIRES_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("artifact share: url signing failed key=%s error=%s", object_key, exc)
        return None


def guess_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"
