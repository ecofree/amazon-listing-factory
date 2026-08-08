from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests


class UnsafeUrlError(RuntimeError):
    pass


class UrlResolutionError(UnsafeUrlError, ConnectionError):
    pass


URL_SAFETY_POLICY_VERSION = "public-http-v3-validated-redirects"
MAX_PUBLIC_REDIRECTS = 5
_PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_PROXY_FAKE_IP_NETWORK_V6 = ipaddress.ip_network("fdfe:dcba:9876::/64")


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError(f"Unsupported image URL: {url}")
    host = parsed.hostname.strip("[]")
    literal_ip = _literal_ip(host)
    addresses = _resolved_addresses(host)
    if not addresses:
        raise UrlResolutionError(f"Image URL host cannot be resolved: {host}")
    for address in addresses:
        assert_public_ip(address, hostname=host, allow_proxy_fake=literal_ip is None)


def assert_public_ip(address: str, *, hostname: str = "", allow_proxy_fake: bool = True) -> None:
    """Reject a private peer after the HTTP stack has connected.

    URL validation alone is vulnerable to DNS rebinding between resolution and
    connection.  Callers that can inspect the socket peer should invoke this
    after opening the response as well.  The configured proxy test networks
    remain allowed for hostname requests because the proxy owns the public
    resolution in that mode.
    """
    try:
        ip = ipaddress.ip_address(str(address).strip("[]"))
    except ValueError as exc:
        raise UrlResolutionError(f"HTTP peer address is invalid: {address}") from exc
    if allow_proxy_fake and (ip in _PROXY_FAKE_IP_NETWORK or ip in _PROXY_FAKE_IP_NETWORK_V6):
        return
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        label = f" for {hostname}" if hostname else ""
        raise UnsafeUrlError(f"HTTP peer resolves to a non-public address{label}: {ip}")


def assert_response_peer_public(response: object, *, hostname: str = "") -> None:
    """Validate an inspectable urllib/requests socket peer, if available."""
    candidates = [
        getattr(getattr(getattr(response, "raw", None), "_connection", None), "sock", None),
        getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None),
    ]
    for sock in candidates:
        if sock is None or not hasattr(sock, "getpeername"):
            continue
        try:
            peer = sock.getpeername()
            address = peer[0] if isinstance(peer, tuple) else peer
            assert_public_ip(str(address), hostname=hostname)
            return
        except OSError:
            continue


def request_public_url(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> requests.Response:
    """Request a public URL while validating every redirect target.

    Callers own and must close the returned response.  Redirects are handled
    explicitly so an unvalidated final Location cannot bypass the URL policy.
    """
    current = str(url or "").strip()
    for _ in range(MAX_PUBLIC_REDIRECTS + 1):
        assert_public_http_url(current)
        response = requests.request(
            method,
            current,
            headers=headers or {},
            allow_redirects=False,
            timeout=timeout,
            stream=stream,
        )
        assert_response_peer_public(response, hostname=urlparse(current).hostname or "")
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = str(response.headers.get("Location") or "").strip()
        response.close()
        if not location:
            raise UnsafeUrlError(f"Public URL redirect has no Location header: {current}")
        current = urljoin(current, location)
    raise UnsafeUrlError(f"Public URL exceeded redirect limit: {url}")


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _resolved_addresses(host: str) -> set[str]:
    literal = _literal_ip(host)
    if literal is not None:
        return {host}
    results: set[str] = set()
    try:
        for family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(host, None):
            if family in {socket.AF_INET, socket.AF_INET6} and sockaddr:
                results.add(str(sockaddr[0]))
    except OSError:
        return set()
    return results
