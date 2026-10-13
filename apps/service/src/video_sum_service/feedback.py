"""In-app user feedback channel backed by GitHub Issues.

The GitHub token lives only in server-side configuration
(``VIDEO_SUM_FEEDBACK_GITHUB_TOKEN``); the frontend never sees it.
"""

from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

FEEDBACK_TOKEN_ENV = "VIDEO_SUM_FEEDBACK_GITHUB_TOKEN"
FEEDBACK_REPO_ENV = "VIDEO_SUM_FEEDBACK_REPO"
DEFAULT_FEEDBACK_REPO = "Jntmkk/BiliSum"
DEPLOYMENT_ENV = "VIDEO_SUM_DEPLOYMENT"

GITHUB_API_BASE = "https://api.github.com"

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_PER_WINDOW = 3
MAX_CONTEXT_JSON_CHARS = 20000

FEEDBACK_CATEGORY_TITLES = {
    "bug": "问题反馈",
    "feature": "功能建议",
    "question": "使用疑问",
    "other": "其他反馈",
}
FEEDBACK_CATEGORY_LABELS = {
    "bug": "bug",
    "feature": "enhancement",
    "question": "question",
    "other": "",
}

# Defense in depth: even though clients should never send secrets, mask
# common credential shapes before anything reaches GitHub.
_SECRET_RULES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "<redacted>"),
    (re.compile(r"ghp_[A-Za-z0-9]{8,}"), "<redacted>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{8,}"), "<redacted>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\.\-]{8,}"), "Bearer <redacted>"),
    (
        re.compile(r"(?i)\b(token|api[_-]?key|secret|password)=([^\s&]+)"),
        lambda match: f"{match.group(1)}=<redacted>",
    ),
]

_rate_limit_lock = threading.Lock()
_rate_limit_hits: dict[str, list[float]] = {}


class FeedbackError(Exception):
    """Base error for the feedback channel."""

    status_code = 502
    detail = "反馈提交失败。"


class FeedbackChannelNotConfiguredError(FeedbackError):
    status_code = 503
    detail = "反馈通道未配置，请到 GitHub 仓库手动提交 issue。"


class FeedbackUpstreamError(FeedbackError):
    status_code = 502
    detail = "创建 GitHub issue 失败，请稍后重试。"


class FeedbackRateLimitedError(FeedbackError):
    status_code = 429
    detail = "提交太频繁，请稍后再试。"


def detect_deployment() -> str:
    """Classify how the service is deployed: docker or local (web/npx/desktop-managed)."""
    explicit = os.environ.get(DEPLOYMENT_ENV, "").strip().lower()
    if explicit in {"docker", "local"}:
        return explicit
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return "docker"
    try:
        if os.path.exists("/.dockerenv"):
            return "docker"
    except OSError:
        pass
    return "local"


def check_rate_limit(key: str) -> bool:
    now = time.monotonic()
    with _rate_limit_lock:
        hits = [ts for ts in _rate_limit_hits.get(key, []) if now - ts < RATE_LIMIT_WINDOW_SECONDS]
        if len(hits) >= RATE_LIMIT_MAX_PER_WINDOW:
            _rate_limit_hits[key] = hits
            return False
        hits.append(now)
        _rate_limit_hits[key] = hits
    return True


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern, replacement in _SECRET_RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def server_context() -> dict[str, Any]:
    return {
        "deployment": detect_deployment(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _render_context_rows(context: dict[str, Any]) -> list[str]:
    return [f"- {key}: {value}" for key, value in context.items() if value is not None]


def build_issue(
    *,
    category: str,
    description: str,
    client_context: dict[str, Any],
    server_side_context: dict[str, Any],
) -> dict[str, Any]:
    category_title = FEEDBACK_CATEGORY_TITLES.get(category, FEEDBACK_CATEGORY_TITLES["other"])
    title_body = re.sub(r"\s+", " ", description).strip()[:50]
    title = redact_secrets(f"[{category_title}] {title_body}")

    merged_context: dict[str, Any] = {}
    merged_context.update(client_context)
    merged_context.update(server_side_context)
    context_json = json.dumps(merged_context, ensure_ascii=False, indent=2, default=str)
    if len(context_json) > MAX_CONTEXT_JSON_CHARS:
        context_json = context_json[:MAX_CONTEXT_JSON_CHARS] + "\n... (truncated)"

    body_lines = [
        "### 问题描述",
        "",
        description.strip(),
        "",
        "### 环境信息",
        "",
        *_render_context_rows(merged_context),
        "",
        "<details><summary>原始上下文</summary>",
        "",
        "```json",
        context_json,
        "```",
        "",
        "</details>",
        "",
    ]
    body = redact_secrets("\n".join(body_lines))

    labels = [FEEDBACK_CATEGORY_LABELS.get(category, "")]
    client_type = str(client_context.get("clientType") or "")
    if client_type.startswith("App"):
        labels.append("area:desktop")
    else:
        labels.append("area:web")
    labels = [label for label in labels if label]
    return {"title": title, "body": body, "labels": labels}


def create_github_issue(
    *,
    repo: str,
    token: str,
    issue: dict[str, Any],
    user_agent: str,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": user_agent,
    }
    with httpx.Client(timeout=20, headers=headers) as client:
        response = client.post(f"{GITHUB_API_BASE}/repos/{repo}/issues", json=issue)
        if response.status_code == 422:
            # Labels may be missing in forks; retry without them instead of failing.
            retry_payload = {**issue, "labels": []}
            response = client.post(f"{GITHUB_API_BASE}/repos/{repo}/issues", json=retry_payload)
    if response.status_code in {401, 403, 404}:
        raise FeedbackChannelNotConfiguredError()
    if response.status_code != 201:
        raise FeedbackUpstreamError()
    data = response.json()
    return {"issue_url": data["html_url"], "issue_number": int(data["number"])}
