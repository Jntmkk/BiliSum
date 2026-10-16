from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from video_sum_service import bilibili_wbi as wbi

NETSCAPE_CONTENT = """# Netscape HTTP Cookie File
.bilibili.com\tTRUE\t/\tFALSE\t1700000000\tSESSDATA\tsess-value-1
.bilibili.com\tTRUE\t/\tFALSE\t1700000000\tbili_jct\tjct-value-1
.bilibili.com\tTRUE\t/\tFALSE\t0\tDedeUserID\t12345
.other-site.com\tTRUE\t/\tFALSE\t1700000000\tSESSDATA\tshould-be-ignored
"""


@pytest.fixture(autouse=True)
def _clear_account_cache():
    wbi._account_cache = None
    yield
    wbi._account_cache = None


def _patch_data_dir(tmp_path: Path):
    settings = SimpleNamespace(data_dir=str(tmp_path))
    return patch.object(wbi, "settings_manager", SimpleNamespace(current=settings))


def _write_cookie_file(tmp_path: Path, content: str = NETSCAPE_CONTENT) -> None:
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    (cookies_dir / "bilibili.txt").write_text(content, encoding="utf-8")


def _nav_response(*, is_login: bool = True) -> httpx.Response:
    data = (
        {
            "isLogin": True,
            "mid": 42,
            "uname": "测试账号",
            "face": "//i0.hdslb.com/bfs/face/abc.jpg",
        }
        if is_login
        else {"isLogin": False}
    )
    return httpx.Response(
        200,
        json={"code": 0, "data": data},
        request=httpx.Request("GET", wbi.BILIBILI_NAV_URL),
    )


def test_load_cookie_header_parses_netscape_file(tmp_path: Path):
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir(parents=True)
    (cookies_dir / "bilibili.txt").write_text(NETSCAPE_CONTENT, encoding="utf-8")

    with _patch_data_dir(tmp_path):
        header = wbi.load_bilibili_cookie_header()

    assert header is not None
    assert "SESSDATA=sess-value-1" in header
    assert "bili_jct=jct-value-1" in header
    assert "should-be-ignored" not in header


def test_load_cookie_header_missing_file(tmp_path: Path):
    with _patch_data_dir(tmp_path):
        assert wbi.load_bilibili_cookie_header() is None


def test_load_cookie_header_requires_sessdata(tmp_path: Path):
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir(parents=True)
    (cookies_dir / "bilibili.txt").write_text(
        ".bilibili.com\tTRUE\t/\tFALSE\t1700000000\tbili_jct\tonly-jct\n",
        encoding="utf-8",
    )
    with _patch_data_dir(tmp_path):
        assert wbi.load_bilibili_cookie_header() is None


def test_describe_account_without_cookie_skips_network(tmp_path: Path):
    with _patch_data_dir(tmp_path), patch.object(httpx, "Client") as client:
        result = wbi.describe_bilibili_account()

    assert result["loggedIn"] is False
    assert "尚未配置" in str(result["message"])
    client.assert_not_called()


def test_describe_account_returns_name_and_normalized_face(tmp_path: Path):
    _write_cookie_file(tmp_path)
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _nav_response()

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        result = wbi.describe_bilibili_account()

    assert result == {
        "loggedIn": True,
        "mid": 42,
        "name": "测试账号",
        "face": "https://i0.hdslb.com/bfs/face/abc.jpg",
        "message": "",
    }


def test_describe_account_reports_expired_login(tmp_path: Path):
    _write_cookie_file(tmp_path)
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _nav_response(is_login=False)

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        result = wbi.describe_bilibili_account()

    assert result["loggedIn"] is False
    assert "失效" in str(result["message"])


def test_describe_account_swallows_network_errors(tmp_path: Path):
    _write_cookie_file(tmp_path)
    client = MagicMock()
    client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        result = wbi.describe_bilibili_account()

    assert result["loggedIn"] is False
    assert result["name"] == ""


