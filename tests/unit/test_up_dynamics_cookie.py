from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from video_sum_service import bilibili_cookie_store as cookie_store
from video_sum_service import bilibili_wbi as wbi

NETSCAPE_CONTENT = """# Netscape HTTP Cookie File
.bilibili.com\tTRUE\t/\tFALSE\t1700000000\tSESSDATA\tsess-value-1
.bilibili.com\tTRUE\t/\tFALSE\t1700000000\tbili_jct\tjct-value-1
.bilibili.com\tTRUE\t/\tFALSE\t0\tDedeUserID\t12345
.other-site.com\tTRUE\t/\tFALSE\t1700000000\tSESSDATA\tshould-be-ignored
"""


@pytest.fixture(autouse=True)
def _reset_cookie_store():
    cookie_store.reset_bilibili_cookie_store_for_tests()
    yield
    cookie_store.reset_bilibili_cookie_store_for_tests()


def _patch_data_dir(tmp_path: Path):
    settings = SimpleNamespace(data_dir=str(tmp_path))
    return patch.object(cookie_store, "settings_manager", SimpleNamespace(current=settings))


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
