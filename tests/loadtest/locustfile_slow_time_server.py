# -*- coding: utf-8 -*-
"""Load testing for slow-time-server via MCP Gateway.

This module tests the slow-time-server through the gateway to validate
timeout enforcement, circuit breaker behaviour, session pool resilience,
and load testing under realistic slow-tool conditions.

User Classes:
- SlowTimeUser: Normal latency testing (get_slow_time with 2s delay)
- TimeoutStormUser: All users hit tools with delays exceeding timeout
- MixedLatencyUser: Mix of instant, slow, and timeout tools
- CircuitBreakerUser: Exercises get_flaky_time for circuit breaker testing

Default Parameters:
- Users: 10
- Spawn rate: 2/s
- Run time: 120s
- Host: http://localhost:8080  (via nginx proxy)

Usage:
    # Via gateway (through nginx)
    locust -f locustfile_slow_time_server.py --host=http://localhost:8080

    # Direct to slow-time-server REST API
    locust -f locustfile_slow_time_server.py --host=http://localhost:8081

    # Headless with specific scenario
    locust -f locustfile_slow_time_server.py \
           --host=http://localhost:8080 \
           --users=10 --spawn-rate=2 --run-time=120s --headless

Environment Variables:
    MCPGATEWAY_BEARER_TOKEN: JWT token for gateway auth
    SLOW_TIME_DELAY: Default delay for slow tools (default: 2)
    SLOW_TIME_GATEWAY_ID: Gateway ID for slow_time_server

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import json
import logging
import os
import random
import uuid

from locust import HttpUser, between, events, tag, task
from locust.runners import MasterRunner, WorkerRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Default Test Parameters
# =============================================================================


@events.init_command_line_parser.add_listener
def set_defaults(parser):
    """Set default values for the Locust web UI."""
    parser.set_defaults(users=10, spawn_rate=2, run_time="120s", host="http://localhost:8080")


# =============================================================================
# Configuration
# =============================================================================

BEARER_TOKEN = os.environ.get("MCPGATEWAY_BEARER_TOKEN", "")
SLOW_TIME_DELAY = float(os.environ.get("SLOW_TIME_DELAY", "2"))

TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
]


# =============================================================================
# Event Handlers
# =============================================================================


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test configuration at start."""
    if isinstance(environment.runner, (MasterRunner, WorkerRunner)):
        return
    logger.info("=" * 60)
    logger.info("SLOW TIME SERVER LOAD TEST")
    logger.info("=" * 60)
    logger.info(f"  Host: {environment.host}")
    logger.info(f"  Default delay: {SLOW_TIME_DELAY}s")
    logger.info(f"  Auth: {'configured' if BEARER_TOKEN else 'NOT configured'}")
    logger.info("=" * 60)


# =============================================================================
# Helper: Build auth headers
# =============================================================================


def auth_headers():
    """Return headers with Authorization if token is set."""
    headers = {"Content-Type": "application/json"}
    if BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"
    return headers


# =============================================================================
# Scenario 1: Gradual Ramp-Up (normal slow tools)
# =============================================================================


class SlowTimeUser(HttpUser):
    """Tests get_slow_time with configurable delay through the REST API.

    This scenario simulates normal usage with slow tools.
    """

    weight = 10
    wait_time = between(1, 3)

    @tag("slow", "rest")
    @task(5)
    def get_slow_time_rest(self):
        """Call slow time via REST API."""
        tz = random.choice(TIMEZONES)
        self.client.get(
            f"/api/v1/time?timezone={tz}&delay={SLOW_TIME_DELAY}",
            headers=auth_headers(),
            name="/api/v1/time [slow]",
        )

    @tag("instant", "rest")
    @task(3)
    def get_config(self):
        """Check server configuration."""
        self.client.get(
            "/api/v1/config",
            headers=auth_headers(),
            name="/api/v1/config",
        )

    @tag("instant", "rest")
    @task(2)
    def get_stats(self):
        """Check server statistics."""
        self.client.get(
            "/api/v1/stats",
            headers=auth_headers(),
            name="/api/v1/stats",
        )

    @tag("health")
    @task(1)
    def health_check(self):
        """Health check (always instant)."""
        self.client.get("/health", name="/health")


