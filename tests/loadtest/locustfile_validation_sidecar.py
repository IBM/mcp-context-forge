# -*- coding: utf-8 -*-
"""Focused Locust scenario for validation-dominant Python vs sidecar comparisons.

This loadtest repeatedly posts large JSON request bodies to `/protocol/initialize`
so the request-validation middleware dominates the cost more than database work.

Environment Variables:
    VALIDATION_LOADTEST_HOST: Target host URL (default: http://localhost:8080)
    VALIDATION_LOADTEST_USERS: Number of concurrent users (default: 50)
    VALIDATION_LOADTEST_SPAWN_RATE: Users spawned per second (default: 5)
    VALIDATION_LOADTEST_RUN_TIME: Test duration (default: 60s)
    MCPGATEWAY_BEARER_TOKEN: Pre-generated bearer token
    JWT_SECRET_KEY: Secret used to auto-generate a bearer token when none is supplied
    JWT_ALGORITHM: JWT algorithm (default: HS256)
    JWT_AUDIENCE: JWT audience claim (default: mcpgateway-api)
    JWT_ISSUER: JWT issuer claim (default: mcpgateway)
    JWT_USERNAME: JWT subject/email (default: admin@example.com)
    LOADTEST_JWT_EXPIRY_HOURS: JWT expiry in hours (default: 8760)
"""

# Standard
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import uuid

# Third-Party
import jwt
from locust import between, events, task
from locust.contrib.fasthttp import FastHttpUser
from locust.runners import MasterRunner, WorkerRunner

from tests.loadtest.validation_sidecar_payloads import (
    build_rejected_initialize_payload,
    build_safe_initialize_payload,
)

logger = logging.getLogger(__name__)

BEARER_TOKEN = os.getenv("MCPGATEWAY_BEARER_TOKEN", "")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "mcpgateway-api")
JWT_ISSUER = os.getenv("JWT_ISSUER", "mcpgateway")
JWT_USERNAME = os.getenv("JWT_USERNAME", os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com"))
JWT_TOKEN_EXPIRY_HOURS = int(os.getenv("LOADTEST_JWT_EXPIRY_HOURS", "8760"))


@events.init_command_line_parser.add_listener
def set_defaults(parser) -> None:
    """Set small, repeatable defaults for the focused validation benchmark."""
    parser.set_defaults(
        users=int(os.getenv("VALIDATION_LOADTEST_USERS", "50")),
        spawn_rate=float(os.getenv("VALIDATION_LOADTEST_SPAWN_RATE", "5")),
        run_time=os.getenv("VALIDATION_LOADTEST_RUN_TIME", "60s"),
        host=os.getenv("VALIDATION_LOADTEST_HOST", "http://localhost:8080"),
    )


def _generate_jwt_token() -> str:
    """Generate a bearer token for the loadtest user."""
    payload = {
        "sub": JWT_USERNAME,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TOKEN_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
        "jti": str(uuid.uuid4()),
        "token_use": "session",
        "user": {
            "email": JWT_USERNAME,
            "full_name": "Validation Load Test",
            "is_admin": True,
            "auth_provider": "local",
        },
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _get_auth_headers() -> dict[str, str]:
    """Return headers for authenticated JSON requests."""
    token = BEARER_TOKEN or _generate_jwt_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


class ValidationInitializeUser(FastHttpUser):
    """Load user focused on validation-heavy initialize requests."""

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Initialize auth headers once per user."""
        self.headers = _get_auth_headers()

    @task(7)
    def initialize_safe_large(self) -> None:
        """Send a large accepted payload through validation and protocol init."""
        with self.client.post(
            "/protocol/initialize",
            json=build_safe_initialize_payload(),
            headers=self.headers,
            name="/protocol/initialize [safe-large]",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Expected 200, got {response.status_code}")

    @task(3)
    def initialize_rejected_large(self) -> None:
        """Send a large payload that should be rejected by request validation."""
        with self.client.post(
            "/protocol/initialize",
            json=build_rejected_initialize_payload(),
            headers=self.headers,
            name="/protocol/initialize [rejected-large]",
            catch_response=True,
        ) as response:
            if response.status_code == 422:
                response.success()
            else:
                response.failure(f"Expected 422, got {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **_kwargs) -> None:
    """Log the focused validation scenario startup."""
    if isinstance(environment.runner, MasterRunner | WorkerRunner):
        return
    logger.info("Starting focused validation loadtest against %s", environment.host)
