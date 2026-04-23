"""URL validation utilities for SSRF protection."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


# Private/internal IP networks that should never be accessed via SSRF
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / cloud metadata
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a blocked private/internal range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # If we can't parse it, block it
    return any(addr in network for network in _BLOCKED_NETWORKS)


def validate_url_not_internal(url: str) -> str:
    """Validate that a URL does not point to an internal/private IP.

    Checks both the URL scheme and resolves the hostname to verify
    the target IP is not in a private range (prevents DNS rebinding).

    Args:
        url: The URL to validate.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If the URL targets an internal resource or has an invalid scheme.
    """
    parsed = urlparse(url)

    # Only allow http and https schemes
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed (only http/https)")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # Resolve hostname to IP and check it's not private
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in resolved_ips:
        ip_str = sockaddr[0]
        if _is_private_ip(ip_str):
            raise ValueError(
                f"URL resolves to private/internal IP ({ip_str}). "
                "Requests to internal networks are not allowed."
            )

    return url


async def validate_url_not_internal_async(url: str) -> str:
    """Async variant of validate_url_not_internal for use in async route handlers.

    Offloads the blocking DNS resolution to a thread pool so the event loop
    is not blocked.
    """
    return await asyncio.to_thread(validate_url_not_internal, url)