# =============================================================================
# Scenario 2: Timeout Storm (all requests exceed timeout)
# =============================================================================


class TimeoutStormUser(HttpUser):
    """Sends requests with very long delays to stress timeout handling.

    All requests use delay=120s which should exceed any reasonable timeout.
    """

    weight = 1
    wait_time = between(2, 5)

    @tag("timeout", "rest")
    @task
    def get_timeout_time(self):
        """Call time with extreme delay (should timeout)."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/time?timezone={tz}&delay=120",
            headers=auth_headers(),
            name="/api/v1/time [timeout]",
            catch_response=True,
        ) as response:
            # Timeouts and 504s are expected behaviour
            if response.status_code in (504, 502, 408, 499):
                response.success()
            elif response.elapsed.total_seconds() > 60:
                response.success()


# =============================================================================
# Scenario 3: Mixed Latency (instant + slow + timeout)
# =============================================================================


class MixedLatencyUser(HttpUser):
    """Mixes instant, slow, and extreme-delay requests.

    Tests per-tool timeout_ms overrides and mixed-latency scenarios.
    """

    weight = 5
    wait_time = between(1, 3)

    @tag("instant", "rest")
    @task(5)
    def get_instant_time(self):
        """Call with zero delay (baseline)."""
        tz = random.choice(TIMEZONES)
        self.client.get(
            f"/api/v1/time?timezone={tz}&delay=0",
            headers=auth_headers(),
            name="/api/v1/time [instant]",
        )

    @tag("slow", "rest")
    @task(3)
    def get_slow_time(self):
        """Call with moderate delay."""
        tz = random.choice(TIMEZONES)
        delay = random.uniform(1, 5)
        self.client.get(
            f"/api/v1/time?timezone={tz}&delay={delay:.1f}",
            headers=auth_headers(),
            name="/api/v1/time [slow-mixed]",
        )

    @tag("timeout", "rest")
    @task(1)
    def get_timeout_time(self):
        """Call with extreme delay."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/time?timezone={tz}&delay=300",
            headers=auth_headers(),
            name="/api/v1/time [timeout-mixed]",
            catch_response=True,
        ) as response:
            if response.status_code in (504, 502, 408, 499):
                response.success()

    @tag("health")
    @task(1)
    def health_check(self):
        """Health check (always instant)."""
        self.client.get("/health", name="/health")


# =============================================================================
# Scenario 4: Circuit Breaker Exercise
# =============================================================================


class CircuitBreakerUser(HttpUser):
    """Exercises the flaky endpoint to test circuit breaker behaviour.

    Sends rapid requests to an endpoint with configurable failure rate.
    Expects the circuit breaker to eventually open.
    """

    weight = 2
    wait_time = between(0.5, 1.5)

    @tag("flaky", "rest")
    @task(8)
    def get_flaky_time(self):
        """Call slow time - some will fail based on server's failure_rate."""
        tz = random.choice(TIMEZONES)
        with self.client.get(
            f"/api/v1/time?timezone={tz}&delay={SLOW_TIME_DELAY}",
            headers=auth_headers(),
            name="/api/v1/time [flaky]",
            catch_response=True,
        ) as response:
            # 5xx errors from circuit breaker are expected
            if response.status_code in (503, 502, 504):
                response.success()

    @tag("echo", "rest")
    @task(2)
    def echo_test(self):
        """Echo test to verify server is still responding."""
        self.client.get(
            "/api/v1/test/echo?message=circuit-breaker-test",
            headers=auth_headers(),
            name="/api/v1/test/echo",
        )
