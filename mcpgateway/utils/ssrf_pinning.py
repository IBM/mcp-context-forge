# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/ssrf_pinning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Outbound DNS pinning helpers.

The outbound URL policy resolves a hostname and checks every resolved address. An HTTP
client that receives the hostname resolves it a second time at connection time, so an
attacker who controls DNS can answer with a public address for the check and a private
address for the connection. These helpers carry the checked addresses to the connection.

Client isolation constraint: ``pin()``, ``connect_async()``, and ``stream_async()`` rewrite
URL origins to validated IP addresses. httpcore keys pooled connections by URL origin,
without including ``sni_hostname``. Different hostnames pinned to one address can therefore
reuse a connection whose certificate was verified for only the first hostname.
Use a client isolated to one validated hostname for all three entry points.
Never share that client across different hostnames. ``SniPinningTransport`` is exempt
because each instance accepts only its validated hostname.
"""

# Standard
from contextlib import asynccontextmanager, AsyncExitStack
from dataclasses import dataclass
import logging
import os
import ssl
from typing import Any, AsyncGenerator, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse
import warnings

# Third-Party
import httpx
import httpx2

# First-Party
from mcpgateway.common.validators import _authority_is_ipv6_literal, pin_url_to_resolved_ip, SecurityValidator
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

# httpx mounts HTTP_PROXY on http:// only and HTTPS_PROXY on https:// only. A variable for the
# other scheme must not skip pinning, because httpx then connects directly and re-resolves DNS.
_PROXY_ENV_VARS_BY_SCHEME = {
    "http": ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"),
    "https": ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy"),
}


def _egress_proxy_applies(url: str) -> bool:
    """Report whether an environment egress proxy would handle this URL.

    Args:
        url: Outbound URL to test.

    Returns:
        bool: True when a proxy variable for the URL's scheme applies and NO_PROXY does not exempt the host.
    """
    parsed = urlparse(url)
    if not any(os.environ.get(name) for name in _PROXY_ENV_VARS_BY_SCHEME.get(parsed.scheme.lower(), ())):
        return False
    hostname = (parsed.hostname or "").lower()
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    for entry in (item.strip().lower().lstrip(".") for item in no_proxy.split(",")):
        if entry == "*":
            return False
        if entry and (hostname == entry or hostname.endswith(f".{entry}")):
            return False
    return True


class SniPinningTransport(httpx2.AsyncHTTPTransport):
    """Dial DNS-pinned addresses while keeping the request's hostname authority and TLS identity.

    The MCP SDK compares the origin it connected to against the origin the
    server advertises (``mcp.client.sse`` raises on a mismatch), so pinning has
    to happen below the SDK: requests keep the validated hostname in their URL
    and ``Host`` header, while every connection goes to an address resolved at
    validation time and TLS is verified against that hostname. Built on httpx2
    because the MCP SDK's client transports run on that stack.
    """

    def __init__(self, sni_hostname: str, pinned_hosts: Sequence[str], **kwargs: Any) -> None:
        """Record the validated hostname and the addresses to dial in its place.

        Args:
            sni_hostname: Validated hostname whose certificate must match.
            pinned_hosts: Addresses resolved at validation time, tried in order.
            **kwargs: Forwarded to ``httpx2.AsyncHTTPTransport``.
        """
        super().__init__(**kwargs)
        self._sni_hostname = sni_hostname
        self._pinned_hosts = tuple(pinned_hosts)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """Send the request to a pinned address with TLS pinned to the validated hostname.

        Args:
            request: Outbound request addressed to the validated hostname.

        Returns:
            httpx2.Response: The upstream response.

        Raises:
            httpx2.UnsupportedProtocol: If the request targets any other host.
            httpx2.ConnectError: If every pinned address refuses the connection.
            httpx2.ConnectTimeout: If every pinned address times out.
        """
        # Compare the IDNA-encoded form: httpx decodes punycode back to Unicode on `url.host`,
        # while the validated hostname arrives punycode-encoded from the pinning validator.
        if request.url.raw_host.decode("ascii") != self._sni_hostname:
            raise httpx2.UnsupportedProtocol(f"Refused a request to unvalidated host {request.url.host}", request=request)
        request.extensions.setdefault("sni_hostname", self._sni_hostname)
        original_url = request.url
        last_error: Optional[Exception] = None
        try:
            for pinned_host in self._pinned_hosts:
                # httpx derived the Host header from the hostname URL at construction time; rewriting
                # the URL afterwards keeps that header while sending the bytes to the pinned address.
                request.url = original_url.copy_with(host=pinned_host)
                try:
                    return await super().handle_async_request(request)
                except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:
                    last_error = exc
            raise last_error if last_error else httpx2.ConnectError("No pinned address available", request=request)
        finally:
            # Restore the logical URL on every exit path. The bytes have already gone to the pinned
            # address; leaving the address on the request would make `response.url` report it and
            # would resolve a relative redirect against it.
            request.url = original_url


@dataclass(frozen=True)
class PinnedTarget:
    """An outbound target whose addresses passed the outbound URL policy."""

    validated_url: str
    hostname: str
    original_authority: str
    resolved_ips: Tuple[str, ...]

    @property
    def is_pinned(self) -> bool:
        """Report whether this target carries addresses to dial.

        Returns:
            bool: True when the connection can be pinned.
        """
        return bool(self.resolved_ips and self.hostname and self.original_authority)

    @property
    def extensions(self) -> Dict[str, str]:
        """Return the HTTPX request extensions that keep TLS bound to the hostname.

        Returns:
            Dict[str, str]: Extensions for an HTTPX request, empty when unpinned.
        """
        return {"sni_hostname": self.hostname} if self.is_pinned else {}

    @staticmethod
    async def _dial(client: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue one request using the verb method for ``method``, as httpx callers already do.

        Uses ``client.post`` / ``client.get`` so a caller's existing client stubs and
        instrumentation keep working, and keeps ``client.request`` as the fallback for verbs
        without a dedicated method.

        Args:
            client: httpx ``AsyncClient`` or a test double exposing the same verb methods.
            method: HTTP method.
            url: URL to dial.
            **kwargs: Forwarded to the verb method.

        Returns:
            httpx.Response: Response returned by the client.
        """
        verb = getattr(client, method.lower(), None) if method.lower() in {"get", "post", "put", "patch", "delete", "head"} else None
        if verb is None:
            response: httpx.Response = await client.request(method, url, **kwargs)
        else:
            response = await verb(url, **kwargs)
        return response

    def pin(self, url: str) -> str:
        """Replace the network location of ``url`` with a single validated address.

        Deprecated: this dials only the first validated address, so a peer that listens on the
        other address family is never reached. Use :meth:`connect_async` or :meth:`stream_async`
        instead, which try every validated address.

        Args:
            url: URL addressed to the original hostname.

        Returns:
            str: The same URL addressed to a validated address, or unchanged when unpinned.
        """
        warnings.warn("PinnedTarget.pin() is deprecated; use connect_async() or stream_async()", DeprecationWarning, stacklevel=2)
        if not self.is_pinned:
            return url
        return pin_url_to_resolved_ip(url, self.resolved_ips[0])

    def apply_headers(self, headers: Mapping[str, str]) -> Dict[str, str]:
        """Return ``headers`` with ``Host`` forced to the validated authority.

        Args:
            headers: Headers prepared for the outbound request.

        Returns:
            Dict[str, str]: Headers whose only ``Host`` entry is the validated authority.

        Raises:
            ValueError: If the validated authority contains header-injection characters.
        """
        if not self.is_pinned:
            return dict(headers)
        if any(char in self.original_authority for char in ("\r", "\n", "@")):
            raise ValueError("Refusing to send a Host header built from an unsafe authority")
        pinned = {key: value for key, value in headers.items() if key.lower() != "host"}
        pinned["Host"] = self.original_authority
        return pinned

    async def connect_async(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send one request, trying every validated address until one answers.

        The request keeps the validated hostname in its ``Host`` header, while each attempt dials
        one validated address. An address that refuses the connection or times out is retried with
        the next one, so a peer bound to only one address family is still reached.

        Purpose-built clients stay with the caller: this uses the ``client`` it is given, so
        custom SSL contexts and per-call timeouts keep working.

        Use a client isolated to this validated hostname. These helpers rewrite the URL
        origin to an IP address. Never share that client across different hostnames.

        Args:
            client: ``httpx.AsyncClient`` used for every attempt.
            method: HTTP method.
            url: URL addressed to the validated hostname, not to an address.
            headers: Headers for the request. A ``Host`` entry is replaced with the validated
                authority on pinned attempts.
            **kwargs: Forwarded to the client verb method (json, data, timeout, follow_redirects...).

        Returns:
            httpx.Response: The first response received.

        Raises:
            httpx.ConnectError: If TLS verification fails or every validated address refuses the connection.
            httpx.ConnectTimeout: If every validated address times out.
        """
        if not self.is_pinned:
            return await self._dial(client, method, url, headers=dict(headers or {}), **kwargs)

        pinned_headers = self.apply_headers(headers or {})
        return await self._dial_pinned(client, method, url, pinned_headers, **kwargs)

    async def _dial_pinned(self, client: Any, method: str, url: str, headers: Dict[str, str], **kwargs: Any) -> httpx.Response:
        """Dial each validated address until one answers, keeping TLS pinned to the hostname.

        ``sni_hostname`` is passed on every attempt so httpcore verifies the certificate against
        the validated hostname rather than the IP literal in the dialled URL. A TLS failure is
        raised immediately instead of being retried on the next address: retrying would mask a
        certificate problem as an unreachable peer.

        Args:
            client: ``httpx.AsyncClient`` or a test double exposing the same verb methods.
            method: HTTP method.
            url: URL addressed to the validated hostname.
            headers: Headers with ``Host`` already forced to the validated authority.
            **kwargs: Forwarded to the client verb method.

        Returns:
            httpx.Response: The first response received.

        Raises:
            httpx.ConnectError: If every validated address refuses the connection, or TLS verification fails.
            httpx.ConnectTimeout: If every validated address times out.
        """
        for address in self.resolved_ips[:-1]:
            try:
                return await self._dial(client, method, pin_url_to_resolved_ip(url, address), headers=headers, extensions=self.extensions, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if _is_tls_failure(exc):
                    raise
                logger.debug(
                    "Pinned attempt failed for %s target; trying the next validated address (%s)",
                    "an IPv6" if ":" in address else "an IPv4",
                    type(exc).__name__,
                )
        return await self._dial(client, method, pin_url_to_resolved_ip(url, self.resolved_ips[-1]), headers=headers, extensions=self.extensions, **kwargs)

    @asynccontextmanager
    async def stream_async(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[httpx.Response, None]:
        """Stream one request, trying every validated address until one answers.

        Retry connection setup only. Keep the response open while the caller reads the body.
        Propagate caller, response-read, and cleanup errors without another request.

        Use a client isolated to this validated hostname. These helpers rewrite the URL
        origin to an IP address. Never share that client across different hostnames.

        Args:
            client: ``httpx.AsyncClient`` used for every attempt.
            method: HTTP method.
            url: URL addressed to the validated hostname, not to an address.
            headers: Headers for the request. A ``Host`` entry is replaced with the validated
                authority on pinned attempts.
            **kwargs: Forwarded to ``client.stream``.

        Yields:
            httpx.Response: The first streaming response received.

        Raises:
            httpx.ConnectError: If TLS verification fails or every validated address refuses the connection.
            httpx.ConnectTimeout: If every validated address times out.
        """
        if not self.is_pinned:
            async with client.stream(method, url, headers=dict(headers or {}), **kwargs) as response:
                yield response
            return

        pinned_headers = self.apply_headers(headers or {})
        for index, address in enumerate(self.resolved_ips):
            async with AsyncExitStack() as stack:
                try:
                    response = await stack.enter_async_context(client.stream(method, pin_url_to_resolved_ip(url, address), headers=pinned_headers, extensions=self.extensions, **kwargs))
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    if _is_tls_failure(exc) or index == len(self.resolved_ips) - 1:
                        raise
                    logger.debug("Pinned stream connection failed; trying another validated address (%s)", type(exc).__name__)
                    continue

                yield response
                return

    def client_kwargs(self, *, verify: Any, limits: Optional[httpx2.Limits] = None) -> Dict[str, Any]:
        """Return the ``httpx2.AsyncClient`` keyword arguments that apply this target's pinning.

        Args:
            verify: TLS verification setting or SSLContext for the connection.
            limits: Optional connection pool limits.

        Returns:
            Dict[str, Any]: ``transport=`` when pinned, ``verify=`` otherwise.
        """
        transport_kwargs: Dict[str, Any] = {"verify": verify}
        if limits is not None:
            transport_kwargs["limits"] = limits
        if not self.is_pinned:
            # An explicit transport disables httpx environment-proxy discovery, so an unpinned
            # target must configure the client directly and leave the transport unset.
            return transport_kwargs
        return {"transport": SniPinningTransport(sni_hostname=self.hostname, pinned_hosts=self.resolved_ips, **transport_kwargs)}


def _is_tls_failure(exc: BaseException) -> bool:
    """Report whether a connection error is a TLS verification failure.

    A pinned attempt dials an IP literal while ``sni_hostname`` carries the validated hostname.
    When verification fails against that hostname, retrying another address cannot help: the
    certificate is wrong for every one of them. Treating it as a transport failure would both
    hide a security-relevant error and invite a pointless retry per address.

    Args:
        exc: Exception raised by the pinned attempt.

    Returns:
        bool: True when the cause chain contains a certificate verification failure.
    """
    seen = 0
    current: Optional[BaseException] = exc
    while current is not None and seen < 10:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
        seen += 1
    return False


async def resolve_pinned_target(url: str, field_name: str = "URL") -> PinnedTarget:
    """Validate an outbound URL and keep the addresses that passed the check.

    Args:
        url: Outbound URL to validate.
        field_name: Human-readable field name for validation errors.

    Returns:
        PinnedTarget: The validated target, unpinned when SSRF protection is disabled or
        an egress proxy applies.

    Raises:
        ValueError: If the URL fails validation.
    """
    if not settings.ssrf_protection_enabled:
        # Skipping the PIN must never skip the VALIDATION: the scheme allowlist,
        # dangerous-protocol, control-character, embedded-credential and XSS checks below
        # are unconditional even when DNS-based SSRF checks are off.
        validated_url = SecurityValidator._validate_url_impl(url, field_name, skip_ssrf=True, reject_ipv6=not _authority_is_ipv6_literal(url))  # pylint: disable=protected-access
        return PinnedTarget(validated_url=validated_url, hostname="", original_authority="", resolved_ips=())
    result = await SecurityValidator.validate_url_for_connection_pinning(url, field_name)
    validated_url = result["validated_url"]
    hostname = result["hostname"]
    original_authority = result["original_authority"]
    resolved_ips = result["resolved_ips"]
    if _egress_proxy_applies(url):
        # The proxy resolves the hostname, so there is no address to pin. The URL policy
        # above still runs: skipping pinning must never skip validation.
        logger.debug("Skipping outbound pinning for %s: an egress proxy performs the resolution", field_name)
        return PinnedTarget(validated_url=validated_url or url, hostname="", original_authority="", resolved_ips=())
    return PinnedTarget(
        validated_url=validated_url or url,
        hostname=hostname or "",
        original_authority=original_authority or "",
        resolved_ips=tuple(resolved_ips or ()),
    )
