# -*- coding: utf-8 -*-
"""
Location: ./mcpgateway/services/metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

MCP Gateway Metrics Service.

This module provides comprehensive Prometheus metrics instrumentation for the MCP Gateway.
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
- ENABLE_METRICS: Enable/disable metrics collection (default: "true")
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
import os
import re

# Third-Party
from fastapi import Response, status
from prometheus_client import Gauge, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

# First-Party
from mcpgateway.config import settings


def setup_metrics(app):
    """
    Configure Prometheus metrics instrumentation for a FastAPI application.

    This function sets up comprehensive HTTP metrics collection including request counts,
    latencies, and payload sizes. It also handles custom application labels and endpoint
    exclusion patterns.

    Args:
        app: FastAPI application instance to instrument

    Environment Variables Used:
        ENABLE_METRICS (str): "true" to enable metrics, "false" to disable (default: "true")
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
    enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"

    if enable_metrics:
        # Detect database engine from DATABASE_URL
        database_url = settings.database_url.lower()
        if database_url.startswith("mysql+pymysql://") or "mariadb" in database_url:
            db_engine = "mariadb"
        elif database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
            db_engine = "postgresql"
        elif database_url.startswith("sqlite://"):
            db_engine = "sqlite"
        elif database_url.startswith("mongodb://"):
            db_engine = "mongodb"
        else:
            db_engine = "unknown"

        # Custom labels gauge with automatic database engine detection
        custom_labels = dict(kv.split("=") for kv in os.getenv("METRICS_CUSTOM_LABELS", "").split(",") if "=" in kv)

        # Always include database engine in metrics
        custom_labels["engine"] = db_engine

        if custom_labels:
            app_info_gauge = Gauge(
                "app_info",
                "Static labels for the application",
                labelnames=list(custom_labels.keys()),
                registry=REGISTRY,
            )
            app_info_gauge.labels(**custom_labels).set(1)

        excluded = [pattern.strip() for pattern in (settings.METRICS_EXCLUDED_HANDLERS or "").split(",") if pattern.strip()]

        # Add database metrics gauge
        db_info_gauge = Gauge(
            "database_info",
            "Database engine information",
            labelnames=["engine", "url_scheme"],
            registry=REGISTRY,
        )

        # Extract URL scheme for additional context
        url_scheme = database_url.split("://", maxsplit=1)[0] if "://" in database_url else "unknown"
        db_info_gauge.labels(engine=db_engine, url_scheme=url_scheme).set(1)

        # Create instrumentator instance
        instrumentator = Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=[re.compile(p) for p in excluded],
        )

        # Instrument FastAPI app
        instrumentator.instrument(app)

        # Expose Prometheus metrics at /metrics/prometheus and include
        # the endpoint in the OpenAPI schema so it appears in Swagger UI.
        instrumentator.expose(app, endpoint="/metrics/prometheus", include_in_schema=True, should_gzip=True)

        print("✅ Metrics instrumentation enabled")
    else:
        print("⚠️ Metrics instrumentation disabled")

        @app.get("/metrics/prometheus")
        async def metrics_disabled():
            """Returns metrics response when metrics collection is disabled.

            Returns:
                Response: HTTP 503 response indicating metrics are disabled.
            """
            return Response(content='{"error": "Metrics collection is disabled"}', media_type="application/json", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
