from __future__ import annotations

import time
from http.cookiejar import Cookie, CookieJar
from pathlib import Path

import pytest

import video_sum_service.bilibili_cookies as bilibili_cookies
from video_sum_infra.config import ServiceSettings
from video_sum_service.app import settings_manager


def write_netscape_cookie_file(path: Path, *, sessdata: str | None, expires: int | None) -> None:
    lines = ["# Netscape HTTP Cookie File"]
    if sessdata is not None:
        expire_text = "0" if expires is None else str(expires)
        lines.append(f".bilibili.com\tTRUE\t/\tTRUE\t{expire_text}\tSESSDATA\t{sessdata}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def make_cookie(name: str, value: str, domain: str = ".bilibili.com") -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=True,
        expires=2000000000,
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def test_capture_bilibili_cookies_from_browser_writes_netscape_file(monkeypatch, tmp_path: Path) -> None:
    settings_manager._settings = ServiceSettings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        tasks_dir=tmp_path / "tasks",
        runtime_channel="base",
    )

    jar = CookieJar()
    jar.set_cookie(make_cookie("SESSDATA", "session-value"))
    jar.set_cookie(make_cookie("bili_jct", "csrf-value"))
    opened_urls: list[str] = []

    monkeypatch.setattr(bilibili_cookies.webbrowser, "open", lambda url: opened_urls.append(url))
    monkeypatch.setattr(bilibili_cookies, "extract_cookies_from_browser", lambda browser, logger: jar)

    result = bilibili_cookies.capture_bilibili_cookies_from_browser(
        browsers=["chrome"],
        timeout_seconds=0,
    )

    cookies_file = Path(str(result["cookiesFile"]))
    assert result["cookieCount"] == 2
    assert result["browser"] == "chrome"
    assert opened_urls == [bilibili_cookies.BILIBILI_LOGIN_URL]
    assert cookies_file.exists()
    content = cookies_file.read_text(encoding="utf-8")
    assert "# Netscape HTTP Cookie File" in content
    assert "SESSDATA\tsession-value" in content
    assert "bili_jct\tcsrf-value" in content


def test_capture_bilibili_cookies_from_browser_requires_login_cookie(monkeypatch, tmp_path: Path) -> None:
    settings_manager._settings = ServiceSettings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        tasks_dir=tmp_path / "tasks",
        runtime_channel="base",
    )

    jar = CookieJar()
    jar.set_cookie(make_cookie("bili_jct", "csrf-value"))

    monkeypatch.setattr(bilibili_cookies.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(bilibili_cookies, "extract_cookies_from_browser", lambda browser, logger: jar)

    with pytest.raises(RuntimeError, match="没有从本机浏览器读取到 B 站登录态"):
        bilibili_cookies.capture_bilibili_cookies_from_browser(
            browsers=["chrome"],
            timeout_seconds=0,
        )


def test_create_bilibili_login_qrcode(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"url": "https://passport.bilibili.com/qrcode", "qrcode_key": "qr-key"}}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, **kwargs) -> FakeResponse:
            assert url == bilibili_cookies.BILIBILI_QRCODE_GENERATE_URL
            return FakeResponse()

    def fake_client(*args, **kwargs) -> FakeClient:
        assert kwargs["headers"]["Referer"] == "https://www.bilibili.com/"
        assert "Mozilla/5.0" in kwargs["headers"]["User-Agent"]
        return FakeClient()

    monkeypatch.setattr(bilibili_cookies.httpx, "Client", fake_client)

    result = bilibili_cookies.create_bilibili_login_qrcode()

    assert result["url"] == "https://passport.bilibili.com/qrcode"
    assert result["qrcodeKey"] == "qr-key"


