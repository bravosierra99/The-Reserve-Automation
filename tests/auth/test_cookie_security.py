"""Tests for web/cookies.py — when cookies get the ``Secure`` attribute.

Background: ``Secure`` on a cookie issued from a plain-http origin makes the
browser discard it *silently*. Every route used to hardcode ``secure=True``,
which meant that on direct LAN access (http://192.168.x.x:8000) the
``participant_sessions`` and ``session`` cookies were never stored — the
server looked fine, the browser just threw the cookie away.

The detection must stay biased toward "secure": in production the request
arrives over a Cloudflare Tunnel that speaks plain http to nginx, so
X-Forwarded-Proto is ``http`` there and cannot be the deciding signal.
"""

from starlette.requests import Request

from reserve_automation.web.cookies import DEFAULT_CF_JWT_HEADER, is_secure_request


def _request(scheme: str = "http", headers: dict | None = None) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]

    class _State:
        auth_config = None

    class _App:
        state = _State()

    return Request({
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "headers": raw_headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "app": _App(),
    })


class TestIsSecureRequest:
    def test_plain_http_direct_is_not_secure(self):
        assert is_secure_request(_request("http")) is False

    def test_direct_https_is_secure(self):
        assert is_secure_request(_request("https")) is True

    def test_cloudflare_jwt_header_is_secure_even_over_http(self):
        # The production case: cloudflared -> nginx is plain http, so the
        # scheme and X-Forwarded-Proto both say "http". The JWT header is the
        # only reliable tell that the browser's leg was https.
        req = _request("http", {DEFAULT_CF_JWT_HEADER: "a.jwt.token"})
        assert is_secure_request(req) is True

    def test_x_forwarded_proto_https_is_secure(self):
        assert is_secure_request(_request("http", {"X-Forwarded-Proto": "https"})) is True

    def test_x_forwarded_proto_uses_first_hop(self):
        req = _request("http", {"X-Forwarded-Proto": "https, http"})
        assert is_secure_request(req) is True

    def test_x_forwarded_proto_http_is_not_secure(self):
        assert is_secure_request(_request("http", {"X-Forwarded-Proto": "http"})) is False

    def test_empty_jwt_header_does_not_count(self):
        assert is_secure_request(_request("http", {DEFAULT_CF_JWT_HEADER: ""})) is False
