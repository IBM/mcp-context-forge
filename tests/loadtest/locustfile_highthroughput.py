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

from locust import between, events, HttpUser, tag, task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_env_file() -> dict[str, str]:
    """Load environment variables from .env file."""
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
    return os.environ.get(key) or _ENV_FILE_VARS.get(key) or default


# JWT Configuration
JWT_SECRET_KEY = _get_config("JWT_SECRET_KEY", "my-test-key")
JWT_ALGORITHM = _get_config("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = _get_config("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = _get_config("JWT_ISSUER", "mcpgateway")
JWT_USERNAME = _get_config("PLATFORM_ADMIN_EMAIL", "admin@example.com")

_CACHED_TOKEN: str | None = None


def _generate_jwt_token() -> str:
    """Generate JWT token for authentication."""
    try:
        import jwt
        payload = {
            "sub": JWT_USERNAME,
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
            "iat": datetime.now(timezone.utc),
            "aud": JWT_AUDIENCE,
            "iss": JWT_ISSUER,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    except Exception as e:
        logger.warning(f"Failed to generate JWT: {e}")
        return ""


def _get_auth_headers() -> dict[str, str]:
    """Get authentication headers."""
    global _CACHED_TOKEN
    if _CACHED_TOKEN is None:
        _CACHED_TOKEN = _generate_jwt_token()
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {_CACHED_TOKEN}",
    }


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary statistics."""
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
        print(f"\n  Response Times (ms):")
        print(f"    Average: {stats.total.avg_response_time:.2f}")
        print(f"    Median:  {stats.total.get_response_time_percentile(0.50):.2f}")
        print(f"    p95:     {stats.total.get_response_time_percentile(0.95):.2f}")
        print(f"    p99:     {stats.total.get_response_time_percentile(0.99):.2f}")

    print("=" * 80 + "\n")


class HighThroughputUser(HttpUser):
    """High-throughput user with minimal wait time.

    Focuses on fast, read-only endpoints to maximize RPS.
    """

    # Minimal wait time for maximum throughput
    wait_time = between(0.01, 0.05)

    def on_start(self):
        """Initialize authentication."""
        self.auth_headers = _get_auth_headers()

    @task(30)
    @tag("fast", "health")
    def health_check(self):
        """Health endpoint - no auth, fastest."""
        self.client.get("/health", name="/health")

    @task(25)
    @tag("fast", "api")
    def list_tools(self):
        """List tools - fast DB query."""
        self.client.get("/tools", headers=self.auth_headers, name="/tools")

    @task(20)
    @tag("fast", "api")
    def list_servers(self):
        """List servers - fast DB query."""
        self.client.get("/servers", headers=self.auth_headers, name="/servers")

    @task(15)
    @tag("fast", "api")
    def list_gateways(self):
        """List gateways - fast DB query."""
        self.client.get("/gateways", headers=self.auth_headers, name="/gateways")

    @task(10)
    @tag("fast", "api")
    def list_resources(self):
        """List resources."""
        self.client.get("/resources", headers=self.auth_headers, name="/resources")

    @task(10)
    @tag("fast", "api")
    def list_prompts(self):
        """List prompts."""
        self.client.get("/prompts", headers=self.auth_headers, name="/prompts")

    @task(5)
    @tag("fast", "api")
    def list_tags(self):
        """List tags."""
        self.client.get("/tags", headers=self.auth_headers, name="/tags")

    @task(5)
    @tag("fast", "api")
    def openapi_schema(self):
        """OpenAPI schema - cached."""
        self.client.get("/openapi.json", headers=self.auth_headers, name="/openapi.json")
