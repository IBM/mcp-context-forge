# -*- coding: utf-8 -*-
"""
Location: ./mcpgateway/services/metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

ContextForge Metrics Service.

This module provides comprehensive Prometheus metrics instrumentation for ContextForge.
It configures and exposes HTTP metrics including request counts, latencies, response sizes,
and custom application metrics.

The service automatically instruments FastAPI applications with standard HTTP metrics
and provides configurable exclusion patterns for endpoints that should not be monitored.
Metrics are exposed at the `/metrics/prometheus` endpoint in Prometheus format.

Supported Metrics:
- http_requests_total: Counter for total HTTP requests by method, endpoint, and status
- http_request_duration_seconds: Histogram of request processing times
- http_request_size_bytes: Histogram of incoming request payload sizes
- http_response_size_bytes: Histogram of outgoing response payload sizes
- app_info: Gauge with custom static labels for application metadata

Environment Variables:
- ENABLE_METRICS: Enable/disable metrics collection (default: "false")
- METRICS_EXCLUDED_HANDLERS: Comma-separated regex patterns for excluded endpoints
- METRICS_CUSTOM_LABELS: Custom labels for app_info gauge (format: "key1=value1,key2=value2")

Usage:
    from mcpgateway.services.metrics import setup_metrics

    app = FastAPI()
    setup_metrics(app)  # Automatically instruments the app

    # Metrics available at: GET /metrics/prometheus

Functions:
- setup_metrics: Configure Prometheus instrumentation for FastAPI app
"""

# Standard
import gzip
import os
import re

# Third-Party
from fastapi import Depends, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

# First-Party
from mcpgateway.config import settings


def _get_registry_collector(metric_name: str):
    """Best-effort lookup for a registered collector by metric name.

    Prometheus client's public API does not expose a lookup helper, and tests
    may instantiate multiple apps in the same process. We use a guarded access
    to the internal registry mapping to avoid duplicate registrations.

    Args:
        metric_name (str): Metric name to look up.

    Returns:
        Any: Registered collector for the metric name, if available.
    """

    names_to_collectors = getattr(REGISTRY, "_names_to_collectors", None)
    if not isinstance(names_to_collectors, dict):
        return None
    return names_to_collectors.get(metric_name)


# Global Metrics
# Exposed for import by services/plugins to increment counters
tool_timeout_counter = Counter(
    "tool_timeout_total",
    "Total number of tool invocation timeouts",
    ["tool_name"],
)

circuit_breaker_open_counter = Counter(
    "circuit_breaker_open_total",
    "Total number of times circuit breaker opened",
    ["tool_name"],
)

password_reset_requests_counter = Counter(
    "password_reset_requests_total",
    "Total number of password reset requests",
    ["outcome"],
)

password_reset_completions_counter = Counter(
    "password_reset_completions_total",
    "Total number of password reset completion attempts",
    ["outcome"],
)

# Content Security Metrics (US-2)
content_size_violations_counter = Counter(
    "content_size_violations_total",
    "Total number of content size limit violations",
    ["content_type"],  # "resource" or "prompt"
)

content_type_violations_counter = Counter(
    "content_type_violations_total",
    "Total number of MIME type violations",
    ["content_type"],  # "resource" or "prompt" — rejected type is in logs, not labels (unbounded cardinality)
)

# MCP Auth Cache Metrics
mcp_auth_cache_events_counter = Counter(
    "mcp_auth_cache_events_total",
    "Total number of MCP auth cache events by outcome",
    ["outcome"],
)

# OAuth / JWKS access-token verification on oauth_enabled virtual servers.
# Outcome labels:
#   success          — IdP-issued token verified and user context populated
#   failed           — verification attempted and rejected (401/503 emitted)
#   not_applicable   — target server is not oauth_enabled, issuer outside the
#                      allowlist, token undecodable, or URL path missing a
#                      server id; caller falls through to internal verify
oauth_verify_events_counter = Counter(
    "oauth_verify_events_total",
    "OAuth access token verification outcomes on virtual server MCP endpoints",
    ["outcome"],
)