def test_describe_account_caches_per_cookie(tmp_path: Path):
    _write_cookie_file(tmp_path)
    nav_calls: list[str] = []
    client = MagicMock()

    def fake_get(url, **kwargs):
        if wbi.BILIBILI_FINGER_SPI_URL in url:
            return _spi_response()
        nav_calls.append(url)
        return _nav_response()

    client.return_value.__enter__.return_value.get.side_effect = fake_get

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        wbi.describe_bilibili_account()
        wbi.describe_bilibili_account()
        wbi.describe_bilibili_account(force=True)

    assert len(nav_calls) == 2


def test_describe_account_cache_invalidated_on_cookie_change(tmp_path: Path):
    _write_cookie_file(tmp_path)
    nav_calls: list[str] = []
    client = MagicMock()

    def fake_get(url, **kwargs):
        if wbi.BILIBILI_FINGER_SPI_URL in url:
            return _spi_response()
        nav_calls.append(url)
        return _nav_response()

    client.return_value.__enter__.return_value.get.side_effect = fake_get

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        wbi.describe_bilibili_account()
        _write_cookie_file(
            tmp_path,
            NETSCAPE_CONTENT.replace("sess-value-1", "sess-value-2"),
        )
        wbi.describe_bilibili_account()

    assert len(nav_calls) == 2


def _spi_response(b3: str = "bv3-value", b4: str = "bv4-value") -> httpx.Response:
    return httpx.Response(
        200,
        json={"code": 0, "data": {"b_3": b3, "b_4": b4}},
        request=httpx.Request("GET", wbi.BILIBILI_FINGER_SPI_URL),
    )


@pytest.fixture(autouse=True)
def _clear_fingerprint_cache():
    wbi.reset_fingerprint_cache_for_tests()
    yield
    wbi.reset_fingerprint_cache_for_tests()


def test_cookie_header_with_fingerprint_appends_missing_buvids():
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _spi_response()

    with patch.object(httpx, "Client", client):
        header = wbi.cookie_header_with_fingerprint("SESSDATA=s; DedeUserID=1")

    assert "SESSDATA=s" in header
    assert "DedeUserID=1" in header
    assert "buvid3=bv3-value" in header
    assert "buvid4=bv4-value" in header


def test_cookie_header_with_fingerprint_keeps_existing_buvid3():
    """文档要求持久化既有 buvid3，不能被新领的值覆盖。"""
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _spi_response()

    with patch.object(httpx, "Client", client):
        header = wbi.cookie_header_with_fingerprint("SESSDATA=s; buvid3=already-there")

    assert "buvid3=already-there" in header
    assert "buvid3=bv3-value" not in header
    # buvid4 原本缺失，仍应补上
    assert "buvid4=bv4-value" in header


def test_fingerprint_is_cached_across_calls():
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _spi_response()

    with patch.object(httpx, "Client", client):
        wbi.cookie_header_with_fingerprint("SESSDATA=s")
        wbi.cookie_header_with_fingerprint("SESSDATA=s")
        wbi.cookie_header_with_fingerprint("SESSDATA=s")

    assert client.return_value.__enter__.return_value.get.call_count == 1


def test_fingerprint_failure_leaves_header_unchanged():
    """指纹接口挂了不应中断请求，只是少两个 cookie。"""
    client = MagicMock()
    client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("boom")

    with patch.object(httpx, "Client", client):
        header = wbi.cookie_header_with_fingerprint("SESSDATA=s")

    assert header == "SESSDATA=s"


def test_load_cookie_header_includes_fingerprint(tmp_path: Path):
    _write_cookie_file(tmp_path)
    client = MagicMock()
    client.return_value.__enter__.return_value.get.return_value = _spi_response()

    with _patch_data_dir(tmp_path), patch.object(httpx, "Client", client):
        header = wbi.load_bilibili_cookie_header()

    assert header is not None
    assert "SESSDATA=sess-value-1" in header
    assert "buvid3=" in header
