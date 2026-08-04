"""Location: ./mcp-servers/python/url_to_markdown_server/src/url_to_markdown_server/ssrf.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

SSRF validation for outbound URL fetches.

Validates a caller-supplied URL against a scheme allowlist, an optional
hostname allowlist, and per-resolved-IP deny rules (loopback, RFC1918,
link-local, CGNAT, multicast, reserved, unspecified, plus operator-configured
CIDRs) before any network fetch is attempted. On success the result is
"pinned" to a single resolved IP address so the caller can connect directly
to that address rather than re-resolving the hostname later, which would
reopen a DNS-rebinding window between validation and fetch.

Framework-independent (stdlib only: ipaddress, socket, asyncio, urllib.parse,
dataclasses) so it can be exercised in unit tests without real DNS or network
access. DNS resolution goes through the module-level ``_getaddrinfo`` seam,
which tests monkeypatch to inject fake results.
"""

import asyncio
import ipaddress
import logging
import os
import socket
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

# Server-side diagnostic log only. Category reasons logged here (e.g. "scheme
# not allowed", "hostname not in allowlist") are for operators debugging a
# misconfiguration or investigating a block - they are never included in the
# exception raised to the caller (see _BLOCKED_MESSAGE below).
logger = logging.getLogger(__name__)

# Generic, fixed caller-facing message. Never interpolate the URL or the
# specific check that tripped into this string - that would help an
# attacker map internal network topology through error text.
_BLOCKED_MESSAGE = "URL is not allowed"

_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}
_ALLOWED_SCHEMES = frozenset(_DEFAULT_PORTS)

# RFC 6598 carrier-grade NAT range - not covered by ipaddress.is_private.
_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# DNS resolution runs in its own small, bounded thread pool rather than
# asyncio's shared default executor. A blocking getaddrinfo() call cannot be
# cancelled once submitted (asyncio.wait_for() only stops *waiting* for it;
# the underlying resolver thread keeps running until the OS call itself
# returns or errors), so a slow/unresponsive DNS server would otherwise let
# stuck lookups accumulate in - and eventually exhaust - the same executor
# every other asyncio.to_thread() call in the process depends on. Confining
# resolution to a dedicated pool caps the damage to this many stuck threads,
# never more.
_DNS_RESOLVER_THREADS = int(os.getenv("MARKDOWN_DNS_RESOLVER_THREADS", "16"))
_DNS_TIMEOUT = float(os.getenv("MARKDOWN_DNS_TIMEOUT", "10"))
_dns_executor = ThreadPoolExecutor(
    max_workers=_DNS_RESOLVER_THREADS, thread_name_prefix="ssrf-dns-resolver"
)

# ThreadPoolExecutor's own work queue is unbounded: submitting more lookups
# than there are worker threads just queues the excess rather than rejecting
# them, so a burst of slow-resolving hostnames could grow that queue without
# limit even though only _DNS_RESOLVER_THREADS run at a time. This semaphore
# caps how many lookups may be admitted (queued or running) at once, sized to
# match the pool so nothing queues behind it - a lookup that can't get a
# permit within its caller's timeout fails closed instead. See
# _resolve_candidates() for why the permit is released on the raw resolver
# future's own completion rather than on the caller's timeout.
_dns_admission = asyncio.Semaphore(_DNS_RESOLVER_THREADS)


class SsrfBlockedError(ValueError):
    """Raised when a URL fails SSRF validation.

    ``str(e)`` is always the generic caller-facing message "URL is not
    allowed" - the specific check that tripped is intentionally never
    included, so callers cannot leak internal network topology through
    error text.
    """

    def __init__(self) -> None:
        """Initialize with the fixed, generic caller-facing message."""
        super().__init__(_BLOCKED_MESSAGE)


@dataclass(frozen=True)
class ValidatedTarget:
    """Result of a successful SSRF validation, ready for a pinned fetch."""

    validated_url: str
    hostname: str
    port: int
    resolved_ip: str
    pinned_url: str
    host_header: str


