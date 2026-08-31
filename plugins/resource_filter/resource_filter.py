# -*- coding: utf-8 -*-
"""Location: ./plugins/resource_filter/resource_filter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Resource Filter Plugin - Demonstrates resource hook functionality.
This plugin demonstrates how to use resource_pre_fetch and resource_post_fetch hooks
to filter and modify resource content. It can:
- Block resources based on URI patterns or protocols
- Limit resource content size
- Redact sensitive information from resource content
- Add metadata to resources
"""

# Standard
import ipaddress
import re
import socket
from typing import List, Pattern
from urllib.parse import unquote, urlparse

# Third-Party
import idna
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginMode,
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)


def _canonical_host(value: str) -> str:
    """Reduce a host or a blocklist entry to one comparable form.

    Both sides of the blocklist comparison run through this so that equivalent
    spellings of the same host match: percent-encoding, case, IPv6 brackets, a
    trailing dot, uncompressed or legacy IP literals, and Unicode versus
    punycode domains.

    Args:
        value: A parsed URL hostname, or a configured blocked-domain entry.

    Returns:
        The canonical form, or an empty string when there is nothing to compare.

    Examples:
        >>> _canonical_host("EVIL.com.")
        'evil.com'
        >>> _canonical_host("[::1]")
        '::1'
        >>> _canonical_host("2130706433")
        '127.0.0.1'
        >>> _canonical_host("[::ffff:7f00:1]")
        '127.0.0.1'
        >>> _canonical_host("m\\u00fcnchen.de")
        'xn--mnchen-3ya.de'
        >>> _canonical_host("blocked.example:8443")
        'blocked.example'
    """
    if not value:
        return ""
    host = unquote(value).strip().lower()
    # blocked_domains entries are hostnames, but the previous netloc comparison
    # also matched "host:port" and "[v6]:port" spellings. Reduce those to the
    # host so such an entry becomes a host-wide block rather than silently
    # matching nothing. A bare IPv6 literal keeps its colons.
    if host.startswith("["):
        closing = host.find("]")
        if closing != -1:
            host = host[1:closing]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    host = host.rstrip(".")
    if not host:
        return ""
    # IP literals compare on their compressed form, so "[::1]", "::1" and the
    # expanded "0:0:0:0:0:0:0:1" are all recognised as the same address. An
    # IPv4-mapped IPv6 address folds down to the IPv4 endpoint it identifies,
    # so "[::ffff:127.0.0.1]" matches a blocked "127.0.0.1".
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            return address.ipv4_mapped.compressed
        return address.compressed
    except ValueError:
        pass
    # Legacy IPv4 spellings (decimal integer, octal, hex, shortened dotted) are
    # rejected by ipaddress but accepted by the platform resolver, so a blocked
    # "127.0.0.1" has to match "2130706433", "0x7f000001" and "127.1" too.
    # Resolvers disagree on octal, so this can over-block, which is the safe
    # direction for a denylist.
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        pass
    # Domains compare as IDNA ASCII, so a Unicode entry and its punycode
    # equivalent match in either direction. Hosts that are not valid IDN
    # (internal names with underscores, for example) are left as-is.
    try:
        return idna.encode(host, uts46=True).decode("ascii")
    except (idna.IDNAError, UnicodeError):
        return host


