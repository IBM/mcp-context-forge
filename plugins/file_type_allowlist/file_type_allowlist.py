# -*- coding: utf-8 -*-
"""Location: ./plugins/file_type_allowlist/file_type_allowlist.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

File Type Allowlist Plugin.
Allows only configured MIME types or file extensions for resource fetches.
Performs checks in pre-fetch (by URI/ext) and post-fetch (by ResourceContent MIME).
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, List
from urllib.parse import urlparse

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.common.models import ResourceContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)


class FileTypeAllowlistConfig(BaseModel):
    """Configuration for the file type allowlist plugin.

    Attributes:
        allowed_mime_types: List of allowed MIME types.
        allowed_extensions: List of allowed file extensions (e.g., ['.md', '.txt']).
    """

    allowed_mime_types: List[str] = Field(default_factory=list)
    allowed_extensions: List[str] = Field(default_factory=list)  # e.g., ['.md', '.txt']


def _ext_from_uri(uri: str) -> str:
    """Extract file extension from a URI.

    Args:
        uri: The URI to extract the extension from.

    Returns:
        The file extension (including the dot) or empty string if none found.
    """
    path = urlparse(uri).path
    if "." in path:
        return "." + path.split(".")[-1].lower()
    return ""


class FileTypeAllowlistPlugin(Plugin):
    """Block non-allowed file types for resources."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the file type allowlist plugin.

        Args:
            config: Plugin configuration containing allowed MIME types and extensions.
        """
        super().__init__(config)
        self._cfg = FileTypeAllowlistConfig(**(config.config or {}))

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Check file extension before fetching resource.

        Args:
            payload: The resource pre-fetch payload containing the URI.
            context: Plugin execution context.

        Returns:
            ResourcePreFetchResult indicating whether to continue or block the fetch.
        """
        ext = _ext_from_uri(payload.uri)
        if self._cfg.allowed_extensions and ext and ext not in [e.lower() for e in self._cfg.allowed_extensions]:
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Disallowed file extension",
                    description=f"Extension {ext} is not allowed",
                    code="FILETYPE_BLOCK",
                    details={"extension": ext},
                ),
            )
        return ResourcePreFetchResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Check MIME type after fetching resource.

        Args:
            payload: The resource post-fetch payload containing the resource content.
            context: Plugin execution context.

        Returns:
            ResourcePostFetchResult indicating whether to continue or block based on MIME type.
        """
        content: Any = payload.content
        if isinstance(content, ResourceContent):
            if self._cfg.allowed_mime_types and content.mime_type:
                if content.mime_type.lower() not in [m.lower() for m in self._cfg.allowed_mime_types]:
                    return ResourcePostFetchResult(
                        continue_processing=False,
                        violation=PluginViolation(
                            reason="Disallowed MIME type",
                            description=f"MIME {content.mime_type} is not allowed",
                            code="FILETYPE_BLOCK",
                            details={"mime_type": content.mime_type},
                        ),
                    )
        return ResourcePostFetchResult(continue_processing=True)
