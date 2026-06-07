"""Unit tests for SSRF URL validation (utils/url_validation.py).

These guard the SSRF protection used before fetching user-supplied URLs.
DNS resolution is mocked so the tests are deterministic and offline.
"""

import socket
from unittest.mock import patch

import pytest

from reserve_automation.utils.url_validation import (
    _is_private_ip,
    validate_url_not_internal,
    validate_url_not_internal_async,
)

GAI_TARGET = "reserve_automation.utils.url_validation.socket.getaddrinfo"

# A routable public address used as the "allowed" case throughout.
PUBLIC_IP = "93.184.216.34"  # example.com


def _gai_result(*ips):
    """Build a socket.getaddrinfo-shaped result for the given IPs.

    Each entry is (family, type, proto, canonname, sockaddr); the validator
    only reads sockaddr[0]. IPv6 sockaddr is a 4-tuple, IPv4 a 2-tuple.
    """
    out = []
    for ip in ips:
        if ":" in ip:
            out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
        else:
            out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
    return out


class TestIsPrivateIp:
    """Direct tests for the _is_private_ip helper."""

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",        # loopback
            "127.255.255.254",  # loopback range edge
            "10.0.0.1",         # RFC1918
            "172.16.0.1",       # RFC1918
            "172.31.255.254",   # RFC1918 upper edge
            "192.168.1.1",      # RFC1918
            "169.254.169.254",  # link-local / cloud metadata endpoint
            "::1",              # IPv6 loopback
            "fc00::1",          # IPv6 unique-local
            "fe80::1",          # IPv6 link-local
        ],
    )
    def test_blocks_private_and_internal(self, ip):
        assert _is_private_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        ["8.8.8.8", "93.184.216.34", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"],
    )
    def test_allows_public(self, ip):
        assert _is_private_ip(ip) is False

    @pytest.mark.parametrize("bad", ["not-an-ip", "", "999.999.999.999", "10.0.0"])
    def test_unparseable_is_blocked(self, bad):
        # Fail closed: anything we cannot parse is treated as private/blocked.
        assert _is_private_ip(bad) is True


class TestValidateUrlScheme:
    """Scheme allowlist — checked before any DNS resolution."""

    @pytest.mark.parametrize(
        "url",
        ["ftp://example.com/x", "file:///etc/passwd", "gopher://example.com", "data:text/plain,hi"],
    )
    def test_rejects_non_http_schemes(self, url):
        with pytest.raises(ValueError, match="not allowed"):
            validate_url_not_internal(url)

    def test_rejects_missing_hostname(self):
        with pytest.raises(ValueError, match="no hostname"):
            validate_url_not_internal("http:///just/a/path")


class TestValidateUrlResolution:
    """Behavior around DNS resolution and private-IP blocking (mocked DNS)."""

    def test_allows_public_host(self):
        with patch(GAI_TARGET, return_value=_gai_result(PUBLIC_IP)):
            assert validate_url_not_internal("https://example.com/path") == \
                "https://example.com/path"

    def test_unresolvable_hostname_rejected(self):
        with patch(GAI_TARGET, side_effect=socket.gaierror("nope")):
            with pytest.raises(ValueError, match="Could not resolve"):
                validate_url_not_internal("https://no-such-host.invalid")

    def test_empty_resolution_rejected(self):
        with patch(GAI_TARGET, return_value=[]):
            with pytest.raises(ValueError, match="No addresses resolved"):
                validate_url_not_internal("https://example.com")

    @pytest.mark.parametrize(
        "ip",
        ["127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.169.254", "::1", "fc00::5"],
    )
    def test_rejects_host_resolving_to_private_ip(self, ip):
        with patch(GAI_TARGET, return_value=_gai_result(ip)):
            with pytest.raises(ValueError, match="private/internal IP"):
                validate_url_not_internal("https://attacker.example/")

    def test_dns_rebinding_any_private_address_blocks(self):
        # A dual-stack / multi-A host where one address is internal must be
        # rejected even though another address is public.
        with patch(GAI_TARGET, return_value=_gai_result(PUBLIC_IP, "10.0.0.7")):
            with pytest.raises(ValueError, match="private/internal IP"):
                validate_url_not_internal("https://mixed.example/")

    def test_all_public_addresses_allowed(self):
        with patch(GAI_TARGET, return_value=_gai_result(PUBLIC_IP, "1.1.1.1")):
            assert validate_url_not_internal("http://multi.example/") == \
                "http://multi.example/"


class TestValidateUrlAsync:
    """The async wrapper offloads to a thread but must enforce the same rules."""

    async def test_async_allows_public(self):
        with patch(GAI_TARGET, return_value=_gai_result(PUBLIC_IP)):
            result = await validate_url_not_internal_async("https://example.com/")
            assert result == "https://example.com/"

    async def test_async_rejects_private(self):
        with patch(GAI_TARGET, return_value=_gai_result("127.0.0.1")):
            with pytest.raises(ValueError, match="private/internal IP"):
                await validate_url_not_internal_async("https://localhost.attacker/")
