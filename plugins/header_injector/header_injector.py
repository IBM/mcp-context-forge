# -*- coding: utf-8 -*-
"""Location: ./plugins/header_injector/header_injector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Header Injector Plugin.

Injects custom HTTP headers into resource fetches by merging into payload.metadata["headers"].

Hook: resource_pre_fetch
"""

# Future
from __future__ import annotations

# Standard
from typing import Dict, Optional

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)


class HeaderInjectorConfig(BaseModel):
    """Configuration for header injection.

    Attributes:
        headers: Dictionary of headers to inject.
        uri_prefixes: Optional list of URI prefixes to filter on.
    """

    headers: Dict[str, str] = {}
    uri_prefixes: Optional[list[str]] = None  # only apply when URI startswith any prefix


def _should_apply(uri: str, prefixes: Optional[list[str]]) -> bool:
    """Check if headers should be applied to a URI.

    Args:
        uri: Resource URI.
        prefixes: Optional list of URI prefixes.

    Returns:
        True if headers should be applied.
    """
    if not prefixes:
        return True
    return any(uri.startswith(p) for p in prefixes)


class HeaderInjectorPlugin(Plugin):
    """Inject custom headers for resource fetching."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the header injector plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = HeaderInjectorConfig(**(config.config or {}))

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Inject custom headers before resource fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with modified headers if applicable.
        """
        if not _should_apply(payload.uri, self._cfg.uri_prefixes):
            return ResourcePreFetchResult(continue_processing=True)
        md = dict(payload.metadata or {})
        hdrs = {**md.get("headers", {}), **self._cfg.headers}
        md["headers"] = hdrs
        new_payload = ResourcePreFetchPayload(uri=payload.uri, metadata=md)
        return ResourcePreFetchResult(modified_payload=new_payload, metadata={"headers_injected": True, "count": len(self._cfg.headers)})
