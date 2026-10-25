"""Hardened server-side fetching of media URLs.

Several routes fetch a URL the client chose (crop source, overlay logo, product shot) and the Meta upload helpers
download a media URL before re-uploading it. A plain `requests.get(url)` lets a caller point the server at its own
internal network (the Docker network, the cloud metadata endpoint at 169.254.169.254) or, through an open redirect on
an approved host, anywhere at all. Everything here:

  * accepts only http(s) URLs with no embedded credentials, on ports 80/443;
  * refuses any host that resolves to a private, loopback, link-local, CGNAT, multicast, reserved or unspecified
    address (IPv4-mapped IPv6 included);
  * follows redirects MANUALLY, re-validating every hop (max 3), never blindly;
  * enforces a hard size cap and an overall time budget while streaming.

Two modes:
  strict_hosts=True   only approved media hosts (Meta CDN suffixes, our R2 public host, our API host) over HTTPS.
                      Use for URLs that arrive from the browser.
  strict_hosts=False  any PUBLIC host. Use where the URL comes from our own already-authorised launch flow and a
                      host allow-list would risk breaking a legitimate source.

Residual risk (documented, accepted): DNS rebinding between our check and the connection. In strict mode the hosts
are ones an attacker cannot re-point; in public mode the caller already holds a write permission.
"""
import ipaddress
import socket
import time
from typing import Iterator, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

_REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3


class UnsafeFetchError(ValueError):
    """The URL (or a redirect hop) is not allowed, or the response is too large. Messages are safe to show a user."""


# IPv6 ranges that can carry or translate to an arbitrary IPv4 address. `is_global` alone does not cover them all.
_BLOCKED_V6_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "64:ff9b::/96",      # NAT64 well-known prefix
    "64:ff9b:1::/48",    # NAT64 local-use prefix
    "2002::/16",         # 6to4 (embeds an IPv4 address)
    "2001::/32",         # Teredo
    "fec0::/10",         # deprecated site-local
))


def _address_is_blocked(raw_address: str) -> bool:
    ip = ipaddress.ip_address(raw_address.split("%")[0])
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif any(ip in network for network in _BLOCKED_V6_NETWORKS):
            return True
    return (not ip.is_global) or ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved


def _assert_public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeFetchError("The media host could not be resolved") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UnsafeFetchError("The media host could not be resolved")
    if any(_address_is_blocked(address) for address in addresses):
        raise UnsafeFetchError("The media host resolves to a private or reserved address")


def validate_media_url(raw_url: str, *, strict_hosts: bool, allow_http: bool = False) -> str:
    """Return the URL if it is safe to fetch, otherwise raise UnsafeFetchError."""
    parsed = urlparse((raw_url or "").strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.username or parsed.password:
        raise UnsafeFetchError("The media URL is not valid")
    if strict_hosts:
        # Reuse the single source of truth for approved media hosts (lazy import: avoids an import cycle).
        from app.services.ad_remix_service import validate_source_image_url
        try:
            checked = validate_source_image_url(raw_url)
        except ValueError as exc:
            raise UnsafeFetchError(str(exc)) from exc
        _assert_public_host(host)   # the stronger check (CGNAT, NAT64, 6to4...) on top of the approved-host list
        return checked
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if scheme not in allowed_schemes:
        raise UnsafeFetchError("The media URL must use HTTPS" if not allow_http else "The media URL must be http(s)")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeFetchError("The media URL is not valid") from exc
    if port not in (None, 80, 443):
        raise UnsafeFetchError("The media URL must use the standard web port")
    _assert_public_host(host)
    return parsed.geturl()


def _http_get(url: str, **kwargs) -> requests.Response:
    """GET through a session that ignores HTTP(S)_PROXY / .netrc: with a proxy the local DNS check would be meaningless
    (the proxy, not this server, would do the connecting)."""
    session = requests.Session()
    session.trust_env = False
    return session.get(url, **kwargs)


def _peer_is_blocked(response: requests.Response) -> bool:
    """DNS-rebinding backstop: after connecting, make sure we actually reached a public address. Best effort — the
    socket is not always reachable (pooled/closed connections), in which case the pre-connect check stands alone."""
    try:
        peer = response.raw._connection.sock.getpeername()[0]
    except Exception:
        return False
    try:
        return _address_is_blocked(peer)
    except ValueError:
        return False


def open_stream(
    url: str, *, strict_hosts: bool, allow_http: bool = False, timeout=(5, 30), headers: Optional[dict] = None,
) -> requests.Response:
    """GET with manual, re-validated redirects. Returns a streaming 2xx response; the caller must close it."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        current = validate_media_url(current, strict_hosts=strict_hosts, allow_http=allow_http)
        response = _http_get(current, stream=True, allow_redirects=False, timeout=timeout, headers=headers)
        if _peer_is_blocked(response):
            response.close()
            raise UnsafeFetchError("The media host connected to a private or reserved address")
        if response.status_code in _REDIRECT_CODES:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise UnsafeFetchError("The media host sent a redirect with no destination")
            next_url = urljoin(current, location)
            if urlparse(current).scheme.lower() == "https" and urlparse(next_url).scheme.lower() == "http":
                raise UnsafeFetchError("The media host tried to redirect from HTTPS to plain HTTP")
            current = next_url
            continue
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response
    raise UnsafeFetchError("The media URL redirected too many times")


def iter_limited(response: requests.Response, max_bytes: int, *, deadline_seconds: float = 120.0, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield the body in chunks, refusing anything larger than max_bytes or slower than the overall deadline."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise UnsafeFetchError(f"The media file is larger than {max_bytes // (1024 * 1024)} MB")
    started = time.monotonic()
    total = 0
    for chunk in response.iter_content(chunk_size=chunk_size):
        total += len(chunk)
        if total > max_bytes:
            raise UnsafeFetchError(f"The media file is larger than {max_bytes // (1024 * 1024)} MB")
        if time.monotonic() - started > deadline_seconds:
            raise UnsafeFetchError("The media host was too slow to download from")
        yield chunk


def fetch_bytes(
    url: str, *, max_bytes: int, strict_hosts: bool, allow_http: bool = False,
    timeout=(5, 30), deadline_seconds: float = 60.0, headers: Optional[dict] = None, chunk_size: int = 64 * 1024,
) -> Tuple[bytes, str]:
    """Download a small media file fully into memory. Returns (bytes, content-type without parameters)."""
    response = open_stream(url, strict_hosts=strict_hosts, allow_http=allow_http, timeout=timeout, headers=headers)
    try:
        body = b"".join(iter_limited(response, max_bytes, deadline_seconds=deadline_seconds, chunk_size=chunk_size))
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
        return body, content_type
    finally:
        response.close()


# 64 MP covers today's phone photos (48-50 MP are common) while staying far below the sizes where decoding can exhaust the
# single worker's memory (a 100 MP image is ~300-400 MB decoded). Logos pass a much lower limit.
MAX_IMAGE_PIXELS = 64_000_000


def assert_image_dimensions_safe(data: bytes, max_pixels: int = MAX_IMAGE_PIXELS) -> None:
    """Refuse a decompression bomb BEFORE anything decodes it: a ~10 MB PNG can declare 100M+ pixels and expand to
    hundreds of MB of RGBA in memory, which would take down the single worker. Reading the header does not decode."""
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception as exc:
        raise UnsafeFetchError("The file is not a readable image") from exc
    if width * height > max_pixels:
        raise UnsafeFetchError(f"The image is too large ({width}x{height}); the limit is {max_pixels // 1_000_000} megapixels")
