# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/ssrf_pinning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Outbound DNS pinning helpers.

The outbound URL policy resolves a hostname and checks every resolved address. An HTTP
client that receives the hostname resolves it a second time at connection time, so an
attacker who controls DNS can answer with a public address for the check and a private
address for the connection. These helpers carry the checked addresses to the connection.

Known ceiling: httpcore keys pooled connections by URL origin and does not include
``sni_hostname`` in that key. On a client shared across destinations, two hostnames pinned
to one address collapse to one origin. Give such a client a per-destination instance if
that matters.
"""

# Standard
from dataclasses import dataclass
import logging
import os
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

# Third-Party
import httpx2

# First-Party
from mcpgateway.common.validators import _authority_is_ipv6_literal, pin_url_to_resolved_ip, SecurityValidator
from mcpgateway.config import settings

logger = logging.getLogger(__name__)

_PROXY_ENV_VARS = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def _egress_proxy_applies(url: str) -> bool:
    """Report whether an environment egress proxy would handle this URL.

    Args:
        url: Outbound URL to test.

    Returns:
        bool: True when a proxy variable applies and NO_PROXY does not exempt the host.
    """
    if not any(os.environ.get(name) for name in _PROXY_ENV_VARS):
        return False
    hostname = (urlparse(url).hostname or "").lower()
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
        for pinned_host in self._pinned_hosts:
            # httpx derived the Host header from the hostname URL at construction time; rewriting
            # the URL afterwards keeps that header while sending the bytes to the pinned address.
            request.url = original_url.copy_with(host=pinned_host)
            try:
                return await super().handle_async_request(request)
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:
                last_error = exc
        request.url = original_url
        raise last_error if last_error else httpx2.ConnectError("No pinned address available", request=request)


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

    def pin(self, url: str) -> str:
        """Replace the network location of ``url`` with the first validated address.

        Args:
            url: URL addressed to the original hostname.

        Returns:
            str: The same URL addressed to a validated address, or unchanged when unpinned.
        """
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
        validated_url = SecurityValidator._validate_url_impl(  # pylint: disable=protected-access
            url, field_name, skip_ssrf=True, reject_ipv6=not _authority_is_ipv6_literal(url)
        )
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
