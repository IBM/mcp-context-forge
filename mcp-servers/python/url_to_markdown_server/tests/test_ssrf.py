"""Location: ./mcp-servers/python/url_to_markdown_server/tests/test_ssrf.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for SSRF URL validation.

All resolver-dependent tests patch ``url_to_markdown_server.ssrf._getaddrinfo``
instead of touching real DNS/network, so this suite is safe to run offline
and in CI.
"""

import asyncio
import socket
import time
from typing import Any

import pytest

from url_to_markdown_server.ssrf import SsrfBlockedError, validate_url


def _addrinfo(ip: str, port: int = 443) -> list[tuple[Any, ...]]:
    """Build a fake socket.getaddrinfo()-shaped result for a single IP."""
    is_v6 = ":" in ip
    family = socket.AF_INET6 if is_v6 else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if is_v6 else (ip, port)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


def _mock_resolver(monkeypatch: pytest.MonkeyPatch, ip: str) -> list[tuple[str, int]]:
    """Patch the resolver seam to always resolve to a single fake IP.

    Returns the list of (host, port) calls made, so callers can assert
    whether the resolver was consulted at all.
    """
    calls: list[tuple[str, int]] = []

    def fake_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        calls.append((host, port))
        return _addrinfo(ip, port)

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", fake_getaddrinfo)
    return calls


# ---------------------------------------------------------------------------
# Deny cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_cloud_metadata_literal_ip() -> None:
    """AWS/GCP/Azure metadata endpoint must be blocked without needing DNS."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_deny_loopback_literal_ip() -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://127.0.0.1:8080/")


@pytest.mark.asyncio
async def test_deny_loopback_via_mocked_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostname (not a literal IP) that resolves to loopback must still be blocked."""
    calls = _mock_resolver(monkeypatch, "127.0.0.1")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://localhost/")
    assert calls, "resolver seam should have been consulted for a non-literal hostname"


@pytest.mark.asyncio
@pytest.mark.parametrize("ip", ["10.0.0.1", "172.16.0.1", "192.168.1.1"])
async def test_deny_rfc1918(ip: str) -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url(f"http://{ip}/")


@pytest.mark.asyncio
async def test_deny_cgnat_not_caught_by_is_private() -> None:
    """100.64.0.0/10 (CGNAT) is not covered by ipaddress.is_private; must be explicitly blocked."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://100.64.0.1/")


@pytest.mark.asyncio
async def test_deny_ipv6_loopback_literal() -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[::1]/")


@pytest.mark.asyncio
async def test_deny_ipv6_site_local() -> None:
    """fec0::/10 (deprecated IPv6 site-local) must be blocked unconditionally.

    Python's ipaddress reports fec0::1 as is_private=False, is_reserved=False,
    is_global=True - it falls through every other category untouched unless
    is_site_local is checked explicitly.
    """
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[fec0::1]/")


@pytest.mark.asyncio
async def test_deny_sixtofour_embedded_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 6to4 literal embedding 127.0.0.1 must be blocked even with the private escape hatch on.

    Python's ipaddress reports the entire 2002::/16 block as is_private=True
    regardless of the embedded address, so without unwrapping sixtofour,
    MARKDOWN_ALLOW_PRIVATE_NETWORKS would wrongly also unblock an embedded
    loopback destination, which should only ever be gated by
    MARKDOWN_ALLOW_LOCALHOST.
    """
    monkeypatch.setenv("MARKDOWN_ALLOW_PRIVATE_NETWORKS", "true")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[2002:7f00:1::]/")


@pytest.mark.asyncio
async def test_deny_sixtofour_embedded_link_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 6to4 literal embedding the cloud metadata address (169.254.169.254) must always be blocked.

    Same misclassification as the loopback case above, but for a category
    (link-local) that has no escape hatch at all.
    """
    monkeypatch.setenv("MARKDOWN_ALLOW_PRIVATE_NETWORKS", "true")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[2002:a9fe:a9fe::]/")


@pytest.mark.asyncio
async def test_allow_sixtofour_embedded_private_under_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 6to4 literal embedding an RFC1918 address is gated like its IPv4 form's escape hatch."""
    monkeypatch.setenv("MARKDOWN_ALLOW_PRIVATE_NETWORKS", "true")
    result = await validate_url("http://[2002:c0a8:0101::]/")
    assert result.resolved_ip == "2002:c0a8:101::"


