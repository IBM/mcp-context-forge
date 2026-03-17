# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/rust_a2a_runtime.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Python client for the experimental Rust A2A runtime sidecar.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.a2a_protocol import PreparedA2AInvocation
from mcpgateway.services.http_client_service import get_http_client, get_http_limits

logger = logging.getLogger(__name__)


class RustA2ARuntimeError(RuntimeError):
    """Raised when the Rust A2A runtime cannot complete a request."""


class RustA2ARuntimeClient:
    """HTTP client used to call the experimental Rust A2A runtime."""

    def __init__(self) -> None:
        """Initialize a runtime client with optional UDS support."""
        self._uds_client: httpx.AsyncClient | None = None
        self._uds_client_lock = asyncio.Lock()

    async def invoke(self, prepared: PreparedA2AInvocation, *, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Execute an A2A invocation through the Rust runtime."""
        client = await self._get_runtime_client()
        target_url = _build_runtime_invoke_url()
        request_timeout = timeout_seconds or float(settings.experimental_rust_a2a_runtime_timeout_seconds)
        proxy_timeout = max(float(settings.experimental_rust_a2a_runtime_timeout_seconds), float(request_timeout) + 5.0)

        response = await client.post(
            target_url,
            json={
                "endpoint_url": prepared.endpoint_url,
                "headers": prepared.headers,
                "json_body": prepared.request_data,
                "timeout_seconds": request_timeout,
            },
            timeout=httpx.Timeout(proxy_timeout),
            follow_redirects=False,
        )

        if response.status_code != 200:
            detail = response.text
            logger.error("Experimental Rust A2A runtime request failed with HTTP %s: %s", response.status_code, detail)
            raise RustA2ARuntimeError(f"Experimental Rust A2A runtime failed with HTTP {response.status_code}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RustA2ARuntimeError(f"Experimental Rust A2A runtime returned invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise RustA2ARuntimeError("Experimental Rust A2A runtime returned a non-object payload")
        return payload

    async def _get_runtime_client(self) -> httpx.AsyncClient:
        uds_path = settings.experimental_rust_a2a_runtime_uds
        if not uds_path:
            return await get_http_client()

        if self._uds_client is not None:
            return self._uds_client

        async with self._uds_client_lock:
            if self._uds_client is None:
                self._uds_client = httpx.AsyncClient(
                    transport=httpx.AsyncHTTPTransport(uds=uds_path),
                    limits=get_http_limits(),
                    timeout=httpx.Timeout(settings.experimental_rust_a2a_runtime_timeout_seconds),
                    follow_redirects=False,
                )
            return self._uds_client


_rust_a2a_runtime_client: RustA2ARuntimeClient | None = None


def get_rust_a2a_runtime_client() -> RustA2ARuntimeClient:
    """Return the lazy singleton Rust A2A runtime client."""
    global _rust_a2a_runtime_client  # pylint: disable=global-statement
    if _rust_a2a_runtime_client is None:
        _rust_a2a_runtime_client = RustA2ARuntimeClient()
    return _rust_a2a_runtime_client


def _build_runtime_invoke_url() -> str:
    """Build the Rust runtime invoke URL, preserving any configured base path."""
    base = urlsplit(settings.experimental_rust_a2a_runtime_url)
    base_path = base.path.rstrip("/")
    target_path = f"{base_path}/invoke" if base_path else "/invoke"
    return urlunsplit((base.scheme, base.netloc, target_path, base.query, ""))
