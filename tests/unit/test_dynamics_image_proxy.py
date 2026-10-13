from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.responses import FileResponse, RedirectResponse

from video_sum_service.routers import dynamics as dynamics_router


IMAGE_URL = "https://i1.hdslb.com/bfs/archive/test-cover.jpg"


class FakeBucket:
    def __init__(self, fail_sign: bool = False) -> None:
        self.puts: list[tuple[str, bytes, dict]] = []
        self.fail_sign = fail_sign

    def put_object(self, key: str, content: bytes, headers=None) -> None:
        self.puts.append((key, content, headers or {}))

    def sign_url(self, method: str, key: str, expires: int) -> str:
        if self.fail_sign:
            raise RuntimeError("sign failed")
        assert method == "GET"
        return f"https://signed.example/{key}?exp={expires}"


class FakeImageResponse:
    status_code = 200
    content = b"fake-image-bytes"
    headers = {"content-type": "image/jpeg"}


def oss_settings() -> SimpleNamespace:
    return SimpleNamespace(
        oss_bucket="yz-hz-oss",
        oss_endpoint="oss-cn-hangzhou.aliyuncs.com",
        oss_access_key_id="ak",
        oss_access_key_secret="sk",
        oss_public_base_url="",
    )


def install_fakes(monkeypatch, tmp_path: Path, fake_bucket: FakeBucket, settings: SimpleNamespace) -> Path:
    cache_dir = tmp_path / "imgs"
    cache_dir.mkdir()
    monkeypatch.setattr(dynamics_router, "_image_cache_dir", lambda request: cache_dir)
    monkeypatch.setattr(dynamics_router, "settings_manager", SimpleNamespace(current=settings))
    monkeypatch.setattr(dynamics_router, "_oss_bucket_client", lambda config: fake_bucket)
    monkeypatch.setattr(dynamics_router.httpx, "get", lambda *args, **kwargs: FakeImageResponse())
    return cache_dir


def test_image_proxy_uploads_and_redirects_to_signed_url(monkeypatch, tmp_path: Path) -> None:
    fake_bucket = FakeBucket()
    cache_dir = install_fakes(monkeypatch, tmp_path, fake_bucket, oss_settings())

    response = dynamics_router.proxy_dynamics_image(url=IMAGE_URL, request=SimpleNamespace())

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://signed.example/up-images/")
    assert "exp=3600" in location

    assert len(fake_bucket.puts) == 1
    key, content, headers = fake_bucket.puts[0]
    assert content == b"fake-image-bytes"
    assert headers.get("Content-Type") == "image/jpeg"

    meta = json.loads((cache_dir / f"{key.split('/', 1)[1]}.json").read_text(encoding="utf-8"))
    assert meta["oss_object_key"] == key
    assert "oss_url" not in meta

    cached = dynamics_router.proxy_dynamics_image(url=IMAGE_URL, request=SimpleNamespace())
    assert isinstance(cached, RedirectResponse)
    assert cached.headers["location"].startswith("https://signed.example/up-images/")


def test_image_proxy_falls_back_to_local_file_when_signing_fails(monkeypatch, tmp_path: Path) -> None:
    fake_bucket = FakeBucket(fail_sign=True)
    install_fakes(monkeypatch, tmp_path, fake_bucket, oss_settings())

    response = dynamics_router.proxy_dynamics_image(url=IMAGE_URL, request=SimpleNamespace())

    assert isinstance(response, FileResponse)
    assert response.status_code == 200


def test_image_proxy_serves_local_file_without_oss(monkeypatch, tmp_path: Path) -> None:
    fake_bucket = FakeBucket()
    no_oss = oss_settings()
    no_oss.oss_bucket = ""
    no_oss.oss_access_key_secret = ""
    install_fakes(monkeypatch, tmp_path, fake_bucket, no_oss)

    response = dynamics_router.proxy_dynamics_image(url=IMAGE_URL, request=SimpleNamespace())

    assert isinstance(response, FileResponse)
    assert response.status_code == 200
    assert fake_bucket.puts == []
