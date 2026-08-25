# -*- coding: utf-8 -*-
"""Module Description.
Location: ./tests/unit/mcpgateway/test_reverse_proxy_live_harness.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Module documentation...
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

RUNNER: Final = Path(__file__).parents[2] / "live_gateway" / "reverse_proxy" / "run.sh"
NAMESPACE_KEYS: Final = (
    "IMAGE_LOCAL",
    "REVERSE_PROXY_E2E_COMPOSE_PROJECT",
    "REVERSE_PROXY_E2E_ARTIFACTS",
    "REVERSE_PROXY_E2E_FAST_SERVER_NAME",
    "REVERSE_PROXY_E2E_COMPLIANCE_SERVER_NAME",
    "REVERSE_PROXY_E2E_AUTH_SERVER_NAME",
    "REVERSE_PROXY_E2E_AUTHORITY_SERVER_NAME",
    "RP_FEATURE_OFF_CONTAINER",
)
PORT_KEYS: Final = (
    "FAST_TEST_PORT",
    "POSTGRES_HOST_PORT",
    "PGBOUNCER_HOST_PORT",
    "REDIS_HOST_PORT",
    "NGINX_PORT",
    "RP_COMPLIANCE_PORT",
    "RP_AUTH_PORT",
    "RP_FEATURE_OFF_PORT",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _run_with_fake_runtime(tmp_path: Path, run_id: str) -> dict[str, str]:
    tmp_path.mkdir()
    fake_bin = tmp_path / f"bin-{run_id}"
    fake_bin.mkdir()
    capture = tmp_path / f"environment-{run_id}"
    counter = tmp_path / f"port-counter-{run_id}"
    _write_executable(fake_bin / "git", '#!/bin/sh\nprintf \'%s\\n\' "$HARNESS_ROOT"\n')
    _write_executable(
        fake_bin / "docker",
        "#!/bin/sh\n"
        'if [ "${1:-}" = "exec" ]; then printf \'%s\\n\' "test-jwt-secret-key-with-32-characters"; fi\n',
    )
    _write_executable(fake_bin / "pkill", "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "uv",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "$*" == *"s.bind"* ]]; then\n'
        '  case "$RP_E2E_RUN_ID" in alpha) base=21000 ;; beta) base=22000 ;; *) base=23000 ;; esac\n'
        '  count=$(<"$HARNESS_COUNTER")\n'
        '  count=$((count + 1))\n'
        '  printf \'%s\' "$count" >"$HARNESS_COUNTER"\n'
        '  printf \'%s\\n\' "$((base + count))"\n'
        'elif [[ "$*" == *"jwt.encode"* ]]; then\n'
        "  printf '%s\\n' test-token\n"
        'elif [[ " $* " == *" pytest "* ]]; then\n'
        '  env | sort >"$HARNESS_CAPTURE"\n'
        "fi\n",
    )
    counter.write_text("0", encoding="utf-8")
    client_root = tmp_path / "client"
    client_root.mkdir()
    (client_root / "pyproject.toml").touch()
    environment = os.environ.copy()
    environment.update(
        {
            "HARNESS_CAPTURE": str(capture),
            "HARNESS_COUNTER": str(counter),
            "HARNESS_ROOT": str(tmp_path),
            "MCP_REVERSE_PROXY_CLIENT_ROOT": str(client_root),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "RP_E2E_RUN_ID": run_id,
        }
    )

    subprocess.run([str(RUNNER)], cwd=tmp_path, env=environment, check=True, capture_output=True, text=True)

    return dict(line.split("=", 1) for line in capture.read_text(encoding="utf-8").splitlines() if "=" in line)


def test_parallel_harness_runs_export_disjoint_runtime_namespaces(tmp_path: Path) -> None:
    first = _run_with_fake_runtime(tmp_path / "first", "alpha")
    second = _run_with_fake_runtime(tmp_path / "second", "beta")

    assert first["REVERSE_PROXY_E2E_RUN_SLUG"] == "alpha"
    assert second["REVERSE_PROXY_E2E_RUN_SLUG"] == "beta"
    for key in NAMESPACE_KEYS:
        assert "alpha" in first[key]
        assert "beta" in second[key]
        assert first[key] != second[key]
    assert len({first[key] for key in PORT_KEYS}) == len(PORT_KEYS)
    assert len({second[key] for key in PORT_KEYS}) == len(PORT_KEYS)
    assert {first[key] for key in PORT_KEYS}.isdisjoint(second[key] for key in PORT_KEYS)
