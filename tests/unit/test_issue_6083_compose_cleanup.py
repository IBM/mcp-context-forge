# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_issue_6083_compose_cleanup.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression coverage for issue #6083 duplicate backend removal.
"""

from pathlib import Path

import tests.performance.utils.generate_docker_compose as compose_module
from tests.performance.utils.generate_docker_compose import DockerComposeGenerator

_RETIRED_FAST_TEST_MARKERS = ("fast_test_server", "register_fast_test", "fastTestServer", "fastTest", "fast-test-server", "register-fast-test")


def test_generated_compose_contains_only_fast_time_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(compose_module, "GATEWAY_SERVICE_TEMPLATE", compose_module.GATEWAY_SERVICE_TEMPLATE.replace("{JWT_SECRET_KEY}", "{{JWT_SECRET_KEY}}"))
    config = tmp_path / "config.yaml"
    config.write_text(
        """
        infrastructure_profiles:
          test:
            postgres_version: 17-bookworm
            gateway_instances: 1
        server_profiles:
          standard:
            gunicorn_workers: 1
        """,
        encoding="utf-8",
    )

    compose = DockerComposeGenerator(config).generate("test")

    assert "fast_time_server:" in compose
    for marker in _RETIRED_FAST_TEST_MARKERS:
        assert marker not in compose, marker


def test_static_stack_files_contain_no_fast_test_backend() -> None:
    """Static Compose and Helm files must not restore the retired backend."""
    repo_root = Path(__file__).resolve().parents[2]
    paths = (
        "docker-compose.yml",
        "docker-compose.with-langfuse.yml",
        "Makefile",
        "charts/mcp-stack/values.yaml",
        "charts/mcp-stack/values-minikube.yaml",
        "charts/mcp-stack/profiles/ocp/values-pgo.yaml",
        "charts/mcp-stack/templates/registration-jobs.yaml",
        "charts/mcp-stack/templates/testing-stack.yaml",
        "charts/mcp-stack/values.schema.json",
    )
    for relative_path in paths:
        content = (repo_root / relative_path).read_text(encoding="utf-8")
        for marker in _RETIRED_FAST_TEST_MARKERS:
            assert marker not in content, f"{relative_path}: {marker}"