class ResourceFilterPlugin(Plugin):
    """Plugin that filters and modifies resources.

    This plugin demonstrates the use of resource hooks to:
    - Validate resource URIs before fetching
    - Filter content after fetching
    - Add metadata to resources
    - Block certain protocols or domains
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the resource filter plugin.

        Args:
            config: Plugin configuration containing filter settings.
        """
        super().__init__(config)
        plugin_config = config.config if config.config else {}
        self.max_content_size = plugin_config.get("max_content_size", 1048576)
        self.allowed_protocols = plugin_config.get("allowed_protocols", ["file", "http", "https"])
        self.blocked_domains = plugin_config.get("blocked_domains", [])
        # Canonicalize the blocklist once at load rather than on every request.
        self._blocked_hosts: List[str] = [canonical for canonical in (_canonical_host(domain) for domain in self.blocked_domains) if canonical]
        # Precompile content filter patterns for performance
        self.content_filters: List[tuple[Pattern[str], str]] = []
        for filter_rule in plugin_config.get("content_filters", []):
            pattern = filter_rule.get("pattern")
            replacement = filter_rule.get("replacement", "***")
            if pattern:
                try:
                    compiled_pattern = re.compile(pattern, re.IGNORECASE)
                    self.content_filters.append((compiled_pattern, replacement))
                except re.error:
                    # Skip invalid patterns
                    pass

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Validate and potentially modify resource requests before fetching.

        Args:
            payload: The resource pre-fetch payload containing URI and metadata.
            context: Plugin execution context.

        Returns:
            ResourcePreFetchResult indicating whether to continue and any modifications.
        """
        # Parse the URI
        try:
            parsed = urlparse(payload.uri)
        except Exception as e:
            violation = PluginViolation(reason="Invalid URI", description=f"Could not parse resource URI: {e}", code="INVALID_URI", details={"uri": payload.uri, "error": str(e)})
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Check if URI has a scheme
        if not parsed.scheme:
            violation = PluginViolation(reason="Invalid URI format", description="URI must have a valid scheme (protocol)", code="INVALID_URI", details={"uri": payload.uri})
            # In transform mode, log but continue
            if self.mode == PluginMode.TRANSFORM:
                return ResourcePreFetchResult(continue_processing=True, violation=violation, modified_payload=payload)
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Check protocol
        if parsed.scheme not in self.allowed_protocols:
            violation = PluginViolation(
                reason="Protocol not allowed",
                description=f"Protocol '{parsed.scheme}' is not in allowed list",
                code="PROTOCOL_BLOCKED",
                details={"uri": payload.uri, "protocol": parsed.scheme, "allowed": self.allowed_protocols},
            )
            # In transform mode, log but continue
            if self.mode == PluginMode.TRANSFORM:
                return ResourcePreFetchResult(continue_processing=True, violation=violation, modified_payload=payload)
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Match on the connected host, not netloc: netloc carries userinfo and port, so
        # "good.com@evil.com" and "evil.com:8080" slip past a blocklist keyed on "evil.com".
        host = _canonical_host(parsed.hostname or "")
        if host:
            if host in self._blocked_hosts or any(host.endswith("." + blocked) for blocked in self._blocked_hosts):
                violation = PluginViolation(reason="Domain is blocked", description=f"Domain '{host}' is in blocked list", code="DOMAIN_BLOCKED", details={"uri": payload.uri, "domain": host})
                # In transform mode, log but continue
                if self.mode == PluginMode.TRANSFORM:
                    return ResourcePreFetchResult(continue_processing=True, violation=violation, modified_payload=payload)
                return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Add metadata to track this plugin processed the request
        modified_payload = ResourcePreFetchPayload(
            uri=payload.uri,
            metadata={
                **(payload.metadata or {}),
                "validated": True,
                "protocol": parsed.scheme,
                "request_id": context.global_context.request_id,
                "user": context.global_context.user,
                "resource_filter_plugin": "pre_fetch_validated",
                "allowed_size": self.max_content_size,
            },
        )

        # Store validation info in context for post-fetch
        context.set_state("uri_validated", True)
        context.set_state("original_uri", payload.uri)

        return ResourcePreFetchResult(continue_processing=True, modified_payload=modified_payload, metadata={"validation": "passed"})

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Filter and modify resource content after fetching.

        Args:
            payload: The resource post-fetch payload containing fetched content.
            context: Plugin execution context.

        Returns:
            ResourcePostFetchResult with potentially modified content.
        """
        # Check if pre-fetch validation was done
        if not context.get_state("uri_validated"):
            # This resource wasn't validated in pre-fetch, skip processing
            return ResourcePostFetchResult(continue_processing=True, modified_payload=payload)

        # Process content if it's text
        modified_content = payload.content
        content_was_modified = False

        # Apply content filters if we have text content
        if hasattr(payload.content, "text") and payload.content.text:
            original_text = payload.content.text
            filtered_text = original_text

            # Check content size
            if len(filtered_text.encode("utf-8")) > self.max_content_size:
                violation = PluginViolation(
                    reason="Content exceeds maximum size",
                    description=f"Resource content exceeds maximum size of {self.max_content_size} bytes",
                    code="CONTENT_TOO_LARGE",
                    details={"uri": payload.uri, "size": len(filtered_text.encode("utf-8")), "max_size": self.max_content_size},
                )
                # In transform mode, log but continue
                if self.mode == PluginMode.TRANSFORM:
                    return ResourcePostFetchResult(continue_processing=True, violation=violation, modified_payload=payload)
                return ResourcePostFetchResult(continue_processing=False, violation=violation)

            # Apply content filters
            for compiled_pattern, replacement in self.content_filters:
                filtered_text = compiled_pattern.sub(replacement, filtered_text)

            # Update content if it was modified
            if filtered_text != original_text:
                # Create new content object with filtered text
                # First-Party
                from mcpgateway.common.models import ResourceContent

                modified_content = ResourceContent(
                    type=payload.content.type,
                    id=payload.content.id,
                    uri=payload.content.uri,
                    mime_type=getattr(payload.content, "mime_type", None),
                    text=filtered_text,
                    blob=getattr(payload.content, "blob", None),
                )
                content_was_modified = True
                context.set_state("content_filtered", True)

        # Only create modified payload if content was actually modified
        if content_was_modified:
            modified_payload = ResourcePostFetchPayload(uri=payload.uri, content=modified_content)
        else:
            # Return original payload if nothing was modified
            modified_payload = payload

        return ResourcePostFetchResult(
            continue_processing=True, modified_payload=modified_payload, metadata={"filtered": context.get_state("content_filtered", False), "original_uri": context.get_state("original_uri")}
        )

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Handle tool invocation results.

        This plugin focuses on resource filtering, so tool invocations pass through unmodified.

        Args:
            payload: The tool invocation result payload.
            context: Plugin execution context.

        Returns:
            ToolPostInvokeResult indicating to continue processing without modifications.
        """
        # This plugin is focused on resource filtering, not tool invocations
        # Simply pass through without modification
        return ToolPostInvokeResult(continue_processing=True, modified_payload=payload)
