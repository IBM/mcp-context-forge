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

import os
import re
from prometheus_client import REGISTRY, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from mcpgateway.config import settings


def setup_metrics(app):
    """Configure Prometheus metrics instrumentation for FastAPI application.
    
    Sets up HTTP request metrics including:
    - Request count by method, endpoint, and status code
    - Request duration histograms
    - Request/response size metrics
    - Custom application info gauge with labels
    
    Args:
        app: FastAPI application instance to instrument
        
    Environment Variables:
        ENABLE_METRICS: Set to "false" to disable metrics (default: "true")
        METRICS_EXCLUDED_HANDLERS: Comma-separated regex patterns for endpoints to exclude
        METRICS_CUSTOM_LABELS: Custom labels for app_info gauge
    """
    enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    excluded_regex = os.getenv("METRICS_EXCLUDED_HANDLERS", "")
    excluded_patterns = [p.strip() for p in excluded_regex.split(",") if p.strip()]

    def excluded_handler(req):
        """Check if request should be excluded from metrics.
        
        Args:
            req: HTTP request object
            
        Returns:
            bool: True if request matches any exclusion pattern
        """
        return any(re.match(pat, req.url.path) for pat in excluded_patterns)

    if enable_metrics:
        # Parse custom labels from env
        custom_labels = dict(
            kv.split("=") for kv in os.getenv("METRICS_CUSTOM_LABELS", "").split(",") if "=" in kv
        )

        # Expose a custom gauge with labels (useful for dashboard filtering)
        if custom_labels:
            app_info_gauge = Gauge(
                "app_info",
                "Static labels for the application",
                labelnames=list(custom_labels.keys()),
                registry=REGISTRY,
            )
            app_info_gauge.labels(**custom_labels).set(1)
        
        excluded = [pattern.strip() for pattern in (settings.METRICS_EXCLUDED_HANDLERS or "").split(",") if pattern.strip()]

        instrumentator = Instrumentator(
            should_group_status_codes=False,
            should_ignore_untemplated=True,
            excluded_handlers=[re.compile(p) for p in excluded],
        )

        instrumentator.instrument(app)
        instrumentator.expose(app, include_in_schema=False, should_gzip=True)
        print("✅ Metrics instrumentation enabled")

