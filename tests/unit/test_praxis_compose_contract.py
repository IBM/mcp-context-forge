"""Contracts for the profile-isolated Praxis Docker Compose service."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any, Final

import pytest
import yaml


ROOT = Path(__file__).parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
ENTRYPOINT = ROOT / "docker-entrypoint.sh"
NGINX_TLS_CONFIG = ROOT / "infra/nginx/nginx-tls.conf"
PRAXIS_SERVICE = "praxis"
PRAXIS_PORT = 9090
PRAXIS_IMAGE: Final = "praxis-dataplane:${PRAXIS_IMAGE_TAG:-ed46eb5}"
CONTROL_PLANE_URL = "https://nginx_tls/praxis/v1"
TOKEN_PATH = "/run/secrets/praxis/token"
CA_PATH = "/run/secrets/praxis/ca.pem"


def _render(*profiles: str) -> dict[str, Any]:
    command = ["docker", "compose"]
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)


def _source() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _praxis(source: dict[str, Any]) -> dict[str, Any]:
    return source["services"][PRAXIS_SERVICE]


def _assert_contract(source: dict[str, Any]) -> None:
    service = _praxis(source)
    environment = service["environment"]
    volumes = service["volumes"]
    secrets = service["secrets"]
    health_test = " ".join(service["healthcheck"]["test"])
    tls_health_test = " ".join(source["services"]["nginx_tls"]["healthcheck"]["test"])
    cert_command = "\n".join(source["services"]["cert_init"]["command"])

    assert service["profiles"] == ["praxis"]
    assert service["depends_on"] == {"nginx_tls": {"condition": "service_healthy"}}
    assert service["image"] == PRAXIS_IMAGE
    assert environment == [f"PRAXIS_CONTROL_PLANE_URL={CONTROL_PLANE_URL}"]
    assert source["secrets"]["praxis_replica_token"]["file"] == "${PRAXIS_REPLICA_TOKEN_FILE:-./secrets/praxis/replica-token}"
    secret_mounts = {secret["target"]: secret for secret in secrets}
    volume_mounts = {volume["target"]: volume for volume in volumes}
    assert TOKEN_PATH in secret_mounts
    assert secret_mounts[TOKEN_PATH] == {
        "source": "praxis_replica_token",
        "target": TOKEN_PATH,
    }
    assert CA_PATH in volume_mounts
    assert volume_mounts[CA_PATH] == {
        "type": "bind",
        "source": "./certs/ca.pem",
        "target": CA_PATH,
        "read_only": True,
    }
    assert service["tmpfs"] == ["/var/lib/praxis:uid=65532,gid=65532,mode=0700"]
    assert service["stop_grace_period"] == "45s"
    assert service["read_only"] is True
    assert "ports" not in service
    assert "expose" not in service
    assert "/livez" in health_test
    assert "/readyz" in health_test
    assert "/dev/tcp/127.0.0.1/9090" in health_test
    assert "DNS:nginx_tls" in cert_command
    assert "gateway:4444" not in json.dumps(service)
    assert "PRAXIS_TRAFFIC_ENABLED" not in json.dumps(service)
    assert " -k" not in health_test
    assert " --insecure" not in health_test
    assert "--cacert /app/certs/ca.pem" in tls_health_test
    assert " -k" not in tls_health_test
    assert " --insecure" not in tls_health_test


def test_default_and_tls_profiles_render_without_praxis() -> None:
    # Given: the default and TLS-only profile selections.
    rendered = (_render(), _render("tls"))

    # When: Compose resolves each complete service graph.
    service_sets = [configuration["services"] for configuration in rendered]

    # Then: neither graph contains the dedicated service or its loopback port.
    assert all(PRAXIS_SERVICE not in services for services in service_sets)
    assert all(f'"published":"{PRAXIS_PORT}"' not in json.dumps(services, separators=(",", ":")) for services in service_sets)


def test_tls_and_praxis_profiles_render_one_isolated_service() -> None:
    # Given: both profiles required by the dedicated deployment.
    rendered = _render("tls", "praxis")

    # When: the Praxis service is selected from parsed Compose output.
    service = rendered["services"][PRAXIS_SERVICE]

    # Then: one service uses only the internal control-plane and probe surfaces.
    assert list(rendered["services"]).count(PRAXIS_SERVICE) == 1
    assert service["environment"] == {"PRAXIS_CONTROL_PLANE_URL": CONTROL_PLANE_URL}
    assert "ports" not in service
    assert "expose" not in service


def test_praxis_profile_without_tls_fails_closed() -> None:
    # Given: the Praxis profile without its required TLS topology.
    command = ["docker", "compose", "--profile", "praxis", "config", "--quiet"]

    # When: Compose validates the contradictory service graph.
    result = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True, timeout=30)

    # Then: the disabled nginx_tls dependency prevents rendering.
    assert result.returncode != 0
    assert "nginx_tls" in result.stderr
    assert "invalid compose project" in result.stderr


def test_gateway_entrypoint_has_no_praxis_child_runtime() -> None:
    # Given: the gateway image entrypoint.
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    # When: its managed child paths are inspected.
    praxis_child_markers = ("PRAXIS_PROXY_ENABLED", "start_managed_praxis_proxy", "PRAXIS_PROXY_PID")

    # Then: only the dedicated Task 16 image can launch Praxis.
    assert all(marker not in entrypoint for marker in praxis_child_markers)


def test_environment_example_uses_canonical_praxis_defaults() -> None:
    # Given: the operator-facing environment template.
    environment_example = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()

    # When/Then: it advertises the canonical settings key and immutable image revision.
    assert "PRAXIS_SHADOW_RENDER_ENABLED=false" in environment_example
    assert "PRAXIS_CONFIG_SHADOW_ENABLED=false" not in environment_example
    assert "PRAXIS_IMAGE_TAG=ed46eb5" in environment_example
    assert "PRAXIS_IMAGE_TAG=latest" not in environment_example


@pytest.mark.parametrize(
    ("_scenario", "mutate"),
    [
        ("missing token", lambda source: source["services"][PRAXIS_SERVICE]["secrets"].pop(0)),
        ("missing CA", lambda source: source["services"][PRAXIS_SERVICE]["volumes"].pop(0)),
        ("untrusted cert", lambda source: source["services"][PRAXIS_SERVICE]["volumes"][0].update(source="./certs/untrusted.pem")),
        ("wrong SAN", lambda source: source["services"]["cert_init"]["command"].__setitem__(0, source["services"]["cert_init"]["command"][0].replace("DNS:nginx_tls", "DNS:wrong-host"))),
        ("HTTP URL", lambda source: source["services"][PRAXIS_SERVICE]["environment"].__setitem__(0, "PRAXIS_CONTROL_PLANE_URL=http://nginx_tls/praxis/v1")),
        ("profile contradiction", lambda source: source["services"][PRAXIS_SERVICE].update(profiles=["tls", "praxis"])),
        ("traffic flag", lambda source: source["services"][PRAXIS_SERVICE]["environment"].append("PRAXIS_TRAFFIC_ENABLED=true")),
        ("incompatible image", lambda source: source["services"][PRAXIS_SERVICE].update(image="gateway:latest")),
        ("mutable image", lambda source: source["services"][PRAXIS_SERVICE].update(image="praxis-dataplane:${PRAXIS_IMAGE_TAG:-latest}")),
        ("insecure TLS bypass", lambda source: source["services"]["nginx_tls"]["healthcheck"]["test"].append("-k")),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_named_insecure_or_incomplete_variants_are_rejected(_scenario: str, mutate: Any) -> None:
    # Given: a copy of the real Compose source with one named contract violation.
    source = deepcopy(_source())
    mutate(source)

    # When/Then: deterministic deployment validation rejects the variant.
    with pytest.raises(AssertionError, match=".*"):
        _assert_contract(source)


def test_source_satisfies_complete_contract() -> None:
    # Given: the checked-in Compose source.
    source = _source()

    # When/Then: every dedicated deployment invariant is present together.
    _assert_contract(source)


def test_tls_upstream_uses_ubi_compatible_startup_resolution() -> None:
    # Given: the TLS proxy configuration consumed by the UBI nginx image.
    configuration = NGINX_TLS_CONFIG.read_text(encoding="utf-8")

    # When/Then: Docker DNS is resolved at nginx startup without the unsupported
    # per-upstream `resolve` parameter; a container restart performs re-resolution.
    assert "server gateway:4444 max_fails=0;" in configuration
    assert "server gateway:4444 resolve" not in configuration
