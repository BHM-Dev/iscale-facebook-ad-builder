import socket

import pytest

from app.services import safe_fetch as sf


class _Sock:
    def __init__(self, peer):
        self._peer = peer

    def getpeername(self):
        return (self._peer, 443)


class _Conn:
    def __init__(self, peer):
        self.sock = _Sock(peer)


class _Raw:
    def __init__(self, peer):
        self._connection = _Conn(peer)


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"x" * 10, chunks=None, peer=None):
        self.raw = _Raw(peer) if peer else None
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [body]
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=0):
        yield from self._chunks


def dns(mapping):
    """Fake getaddrinfo: host -> list of IP strings."""
    def fake(host, port, type=0, **kw):
        if host not in mapping:
            raise socket.gaierror("nope")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in mapping[host]]
    return fake


PUBLIC = {"cdn.example.com": ["93.184.216.34"], "scontent.fbcdn.net": ["157.240.1.1"], "l.facebook.com": ["157.240.2.2"]}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns(PUBLIC))


# ---- URL validation, public mode --------------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://127.0.0.1/a.png", "https://[::1]/a.png", "https://10.0.0.5/a.png", "https://192.168.1.10/a.png",
    "https://172.16.0.1/a.png", "https://169.254.169.254/latest/meta-data/", "https://100.64.0.1/a.png",
    "https://0.0.0.0/a.png", "https://[::ffff:127.0.0.1]/a.png",
])
def test_internal_and_special_addresses_are_blocked(monkeypatch, url):
    host = url.split("//")[1].split("/")[0].strip("[]")
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({host: [host]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url(url, strict_hosts=False)


def test_hostname_that_resolves_to_a_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({"evil.example.com": ["93.184.216.34", "10.0.0.7"]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://evil.example.com/a.png", strict_hosts=False)


def test_ipv4_mapped_ipv6_loopback_is_blocked(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({"mapped.example.com": ["::ffff:127.0.0.1"]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://mapped.example.com/a.png", strict_hosts=False)


@pytest.mark.parametrize("url", [
    "ftp://cdn.example.com/a.png", "file:///etc/passwd", "https://user:pw@cdn.example.com/a.png",
    "https://cdn.example.com:8080/a.png", "https://cdn.example.com:22/a.png", "", "not a url", "https:///a.png",
])
def test_bad_scheme_credentials_ports_and_garbage_are_rejected(url):
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url(url, strict_hosts=False, allow_http=True)


def test_http_only_when_allowed_and_public_host_passes():
    assert sf.validate_media_url("https://cdn.example.com/a.png", strict_hosts=False).startswith("https://cdn.example.com")
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("http://cdn.example.com/a.png", strict_hosts=False)
    assert sf.validate_media_url("http://cdn.example.com/a.png", strict_hosts=False, allow_http=True)


# ---- strict host mode -----------------------------------------------------------------------------------------
def test_strict_mode_only_accepts_approved_media_hosts():
    assert sf.validate_media_url("https://scontent.fbcdn.net/v/a.jpg", strict_hosts=True)
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://cdn.example.com/a.png", strict_hosts=True)       # public, but not approved
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("http://scontent.fbcdn.net/v/a.jpg", strict_hosts=True)   # not https
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://evilfbcdn.net/a.jpg", strict_hosts=True)         # suffix trick


# ---- redirects --------------------------------------------------------------------------------------------------
def test_redirect_from_an_approved_host_into_the_internal_network_is_blocked(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({**PUBLIC, "169.254.169.254": ["169.254.169.254"]}))
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        assert kw["allow_redirects"] is False        # never lets requests follow redirects on its own
        return FakeResponse(302, {"Location": "https://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(sf, "_http_get", fake_get)
    with pytest.raises(sf.UnsafeFetchError):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)
    assert calls == ["https://cdn.example.com/a.png"]   # the internal URL was never requested


def test_strict_mode_blocks_a_redirect_to_an_unapproved_host(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(302, {"Location": "https://cdn.example.com/steal.png"}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.fetch_bytes("https://l.facebook.com/l.php?u=x", max_bytes=1000, strict_hosts=True)


def test_redirect_chain_is_limited(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(302, {"Location": "https://cdn.example.com/next.png"}))
    with pytest.raises(sf.UnsafeFetchError, match="too many times"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)


def test_a_good_redirect_is_followed_and_validated(monkeypatch):
    seq = [FakeResponse(301, {"Location": "/final.png"}), FakeResponse(200, {"Content-Type": "image/png; charset=x"}, body=b"PNGDATA")]
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return seq.pop(0)

    monkeypatch.setattr(sf, "_http_get", fake_get)
    body, ctype = sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)
    assert body == b"PNGDATA" and ctype == "image/png" and seen == ["https://cdn.example.com/a.png", "https://cdn.example.com/final.png"]


def test_redirect_without_a_destination_is_rejected(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(302, {}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)


# ---- size and time limits -------------------------------------------------------------------------------------
def test_declared_content_length_over_the_cap_is_refused_without_reading(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(200, {"Content-Length": str(50 * 1024 * 1024)}, chunks=[]))
    with pytest.raises(sf.UnsafeFetchError, match="larger than"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=10 * 1024 * 1024, strict_hosts=False)


def test_body_that_lies_about_its_size_is_cut_off_while_streaming(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(200, {}, chunks=[b"a" * 600, b"b" * 600]))
    with pytest.raises(sf.UnsafeFetchError, match="larger than"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)


def test_slow_download_hits_the_overall_deadline(monkeypatch):
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 0.0 if ticks["n"] <= 2 else 999.0    # never runs out, however many times anything reads the clock

    monkeypatch.setattr(sf.time, "monotonic", clock)
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(200, {}, chunks=[b"a", b"b", b"c"]))
    with pytest.raises(sf.UnsafeFetchError, match="too slow"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False, deadline_seconds=60)


def test_http_error_status_is_raised_and_connection_closed(monkeypatch):
    resp = FakeResponse(404)
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: resp)
    with pytest.raises(RuntimeError):
        sf.open_stream("https://cdn.example.com/a.png", strict_hosts=False)
    assert resp.closed


# ---- 2026-10-25 security-review hardening ------------------------------------------------------------------------
@pytest.mark.parametrize("address", [
    "2002:7f00:0001::1",       # 6to4 embedding 127.0.0.1
    "2002:a9fe:a9fe::1",      # 6to4 embedding 169.254.169.254
    "64:ff9b::7f00:1",        # NAT64 -> 127.0.0.1
    "64:ff9b:1::a00:5",       # NAT64 local-use
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",   # Teredo
    "fec0::1",                # deprecated site-local
    "::ffff:169.254.169.254", # IPv4-mapped metadata address
])
def test_ipv6_forms_that_embed_private_ipv4_are_blocked(monkeypatch, address):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({"x.example.com": [address]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://x.example.com/a.png", strict_hosts=False)


def test_strict_mode_also_applies_the_stronger_address_check(monkeypatch):
    # an approved-looking host that resolves to CGNAT space must be refused even though the host list allows it
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({"scontent.fbcdn.net": ["100.64.0.9"]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url("https://scontent.fbcdn.net/a.jpg", strict_hosts=True)


def test_dns_rebinding_backstop_refuses_a_connection_that_landed_on_a_private_address(monkeypatch):
    # validation saw a public IP, but by connect time the name pointed at the metadata address
    resp = FakeResponse(200, {}, body=b"secret-credentials", peer="169.254.169.254")
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: resp)
    with pytest.raises(sf.UnsafeFetchError, match="private or reserved"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)
    assert resp.closed


def test_a_normal_public_peer_is_fine(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(200, {"Content-Type": "image/png"}, body=b"ok", peer="93.184.216.34"))
    assert sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)[0] == b"ok"


def test_proxy_environment_is_ignored(monkeypatch):
    seen = {}

    class S:
        trust_env = True

        def get(self, url, **kw):
            seen["trust_env"] = self.trust_env
            return FakeResponse(200, {}, body=b"x")

    monkeypatch.setattr(sf.requests, "Session", S)
    sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)
    assert seen["trust_env"] is False


def test_decompression_bomb_is_refused_before_decoding():
    import io
    from PIL import Image
    ok = io.BytesIO(); Image.new("RGB", (100, 100)).save(ok, "PNG")
    sf.assert_image_dimensions_safe(ok.getvalue())                                # normal image passes
    phone = io.BytesIO(); Image.new("1", (8160, 6120)).save(phone, "PNG")         # a 50 MP phone photo must NOT be refused
    sf.assert_image_dimensions_safe(phone.getvalue())
    big = io.BytesIO(); Image.new("1", (9000, 9000)).save(big, "PNG")             # 81 MP, tiny file: the classic bomb shape
    assert len(big.getvalue()) < 200_000
    with pytest.raises(sf.UnsafeFetchError, match="too large"):
        sf.assert_image_dimensions_safe(big.getvalue())
    with pytest.raises(sf.UnsafeFetchError, match="not a readable image"):
        sf.assert_image_dimensions_safe(b"not an image at all")


# ---- cases the review found missing -----------------------------------------------------------------------------------
@pytest.mark.parametrize("host,resolves_to", [
    ("2130706433", "127.0.0.1"),        # decimal form of 127.0.0.1
    ("0x7f.0.0.1", "127.0.0.1"),        # hex
    ("017700000001", "127.0.0.1"),      # octal
    ("127.1", "127.0.0.1"),             # short form
    ("localhost.", "127.0.0.1"),        # trailing dot
])
def test_numeric_and_trailing_dot_host_tricks_end_up_blocked(monkeypatch, host, resolves_to):
    # getaddrinfo (what both the validator and requests rely on) normalises these to the real address, which is blocked
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({host.rstrip("."): [resolves_to]}))
    with pytest.raises(sf.UnsafeFetchError):
        sf.validate_media_url(f"https://{host}/a.png", strict_hosts=False)


def test_port_zero_and_non_numeric_ports_are_rejected():
    for url in ("https://cdn.example.com:0/a.png", "https://cdn.example.com:443abc/a.png"):
        with pytest.raises(sf.UnsafeFetchError):
            sf.validate_media_url(url, strict_hosts=False)


def test_scheme_relative_redirect_to_an_internal_host_is_blocked(monkeypatch):
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({**PUBLIC, "169.254.169.254": ["169.254.169.254"]}))
    calls = []

    def fake(url, **kw):
        calls.append(url)
        return FakeResponse(302, {"Location": "//169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(sf, "_http_get", fake)
    with pytest.raises(sf.UnsafeFetchError):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False)
    assert calls == ["https://cdn.example.com/a.png"]


def test_https_to_http_redirect_is_refused_even_when_http_is_allowed(monkeypatch):
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(302, {"Location": "http://cdn.example.com/a.png"}))
    with pytest.raises(sf.UnsafeFetchError, match="HTTPS to plain HTTP"):
        sf.fetch_bytes("https://cdn.example.com/a.png", max_bytes=1000, strict_hosts=False, allow_http=True)


def test_strict_mode_accepts_the_configured_r2_host_and_an_approved_to_approved_redirect(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "R2_PUBLIC_URL", "https://pub-test123.r2.dev")
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns({**PUBLIC, "pub-test123.r2.dev": ["104.18.1.1"]}))
    assert sf.validate_media_url("https://pub-test123.r2.dev/ref_abc.png", strict_hosts=True)
    seq = [FakeResponse(302, {"Location": "https://scontent.fbcdn.net/final.jpg"}), FakeResponse(200, {"Content-Type": "image/jpeg"}, body=b"JPG", peer="157.240.1.1")]
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: seq.pop(0))
    body, ctype = sf.fetch_bytes("https://pub-test123.r2.dev/x.png", max_bytes=1000, strict_hosts=True)
    assert body == b"JPG" and ctype == "image/jpeg"


def test_upload_video_leaves_no_temp_file_behind_when_the_download_fails(monkeypatch, tmp_path):
    """A failed or oversized download used to leave a partial file (up to the 500 MB cap) on the VPS disk each time."""
    import glob
    import tempfile
    from app.services.facebook_service import FacebookService

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(sf.socket, "getaddrinfo", dns(PUBLIC))
    monkeypatch.setattr(sf, "_http_get", lambda url, **kw: FakeResponse(200, {}, chunks=[b"a" * 600, b"b" * 600]))
    monkeypatch.setattr(sf, "iter_limited", sf.iter_limited)           # real implementation
    import app.services.facebook_service as fs
    real_iter = sf.iter_limited
    monkeypatch.setattr(sf, "iter_limited", lambda resp, max_bytes, **kw: real_iter(resp, 1000, **kw))   # tiny cap -> download aborts mid-way

    svc = FacebookService.__new__(FacebookService)       # no Meta connection needed: the failure happens before any Meta call
    monkeypatch.setattr(FacebookService, "_get_account", lambda self, account_id=None: object())
    with pytest.raises(sf.UnsafeFetchError):
        svc.upload_video("https://cdn.example.com/clip.mp4", wait_for_ready=False)
    assert glob.glob(str(tmp_path / "*")) == [], "a partial video download was left on disk"