def test_poll_bilibili_login_qrcode_writes_confirmed_cookies(monkeypatch, tmp_path: Path) -> None:
    settings_manager._settings = ServiceSettings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        tasks_dir=tmp_path / "tasks",
        runtime_channel="base",
    )

    jar = CookieJar()
    jar.set_cookie(make_cookie("SESSDATA", "session-value"))

    class FakeCookies:
        def __init__(self) -> None:
            self.jar = jar

    class FakeResponse:
        cookies = FakeCookies()

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"code": 0, "message": ""}}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, params: dict[str, str], **kwargs) -> FakeResponse:
            assert url == bilibili_cookies.BILIBILI_QRCODE_POLL_URL
            assert params == {"qrcode_key": "qr-key"}
            return FakeResponse()

    def fake_client(*args, **kwargs) -> FakeClient:
        assert kwargs["headers"]["Referer"] == "https://www.bilibili.com/"
        assert "Mozilla/5.0" in kwargs["headers"]["User-Agent"]
        return FakeClient()

    monkeypatch.setattr(bilibili_cookies.httpx, "Client", fake_client)

    result = bilibili_cookies.poll_bilibili_login_qrcode("qr-key")

    cookies_file = Path(str(result["cookiesFile"]))
    assert result["status"] == "confirmed"
    assert result["cookieCount"] == 1
    assert "SESSDATA\tsession-value" in cookies_file.read_text(encoding="utf-8")


def _configure_service_settings(
    monkeypatch, tmp_path: Path, cookies_file: str | None = None
) -> None:
    settings_manager._settings = ServiceSettings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        tasks_dir=tmp_path / "tasks",
        runtime_channel="base",
        ytdlp_cookies_file=cookies_file or "",
    )
    monkeypatch.delenv("VIDEO_SUM_YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)


def test_check_bilibili_login_status_without_cookie_file(monkeypatch, tmp_path: Path) -> None:
    _configure_service_settings(monkeypatch, tmp_path)

    result = bilibili_cookies.check_bilibili_login_status()

    assert result["configured"] is False
    assert result["cookieFile"] is None
    assert result["hasSessdata"] is False
    assert result["onlineValid"] is None
    assert "尚未配置" in str(result["message"])


def test_check_bilibili_login_status_with_valid_sessdata(monkeypatch, tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    write_netscape_cookie_file(
        cookies_file, sessdata="session-value", expires=int(time.time()) + 3600
    )
    _configure_service_settings(monkeypatch, tmp_path, cookies_file=str(cookies_file))

    class FakeResponse:
        def json(self) -> dict[str, object]:
            return {"code": 0, "data": {"isLogin": True, "uname": "测试用户"}}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, **kwargs) -> FakeResponse:
            assert url == bilibili_cookies.BILIBILI_NAV_URL
            assert "SESSDATA=session-value" in kwargs["headers"]["Cookie"]
            return FakeResponse()

    monkeypatch.setattr(bilibili_cookies.httpx, "Client", FakeClient)

    result = bilibili_cookies.check_bilibili_login_status()

    assert result["configured"] is True
    assert result["hasSessdata"] is True
    assert result["sessdataExpired"] is False
    assert result["onlineValid"] is True
    assert result["account"] == "测试用户"
    assert "登录态有效" in str(result["message"])


def test_check_bilibili_login_status_with_expired_sessdata(monkeypatch, tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    write_netscape_cookie_file(
        cookies_file, sessdata="expired-value", expires=int(time.time()) - 3600
    )
    _configure_service_settings(monkeypatch, tmp_path, cookies_file=str(cookies_file))

    result = bilibili_cookies.check_bilibili_login_status()

    assert result["configured"] is True
    assert result["hasSessdata"] is True
    assert result["sessdataExpired"] is True
    assert result["onlineValid"] is None
    assert "已过期" in str(result["message"])


def test_check_bilibili_login_status_without_sessdata(monkeypatch, tmp_path: Path) -> None:
    cookies_file = tmp_path / "cookies.txt"
    write_netscape_cookie_file(cookies_file, sessdata=None, expires=None)
    _configure_service_settings(monkeypatch, tmp_path, cookies_file=str(cookies_file))

    result = bilibili_cookies.check_bilibili_login_status()

    assert result["configured"] is True
    assert result["hasSessdata"] is False
    assert result["onlineValid"] is None
    assert "缺少 SESSDATA" in str(result["message"])
