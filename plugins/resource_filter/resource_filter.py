# -*- coding: utf-8 -*-
"""Resource Filter Plugin - Demonstrates resource hook functionality.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This plugin demonstrates how to use resource_pre_fetch and resource_post_fetch hooks
to filter and modify resource content. It can:
- Block resources based on URI patterns or protocols
- Limit resource content size
- Redact sensitive information from resource content
- Add metadata to resources
"""

import re
from typing import Any, Optional
from urllib.parse import urlparse

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig, PluginMode
from mcpgateway.plugins.framework.plugin_types import (
    PluginContext,
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)


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
        self.content_filters = plugin_config.get("content_filters", [])

    async def resource_pre_fetch(
        self, payload: ResourcePreFetchPayload, context: PluginContext
    ) -> ResourcePreFetchResult:
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
            violation = PluginViolation(
                reason="Invalid URI",
                description=f"Could not parse resource URI: {e}",
                code="INVALID_URI",
                details={"uri": payload.uri, "error": str(e)}
            )
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=violation
            )

        # Check if URI has a scheme
        if not parsed.scheme:
            violation = PluginViolation(
                reason="Invalid URI format",
                description="URI must have a valid scheme (protocol)",
                code="INVALID_URI",
                details={"uri": payload.uri}
            )
            # In permissive mode, log but continue
            if self.mode == PluginMode.PERMISSIVE:
                return ResourcePreFetchResult(
                    continue_processing=True,
                    violation=violation,
                    modified_payload=payload
                )
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=violation
            )

        # Check protocol
        if parsed.scheme not in self.allowed_protocols:
            violation = PluginViolation(
                reason="Protocol not allowed",
                description=f"Protocol '{parsed.scheme}' is not in allowed list",
                code="PROTOCOL_BLOCKED",
                details={
                    "uri": payload.uri,
                    "protocol": parsed.scheme,
                    "allowed": self.allowed_protocols
                }
            )
            # In permissive mode, log but continue
            if self.mode == PluginMode.PERMISSIVE:
                return ResourcePreFetchResult(
                    continue_processing=True,
                    violation=violation,
                    modified_payload=payload
                )
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=violation
            )

        # Check domain blocking (case-insensitive)
        if parsed.netloc:
            # Convert both to lowercase for comparison
            domain_lower = parsed.netloc.lower()
            blocked_domains_lower = [d.lower() for d in self.blocked_domains]
            if domain_lower in blocked_domains_lower or any(domain_lower.endswith('.' + d) for d in blocked_domains_lower):
                violation = PluginViolation(
                    reason="Domain is blocked",
                    description=f"Domain '{parsed.netloc}' is in blocked list",
                    code="DOMAIN_BLOCKED",
                    details={
                        "uri": payload.uri,
                        "domain": parsed.netloc
                    }
                )
                # In permissive mode, log but continue
                if self.mode == PluginMode.PERMISSIVE:
                    return ResourcePreFetchResult(
                        continue_processing=True,
                        violation=violation,
                        modified_payload=payload
                    )
                return ResourcePreFetchResult(
                    continue_processing=False,
                    violation=violation
                )

        # Add metadata to track this plugin processed the request
        modified_payload = ResourcePreFetchPayload(
            uri=payload.uri,
            metadata={
                **payload.metadata,
                "validated": True,
                "protocol": parsed.scheme,
                "request_id": context.request_id,
                "user": context.user,
                "resource_filter_plugin": "pre_fetch_validated",
                "allowed_size": self.max_content_size
            }
        )

        # Store validation info in context for post-fetch
        context.set_state("uri_validated", True)
        context.set_state("original_uri", payload.uri)

        return ResourcePreFetchResult(
            continue_processing=True,
            modified_payload=modified_payload,
            metadata={"validation": "passed"}
        )

    async def resource_post_fetch(
        self, payload: ResourcePostFetchPayload, context: PluginContext
    ) -> ResourcePostFetchResult:
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
            return ResourcePostFetchResult(
                continue_processing=True,
                modified_payload=payload
            )

        # Process content if it's text
        modified_content = payload.content
        content_was_modified = False

        # Apply content filters if we have text content
        if hasattr(payload.content, 'text') and payload.content.text:
            original_text = payload.content.text
            filtered_text = original_text

            # Check content size
            if len(filtered_text.encode('utf-8')) > self.max_content_size:
                violation = PluginViolation(
                    reason="Content exceeds maximum size",
                    description=f"Resource content exceeds maximum size of {self.max_content_size} bytes",
                    code="CONTENT_TOO_LARGE",
                    details={
                        "uri": payload.uri,
                        "size": len(filtered_text.encode('utf-8')),
                        "max_size": self.max_content_size
                    }
                )
                # In permissive mode, log but continue
                if self.mode == PluginMode.PERMISSIVE:
                    return ResourcePostFetchResult(
                        continue_processing=True,
                        violation=violation,
                        modified_payload=payload
                    )
                return ResourcePostFetchResult(
                    continue_processing=False,
                    violation=violation
                )

            # Apply content filters
            for filter_rule in self.content_filters:
                pattern = filter_rule.get("pattern")
                replacement = filter_rule.get("replacement", "***")
                if pattern:
                    filtered_text = re.sub(
                        pattern,
                        replacement,
                        filtered_text,
                        flags=re.IGNORECASE
                    )

            # Update content if it was modified
            if filtered_text != original_text:
                # Create new content object with filtered text
                from mcpgateway.models import ResourceContent
                modified_content = ResourceContent(
                    type=payload.content.type,
                    uri=payload.content.uri,
                    text=filtered_text
                )
                content_was_modified = True
                context.set_state("content_filtered", True)

        # Only create modified payload if content was actually modified
        if content_was_modified:
            modified_payload = ResourcePostFetchPayload(
                uri=payload.uri,
                content=modified_content
            )
        else:
            # Return original payload if nothing was modified
            modified_payload = payload

        return ResourcePostFetchResult(
            continue_processing=True,
            modified_payload=modified_payload,
            metadata={
                "filtered": context.get_state("content_filtered", False),
                "original_uri": context.get_state("original_uri")
            }
        )
