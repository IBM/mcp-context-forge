# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_tls_compose.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for the Compose TLS workflows.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def _compose_config(*files: str) -> dict:
    result = subprocess.run(
        ["docker", "compose", *sum((["-f", file] for file in files), []), "--profile", "tls", "config", "--format", "json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_nginx_tls_selects_http_or_https_gateway_scheme_per_compose_stack() -> None:
    nginx_only = _compose_config("docker-compose.yml")
    end_to_end = _compose_config("docker-compose.yml", "docker-compose.gateway-tls.yml")

    assert nginx_only["services"]["nginx_tls"]["environment"]["GATEWAY_SCHEME"] == "http"
    assert end_to_end["services"]["nginx_tls"]["environment"]["GATEWAY_SCHEME"] == "https"
    nginx_config = (REPO_ROOT / "infra/nginx/nginx-tls.conf").read_text(encoding="utf-8")
    entrypoint = (REPO_ROOT / "infra/nginx/docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "proxy_pass __GATEWAY_SCHEME__://gateway_backend;" in nginx_config
    assert 'sed -i "s/__GATEWAY_SCHEME__/$GATEWAY_SCHEME/g" "$NGINX_CONF"' in entrypoint


def test_compose_tls_e2e_pins_gateway_to_one_published_port() -> None:
    result = subprocess.run(
        ["make", "-n", "compose-tls-e2e"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--scale nginx=0 --scale gateway=1" in result.stdout


def test_nginx_tls_documents_unsupported_dynamic_resolution() -> None:
    config = (REPO_ROOT / "infra/nginx/nginx-tls.conf").read_text(encoding="utf-8")

    assert "server gateway:4444 max_fails=0;" in config
    assert "`resolve` is unsupported by the bundled nginx image" in config