@pytest.mark.asyncio
async def test_deny_sixtofour_embedded_private_without_escape_hatch() -> None:
    """Same 6to4-embedded-private address, but without the escape hatch: must stay blocked."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[2002:c0a8:0101::]/")


@pytest.mark.asyncio
async def test_deny_ipv4_mapped_ipv6_loopback() -> None:
    """::ffff:127.0.0.1 must be recognized as loopback despite the IPv6 wrapper."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[::ffff:127.0.0.1]/")


@pytest.mark.asyncio
async def test_deny_unspecified() -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://0.0.0.0/")


@pytest.mark.asyncio
async def test_deny_multicast() -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://224.0.0.1/")


@pytest.mark.asyncio
async def test_deny_userinfo_bypass_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://trusted.com@127.0.0.1/ must be blocked at the credentials check,

    before any resolution is attempted - the resolver mock must never be
    called for this case.
    """
    calls = _mock_resolver(monkeypatch, "93.184.216.34")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://trusted.com@127.0.0.1/")
    assert calls == [], "resolver must not be consulted when credentials are present"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://127.0.0.1/", "gopher://127.0.0.1/"],
)
async def test_deny_disallowed_scheme(url: str) -> None:
    with pytest.raises(SsrfBlockedError):
        await validate_url(url)


@pytest.mark.asyncio
async def test_deny_dns_resolved_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostname whose mocked DNS resolution returns a private IP must be blocked.

    Proves resolved addresses are checked, not just literal-IP inputs.
    """
    _mock_resolver(monkeypatch, "10.1.2.3")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://internal.example.test/")


@pytest.mark.asyncio
async def test_deny_allowlist_blocks_non_allowed_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public IP is still blocked if the hostname is not on a configured allowlist."""
    monkeypatch.setenv("MARKDOWN_ALLOWED_HOSTS", "trusted.example.com")
    _mock_resolver(monkeypatch, "93.184.216.34")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://evil.com/")


@pytest.mark.asyncio
async def test_deny_allowlist_trailing_dot_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trailing-dot FQDN normalization happens before the allowlist check, not after."""
    monkeypatch.setenv("MARKDOWN_ALLOWED_HOSTS", "trusted.com")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://evil.com./")


@pytest.mark.asyncio
async def test_deny_any_blocked_candidate_blocks_whole_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a hostname resolves to multiple IPs and any one is blocked, the whole URL is blocked."""

    def fake_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        return _addrinfo("93.184.216.34", port) + _addrinfo("127.0.0.1", port)

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://multi.example.test/")


@pytest.mark.asyncio
async def test_invalid_cidr_in_blocked_networks_is_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A single malformed CIDR entry must not fail-closed every request.

    A typo in an operator-configured MARKDOWN_BLOCKED_NETWORKS entry must be
    logged (so the misconfiguration is diagnosable) and skipped - not allowed
    to poison validation for every other, well-formed entry and every other
    request. The core categorical blocks (private/loopback/etc.) are
    unaffected either way since they don't depend on this list.
    """
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "not-a-cidr,203.0.113.0/24")
    _mock_resolver(monkeypatch, "8.8.8.8")

    with caplog.at_level("WARNING", logger="url_to_markdown_server.ssrf"):
        result = await validate_url("http://example.com/")

    assert result.resolved_ip == "8.8.8.8"
    assert "not-a-cidr" in caplog.text


@pytest.mark.asyncio
async def test_deny_blocked_networks_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "93.184.216.0/24")
    _mock_resolver(monkeypatch, "93.184.216.34")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://example.com/")


