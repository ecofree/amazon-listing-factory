from __future__ import annotations

import ipaddress
import os
import socket
import time
from urllib.parse import urljoin, urlparse

import requests


class UnsafeUrlError(RuntimeError):
    pass


class UrlResolutionError(UnsafeUrlError, ConnectionError):
    pass


URL_SAFETY_POLICY_VERSION = 'public-http-v4-effective-proxy-route'
MAX_PUBLIC_REDIRECTS = 5
_PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_PROXY_FAKE_IP_NETWORK_V6 = ipaddress.ip_network("fdfe:dcba:9876::/64")


def proxy_for_url(url: str) -> str:
    from urllib.request import getproxies, proxy_bypass
    parsed=urlparse(url)
    return '' if proxy_bypass(parsed.netloc) else str(getproxies().get(parsed.scheme) or getproxies().get('all') or '')


def assert_public_http_url(url: str, *, proxy_url: str | None = None) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError(f"Unsupported image URL: {url}")
    host = parsed.hostname.strip("[]")
    literal_ip = _literal_ip(host)
    addresses = _resolved_addresses(host)
    if not addresses:
        raise UrlResolutionError(f"Image URL host cannot be resolved: {host}")
    proxy_url=proxy_for_url(url) if proxy_url is None else proxy_url
    for address in addresses:
        assert_public_ip(address, hostname=host, allow_proxy_fake=literal_ip is None and bool(proxy_url))


def assert_public_ip(
    address: str,
    *,
    hostname: str = "",
    allow_proxy_fake: bool = False,
    proxy_url: str = '',
) -> None:
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
    if proxy_url and ip in _configured_proxy_addresses(proxy_url):
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


def assert_response_peer_public(response: object, *, hostname: str = '', url: str = '', proxy_url: str | None = None) -> None:
    """Validate an inspectable peer; proxy exceptions require this effective route."""
    url=url or ('https://'+hostname if hostname else '')
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
            if proxy_url is None:
                bound=getattr(response,'_factory_proxy_url',None)
                proxy_url=bound if isinstance(bound,str) else proxy_for_url(url)
            assert_public_ip(
                str(address),
                hostname=hostname,
                proxy_url=proxy_url,
                allow_proxy_fake=bool(proxy_url),
            )
            return
        except OSError:
            continue


def _configured_proxy_addresses(proxy_url: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Only the proxy selected for this request, not other configured proxies."""
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for value in (proxy_url,):
        if not value:
            continue
        try:
            host = urlparse(value).hostname or ""
            literal = _literal_ip(host)
            if literal is not None:
                addresses.add(literal)
                continue
            for address in _resolved_addresses(host):
                addresses.add(ipaddress.ip_address(address))
        except (OSError, ValueError):
            continue
    return addresses


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
    deadline = time.monotonic() + timeout
    for _ in range(MAX_PUBLIC_REDIRECTS + 1):
        proxies=requests.utils.get_environ_proxies(current)
        proxy_url=requests.utils.select_proxy(current,proxies) or ''
        assert_public_http_url(current,proxy_url=proxy_url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout('Public URL total deadline exhausted')
        from .service_response import start_submission
        start_submission()
        response = requests.request(
            method,
            current,
            headers=headers or {},
            allow_redirects=False,
            timeout=remaining,
            stream=stream,
            proxies={'http':'','https':'','all':'',**proxies},
        )
        response._factory_proxy_url=proxy_url
        try:
            if time.monotonic() >= deadline:
                raise requests.Timeout('Public URL total deadline exhausted')
            assert_response_peer_public(response, hostname=urlparse(current).hostname or '', url=current, proxy_url=proxy_url)
        except (UnsafeUrlError, requests.Timeout):
            response.close()
            raise
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
