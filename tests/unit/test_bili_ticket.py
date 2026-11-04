from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from video_sum_service import bilibili_wbi as wbi


def _patch_data_dir(tmp_path: Path):
    settings = SimpleNamespace(data_dir=str(tmp_path))
    return patch.object(wbi, "settings_manager", SimpleNamespace(current=settings))


def _write_cookie_file(tmp_path: Path) -> Path:
    cookie_file = tmp_path / "cookies" / "bilibili.txt"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t1807587122\tSESSDATA\ttest-sessdata\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t1807587122\tbili_jct\ttest-jct\n"
        ".bilibili.com\tTRUE\t/\tTRUE\t1807587122\tbuvid3\ttest-buvid3\n",
        encoding="utf-8",
    )
    return cookie_file


def test_load_cookie_header_includes_bili_ticket(tmp_path: Path) -> None:
    _write_cookie_file(tmp_path)
    captured: dict[str, str] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "code": 0,
                "message": "OK",
                "data": {
                    "ticket": "test-ticket-jwt",
                    "created_at": 0,
                    "ttl": 259200,
                    "context": {},
                },
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.headers = kwargs.get("headers", {})

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def post(self, url: str, **kwargs) -> FakeResponse:
            captured["url"] = url
            return FakeResponse()

    with (
        _patch_data_dir(tmp_path),
        patch.object(wbi, "_device_fingerprint_cookies", return_value={}),
        patch.object(httpx, "Client", FakeClient),
    ):
        header = wbi.load_bilibili_cookie_header()

    assert header is not None
    assert "bili_ticket=test-ticket-jwt" in header
    assert "SESSDATA=test-sessdata" in header
    assert "key_id=ec02" in captured["url"]
    assert "context%5Bts%5D=" in captured["url"]


def test_cookie_header_with_ticket_falls_back_on_failure() -> None:
    original = "SESSDATA=x; buvid3=y"

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *exc) -> None:
            return None

        def post(self, url: str, **kwargs):
            raise httpx.ConnectError("no route")

    with (
        patch.object(httpx, "Client", FakeClient),
        patch.object(wbi, "_device_fingerprint_cookies", return_value={}),
        patch.dict("os.environ", {}, clear=True),
    ):
        wbi.reset_ticket_cache_for_tests()
        result = wbi.cookie_header_with_ticket(original)

    assert result == original


def test_cookie_header_with_ticket_skips_when_present() -> None:
    original = "SESSDATA=x; bili_ticket=existing"
    assert wbi.cookie_header_with_ticket(original) == original