@pytest.mark.asyncio
async def test_deny_dns_resolution_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolver that never returns must not be allowed to run past the caller's timeout.

    Pre-fix, DNS resolution had no deadline of its own - only the later
    session.stream() call was bounded - so a slow/unresponsive resolver could
    silently exceed the caller-advertised request timeout. Uses a real
    blocking sleep (not asyncio.sleep) in the resolver seam because the
    dedicated DNS thread pool runs it via a real OS thread, exactly like the
    real socket.getaddrinfo() call it stands in for.
    """

    def slow_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        time.sleep(2)
        return _addrinfo("93.184.216.34", port)

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", slow_getaddrinfo)

    start = asyncio.get_running_loop().time()
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://slow.example.test/", timeout=0.2)
    elapsed = asyncio.get_running_loop().time() - start

    assert elapsed < 1.0, "validate_url() must not wait past the given timeout for a slow resolver"


@pytest.mark.asyncio
async def test_dns_resolver_admission_rejects_when_saturated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup must fail closed, not queue indefinitely, once resolver admission is saturated.

    ThreadPoolExecutor's own work queue is unbounded, so without a bounded admission
    control a burst of slow-resolving hostnames would queue behind the fixed pool of
    worker threads instead of being rejected. Shrinks the admission semaphore to a
    single permit (independent of the real thread pool, which stays at its full
    configured size) and holds that permit with a real blocking sleep in the resolver
    seam, standing in for a stuck getaddrinfo() call. A second, concurrent lookup must
    fail within its own timeout instead of waiting for the first to finish.
    """
    import url_to_markdown_server.ssrf as ssrf_module

    monkeypatch.setattr(ssrf_module, "_dns_admission", asyncio.Semaphore(1))

    calls = {"n": 0}

    def dispatch(host: str, port: int) -> list[tuple[Any, ...]]:
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.5)
        return _addrinfo("93.184.216.34", port)

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", dispatch)

    first = asyncio.ensure_future(validate_url("http://first.example.test/", timeout=2))
    await asyncio.sleep(0.1)  # let the first lookup actually start and take the only permit

    start = asyncio.get_running_loop().time()
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://second.example.test/", timeout=0.2)
    elapsed = asyncio.get_running_loop().time() - start
    assert (
        elapsed < 0.4
    ), "a saturated resolver must fail within the caller's own timeout, not queue"

    # The first lookup must still complete successfully once its slow call returns,
    # proving the permit was genuinely held by real work rather than leaked.
    target = await first
    assert target.resolved_ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_dns_resolver_admission_held_until_real_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission permit must stay held until the resolver call actually returns.

    A caller that times out on validate_url() cannot stop the underlying
    getaddrinfo() call already running in the resolver thread pool. If the permit
    were released on that caller's timeout instead of on the real thread's
    completion, a second lookup could be admitted while the first's thread is still
    running, letting the configured bound be exceeded by however many callers keep
    timing out on the same stuck lookup.
    """
    import url_to_markdown_server.ssrf as ssrf_module

    monkeypatch.setattr(ssrf_module, "_dns_admission", asyncio.Semaphore(1))

    def slow_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        time.sleep(0.4)
        return _addrinfo("93.184.216.34", port)

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", slow_getaddrinfo)

    # This call's own wait_for gives up well before the resolver thread finishes.
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://first.example.test/", timeout=0.05)

    # Immediately afterwards, the permit must still be held by the still-running
    # resolver thread - a second lookup must fail closed too, not be admitted.
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://second.example.test/", timeout=0.05)

    # Once the slow thread genuinely finishes, the permit is released and a
    # subsequent lookup succeeds normally.
    await asyncio.sleep(0.5)
    target = await validate_url("http://third.example.test/", timeout=1)
    assert target.resolved_ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_dns_admission_release_swallows_closed_loop_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admission-release callback must not propagate a closed-loop RuntimeError.

    call_soon_threadsafe() raises RuntimeError once its target loop is closed. The
    resolver's worker thread can still fire its done-callback after that point (e.g.
    during interpreter/process shutdown), and there is nothing meaningful left to
    release the permit into at that point, so the callback must swallow it rather
    than crash the worker thread.
    """
    import url_to_markdown_server.ssrf as ssrf_module

    monkeypatch.setattr(
        "url_to_markdown_server.ssrf._getaddrinfo",
        lambda host, port: _addrinfo("93.184.216.34", port),
    )

    loop = asyncio.get_running_loop()
    real_call_soon_threadsafe = loop.call_soon_threadsafe

    def raising_call_soon_threadsafe(callback, *args, **kwargs):
        if (
            getattr(callback, "__self__", None) is ssrf_module._dns_admission
            and getattr(callback, "__func__", None) is asyncio.Semaphore.release
        ):
            raise RuntimeError("event loop is closed")
        return real_call_soon_threadsafe(callback, *args, **kwargs)

    monkeypatch.setattr(loop, "call_soon_threadsafe", raising_call_soon_threadsafe)

    target = await validate_url("http://release-swallow.example.test/")
    assert target.resolved_ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_deny_dns_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://nonexistent.example.test/")


