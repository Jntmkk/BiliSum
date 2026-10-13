from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import video_sum_service.feedback as feedback_module
from video_sum_infra.config import ServiceSettings
from video_sum_service.app import app, settings_manager
import video_sum_service.app as service_app
import video_sum_service.routers.system as system_router
from video_sum_service.auth import ACCESS_TOKEN_ENV, AccessTokenManager


@pytest.fixture(autouse=True)
def restore_app_state(monkeypatch):
    original_settings = settings_manager.current
    original_app_manager = service_app.access_token_manager
    original_router_manager = system_router.access_token_manager
    monkeypatch.delenv(feedback_module.FEEDBACK_TOKEN_ENV, raising=False)
    monkeypatch.delenv(feedback_module.FEEDBACK_REPO_ENV, raising=False)
    monkeypatch.delenv(feedback_module.DEPLOYMENT_ENV, raising=False)
    feedback_module._rate_limit_hits.clear()
    yield
    settings_manager._settings = original_settings
    service_app.access_token_manager = original_app_manager
    system_router.access_token_manager = original_router_manager


@pytest.fixture
def authed_client(monkeypatch) -> TestClient:
    manager = AccessTokenManager(Path("unused"), env={ACCESS_TOKEN_ENV: "test-token"})
    monkeypatch.setattr(service_app, "access_token_manager", manager)
    monkeypatch.setattr(system_router, "access_token_manager", manager)
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


def test_feedback_requires_auth() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/feedback",
        json={"category": "bug", "description": "摘要任务一直失败"},
    )
    assert response.status_code == 401


def test_feedback_validates_payload(authed_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv(feedback_module.FEEDBACK_TOKEN_ENV, "ghp_testtoken")
    short = authed_client.post("/api/v1/feedback", json={"category": "bug", "description": "短"})
    assert short.status_code == 422
    bad_category = authed_client.post(
        "/api/v1/feedback",
        json={"category": "nope", "description": "描述长度足够的问题"},
    )
    assert bad_category.status_code == 422


def test_feedback_returns_503_when_channel_not_configured(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/v1/feedback",
        json={"category": "bug", "description": "摘要任务一直失败"},
    )
    assert response.status_code == 503


def test_feedback_creates_issue(authed_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv(feedback_module.FEEDBACK_TOKEN_ENV, "ghp_testtoken")
    posted: list[dict] = []

    class FakeResponse:
        status_code = 201

        def json(self) -> dict:
            return {"html_url": "https://github.com/Jntmkk/BiliSum/issues/42", "number": 42}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url: str, json: dict):
            posted.append({"url": url, "payload": json})
            return FakeResponse()

    monkeypatch.setattr(feedback_module.httpx, "Client", FakeClient)
    response = authed_client.post(
        "/api/v1/feedback",
        json={
            "category": "bug",
            "description": "摘要任务一直失败，提示 LLM 无响应",
            "context": {"clientType": "App (macOS)", "route": "/videos/abc"},
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "issue_url": "https://github.com/Jntmkk/BiliSum/issues/42",
        "issue_number": 42,
    }
    assert posted[0]["url"].endswith("/repos/Jntmkk/BiliSum/issues")
    payload = posted[0]["payload"]
    assert payload["title"].startswith("[问题反馈]")
    assert "bug" in payload["labels"]
    assert "area:desktop" in payload["labels"]
    assert "App (macOS)" in payload["body"]
    assert "deployment" in payload["body"]


def test_feedback_retries_without_missing_labels(authed_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv(feedback_module.FEEDBACK_TOKEN_ENV, "ghp_testtoken")
    attempts: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

        def json(self) -> dict:
            return {"html_url": "https://github.com/Jntmkk/BiliSum/issues/7", "number": 7}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url: str, json: dict):
            attempts.append(json)
            return FakeResponse(422 if len(attempts) == 1 else 201)

    monkeypatch.setattr(feedback_module.httpx, "Client", FakeClient)
    response = authed_client.post(
        "/api/v1/feedback",
        json={"category": "question", "description": "知识库索引怎么重建"},
    )
    assert response.status_code == 200
    assert attempts[0]["labels"] == ["question", "area:web"]
    assert attempts[1]["labels"] == []


def test_feedback_rate_limits_repeated_submissions(authed_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv(feedback_module.FEEDBACK_TOKEN_ENV, "ghp_testtoken")

    class FakeResponse:
        status_code = 201

        def json(self) -> dict:
            return {"html_url": "https://github.com/Jntmkk/BiliSum/issues/1", "number": 1}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url: str, json: dict):
            return FakeResponse()

    monkeypatch.setattr(feedback_module.httpx, "Client", FakeClient)
    payload = {"category": "bug", "description": "重复提交测试"}
    for _ in range(feedback_module.RATE_LIMIT_MAX_PER_WINDOW):
        assert authed_client.post("/api/v1/feedback", json=payload).status_code == 200
    assert authed_client.post("/api/v1/feedback", json=payload).status_code == 429


def test_redact_secrets_masks_common_credentials() -> None:
    text = (
        "key=sk-abcdef123456 token=ghp_abcdef123456 "
        "auth: Bearer abcdef123456 api_key=secretvalue"
    )
    redacted = feedback_module.redact_secrets(text)
    assert "sk-abcdef123456" not in redacted
    assert "ghp_abcdef123456" not in redacted
    assert "secretvalue" not in redacted
    assert "<redacted>" in redacted


def test_detect_deployment_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv(feedback_module.DEPLOYMENT_ENV, "docker")
    assert feedback_module.detect_deployment() == "docker"
    monkeypatch.setenv(feedback_module.DEPLOYMENT_ENV, "local")
    assert feedback_module.detect_deployment() == "local"
    monkeypatch.delenv(feedback_module.DEPLOYMENT_ENV)
    result = feedback_module.detect_deployment()
    assert result in {"docker", "local"}


def test_build_issue_redacts_description_secrets() -> None:
    issue = feedback_module.build_issue(
        category="bug",
        description="我的密钥是 sk-abcdef1234567890 请帮忙看看",
        client_context={"clientType": "Web"},
        server_side_context={"deployment": "docker"},
    )
    assert "sk-abcdef" not in issue["body"]
    assert "sk-abcdef" not in issue["title"]
