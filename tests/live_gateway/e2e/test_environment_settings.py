# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_environment_settings.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify file configuration against an isolated gateway started through the CLI.
"""

# Standard
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

# Third-Party
import httpx
import pytest

# Local
from tests.helpers.auth import make_auth_headers, make_test_jwt

pytestmark = pytest.mark.e2e
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("enabled", [True, False])
def test_cli_file_configuration_and_metrics_authorization(tmp_path, unused_tcp_port, enabled):
    """File values control listener and metrics while preserving authentication and feature gates."""
    signing_key = secrets.token_urlsafe(48)
    config = {
        "HOST": "127.0.0.1",
        "PORT": str(unused_tcp_port),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'gateway.db'}",
        "CACHE_TYPE": "memory",
        "REDIS_URL": "",
        "JWT_SECRET_KEY": signing_key,
        "AUTH_ENCRYPTION_SECRET": secrets.token_urlsafe(48),
        "PLATFORM_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DEFAULT_USER_PASSWORD": secrets.token_urlsafe(32),
        "PLATFORM_ADMIN_EMAIL": "admin@example.com",
        "AUTH_REQUIRED": "true",
        "MCP_REQUIRE_AUTH": "true",
        "REQUIRE_USER_IN_DB": "false",
        "MCPGATEWAY_ADMIN_API_ENABLED": "true",
        "MCPGATEWAY_UI_ENABLED": "false",
        "MCPGATEWAY_A2A_ENABLED": "false",
        "PLUGINS_ENABLED": "false",
        "LOG_LEVEL": "ERROR",
        "LOG_TO_FILE": "false",
        "ENABLE_METRICS": str(enabled).lower(),
        "METRICS_CUSTOM_LABELS": "region=environment-test",
        "OTEL_ENABLE_OBSERVABILITY": "false",
        "METRICS_CLEANUP_ENABLED": "false",
        "METRICS_ROLLUP_ENABLED": "false",
    }
    (tmp_path / ".env").write_text("\n".join(f"{key}={value}" for key, value in config.items()) + "\n")
    environment = {"PATH": os.environ["PATH"], "PYTHONPATH": str(_REPO_ROOT), "PYTHONUNBUFFERED": "1"}
    token = make_test_jwt("admin@example.com", is_admin=True, teams=None, secret=signing_key, algorithm="HS256")
    log_path = tmp_path / "startup.log"
    with log_path.open("w") as log_file:
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "mcpgateway.cli"],
            cwd=tmp_path,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        ) as process:
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{unused_tcp_port}", timeout=15, trust_env=False) as client:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        assert process.poll() is None, log_path.read_text()[-5000:]
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.1)
                    else:
                        pytest.fail(f"Gateway startup timed out: {log_path.read_text()[-5000:]}")
                    assert client.get("/metrics/prometheus").status_code in (401, 403)
                    assert client.get("/metrics/prometheus", headers=make_auth_headers("invalid-token")).status_code in (401, 403)
                    response = client.get("/metrics/prometheus", headers=make_auth_headers(token))
                    assert response.status_code == (200 if enabled else 503), response.text
                    if enabled:
                        assert 'region="environment-test"' in response.text
                        assert 'engine="sqlite"' in response.text
                    else:
                        assert response.json()["error"] == "Metrics collection is disabled"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