def _getaddrinfo(host: str, port: int) -> list[tuple[Any, ...]]:
    """Resolve host/port via the stdlib resolver (blocking call).

    Isolated as a module-level seam so tests can monkeypatch
    ``url_to_markdown_server.ssrf._getaddrinfo`` to inject fake resolution
    results instead of hitting real DNS.
    """
    return socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)


def _env_bool(name: str, default: bool) -> bool:
    """Parse an opt-in boolean environment variable, defaulting when unset/empty.

    Only a recognized truthy value enables the feature; unset, empty, or any
    unrecognized value falls back to ``default``. This is the right shape for
    flags that default to *off* (the two SSRF escape hatches): failing to
    recognize garbage input as "on" is harmless there.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_enabled_by_default(name: str) -> bool:
    """Parse a boolean environment variable that defaults to True (secure-by-default).

    Only an explicit, recognized falsey value disables the feature; unset,
    empty, or any unrecognized value leaves it enabled. This is the right
    shape for flags that default to *on* (SSRF protection itself): a typo or
    unrecognized value must never silently disable protection.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_csv(name: str) -> list[str]:
    """Parse a comma-separated environment variable into stripped, non-empty items."""
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_networks(name: str) -> list[_IPNetwork]:
    """Parse a comma-separated list of CIDR networks from an environment variable.

    A malformed entry is logged and skipped rather than raising and letting the
    (broad, generic) outer exception handler turn one operator typo into a
    fail-closed block of every single request with no diagnostic signal. This
    is deliberately *not* fail-closed-on-bad-config: the other blocked
    categories (private/loopback/link-local/CGNAT/reserved/etc.) are enforced
    unconditionally regardless of this list, so skipping one bad entry here
    only narrows the operator-configured supplemental deny list, never the
    core SSRF protections.
    """
    networks: list[_IPNetwork] = []
    for item in _env_csv(name):
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning(f"Ignoring invalid CIDR in {name}: {item!r}")
    return networks


def _hostname_allowed(hostname: str, allowed_hosts: list[str]) -> bool:
    """Check a normalized hostname against an optional allowlist.

    An empty allowlist means "no restriction". A non-empty allowlist entry
    either matches the hostname exactly, or - if it is of the form
    "*.example.com" - matches any strict subdomain of example.com. The
    wildcard form deliberately does not match the bare apex domain.
    """
    if not allowed_hosts:
        return True
    for entry in allowed_hosts:
        normalized = entry.strip().lower().rstrip(".")
        if normalized.startswith("*."):
            suffix = normalized[1:]  # ".example.com"
            if hostname.endswith(suffix):
                return True
        elif hostname == normalized:
            return True
    return False


def _normalize_hostname(hostname: str) -> str:
    """IDNA-encode a non-literal-IP hostname to its ASCII/punycode form.

    Pre-fix, httpx auto-punycoded Unicode hostnames when making the actual
    request; the pinned-fetch path here hands the hostname straight to a
    ``Host`` header instead, and httpx's header encoder raises a raw
    ``UnicodeEncodeError`` for non-ASCII hostnames rather than encoding them.
    Normalizing here - before the allowlist check - ensures caller-supplied
    hostnames and ``MARKDOWN_ALLOWED_HOSTS`` entries are compared in the same
    (punycode) form, and that only ASCII ever reaches the ``Host`` header.

    IP literals must never be passed through the IDNA codec (it is only
    meaningful for domain names, not addresses), so those are returned
    unchanged. A malformed IDN label raises ``UnicodeError`` from the codec;
    the caller is responsible for converting that into ``SsrfBlockedError``.
    """
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return hostname

    return hostname.encode("idna").decode("ascii")