# Streamable HTTP GET rejections (#4205). Clients that probe a passive SSE
# stream before `initialize` (or against a stateless gateway) are 405'd with
# `Allow: POST, DELETE`. Outcome labels mirror the Rust runtime's counter
# split so ops can distinguish client-side from deployment-config causes:
#   no_session_id           — client didn't present `Mcp-Session-Id`
#   stateful_disabled       — this gateway runs with `use_stateful_sessions=False`
transport_get_rejected_counter = Counter(
    "transport_get_rejected_total",
    "GET /mcp 405 rejections by reason (no session anchor available)",
    ["outcome"],
)


def setup_metrics(app):
    """
    Configure Prometheus metrics instrumentation for a FastAPI application.

    This function sets up comprehensive HTTP metrics collection including request counts,
    latencies, and payload sizes. It also handles custom application labels and endpoint
    exclusion patterns.

    Args:
        app: FastAPI application instance to instrument

    Environment Variables Used:
        ENABLE_METRICS (str): "true" to enable metrics, "false" to disable (default: "false")
        METRICS_EXCLUDED_HANDLERS (str): Comma-separated regex patterns for endpoints
                                        to exclude from metrics collection
        METRICS_CUSTOM_LABELS (str): Custom labels in "key1=value1,key2=value2" format
                                   for the app_info gauge metric

    Side Effects:
        - Registers Prometheus metrics collectors with the global registry
        - Adds middleware to the FastAPI app for request instrumentation
        - Exposes /metrics/prometheus endpoint for Prometheus scraping
        - Prints status messages to stdout

    Example:
        >>> from fastapi import FastAPI
        >>> from mcpgateway.services.metrics import setup_metrics
        >>> app = FastAPI()
        >>> # setup_metrics(app)  # Configures Prometheus metrics
        >>> # Metrics available at GET /metrics/prometheus
    """
    enable_metrics = settings.ENABLE_METRICS

    if enable_metrics:
        # Detect database engine from DATABASE_URL
        database_url = settings.database_url.lower()
        if database_url.startswith(("postgresql", "postgres://")):
            db_engine = "postgresql"
        elif database_url.startswith("sqlite"):
            db_engine = "sqlite"
        else:
            db_engine = "unknown"

        # Custom labels gauge with automatic database engine detection
        # NOTE: setup_metrics may be invoked multiple times in a single process
        # (tests instantiate multiple FastAPI apps). Prometheus client registries
        # do not allow registering the same metric name twice, so we must re-use
        # an existing collector when present.
        custom_labels = dict(kv.split("=") for kv in os.getenv("METRICS_CUSTOM_LABELS", "").split(",") if "=" in kv)

        # Always include database engine in metrics
        custom_labels["engine"] = db_engine

        # Use a deterministic label order for stable registration.
        # Keep `engine` first, then any custom labels sorted.
        extra_label_names = sorted(label for label in custom_labels.keys() if label != "engine")
        desired_label_names = ["engine", *extra_label_names]

        app_info_gauge = _get_registry_collector("app_info")
        if app_info_gauge is None:
            try:
                app_info_gauge = Gauge(
                    "app_info",
                    "Static labels for the application",
                    labelnames=desired_label_names,
                    registry=REGISTRY,
                )
            except ValueError:
                # Another test/app instance registered it first; reuse it.
                app_info_gauge = _get_registry_collector("app_info")

        if app_info_gauge is not None:
            labelnames = getattr(app_info_gauge, "_labelnames", ())
            if labelnames:
                labels = {name: custom_labels.get(name, "") for name in labelnames}
                app_info_gauge.labels(**labels).set(1)
            else:
                app_info_gauge.set(1)

        excluded = [pattern.strip() for pattern in (settings.METRICS_EXCLUDED_HANDLERS or "").split(",") if pattern.strip()]

        # Add database metrics gauge
        db_info_gauge = _get_registry_collector("database_info")
        if db_info_gauge is None:
            try:
                db_info_gauge = Gauge(
                    "database_info",
                    "Database engine information",
                    labelnames=["engine", "url_scheme"],
                    registry=REGISTRY,
                )
            except ValueError:
                db_info_gauge = _get_registry_collector("database_info")

        # Extract URL scheme for additional context
        url_scheme = database_url.split("://", maxsplit=1)[0] if "://" in database_url else "unknown"
        if db_info_gauge is not None:
            db_info_gauge.labels(engine=db_engine, url_scheme=url_scheme).set(1)

        # Add HTTP connection pool metrics with lazy initialization
        # These gauges are updated from app lifespan after SharedHttpClient is ready
        http_pool_max_connections = _get_registry_collector("http_pool_max_connections")
        if http_pool_max_connections is None:
            try:
                http_pool_max_connections = Gauge(
                    "http_pool_max_connections",
                    "Maximum allowed HTTP connections in the pool",
                    registry=REGISTRY,
                )
            except ValueError:
                http_pool_max_connections = _get_registry_collector("http_pool_max_connections")

        http_pool_max_keepalive = _get_registry_collector("http_pool_max_keepalive_connections")
        if http_pool_max_keepalive is None:
            try:
                http_pool_max_keepalive = Gauge(
                    "http_pool_max_keepalive_connections",
                    "Maximum idle keepalive connections to retain",
                    registry=REGISTRY,
                )
            except ValueError:
                http_pool_max_keepalive = _get_registry_collector("http_pool_max_keepalive_connections")

        # Store update function as a module-level attribute so it can be called
        # from the application lifespan after SharedHttpClient is initialized
        def update_http_pool_metrics():
            """Update HTTP connection pool metrics from SharedHttpClient stats."""
            try:
                # First-Party
                from mcpgateway.services.http_client_service import SharedHttpClient  # pylint: disable=import-outside-toplevel

                # Only update if client is initialized
                if SharedHttpClient._instance and SharedHttpClient._instance._initialized:  # pylint: disable=protected-access
                    stats = SharedHttpClient._instance.get_pool_stats()  # pylint: disable=protected-access
                    if http_pool_max_connections is not None:
                        http_pool_max_connections.set(stats.get("max_connections", 0))
                    if http_pool_max_keepalive is not None:
                        http_pool_max_keepalive.set(stats.get("max_keepalive", 0))
                    # Note: httpx doesn't expose current connection count, only limits
            except Exception:  # nosec B110
                pass  # Silently skip if client not initialized or error occurs

        # Make the update function available at module level for lifespan calls
        app.state.update_http_pool_metrics = update_http_pool_metrics

        # Create instrumentator instance
        instrumentator = Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=[re.compile(p) for p in excluded],
        )

        # Instrument FastAPI app
        instrumentator.instrument(app)

        # Expose Prometheus metrics at /metrics/prometheus with auth.
        # We define the endpoint manually (instead of instrumentator.expose)
        # so we can gate it behind require_auth.
        # First-Party
        from mcpgateway.utils.verify_credentials import require_auth

        @app.get("/metrics/prometheus", include_in_schema=True, tags=["Metrics"])
        def prometheus_metrics(request: Request, _user=Depends(require_auth)):
            """Prometheus metrics endpoint (requires authentication).

            Args:
                request: The incoming HTTP request (used to check Accept-Encoding).
                _user: Authenticated user from require_auth dependency.

            Returns:
                Response: Prometheus metrics in text exposition format.
            """
            registry = REGISTRY
            if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
                # Third-Party
                from prometheus_client import CollectorRegistry, multiprocess

                registry = CollectorRegistry()
                multiprocess.MultiProcessCollector(registry)
            if "gzip" in request.headers.get("Accept-Encoding", ""):
                resp = Response(content=gzip.compress(generate_latest(registry)))
                resp.headers["Content-Type"] = CONTENT_TYPE_LATEST
                resp.headers["Content-Encoding"] = "gzip"
            else:
                resp = Response(content=generate_latest(registry))
                resp.headers["Content-Type"] = CONTENT_TYPE_LATEST
            return resp

        print("✅ Metrics instrumentation enabled")
    else:
        print("⚠️ Metrics instrumentation disabled")

        # First-Party
        from mcpgateway.utils.verify_credentials import require_auth

        @app.get("/metrics/prometheus", tags=["Metrics"])
        async def metrics_disabled(_user=Depends(require_auth)):  # pylint: disable=unused-argument
            """Returns 503 when metrics collection is disabled (requires authentication).

            Args:
                _user: Authenticated user from require_auth dependency.

            Returns:
                Response: HTTP 503 response indicating metrics are disabled.
            """
            return Response(content='{"error": "Metrics collection is disabled"}', media_type="application/json", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
