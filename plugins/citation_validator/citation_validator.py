# -*- coding: utf-8 -*-
"""Location: ./plugins/citation_validator/citation_validator.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Citation Validator Plugin.

Validates links (citations) by checking reachability (HTTP status) and optional
content keyword hints. Annotates or blocks based on configuration.

Hooks: resource_post_fetch, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.utils.retry_manager import ResilientHttpClient

URL_RE = re.compile(r"https?://[\w\-\._~:/%#\[\]@!\$&'\(\)\*\+,;=]+", re.IGNORECASE)


class CitationConfig(BaseModel):
    """Configuration for citation validation.

    Attributes:
        fetch_timeout: HTTP request timeout in seconds.
        require_200: Whether to require HTTP 200 status (vs 2xx/3xx).
        content_keywords: Optional keywords that must appear in fetched content.
        max_links: Maximum number of links to validate.
        block_on_all_fail: Block if all citations fail validation.
        block_on_any_fail: Block if any citation fails validation.
        user_agent: User-Agent header for HTTP requests.
    """

    fetch_timeout: float = 6.0
    require_200: bool = True
    content_keywords: List[str] = []
    max_links: int = 20
    block_on_all_fail: bool = False
    block_on_any_fail: bool = False
    user_agent: str = "MCP-Context-Forge/1.0 CitationValidator"


async def _check_url(url: str, cfg: CitationConfig) -> Tuple[bool, int, Optional[str]]:
    """Validate a URL by checking HTTP status and optional content keywords.

    Args:
        url: URL to validate.
        cfg: Citation configuration.

    Returns:
        Tuple of (is_valid, http_status, response_text).
    """
    headers = {"User-Agent": cfg.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    async with ResilientHttpClient(client_args={"headers": headers, "timeout": cfg.fetch_timeout}) as client:
        try:
            resp = await client.get(url)
            ok = (resp.status_code == 200) if cfg.require_200 else (200 <= resp.status_code < 400)
            text = None
            if ok and cfg.content_keywords:
                # only read when needed to save time
                try:
                    text = resp.text
                except Exception:
                    text = None
                if text is not None:
                    text_l = text.lower()
                    for kw in cfg.content_keywords:
                        if kw.lower() not in text_l:
                            ok = False
                            break
            return ok, resp.status_code, text
        except Exception:
            return False, 0, None


def _extract_links(text: str, limit: int) -> List[str]:
    """Extract unique URLs from text up to a limit.

    Args:
        text: Text content to extract URLs from.
        limit: Maximum number of URLs to extract.

    Returns:
        List of unique URLs in order of appearance.
    """
    links = URL_RE.findall(text or "")
    # Keep order, dedupe
    seen = set()
    out: List[str] = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


class CitationValidatorPlugin(Plugin):
    """Validates citations by checking URL reachability and content."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the citation validator plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CitationConfig(**(config.config or {}))

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Validate citations in resource content after fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with validation status and metadata.
        """
        c = payload.content
        if not hasattr(c, "text") or not isinstance(c.text, str) or not c.text:
            return ResourcePostFetchResult(continue_processing=True)
        links = _extract_links(c.text, self._cfg.max_links)
        if not links:
            return ResourcePostFetchResult(continue_processing=True)
        results: Dict[str, Dict[str, Any]] = {}
        successes = 0
        for url in links:
            ok, status, _ = await _check_url(url, self._cfg)
            results[url] = {"ok": ok, "status": status}
            if ok:
                successes += 1
        all_fail = successes == 0
        any_fail = successes != len(links)
        if (self._cfg.block_on_all_fail and all_fail) or (self._cfg.block_on_any_fail and any_fail):
            return ResourcePostFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Invalid citations",
                    description="One or more citations failed validation",
                    code="CITATION_INVALID",
                    details={"results": results},
                ),
            )
        return ResourcePostFetchResult(metadata={"citation_results": results})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Validate citations in tool result after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with validation status and metadata.
        """
        text = payload.result if isinstance(payload.result, str) else None
        if not text:
            return ToolPostInvokeResult(continue_processing=True)
        links = _extract_links(text, self._cfg.max_links)
        if not links:
            return ToolPostInvokeResult(continue_processing=True)
        results: Dict[str, Dict[str, Any]] = {}
        successes = 0
        for url in links:
            ok, status, _ = await _check_url(url, self._cfg)
            results[url] = {"ok": ok, "status": status}
            if ok:
                successes += 1
        all_fail = successes == 0
        any_fail = successes != len(links)
        if (self._cfg.block_on_all_fail and all_fail) or (self._cfg.block_on_any_fail and any_fail):
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Invalid citations",
                    description="One or more citations failed validation",
                    code="CITATION_INVALID",
                    details={"results": results},
                ),
            )
        return ToolPostInvokeResult(metadata={"citation_results": results})
