"""Regression coverage for issue #6083 duplicate backend removal."""

from pathlib import Path

import tests.performance.utils.generate_docker_compose as compose_module
from tests.performance.utils.generate_docker_compose import DockerComposeGenerator


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
    assert "fast_test_server" not in compose
    assert "register_fast_test" not in compose
