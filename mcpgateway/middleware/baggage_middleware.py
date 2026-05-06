# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/baggage_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OpenTelemetry Baggage Middleware for HTTP header extraction.

This middleware extracts configured HTTP headers and converts them to W3C baggage
for distributed tracing context propagation. It implements a strict security model:
- Only explicitly configured headers are processed (fail-closed)
- All values are sanitized
- Size limits are enforced
- Rejected headers are logged for audit

The middleware integrates with OpenTelemetry's baggage API to ensure baggage
is available in all spans created during the request lifecycle.
"""

# Standard
import logging
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

# First-Party
from mcpgateway.baggage import (
    BaggageConfig,
    extract_baggage_from_headers,
    filter_incoming_baggage,
    merge_baggage,
    parse_w3c_baggage_header,
)

logger = logging.getLogger(__name__)

# Try to import OpenTelemetry baggage API
try:
    # Third-Party
    from opentelemetry import baggage as otel_baggage
    from opentelemetry.context import attach as otel_attach
    from opentelemetry.context import detach as otel_detach
    from opentelemetry.context import get_current as otel_get_current

    OTEL_BAGGAGE_AVAILABLE = True
except ImportError:
    otel_baggage = None
    otel_attach = None
    otel_detach = None
    otel_get_current = None
    OTEL_BAGGAGE_AVAILABLE = False
    logger.debug("OpenTelemetry baggage API not available")


class BaggageMiddleware:
    """ASGI middleware for HTTP header to W3C baggage conversion.

    This middleware:
    1. Extracts configured HTTP headers from incoming requests
    2. Validates and sanitizes header values
    3. Converts headers to W3C baggage format
    4. Merges with existing upstream baggage
    5. Sets baggage in OpenTelemetry context for span propagation

    Security features:
    - Strict allowlist (only configured headers processed)
    - Value sanitization (CRLF removal, control character stripping)
    - Size limits (max items, max bytes)
    - Audit logging for rejected headers

    The middleware must wrap OpenTelemetryRequestMiddleware so baggage is attached
    before the request-root span is created.
    """

    def __init__(
        self,
        app: Any,
        config: Optional[BaggageConfig] = None,
    ):
        """Initialize the baggage middleware.

        Args:
            app: The ASGI application to wrap
            config: Optional pre-loaded BaggageConfig (loaded from settings if not provided)
        """
        self.app = app
        self._config: Optional[BaggageConfig] = config
        self._config_loaded = False

    def _ensure_config_loaded(self) -> BaggageConfig:
        """Lazy-load baggage configuration on first request.

        Returns:
            Loaded BaggageConfig instance
        """
        if not self._config_loaded:
            if self._config is None:
                try:
                    self._config = BaggageConfig.from_settings()
                    if self._config.enabled:
                        logger.info(f"Baggage middleware enabled with {len(self._config.mappings)} header mappings")
                except Exception as e:
                    logger.error(f"Failed to load baggage configuration: {e}")
                    # Create disabled config as fallback
                    self._config = BaggageConfig(
                        enabled=False,
                        mappings=[],
                        propagate_to_external=False,
                        max_items=32,
                        max_size_bytes=8192,
                        log_rejected=True,
                        log_sanitization=True,
                    )
            self._config_loaded = True

        return self._config

    def _extract_headers_from_scope(self, scope: Mapping[str, Any]) -> Dict[str, str]:
        """Extract HTTP headers from ASGI scope.

        Args:
            scope: ASGI connection scope

        Returns:
            Dictionary of header name -> value (decoded from bytes)
        """
        headers: Dict[str, str] = {}
        scope_headers = scope.get("headers", [])

        for key_bytes, value_bytes in scope_headers:
            try:
                key = key_bytes.decode("latin-1")
                value = value_bytes.decode("latin-1")
                headers[key] = value
            except (AttributeError, TypeError, UnicodeDecodeError) as e:
                logger.debug(f"Failed to decode header: {e}")
                continue

        return headers

    def _extract_existing_baggage(self, headers: Dict[str, str], config: BaggageConfig) -> Dict[str, str]:
        """Extract existing W3C baggage from upstream request headers.

        Args:
            headers: HTTP request headers
            config: BaggageConfig instance for filtering baggage

        Returns:
            Dictionary of existing baggage key -> value
        """
        baggage_header = headers.get("baggage", "")
        if not baggage_header:
            return {}

        try:
            return filter_incoming_baggage(parse_w3c_baggage_header(baggage_header), config)
        except Exception as e:
            logger.debug(f"Failed to parse upstream baggage header: {e}")
            return {}

    def _set_baggage_in_context(self, baggage: Dict[str, str]) -> Optional[object]:
        """Set baggage in OpenTelemetry context.

        Args:
            baggage: Dictionary of baggage key -> value to set

        Returns:
            Context token if baggage was attached, otherwise None.
        """
        if otel_baggage is None or otel_attach is None or otel_get_current is None:
            logger.debug("OpenTelemetry baggage API not available, skipping context update")
            return None

        if not baggage:
            return None

        try:
            current_context = otel_get_current()
            for key, value in baggage.items():
                current_context = otel_baggage.set_baggage(key, value, context=current_context)
                logger.debug(f"Set baggage in context: {key}={value}")
            return otel_attach(current_context)
        except Exception as e:
            logger.warning(f"Failed to set baggage in OpenTelemetry context: {e}")
            return None

    async def __call__(
        self,
        scope: Mapping[str, Any],
        receive: Callable[[], Awaitable[Dict[str, Any]]],
        send: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Process ASGI request and extract baggage from headers.

        Args:
            scope: ASGI connection scope
            receive: ASGI receive callable
            send: ASGI send callable
        """
        # Only process HTTP requests
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # Lazy-load configuration
        config = self._ensure_config_loaded()

        # Skip if baggage is disabled
        if not config.enabled:
            await self.app(scope, receive, send)
            return

        baggage_token = None
        try:
            # Extract headers from ASGI scope
            headers = self._extract_headers_from_scope(scope)

            # Extract existing upstream baggage
            existing_baggage = self._extract_existing_baggage(headers, config)

            # Extract baggage from configured headers
            header_baggage = extract_baggage_from_headers(headers, config)

            # Merge header-derived and existing baggage
            merged_baggage = merge_baggage(header_baggage, existing_baggage)

            # Set baggage in OpenTelemetry context
            if merged_baggage:
                baggage_token = self._set_baggage_in_context(merged_baggage)
                logger.debug(f"Set {len(merged_baggage)} baggage entries in context " f"({len(header_baggage)} from headers, {len(existing_baggage)} from upstream)")

        except Exception as e:
            # Log error but don't fail the request
            logger.error(f"Baggage middleware error: {e}", exc_info=True)

        try:
            await self.app(scope, receive, send)
        finally:
            if baggage_token is not None and otel_detach is not None:
                otel_detach(baggage_token)
