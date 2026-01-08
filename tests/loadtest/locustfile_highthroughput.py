# -*- coding: utf-8 -*-
"""High-throughput Locust load test for maximum RPS.

This locustfile is optimized for achieving 1000+ RPS by:
1. Focusing on fast endpoints only (health, tools, servers)
2. Minimizing wait times between requests
3. Avoiding slow endpoints (admin UI, external MCP calls)

Usage:
    locust -f tests/loadtest/locustfile_highthroughput.py --host=http://localhost:8080 \
        --users=1000 --spawn-rate=100 --run-time=3m --headless

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from locust import constant_throughput, events, tag, task
from locust.contrib.fasthttp import FastHttpUser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_env_file() -> dict[str, str]:
    """Load environment variables from .env file.

    Returns:
        Dictionary of environment variable key-value pairs.
    """
    env_vars: dict[str, str] = {}
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.cwd().parent.parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for path in search_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"\'')
                        env_vars[key] = value
            break
    return env_vars


_ENV_FILE_VARS = _load_env_file()


def _get_config(key: str, default: str = "") -> str:
    """Get configuration value from environment or .env file.

    Args:
        key: Configuration key name.
        default: Default value if key not found.

    Returns:
        Configuration value or default.
    """
    return os.environ.get(key) or _ENV_FILE_VARS.get(key) or default


# JWT Configuration
JWT_SECRET_KEY = _get_config("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = _get_config("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _get_config("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _get_config("JWT_ISSUER", "mcpgateway")
JWT_USERNAME = _get_config("PLATFORM_ADMIN_EMAIL", "admin@example.com")

_CACHED_TOKEN: str | None = None


def _generate_jwt_token() -> str:
    """Generate JWT token for authentication.

    Returns:
        JWT token string, or empty string on failure.
    """
    try:
        import jwt  # pylint: disable=import-outside-toplevel

        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    except Exception as e:
        logger.warning("Failed to generate JWT: %s", e)
        return ""


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers with cached JWT token.

    Returns:
        Dictionary of HTTP headers for authentication.
    """
    global _CACHED_TOKEN  # pylint: disable=global-statement
    if _CACHED_TOKEN is None:
        _CACHED_TOKEN = _generate_jwt_token()
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {_CACHED_TOKEN}",
    }


@events.test_stop.add_listener
def on_test_stop(environment: Any, **_kwargs: Any) -> None:
    """Print summary statistics when test stops.

    Args:
        environment: Locust environment object containing stats.
        **_kwargs: Additional keyword arguments (unused).
    """
    stats = environment.stats
    if not stats.entries:
        return

    print("\n" + "=" * 80)
    print("HIGH-THROUGHPUT LOAD TEST SUMMARY")
    print("=" * 80)

    total_rps = stats.total.total_rps
    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0

    print(f"\n  Total Requests:  {total_requests:,}")
    print(f"  Total Failures:  {total_failures:,} ({failure_rate:.2f}%)")
    print(f"  RPS:             {total_rps:.2f}")

    if total_requests > 0:
        print("\n  Response Times (ms):")
        print(f"    Average: {stats.total.avg_response_time:.2f}")
        print(f"    Median:  {stats.total.get_response_time_percentile(0.50):.2f}")
        print(f"    p95:     {stats.total.get_response_time_percentile(0.95):.2f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):.2f}")

    print("=" * 80 + "\n")


class HighThroughputUser(FastHttpUser):
    """High-throughput user for maximum RPS testing.

    Uses FastHttpUser (gevent-based) and constant_throughput for predictable load.
    Focuses on fast, read-only endpoints.

    Target RPS per user. With 4000 users:
      constant_throughput(1)  =  4,000 RPS
      constant_throughput(2)  =  8,000 RPS
      constant_throughput(5)  = 20,000 RPS
    Start low and increase based on server/client capacity.
    """

    # 2 requests/second per user for predictable throughput
    wait_time = constant_throughput(2)

    # Connection tuning for high concurrency
    connection_timeout = 30.0
    network_timeout = 30.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize user with auth headers attribute.

        Args:
            *args: Positional arguments passed to parent HttpUser.
            **kwargs: Keyword arguments passed to parent HttpUser.
        """
        super().__init__(*args, **kwargs)
        self.auth_headers: dict[str, str] = {}

    def on_start(self) -> None:
        """Initialize authentication on user start."""
        self.auth_headers = _get_auth_headers()

    def _validate_response(self, response: Any, expected_type: str = "json") -> bool:
        """Validate response is successful and contains expected content.

        Args:
            response: HTTP response object from catch_response context.
            expected_type: Expected content type ("json" or other).

        Returns:
            True if validation passed, False otherwise.
        """
        if response.status_code != 200:
            response.failure(f"Expected 200, got {response.status_code}")
            return False
        if expected_type == "json":
            try:
                data = response.json()
                if data is None:
                    response.failure("Response JSON is null")
                    return False
            except Exception as e:
                response.failure(f"Invalid JSON: {e}")
                return False
        response.success()
        return True

    @task(30)
    @tag("fast", "health")
    def health_check(self) -> None:
        """Health endpoint - no auth, fastest."""
        with self.client.get("/health", name="/health", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Health check failed: {response.status_code}")
            else:
                response.success()

    @task(25)
    @tag("fast", "api")
    def list_tools(self) -> None:
        """List tools - fast DB query."""
        with self.client.get("/tools", headers=self.auth_headers, name="/tools", catch_response=True) as response:
            self._validate_response(response)

    @task(20)
    @tag("fast", "api")
    def list_servers(self) -> None:
        """List servers - fast DB query."""
        with self.client.get("/servers", headers=self.auth_headers, name="/servers", catch_response=True) as response:
            self._validate_response(response)

    @task(15)
    @tag("fast", "api")
    def list_gateways(self) -> None:
        """List gateways - fast DB query."""
        with self.client.get("/gateways", headers=self.auth_headers, name="/gateways", catch_response=True) as response:
            self._validate_response(response)

    @task(10)
    @tag("fast", "api")
    def list_resources(self) -> None:
        """List resources."""
        with self.client.get("/resources", headers=self.auth_headers, name="/resources", catch_response=True) as response:
            self._validate_response(response)

    @task(10)
    @tag("fast", "api")
    def list_prompts(self) -> None:
        """List prompts."""
        with self.client.get("/prompts", headers=self.auth_headers, name="/prompts", catch_response=True) as response:
            self._validate_response(response)

    @task(5)
    @tag("fast", "api")
    def list_tags(self) -> None:
        """List tags."""
        with self.client.get("/tags", headers=self.auth_headers, name="/tags", catch_response=True) as response:
            self._validate_response(response)

    @task(5)
    @tag("fast", "api")
    def openapi_schema(self) -> None:
        """OpenAPI schema - cached."""
        with self.client.get("/openapi.json", headers=self.auth_headers, name="/openapi.json", catch_response=True) as response:
            self._validate_response(response)