def _unwrap_embedded_ipv4(ip: _IPAddress) -> _IPAddress:
    """Unwrap an IPv6 address that embeds an IPv4 destination to that IPv4 address.

    Covers IPv4-mapped (``::ffff:a.b.c.d``) and 6to4 (``2002:aabb:ccdd::/48``)
    addresses. Both wrap an IPv4 destination inside an IPv6 literal, and
    Python's ``ipaddress`` module does not classify either form using the
    embedded address's own category: ``is_private`` reports True for the
    *entire* ``2002::/16`` block regardless of what is embedded, so without
    unwrapping, a 6to4 literal embedding a loopback address (``2002:7f00:1::``
    -> ``127.0.0.1``) or a link-local/metadata address
    (``2002:a9fe:a9fe::`` -> ``169.254.169.254``) would be misclassified as
    merely "private" - letting it slip through under
    ``MARKDOWN_ALLOW_PRIVATE_NETWORKS`` even though the real target should
    stay blocked unconditionally, or be gated by ``MARKDOWN_ALLOW_LOCALHOST``
    instead. Unwrapping first lets every category check run against the
    embedded IPv4 address's own, correct classification.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def _in_blocked_networks(ip: _IPAddress, blocked_networks: list[_IPNetwork]) -> bool:
    """Return True if ``ip`` falls inside any operator-configured blocked CIDR.

    Address and network families must match before ``in`` is evaluated -
    Python raises ``TypeError`` when mixing an IPv4 address with an IPv6
    network and vice versa.
    """
    for network in blocked_networks:
        if isinstance(ip, ipaddress.IPv4Address) and isinstance(network, ipaddress.IPv4Network):
            if ip in network:
                return True
        elif isinstance(ip, ipaddress.IPv6Address) and isinstance(network, ipaddress.IPv6Network):
            if ip in network:
                return True
    return False


def _is_blocked_ip(
    ip: _IPAddress,
    *,
    allow_localhost: bool,
    allow_private_networks: bool,
    blocked_networks: list[_IPNetwork],
) -> bool:
    """Return True if ``ip`` must be blocked under the SSRF policy.

    Category precedence matters, and is deliberately not a simple "OR of all
    categories": ``is_loopback`` is checked *first* and independently,
    because Python's IPv6 ``is_reserved`` also reports True for ``::1``
    (loopback falls inside the ``::/8`` reserved block) - checking
    ``is_reserved`` first would make ``MARKDOWN_ALLOW_LOCALHOST`` a no-op for
    IPv6 loopback. Link-local/unspecified/multicast/reserved/site-local
    (excluding loopback, already handled) are then always blocked with no
    escape hatch - they also overlap with ``is_private`` in Python's
    ipaddress module, so they are checked before it. ``is_site_local``
    (deprecated ``fec0::/10``) is IPv6-only and Python does not fold it into
    ``is_private``/``is_reserved`` at all, so it needs an explicit check
    (``getattr`` because ``IPv4Address`` has no such attribute) - without it,
    ``fec0::1`` falls through every category untouched
    (``is_private=False``, ``is_reserved=False``, ``is_global=True``) and
    would otherwise be treated as an ordinary public address. "Private but
    not loopback" is gated by its own, independent escape hatch. CGNAT and
    operator-configured blocked networks are always blocked regardless of
    either escape hatch.

    ``MARKDOWN_BLOCKED_NETWORKS`` is matched against *both* the address as the
    caller wrote it and its unwrapped form, while the category checks below
    run only on the unwrapped form. Matching both is required because
    unwrapping changes the address family: an operator-configured IPv6 CIDR
    (say ``2002::/16`` or ``::ffff:0:0/96``) can only ever match the original
    literal, and an operator-configured IPv4 CIDR (say ``10.0.0.0/8``) can
    only ever match the unwrapped address of a 6to4/IPv4-mapped literal
    wrapping that range. Checking one form alone leaves the other as a bypass.
    """
    effective = _unwrap_embedded_ipv4(ip)

    if _in_blocked_networks(ip, blocked_networks) or _in_blocked_networks(
        effective, blocked_networks
    ):
        return True

    if effective.is_loopback:
        if not allow_localhost:
            return True
    elif (
        effective.is_link_local
        or effective.is_unspecified
        or effective.is_multicast
        or effective.is_reserved
        or getattr(effective, "is_site_local", False)
    ):
        return True
    elif effective.is_private:
        if not allow_private_networks:
            return True

    if isinstance(effective, ipaddress.IPv4Address) and effective in _CGNAT_NETWORK:
        return True

    return False


async def _resolve_candidates(hostname: str, port: int, timeout: float) -> list[_IPAddress]:
    """Resolve hostname to its IP candidate(s), bounded by ``timeout``.

    If ``hostname`` is itself a literal IP address, it is returned as the
    sole candidate without consulting the resolver. Otherwise resolution is
    delegated to ``_getaddrinfo`` on the dedicated DNS thread pool, with a
    hard deadline: pre-fix, DNS resolution happened inside httpx's own
    connect timeout, so a hung resolver could never silently outlive the
    caller-advertised request timeout the way an unbounded
    ``asyncio.to_thread()`` call could. Timing out here still leaves the
    submitted lookup running in the (bounded) resolver pool rather than the
    shared default executor - see the pool's construction above for why that
    isolation matters.

    Admission to that pool is itself bounded by ``_dns_admission``: a lookup
    that cannot get a permit within ``timeout`` fails closed rather than
    queueing behind the fixed worker threads. The permit is taken on the raw
    ``concurrent.futures.Future`` from ``_dns_executor.submit()``, not on the
    ``asyncio.wait_for()``-wrapped one below, and released only when that raw
    future actually completes: giving up on the wrapped future (our own
    timeout) does not stop the OS-level call already running in its thread,
    so releasing on that timeout instead would let the bound be exceeded by
    however many callers keep timing out on the same stuck lookup.
    """
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        return [literal]

    try:
        await asyncio.wait_for(_dns_admission.acquire(), timeout=timeout)
    except TimeoutError as exc:
        logger.warning(f"Blocked URL ({hostname!r}): DNS resolver saturated")
        raise SsrfBlockedError() from exc

    loop = asyncio.get_running_loop()
    raw_future = _dns_executor.submit(_getaddrinfo, hostname, port)

    def _release_admission(_future: "Future[list[tuple[Any, ...]]]") -> None:
        # Runs on the resolver worker thread when the OS-level call actually
        # returns, however long after the caller (below) gave up waiting for
        # it. The loop may already be closed by then (e.g. process shutdown);
        # there is nothing meaningful left to release the permit into, so that
        # is not an error.
        try:
            loop.call_soon_threadsafe(_dns_admission.release)
        except RuntimeError:
            pass

    raw_future.add_done_callback(_release_admission)

    try:
        results = await asyncio.wait_for(asyncio.wrap_future(raw_future), timeout=timeout)
    except socket.gaierror as exc:
        logger.warning(f"Blocked URL ({hostname!r}): DNS resolution failed")
        raise SsrfBlockedError() from exc
    except TimeoutError as exc:
        logger.warning(f"Blocked URL ({hostname!r}): DNS resolution timed out")
        raise SsrfBlockedError() from exc

    candidates: list[_IPAddress] = []
    for entry in results:
        sockaddr = entry[4]
        address = str(sockaddr[0]).split("%", 1)[0]
        candidates.append(ipaddress.ip_address(address))

    if not candidates:
        logger.warning(f"Blocked URL ({hostname!r}): DNS resolution returned no addresses")
        raise SsrfBlockedError()

    return candidates


def _format_host(host: str, is_ipv6: bool) -> str:
    """Bracket an IPv6 literal for use in a netloc; leave other hosts as-is."""
    return f"[{host}]" if is_ipv6 else host


def _build_result(
    *,
    scheme: str,
    hostname: str,
    port: int,
    default_port: int,
    parsed: SplitResult,
    resolved_ip: _IPAddress,
) -> ValidatedTarget:
    """Assemble the ValidatedTarget from validated, normalized components."""
    host_part = _format_host(hostname, ":" in hostname)
    netloc = host_part if port == default_port else f"{host_part}:{port}"
    validated_url = urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))

    resolved_ip_str = str(resolved_ip)
    pinned_host_part = _format_host(resolved_ip_str, resolved_ip.version == 6)
    pinned_netloc = pinned_host_part if port == default_port else f"{pinned_host_part}:{port}"
    pinned_url = urlunsplit((scheme, pinned_netloc, parsed.path, parsed.query, ""))

    host_header = host_part if port == default_port else f"{host_part}:{port}"

    return ValidatedTarget(
        validated_url=validated_url,
        hostname=hostname,
        port=port,
        resolved_ip=resolved_ip_str,
        pinned_url=pinned_url,
        host_header=host_header,
    )


async def _validate_url(url: str, timeout: float) -> ValidatedTarget:
    """Perform the actual validation steps; may raise SsrfBlockedError or bubble parse errors."""
    parsed = urlsplit(url)

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        logger.warning(f"Blocked URL: scheme not allowed ({scheme!r})")
        raise SsrfBlockedError()

    # Reject embedded credentials explicitly - do not rely on .hostname
    # alone being "safe" (e.g. http://trusted.com@127.0.0.1/).
    if parsed.username is not None or parsed.password is not None:
        logger.warning("Blocked URL: credentials in URL")
        raise SsrfBlockedError()

    raw_hostname = parsed.hostname
    if not raw_hostname:
        logger.warning("Blocked URL: missing hostname")
        raise SsrfBlockedError()

    hostname = raw_hostname.lower().rstrip(".")
    if not hostname:
        logger.warning("Blocked URL: hostname empty after normalization")
        raise SsrfBlockedError()

    try:
        hostname = _normalize_hostname(hostname)
    except UnicodeError as exc:
        logger.warning(f"Blocked URL: malformed IDN hostname ({hostname!r})")
        raise SsrfBlockedError() from exc

    allowed_hosts = _env_csv("MARKDOWN_ALLOWED_HOSTS")
    if not _hostname_allowed(hostname, allowed_hosts):
        logger.warning(f"Blocked URL: hostname not in allowlist ({hostname!r})")
        raise SsrfBlockedError()

    default_port = _DEFAULT_PORTS[scheme]
    port = parsed.port if parsed.port is not None else default_port

    candidates = await _resolve_candidates(hostname, port, timeout)

    if _env_enabled_by_default("MARKDOWN_SSRF_PROTECTION_ENABLED"):
        allow_localhost = _env_bool("MARKDOWN_ALLOW_LOCALHOST", False)
        allow_private_networks = _env_bool("MARKDOWN_ALLOW_PRIVATE_NETWORKS", False)
        blocked_networks = _env_networks("MARKDOWN_BLOCKED_NETWORKS")

        # If ANY resolved candidate is blocked, the whole URL is blocked -
        # an attacker must not be able to get a "safe" address through
        # simply because it round-robins with a blocked one.
        for candidate in candidates:
            if _is_blocked_ip(
                candidate,
                allow_localhost=allow_localhost,
                allow_private_networks=allow_private_networks,
                blocked_networks=blocked_networks,
            ):
                logger.warning(f"Blocked URL ({hostname!r}): resolved to blocked IP")
                raise SsrfBlockedError()

    resolved_ip = candidates[0]
    return _build_result(
        scheme=scheme,
        hostname=hostname,
        port=port,
        default_port=default_port,
        parsed=parsed,
        resolved_ip=resolved_ip,
    )


async def validate_url(url: str, *, timeout: float | None = None) -> ValidatedTarget:
    """Validate ``url`` against the SSRF policy and pin it to a resolved IP.

    ``timeout`` bounds DNS resolution so a slow/unresponsive resolver cannot
    silently run past the caller's own request timeout; callers should pass
    the same per-request timeout they use for the subsequent fetch. Defaults
    to ``MARKDOWN_DNS_TIMEOUT`` (10s) when omitted, so this module stays
    independently usable/testable without a caller-supplied value.

    Raises SsrfBlockedError on any rejection. Never raises anything else for
    malformed input - any unexpected exception raised while parsing or
    resolving the URL is caught and re-raised as SsrfBlockedError so callers
    can rely on a single exception type.
    """
    try:
        return await _validate_url(url, _DNS_TIMEOUT if timeout is None else timeout)
    except SsrfBlockedError:
        raise
    except Exception as exc:
        logger.warning(f"Blocked URL: malformed input during validation ({exc.__class__.__name__})")
        raise SsrfBlockedError() from exc
