# -*- coding: utf-8 -*-
"""
Location: ./mcpgateway/services/metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

MCP Gateway Metrics Service.

This module provides Prometheus metrics instrumentation for the MCP Gateway.
It configures and exposes HTTP metrics including request counts, latencies,
and response sizes.

Environment Variables:
- ENABLE_METRICS: Enable/disable metrics collection (default: "true")
- METRICS_EXCLUDED_HANDLERS: Comma-separated regex patterns for excluded endpoints
- METRICS_CUSTOM_LABELS: Custom labels for app_info gauge (format: "key1=value1,key2=value2")

Functions:
- setup_metrics: Configure Prometheus instrumentation for FastAPI app
"""

# Standard
import os
import re

# Third-Party
from prometheus_client import Counter, Gauge, Histogram, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

# First-Party
from mcpgateway.config import settings


def setup_metrics(app):
    enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    [p.strip() for p in os.getenv("METRICS_EXCLUDED_HANDLERS", "").split(",") if p.strip()]

    if enable_metrics:

        http_requests_total = Counter(
            "http_requests_total",
            "Total number of HTTP requests",
            labelnames=("method", "endpoint", "status_code"),
        )

        http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "Histogram of HTTP request durations",
            labelnames=("method", "endpoint"),
            buckets=(0.05, 0.1, 0.3, 1, 3, 5),
        )

        http_request_size_bytes = Histogram(
            "http_request_size_bytes",
            "Histogram of HTTP request sizes",
            labelnames=("method", "endpoint"),
            buckets=(100, 500, 1000, 5000, 10000),
        )

        http_response_size_bytes = Histogram(
            "http_response_size_bytes",
            "Histogram of HTTP response sizes",
            labelnames=("method", "endpoint"),
            buckets=(100, 500, 1000, 5000, 10000),
        )

        # Add metrics to instrumentator
        instrumentator = Instrumentator()
        instrumentator.add(http_requests_total)
        instrumentator.add(http_request_duration_seconds)
        instrumentator.add(http_request_size_bytes)
        instrumentator.add(http_response_size_bytes)

        # Custom labels gauge
        custom_labels = dict(kv.split("=") for kv in os.getenv("METRICS_CUSTOM_LABELS", "").split(",") if "=" in kv)
        if custom_labels:
            app_info_gauge = Gauge(
                "app_info",
                "Static labels for the application",
                labelnames=list(custom_labels.keys()),
                registry=REGISTRY,
            )
            app_info_gauge.labels(**custom_labels).set(1)

        excluded = [pattern.strip() for pattern in (settings.METRICS_EXCLUDED_HANDLERS or "").split(",") if pattern.strip()]

        # Create a single Instrumentator instance
        instrumentator = Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=[re.compile(p) for p in excluded],
        )

        # Instrument FastAPI app
        instrumentator.instrument(app)

        # Expose Prometheus metrics at /metrics/prometheus
        instrumentator.expose(app, endpoint="/metrics/prometheus", include_in_schema=False, should_gzip=True)

        print("✅ Metrics instrumentation enabled")


# def setup_metrics(app):
#     """Configure Prometheus metrics instrumentation for FastAPI application.

#     Sets up HTTP request metrics including:
#     - Request count by method, endpoint, and status code
#     - Request duration histograms
#     - Request/response size metrics
#     - Custom application info gauge with labels

#     Args:
#         app: FastAPI application instance to instrument

#     Environment Variables:
#         ENABLE_METRICS: Set to "false" to disable metrics (default: "true")
#         METRICS_EXCLUDED_HANDLERS: Comma-separated regex patterns for endpoints to exclude
#         METRICS_CUSTOM_LABELS: Custom labels for app_info gauge
#     """
#     enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"
#     excluded_regex = os.getenv("METRICS_EXCLUDED_HANDLERS", "")
#     excluded_patterns = [p.strip() for p in excluded_regex.split(",") if p.strip()]

#     def excluded_handler(req):
#         """Check if request should be excluded from metrics.

#         Args:
#             req: HTTP request object

#         Returns:
#             bool: True if request matches any exclusion pattern
#         """
#         return any(re.match(pat, req.url.path) for pat in excluded_patterns)

#     if enable_metrics:
#         # Parse custom labels from env
#         custom_labels = dict(kv.split("=") for kv in os.getenv("METRICS_CUSTOM_LABELS", "").split(",") if "=" in kv)

#         # Expose a custom gauge with labels (useful for dashboard filtering)
#         if custom_labels:
#             app_info_gauge = Gauge(
#                 "app_info",
#                 "Static labels for the application",
#                 labelnames=list(custom_labels.keys()),
#                 registry=REGISTRY,
#             )
#             app_info_gauge.labels(**custom_labels).set(1)

#         excluded = [pattern.strip() for pattern in (settings.METRICS_EXCLUDED_HANDLERS or "").split(",") if pattern.strip()]

#         instrumentator = Instrumentator(
#             should_group_status_codes=False,
#             should_ignore_untemplated=True,
#             excluded_handlers=[re.compile(p) for p in excluded],
#         )

#         custom_duration_histogram = Histogram(
#             "http_request_duration_seconds",
#             "Request latency",
#             buckets=(0.05, 0.1, 0.3, 1, 3, 5),
#             labelnames=("handler", "method"),
#         )

#         instrumentator.add(custom_duration_histogram)

#         instrumentator = Instrumentator(
#             should_group_status_codes=False,
#             should_ignore_untemplated=True,
#             excluded_handlers=[re.compile(p) for p in excluded],
#         )

#         instrumentator.instrument(app)
#         #instrumentator.expose(app, include_in_schema=False, should_gzip=True)
#         instrumentator.expose(app, endpoint="/metrics/prometheus", include_in_schema=False, should_gzip=True)

#         print("✅ Metrics instrumentation enabled")
