"""SSRF-safe HTTP fetch utility.

Resolves DNS before connecting and validates every resolved IP against
private/reserved ranges.  Connects to the **pre-resolved IP** directly
(no second DNS lookup, no rebinding window).

No Django imports — reusable by any extractor.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import urljoin, urlparse

from apps.core.user_agent import USER_AGENT

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class SSRFBlockedError(ValueError):
    """Raised when a URL resolves to a blocked (private/reserved) IP."""

    def __init__(self, url: str, blocked_ip: str):
        self.url = url
        self.blocked_ip = blocked_ip
        super().__init__(f"Blocked request to {url}: resolved to {blocked_ip}")


@dataclass
class FetchResponse:
    status: int
    headers: dict[str, str]  # lowercased header names
    body: bytes  # already read, capped at max_bytes


class _FetchOneResult(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes
    redirect_location: str | None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_MAX_REDIRECTS = 5


def _is_blocked(addr: str) -> bool:
    """Return True if *addr* is not globally routable unicast.

    Uses ``is_global`` rather than enumerating bad categories — this way
    new reserved ranges added in future Python versions are automatically
    blocked.  Also handles IPv4-mapped IPv6 (e.g. ``::ffff:127.0.0.1``).

    Multicast is checked separately because Python considers multicast
    addresses ``is_global`` (they are globally allocated), but they are
    not unicast-routable and no legitimate web page lives at one.
    """
    ip = ipaddress.ip_address(addr)
    return not ip.is_global or ip.is_multicast


def _resolve_and_validate(hostname: str, port: int) -> str:
    """Resolve *hostname* via DNS and return the first non-blocked IP.

    Raises ``SSRFBlockedError`` if every resolved address is blocked,
    or ``OSError`` if DNS resolution fails entirely.
    """
    infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    if not infos:
        raise OSError(f"DNS resolution returned no results for {hostname}")

    for _family, _type, _proto, _canonname, sockaddr in infos:
        addr = sockaddr[0]
        if isinstance(addr, str) and not _is_blocked(addr):
            return addr

    # Every resolved IP was blocked — raise with the first one for diagnostics.
    first_addr = infos[0][4][0]
    if not isinstance(first_addr, str):
        raise OSError(f"DNS resolution returned non-IP sockaddr for {hostname}")
    raise SSRFBlockedError(f"http://{hostname}:{port}", first_addr)


def _fetch_one(
    ip: str,
    port: int,
    hostname: str,
    path: str,
    *,
    use_tls: bool,
    timeout: float,
    max_bytes: int,
) -> _FetchOneResult:
    """Single HTTP request to *ip*."""
    # Always create a plain HTTPConnection to the resolved IP.
    # For TLS we wrap the socket after connect() — this lets us use
    # server_hostname for SNI/cert validation against the real hostname.
    conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    ctx = ssl.create_default_context() if use_tls else None

    headers_out = {
        "Host": hostname,
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Connection": "close",
    }

    try:
        conn.connect()
        if ctx is not None:
            conn.sock = ctx.wrap_socket(conn.sock, server_hostname=hostname)
        conn.request("GET", path, headers=headers_out)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        body = resp.read(max_bytes)
        redirect = (
            resp_headers.get("location")
            if status in (301, 302, 303, 307, 308)
            else None
        )
        return _FetchOneResult(status, resp_headers, body, redirect)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def safe_fetch(url: str, *, timeout: float, max_bytes: int = 65536) -> FetchResponse:
    """Fetch *url* with SSRF protection.

    - Validates scheme (http/https only).
    - Resolves DNS and blocks private/reserved IPs.
    - Connects to the pre-resolved IP (no DNS rebinding gap).
    - Follows up to 5 redirects, re-validating each hop.
    - Enforces a wall-clock *timeout* across all hops.

    Raises:
        SSRFBlockedError: URL targets a private/reserved IP.
        socket.timeout: wall-clock deadline exceeded.
        OSError / ConnectionError: network-level failure.
    """
    deadline = time.monotonic() + timeout

    current_url = url
    last_response: FetchResponse | None = None
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urlparse(current_url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise SSRFBlockedError(current_url, "invalid-scheme")

        hostname = parsed.hostname or ""
        if not hostname:
            raise SSRFBlockedError(current_url, "empty-hostname")
        use_tls = scheme == "https"
        default_port = 443 if use_tls else 80
        port = parsed.port or default_port
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # Resolve and validate IP
        ip = _resolve_and_validate(hostname, port)

        # Calculate remaining time budget
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("wall-clock deadline exceeded")
        hop_timeout = max(remaining, 0.5)

        result = _fetch_one(
            ip,
            port,
            hostname,
            path,
            use_tls=use_tls,
            timeout=hop_timeout,
            max_bytes=max_bytes,
        )
        last_response = FetchResponse(
            status=result.status, headers=result.headers, body=result.body
        )

        if result.redirect_location is None:
            return last_response

        # Follow redirect — resolve the new URL
        current_url = urljoin(current_url, result.redirect_location)

    # Exhausted redirect budget — return last response as-is
    assert last_response is not None
    return last_response
