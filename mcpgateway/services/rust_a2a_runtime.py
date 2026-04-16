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

    def __init__(self, message: str, *, is_timeout: bool = False) -> None:
        """Initialize with message and optional timeout flag."""
        super().__init__(message)
        self.is_timeout = is_timeout


class RustA2ARuntimeClient:
    """HTTP client used to call the experimental Rust A2A runtime."""

    def __init__(self) -> None:
        """Initialize a runtime client with optional UDS support."""
        self._uds_client: httpx.AsyncClient | None = None
        self._uds_client_lock = asyncio.Lock()

    async def invoke(self, prepared: PreparedA2AInvocation, *, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """Execute an A2A invocation through the Rust runtime.

        Args:
            prepared: Fully resolved invocation payload from :func:`prepare_a2a_invocation`.
            timeout_seconds: Optional per-request timeout override (seconds).

        Returns:
            Parsed JSON dict from the Rust runtime response.

        Raises:
            RustA2ARuntimeError: On non-200 response, invalid JSON, or non-object payload.
        """
        client = await self._get_runtime_client()
        target_url = _build_runtime_invoke_url()
        request_timeout = timeout_seconds or float(settings.experimental_rust_a2a_runtime_timeout_seconds)
        proxy_timeout = max(float(settings.experimental_rust_a2a_runtime_timeout_seconds), float(request_timeout) + 5.0)

        payload: Dict[str, Any] = {
            "endpoint_url": prepared.base_endpoint_url or prepared.endpoint_url,
            "headers": prepared.headers,
            "json_body": prepared.request_data,
            "timeout_seconds": request_timeout,
        }
        # Pass encrypted auth blobs so the Rust side decrypts them (avoids
        # plaintext secrets transiting the Python→Rust boundary).
        if prepared.auth_value_encrypted:
            payload["auth_headers_encrypted"] = prepared.auth_value_encrypted
        if prepared.auth_query_params_encrypted:
            payload["auth_query_params_encrypted"] = prepared.auth_query_params_encrypted

        try:
            response = await client.post(
                target_url,
                json=payload,
                timeout=httpx.Timeout(proxy_timeout),
                follow_redirects=False,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Sidecar process is down, UDS socket missing, or DNS/TCP
            # connect failed.  Surface as RustA2ARuntimeError so the caller's
            # existing handling kicks in (vs. an uncaught httpx exception
            # becoming an opaque 500).
            logger.error("Experimental Rust A2A runtime unreachable at %s: %s", target_url, exc)
            is_timeout = isinstance(exc, httpx.ConnectTimeout)
            raise RustA2ARuntimeError(
                f"Experimental Rust A2A runtime unreachable: {exc}",
                is_timeout=is_timeout,
            ) from exc
        except httpx.TimeoutException as exc:
            # Read/write/pool timeout talking to the sidecar.  Flag as a
            # timeout so callers can distinguish retriable slow-sidecar
            # cases from hard connection errors.
            logger.error("Experimental Rust A2A runtime request timed out at %s: %s", target_url, exc)
            raise RustA2ARuntimeError(
                f"Experimental Rust A2A runtime timed out: {exc}",
                is_timeout=True,
            ) from exc
        except httpx.HTTPError as exc:
            # Safety net for other httpx transport errors (RemoteProtocolError,
            # ReadError, WriteError, NetworkError, etc.).  Without this the
            # caller's ``except RustA2ARuntimeError`` branch would be bypassed
            # and a generic 500 would surface with no context.  is_timeout=False
            # since these are hard protocol/transport faults, not retriable.
            logger.error("Experimental Rust A2A runtime transport error at %s: %s", target_url, exc)
            raise RustA2ARuntimeError(
                f"Experimental Rust A2A runtime transport error: {exc}",
                is_timeout=False,
            ) from exc

        if response.status_code != 200:
            detail = response.text
            is_upstream_timeout = response.status_code == 504
            # Truncate detail to avoid leaking auth blobs that may appear
            # in Rust sidecar error responses.
            safe_detail = (detail[:500] + "...") if len(detail) > 500 else detail
            logger.error("Experimental Rust A2A runtime request failed with HTTP %s: %s", response.status_code, safe_detail)
            raise RustA2ARuntimeError(
                f"Experimental Rust A2A runtime failed with HTTP {response.status_code}: {safe_detail}",
                is_timeout=is_upstream_timeout,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RustA2ARuntimeError(f"Experimental Rust A2A runtime returned invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise RustA2ARuntimeError("Experimental Rust A2A runtime returned a non-object payload")
        return payload

    async def _get_runtime_client(self) -> httpx.AsyncClient:
        """Return the httpx client, lazily creating a UDS transport if configured.

        Returns:
            Shared HTTP client, or a lazily-created UDS client when ``experimental_rust_a2a_runtime_uds`` is set.
        """
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
    """Return the lazy singleton Rust A2A runtime client.

    Returns:
        RustA2ARuntimeClient singleton instance.
    """
    global _rust_a2a_runtime_client  # pylint: disable=global-statement
    if _rust_a2a_runtime_client is None:
        _rust_a2a_runtime_client = RustA2ARuntimeClient()
    return _rust_a2a_runtime_client


def _build_runtime_invoke_url() -> str:
    """Build the Rust runtime invoke URL, preserving any configured base path.

    Returns:
        Absolute URL pointing to the ``/invoke`` endpoint of the Rust sidecar.
    """
    base = urlsplit(settings.experimental_rust_a2a_runtime_url)
    base_path = base.path.rstrip("/")
    target_path = f"{base_path}/invoke" if base_path else "/invoke"
    return urlunsplit((base.scheme, base.netloc, target_path, base.query, ""))
