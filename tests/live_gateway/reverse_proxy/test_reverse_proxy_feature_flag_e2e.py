# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/reverse_proxy/test_reverse_proxy_feature_flag_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live feature-flag isolation for reverse-proxy routes.
"""

from __future__ import annotations

import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import anyio
import pytest
import websockets


@pytest.mark.e2e
def test_feature_flag_off_removes_websocket_route() -> None:
    container_name = os.environ.get("RP_FEATURE_OFF_CONTAINER", f"mcpgw-rp-feature-off-{os.getpid()}")
    host_port = int(os.environ.get("RP_FEATURE_OFF_PORT", "18081"))
    gateway_image = os.environ.get("IMAGE_LOCAL", "mcpgateway/mcpgateway:reverse-proxy-e2e")
    subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True, text=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{host_port}:4444",
            "-e",
            "JWT_SECRET_KEY=t8-feature-off-jwt-secret-key-123456",  # pragma: allowlist secret
            "-e",
            "AUTH_ENCRYPTION_SECRET=t8-feature-off-encryption-secret",  # pragma: allowlist secret
            "-e",
            "BASIC_AUTH_PASSWORD=t8-feature-off-password",  # pragma: allowlist secret
            "-e",
            "PLATFORM_ADMIN_PASSWORD=t8-feature-off-password",  # pragma: allowlist secret
            "-e",
            "HOST=0.0.0.0",
            "-e",
            "DATABASE_URL=sqlite:////tmp/feature-off.db",
            "-e",
            "MCPGATEWAY_REVERSE_PROXY_ENABLED=false",
            "-e",
            "MCPGATEWAY_REVERSE_PROXY_DISTRIBUTED_ENABLED=false",
            "-e",
            "PLUGINS_ENABLED=false",
            "-e",
            "GUNICORN_WORKERS=1",
            gateway_image,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{host_port}/health", timeout=2):  # noqa: S310 - fixed local live-test target
                    break
            except (HTTPError, URLError, TimeoutError, ConnectionError):
                time.sleep(1)
        else:
            pytest.fail("feature-off gateway did not become healthy")

        request = Request(f"http://127.0.0.1:{host_port}/reverse-proxy/sessions")
        with pytest.raises(HTTPError) as missing_http_route:
            urlopen(request, timeout=5)  # noqa: S310 - fixed local live-test target
        assert missing_http_route.value.code == 404

        async def verify() -> None:
            with pytest.raises(websockets.InvalidStatus) as rejected:
                async with websockets.connect(f"ws://127.0.0.1:{host_port}/reverse-proxy/ws"):
                    pytest.fail("feature-off WebSocket route was accepted")
            assert rejected.value.response.status_code in {403, 404}

        anyio.run(verify)
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True, text=True)