@pytest.mark.asyncio
async def test_malformed_url_raises_ssrf_blocked_error() -> None:
    """Parse failures must surface as SsrfBlockedError, never as raw ValueError/etc."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://")


@pytest.mark.asyncio
async def test_deny_hostname_that_normalizes_to_empty() -> None:
    """A hostname consisting only of dots normalizes to empty and must be blocked."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://.../")


@pytest.mark.asyncio
async def test_deny_invalid_port_raises_ssrf_blocked_error() -> None:
    """An out-of-range port raises ValueError from urllib; it must surface as SsrfBlockedError."""
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://example.com:99999/")


@pytest.mark.asyncio
async def test_deny_empty_resolver_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolver that returns no candidates at all must be treated as blocked, not as success."""

    def fake_getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
        return []

    monkeypatch.setattr("url_to_markdown_server.ssrf._getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://empty-result.example.test/")


@pytest.mark.asyncio
async def test_deny_blocked_networks_env_var_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    """MARKDOWN_BLOCKED_NETWORKS must also match IPv6 CIDRs, not just IPv4.

    Uses a globally-routable IPv6 address (not private/reserved/etc.) so the
    match is proven via the blocked-networks check itself, not an earlier
    category check.
    """
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "2606:4700:4700::/48")
    _mock_resolver(monkeypatch, "2606:4700:4700::1111")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://v6-example.test/")


@pytest.mark.asyncio
async def test_blocked_networks_ipv6_cidr_matches_sixtofour_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-configured IPv6 CIDR must match a 6to4 literal inside it.

    _unwrap_embedded_ipv4() rewrites 2002:0808:0808:: to the public address
    8.8.8.8, which clears every category check on its own - so if the
    blocked-networks lookup only ever saw the unwrapped form, an IPv6 CIDR
    could never match it (family mismatch) and the address would be allowed
    regardless of the operator's configuration, and regardless of the escape
    hatches.
    """
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "2002::/16")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[2002:0808:0808::]/")


@pytest.mark.asyncio
async def test_blocked_networks_ipv6_cidr_matches_ipv4_mapped_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same bypass shape as the 6to4 case, via an IPv4-mapped literal."""
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "::ffff:0:0/96")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[::ffff:8.8.8.8]/")


@pytest.mark.asyncio
async def test_blocked_networks_ipv4_cidr_matches_sixtofour_embedded_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-configured IPv4 CIDR must still match a 6to4-wrapped target inside it.

    The mirror of the two tests above: the blocked-networks lookup has to see
    the unwrapped form too, or wrapping a blocked IPv4 destination in a 6to4
    literal would evade the operator's own deny list. The private escape hatch
    is on so the block is proven by the CIDR match rather than by 2002::/16
    being reported as private.
    """
    monkeypatch.setenv("MARKDOWN_ALLOW_PRIVATE_NETWORKS", "true")
    monkeypatch.setenv("MARKDOWN_BLOCKED_NETWORKS", "10.0.0.0/8")
    with pytest.raises(SsrfBlockedError):
        await validate_url("http://[2002:0a00:0001::]/")


@pytest.mark.asyncio
async def test_error_message_is_generic_and_fixed() -> None:
    """The exception message must never leak which check tripped."""
    with pytest.raises(SsrfBlockedError) as exc_info:
        await validate_url("http://127.0.0.1/")
    assert str(exc_info.value) == "URL is not allowed"


# ---------------------------------------------------------------------------
# Allow cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allow_public_ip_via_mocked_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, "93.184.216.34")

    result = await validate_url("http://example.com/")

    assert result.resolved_ip == "93.184.216.34"
    assert result.hostname == "example.com"
    assert result.port == 80
    assert "93.184.216.34" in result.pinned_url
    assert result.host_header == "example.com"  # default port omitted


@pytest.mark.asyncio
async def test_allow_exact_match_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKDOWN_ALLOWED_HOSTS", "example.com,other.example.org")
    _mock_resolver(monkeypatch, "93.184.216.34")

    result = await validate_url("http://example.com/")

    assert result.hostname == "example.com"
    assert result.resolved_ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_allow_wildcard_allowlist_matches_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKDOWN_ALLOWED_HOSTS", "*.example.com")
    _mock_resolver(monkeypatch, "93.184.216.34")

    result = await validate_url("http://api.example.com/")

    assert result.hostname == "api.example.com"
    assert result.resolved_ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_deny_wildcard_allowlist_does_not_match_apex(monkeypatch: pytest.MonkeyPatch) -> None:
    """*.example.com must not match the bare apex domain example.com."""
    monkeypatch.setenv("MARKDOWN_ALLOWED_HOSTS", "*.example.com")
    _mock_resolver(monkeypatch, "93.184.216.34")

    with pytest.raises(SsrfBlockedError):
        await validate_url("http://example.com/")


