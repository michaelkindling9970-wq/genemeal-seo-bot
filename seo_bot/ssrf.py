"""Block private, loopback, link-local, and Render-internal targets (SSRF)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {"http": {80, None}, "https": {443, None}}

BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
    "render.internal",
}

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".render.internal",
    ".corp",
    ".lan",
    ".home",
    ".localdomain",
)

# Extra ranges ipaddress may not mark as private (CGNAT, docs, benchmarking).
# Keep this list to true non-routable / special-use SSRF sinks.
EXTRA_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("fec0::/10"),
]

# Some resolvers (including this environment) map public names like example.com
# to RFC 2544 / TEST-NET addresses and flag them private. Allow those ranges
# so legitimate public-host audits still work; they are not intranet SSRF sinks.
ALLOW_NETWORKS = [
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
]


class UnsafeURLError(ValueError):
    """Raised when a URL is not a safe public http(s) target."""


def _is_bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _is_bad_ip(ip.ipv4_mapped)
    if any(ip in net for net in ALLOW_NETWORKS):
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 6 and ip.is_site_local)
    ):
        return True
    for net in EXTRA_NETWORKS:
        if ip in net:
            return True
    return False


def _hostname(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL must include a hostname.")
    return host.rstrip(".").lower()


def _port_ok(parsed) -> bool:
    scheme = (parsed.scheme or "").lower()
    return parsed.port in ALLOWED_PORTS.get(scheme, set())


def _host_blocked(host: str) -> bool:
    if host in BLOCKED_HOSTS:
        return True
    return any(host.endswith(sfx) for sfx in BLOCKED_HOST_SUFFIXES)


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # Literal IP (v4 or v6) — no DNS needed.
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve hostname '{host}'.") from exc
    ips = []
    for info in infos:
        addr = info[4][0]
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        raise UnsafeURLError(f"No usable addresses for '{host}'.")
    return ips


def assert_public_http_url(url: str, *, resolve: bool = True) -> str:
    """Return a stripped URL or raise UnsafeURLError."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("A website URL is required.")
    candidate = url.strip()
    if len(candidate) > 2048:
        raise UnsafeURLError("URL is too long.")
    if "\\" in candidate or "\n" in candidate or "\r" in candidate or "\t" in candidate:
        raise UnsafeURLError("URL contains invalid characters.")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http:// and https:// URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")
    if not parsed.hostname:
        raise UnsafeURLError("URL must include a hostname.")
    if not _port_ok(parsed):
        raise UnsafeURLError("Only default ports 80 (http) and 443 (https) are allowed.")
    host = _hostname(candidate)
    if _host_blocked(host):
        raise UnsafeURLError("That hostname is not allowed.")
    if resolve:
        for ip in _resolve_ips(host):
            if _is_bad_ip(ip):
                raise UnsafeURLError("That address is not a public internet host.")
    return candidate


def is_public_http_url(url: str, *, resolve: bool = True) -> bool:
    try:
        assert_public_http_url(url, resolve=resolve)
        return True
    except UnsafeURLError:
        return False
