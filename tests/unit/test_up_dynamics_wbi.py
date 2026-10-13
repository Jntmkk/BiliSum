import hashlib
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from video_sum_service import bilibili_wbi as wbi


@pytest.fixture(autouse=True)
def _fresh_signer_cache():
    """模块级签名器带内存缓存，测试间必须清空，否则 nav 请求被缓存跳过。"""
    wbi._signer.invalidate()
    yield
    wbi._signer.invalidate()


def test_mixin_table_has_64_entries():
    assert len(wbi.MIXIN_KEY_ENC_TAB) == 64
    assert sorted(wbi.MIXIN_KEY_ENC_TAB) == list(range(64))


def test_derive_mixin_key_matches_reference_algorithm():
    img_key = "0123456789abcdef0123456789abcdef"
    sub_key = "fedcba9876543210fedcba9876543210"
    raw = img_key + sub_key
    expected = "".join(raw[i] for i in wbi.MIXIN_KEY_ENC_TAB)[:32]
    assert wbi._derive_mixin_key(img_key, sub_key) == expected


def test_sign_params_produces_stable_wrid():
    params = {"mid": "1001", "ps": 30, "pn": 1}
    signed = wbi._sign_params(dict(params), "m" * 32)
    assert signed["w_rid"] == hashlib.md5(
        (urllib.parse.urlencode(sorted({**params, "wts": signed["wts"]}.items())) + "m" * 32).encode()
    ).hexdigest()
    assert signed["wts"] > 0
    # 幂等：不含残留 w_rid 且重新签名结果一致（wts 相同时）
    assert "w_rid" not in params


def test_sign_params_filters_special_characters():
    params = {"keyword": "a!'()*b"}
    signed = wbi._sign_params(dict(params), "k" * 32)
    expected_query = urllib.parse.urlencode(
        sorted({"keyword": "ab", "wts": signed["wts"]}.items())
    )
    assert signed["w_rid"] == hashlib.md5((expected_query + "k" * 32).encode()).hexdigest()


def _nav_response(img_key: str, sub_key: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "code": 0,
        "data": {
            "wbi_img": {
                "img_url": f"https://i0.hdslb.com/bfs/wbi/{img_key}.png",
                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png",
            }
        },
    }
    return response


def test_signed_get_success():
    with patch.object(wbi.httpx, "Client") as client_cls:
        fake_client = MagicMock()
        client_cls.return_value.__enter__.return_value = fake_client
        fake_client.get.side_effect = [
            _nav_response("a" * 32, "b" * 32),
            MagicMock(status_code=200, json=lambda: {"code": 0, "data": {"list": {}}}),
        ]
        result = wbi._signed_get(wbi.BILIBILI_SPACE_ARC_SEARCH_URL, {"mid": "1"}, "cookie")
    assert result == {"list": {}}


def test_signed_get_refreshes_keys_on_risk_control():
    calls = []

    def fake_get(url, params=None, headers=None):
        calls.append(url)
        if "nav" in url:
            return _nav_response("c" * 32, "d" * 32)
        if len(calls) == 2:
            return MagicMock(status_code=200, json=lambda: {"code": -352, "message": "风控"})
        return MagicMock(status_code=200, json=lambda: {"code": 0, "data": {}})

    with patch.object(wbi.httpx, "Client") as client_cls:
        fake_client = MagicMock()
        fake_client.get.side_effect = fake_get
        client_cls.return_value.__enter__.return_value = fake_client
        wbi._signer.invalidate()
        result = wbi._signed_get(wbi.BILIBILI_SPACE_ARC_SEARCH_URL, {"mid": "1"}, "cookie")
    assert result == {}
    # nav + 第一次 -352 + 刷新 key 重新取 nav + 重试成功
    assert len(calls) == 4


def test_signed_get_raises_after_retry_exhausts():
    def fake_get(url, params=None, headers=None):
        if "nav" in url:
            return _nav_response("c" * 32, "d" * 32)
        return MagicMock(status_code=200, json=lambda: {"code": -352, "message": "风控"})

    with patch.object(wbi.httpx, "Client") as client_cls:
        fake_client = MagicMock()
        fake_client.get.side_effect = fake_get
        client_cls.return_value.__enter__.return_value = fake_client
        wbi._signer.invalidate()
        try:
            wbi._signed_get(wbi.BILIBILI_SPACE_ARC_SEARCH_URL, {"mid": "1"}, "cookie")
        except wbi.WbiRiskControlError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected WbiRiskControlError")


def test_fetch_up_videos_parses_vlist():
    payload = {
        "code": 0,
        "data": {
            "list": {
                "vlist": [
                    {
                        "bvid": "BV1xx411c7mD",
                        "aid": 123,
                        "title": "测试视频",
                        "pic": "//i0.hdslb.com/bfs/archive/x.jpg",
                        "length": "03:22",
                        "created": 1700000000,
                        "description": "简介",
                    }
                ]
            }
        },
    }

    def fake_get(url, params=None, headers=None):
        if "nav" in url:
            return _nav_response("a" * 32, "b" * 32)
        return MagicMock(status_code=200, json=lambda: payload)

    with patch.object(wbi.httpx, "Client") as client_cls:
        fake_client = MagicMock()
        fake_client.get.side_effect = fake_get
        client_cls.return_value.__enter__.return_value = fake_client
        wbi._signer.invalidate()
        items = wbi.fetch_up_videos("1001", "cookie")

    assert len(items) == 1
    item = items[0]
    assert item.bvid == "BV1xx411c7mD"
    assert item.aid == 123
    assert item.duration == 202
    assert item.cover_url == "https://i0.hdslb.com/bfs/archive/x.jpg"
    assert item.pubdate == 1700000000


def test_parse_duration_formats():
    assert wbi._parse_duration_seconds("03:22") == 202
    assert wbi._parse_duration_seconds("1:02:03") == 3723
    assert wbi._parse_duration_seconds("45") == 45
    assert wbi._parse_duration_seconds("") == 0
    assert wbi._parse_duration_seconds("invalid") == 0
    assert wbi._parse_duration_seconds(None) == 0


def test_resolve_up_identity_from_url_and_mid():
    identity_payload = {"code": 0, "data": {"name": "某 UP", "face": "https://face/x.jpg"}}

    def fake_get(url, params=None, headers=None):
        if "nav" in url:
            return _nav_response("a" * 32, "b" * 32)
        return MagicMock(status_code=200, json=lambda: identity_payload)

    with patch.object(wbi.httpx, "Client") as client_cls:
        fake_client = MagicMock()
        fake_client.get.side_effect = fake_get
        client_cls.return_value.__enter__.return_value = fake_client
        wbi._signer.invalidate()
        by_url = wbi.resolve_up_identity("https://space.bilibili.com/208259", "cookie")
        by_mid = wbi.resolve_up_identity("208259", "cookie")
    assert by_url == {"mid": "208259", "name": "某 UP", "face": "https://face/x.jpg"}
    assert by_mid["mid"] == "208259"


def test_resolve_up_identity_rejects_unknown_query():
    try:
        wbi.resolve_up_identity("不是链接也不是数字", "cookie")
    except wbi.UpDynamicsError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UpDynamicsError")