@pytest.mark.asyncio
async def test_allow_private_networks_escape_hatch_leaves_loopback_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MARKDOWN_ALLOW_PRIVATE_NETWORKS unblocks private-but-not-loopback only.

    The two escape hatches must not cross-loosen each other:
    MARKDOWN_ALLOW_LOCALHOST stays at its default (false), so loopback is
    still blocked for the same run.
    """
    monkeypatch.setenv("MARKDOWN_ALLOW_PRIVATE_NETWORKS", "true")

    result = await validate_url("http://10.1.2.3/")
    assert result.resolved_ip == "10.1.2.3"

    with pytest.raises(SsrfBlockedError):
        await validate_url("http://127.0.0.1/")


@pytest.mark.asyncio
async def test_allow_localhost_escape_hatch_covers_ipv6_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MARKDOWN_ALLOW_LOCALHOST=true must also unblock IPv6 loopback ([::1]).

    Python's IPv6Address('::1').is_reserved is also True (::1 falls inside
    the ::/8 reserved block), so the loopback check must take precedence
    over the reserved check - otherwise this escape hatch is a no-op for
    IPv6 even though it works for IPv4's 127.0.0.1.
    """
    monkeypatch.setenv("MARKDOWN_ALLOW_LOCALHOST", "true")

    result = await validate_url("http://[::1]/")

    assert result.resolved_ip == "::1"


@pytest.mark.asyncio
async def test_allow_explicit_non_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, "93.184.216.34")

    result = await validate_url("https://example.com:8443/")

    assert result.port == 8443
    assert result.host_header == "example.com:8443"
    assert ":8443" in result.pinned_url


@pytest.mark.asyncio
async def test_allow_ssrf_protection_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """MARKDOWN_SSRF_PROTECTION_ENABLED=false skips the private/loopback/etc. checks."""
    monkeypatch.setenv("MARKDOWN_SSRF_PROTECTION_ENABLED", "false")

    result = await validate_url("http://127.0.0.1/")

    assert result.resolved_ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_allow_idn_hostname_normalizes_to_punycode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Unicode (IDN) hostname must be IDNA-encoded to punycode before use.

    Pre-fix, httpx auto-punycoded the hostname when making the actual
    request; post-fix, validate_url() hands the hostname straight to a Host
    header, so a raw Unicode hostname must be normalized here or httpx's
    header encoder raises a raw UnicodeEncodeError instead of a clean,
    generic SsrfBlockedError.
    """
    calls = _mock_resolver(monkeypatch, "93.184.216.34")

    result = await validate_url("http://例え.jp/")

    assert result.hostname == "xn--r8jz45g.jp"
    assert calls == [("xn--r8jz45g.jp", 80)], "resolver must see the punycode form, not Unicode"


@pytest.mark.asyncio
async def test_deny_malformed_idn_hostname() -> None:
    """A hostname label that fails IDNA encoding must raise SsrfBlockedError, not UnicodeError."""
    with pytest.raises(SsrfBlockedError):
        await validate_url(f"http://{'a' * 300}.example.com/")


@pytest.mark.asyncio
async def test_allow_literal_ip_skips_idna_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A literal IP address must never be passed through the IDNA codec."""
    result = await validate_url("http://93.184.216.34/")
    assert result.hostname == "93.184.216.34"


@pytest.mark.asyncio
async def test_deny_ssrf_protection_unrecognized_value_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognized MARKDOWN_SSRF_PROTECTION_ENABLED value must not silently disable protection.

    Only an explicit, recognized falsey value (0/false/no/off) may disable
    the per-IP SSRF checks - this flag defaults to "on", so a typo or
    unrecognized value must fail closed (protection stays enabled).
    """
    monkeypatch.setenv("MARKDOWN_SSRF_PROTECTION_ENABLED", "garbage")

    with pytest.raises(SsrfBlockedError):
        await validate_url("http://10.1.2.3/")
