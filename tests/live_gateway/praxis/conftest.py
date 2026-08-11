"""Isolated production-style Compose lifecycle for live Praxis tests."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError

import pytest

from tests.helpers.auth import make_test_jwt
from .live_api import BearerToken, LiveApi


ROOT = Path(__file__).parents[3]
COMPOSE_OVERRIDE = ROOT / "tests/live_gateway/praxis/docker-compose.e2e.yml"


@dataclass(frozen=True, slots=True)
class LiveStack:
    """Namespaced live-stack controls and secret-free public evidence."""

    project: str
    environment: dict[str, str]
    api: LiveApi
    token_a_path: Path
    token_b_path: Path
    stale_age_path: Path

    def compose(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run one command against only this E2E project."""
        result = subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", "docker-compose.yml", "-f", str(COMPOSE_OVERRIDE), *arguments],
            cwd=ROOT,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if check and result.returncode != 0:
            diagnostics = subprocess.run(
                ["docker", "compose", "-p", self.project, "-f", "docker-compose.yml", "-f", str(COMPOSE_OVERRIDE), "logs", "--no-color", "--tail", "300", "migration", "gateway", "nginx_tls"],
                cwd=ROOT,
                env=self.environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            redacted = result.stderr + diagnostics.stdout + diagnostics.stderr
            for name in ("JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET", "POSTGRES_PASSWORD", "PRAXIS_BUNDLE_ENCRYPTION_KEYS"):
                redacted = redacted.replace(self.environment[name], "[REDACTED]")
            raise AssertionError(redacted)
        return result


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


@pytest.fixture(scope="session")
def live_stack() -> Generator[LiveStack, None, None]:
    """Start and deterministically tear down a unique TLS control plane."""
    with tempfile.TemporaryDirectory(prefix="praxis-e2e-", dir=ROOT / ".omo/evidence") as temporary:
        root = Path(temporary)
        certs = root / "certs"
        certs.mkdir(mode=0o700)
        token_a = root / "replica-a.token"
        token_b = root / "replica-b.token"
        token_a.write_text("provisioning-pending\n", encoding="utf-8")
        token_b.write_text("provisioning-pending\n", encoding="utf-8")
        stale_age = root / "stale-age-seconds"
        stale_age.write_text("0\n", encoding="utf-8")
        token_a.chmod(0o640)
        token_b.chmod(0o640)
        project = f"praxis-e2e-{secrets.token_hex(4)}"
        jwt_secret = secrets.token_urlsafe(48)
        encryption_secret = secrets.token_urlsafe(48)
        bundle_key = __import__("base64").b64encode(secrets.token_bytes(32)).decode()
        tls_port = _free_port()
        environment = {
            **os.environ,
            "IMAGE_LOCAL": "mcpgateway/mcpgateway:praxis-e2e",
            "JWT_SECRET_KEY": jwt_secret,
            "AUTH_ENCRYPTION_SECRET": encryption_secret,
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "PRAXIS_E2E_ADMIN_PASSWORD": secrets.token_urlsafe(32),
            "PRAXIS_SHADOW_RENDER_ENABLED": "true",
            "PRAXIS_ARTIFACT_DELIVERY_ENABLED": "true",
            "PRAXIS_ACTIVATION_ENABLED": "true",
            "PRAXIS_TRAFFIC_ENABLED": "false",
            "PRAXIS_BUNDLE_ACTIVE_KEY_ID": "e2e-key",
            "PRAXIS_BUNDLE_ENCRYPTION_KEYS": f'{{"e2e-key":"{bundle_key}"}}',
            "PRAXIS_E2E_CERT_DIR": str(certs),
            "PRAXIS_E2E_HTTP_PORT": _free_port(),
            "PRAXIS_E2E_TLS_PORT": tls_port,
            "NGINX_PORT": _free_port(),
            "NGINX_TLS_PORT": tls_port,
            "POSTGRES_PORT": _free_port(),
            "PGBOUNCER_PORT": _free_port(),
            "REDIS_PORT": _free_port(),
            "PRAXIS_E2E_TOKEN_A": str(token_a),
            "PRAXIS_E2E_TOKEN_B": str(token_b),
            "PRAXIS_E2E_SECRET_GID": str(os.getgid()),
            "PRAXIS_E2E_STALE_AGE": str(stale_age),
        }
        admin = BearerToken(make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=jwt_secret))
        stack = LiveStack(project, environment, LiveApi(f"https://127.0.0.1:{tls_port}", str(certs / "ca.pem"), admin), token_a, token_b, stale_age)
        try:
            stack.compose("--profile", "tls", "up", "-d", "nginx_tls")
            deadline = time.monotonic() + 60
            last_response = None
            while time.monotonic() < deadline:
                try:
                    response = stack.api.request("GET", "/health") if (certs / "ca.pem").exists() else None
                except URLError:
                    response = None
                last_response = response
                if response is not None and response.status == 200:
                    break
                time.sleep(1)
            else:
                status = stack.compose("ps", check=False)
                logs = stack.compose("logs", "--no-color", "--tail", "120", "gateway", "nginx_tls", check=False)
                diagnostic = status.stdout + status.stderr + logs.stdout + logs.stderr
                for name in ("JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET", "POSTGRES_PASSWORD", "PRAXIS_BUNDLE_ENCRYPTION_KEYS"):
                    diagnostic = diagnostic.replace(environment[name], "[REDACTED]")
                observed = "no response" if last_response is None else f"HTTP {last_response.status}: {last_response.body[:256]!r}"
                raise AssertionError(f"TLS gateway did not become healthy ({observed})\n" + diagnostic)
            yield stack
        finally:
            result = stack.compose("--profile", "tls", "--profile", "praxis-e2e", "down", "--remove-orphans", "--volumes", check=False)
            if result.returncode != 0:
                raise AssertionError("isolated Compose teardown failed")
