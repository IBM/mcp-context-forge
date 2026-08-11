"""Parsed-manifest contracts for the dedicated Praxis Helm deployments."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
from typing import Any, Literal, assert_never

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = ROOT / "charts" / "mcp-stack"
FIXTURE = Path(__file__).parent / "fixtures" / "praxis-two-replicas-values.yaml"
Mutation = Literal["duplicate_replica", "duplicate_secret", "plaintext", "http", "missing_ca", "missing_token", "rwx", "traffic", "root", "grace"]

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed; chart-render tests cannot run")


def _render(values_file: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = ["helm", "template", "task18-review", str(CHART_DIR)]
    if values_file is not None:
        command.extend(["-f", str(values_file)])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _manifests(rendered: str) -> list[dict[str, Any]]:
    return [document for document in yaml.safe_load_all(rendered) if document]


def _praxis_deployments(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        manifest
        for manifest in manifests
        if manifest.get("kind") == "Deployment" and manifest.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "praxis"
    ]


def _fixture_values() -> dict[str, Any]:
    values = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(values, dict)
    return values


def _mutate(values: dict[str, Any], mutation: Mutation) -> None:
    praxis = values["praxis"]
    match mutation:
        case "duplicate_replica":
            praxis["replicas"][1]["replicaId"] = praxis["replicas"][0]["replicaId"]
        case "duplicate_secret":
            praxis["replicas"][1]["tokenSecret"]["name"] = praxis["replicas"][0]["tokenSecret"]["name"]
        case "plaintext":
            praxis["replicas"][0]["tokenSecret"]["value"] = "plaintext-token-sentinel"
        case "http":
            praxis["controlPlane"]["url"] = "http://contextforge.example.com/praxis/v1"
        case "missing_ca":
            del praxis["controlPlane"]["caSecret"]
        case "missing_token":
            del praxis["replicas"][0]["tokenSecret"]["key"]
        case "rwx":
            praxis["storage"]["persistence"] = {"accessModes": ["ReadWriteMany"]}
        case "traffic":
            praxis["traffic"]["enabled"] = True
        case "root":
            praxis["podSecurityContext"]["runAsUser"] = 0
        case "grace":
            praxis["terminationGracePeriodSeconds"] = 30
        case unreachable:
            assert_never(unreachable)


def test_default_render_has_no_praxis_resources() -> None:
    # Given default chart values, when Helm renders, then no Praxis-owned object exists.
    result = _render()
    assert result.returncode == 0, result.stderr
    assert not [
        manifest
        for manifest in _manifests(result.stdout)
        if manifest.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "praxis"
    ]


def test_two_replica_fixture_renders_isolated_singleton_deployments() -> None:
    # Given two registered identities, when Helm renders, then each owns one Recreate Deployment.
    result = _render(FIXTURE)
    assert result.returncode == 0, result.stderr
    deployments = _praxis_deployments(_manifests(result.stdout))
    assert len(deployments) == 2
    assert len({deployment["metadata"]["name"] for deployment in deployments}) == 2
    assert {deployment["metadata"]["labels"]["contextforge.io/praxis-replica-id"] for deployment in deployments} == {
        "praxis-replica-a",
        "praxis-replica-b",
    }
    assert all(deployment["spec"]["replicas"] == 1 for deployment in deployments)
    assert all(deployment["spec"]["strategy"] == {"type": "Recreate"} for deployment in deployments)


def test_two_replica_fixture_mounts_external_identity_and_local_state() -> None:
    # Given valid external identity refs, when rendered, then only read-only projections and emptyDir are mounted.
    deployments = _praxis_deployments(_manifests(_render(FIXTURE).stdout))
    token_refs: set[tuple[str, str]] = set()
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        projected_sources = next(volume["projected"]["sources"] for volume in pod["volumes"] if volume["name"] == "praxis-credentials")
        secret_refs = [(source["secret"]["name"], source["secret"]["items"][0]["key"]) for source in projected_sources]
        token_refs.add(secret_refs[0])
        assert secret_refs[1] == ("praxis-control-plane-ca", "ca.pem")
        assert {volume["name"] for volume in pod["volumes"] if "emptyDir" in volume} == {"praxis-data", "tmp"}
        assert all(mount["readOnly"] for mount in container["volumeMounts"] if mount["name"] == "praxis-credentials")
        assert {mount["mountPath"] for mount in container["volumeMounts"]} == {"/run/secrets/praxis", "/var/lib/praxis", "/tmp"}
    assert token_refs == {("praxis-replica-a-token", "token"), ("praxis-replica-b-token", "token")}


def test_two_replica_fixture_uses_launcher_runtime_and_hardening_contract() -> None:
    # Given the Task 16 image contract, when rendered, then probes, revision, shutdown, and hardening remain exact.
    deployments = _praxis_deployments(_manifests(_render(FIXTURE).stdout))
    for deployment in deployments:
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        env = {entry["name"]: entry["value"] for entry in container["env"]}
        assert container["image"] == "praxis-dataplane:ed46eb5"
        assert pod["terminationGracePeriodSeconds"] == 45
        assert env == {"PRAXIS_CONTROL_PLANE_URL": "https://contextforge.example.com/praxis/v1"}
        liveness_command = container["livenessProbe"]["exec"]["command"]
        readiness_command = container["readinessProbe"]["exec"]["command"]
        assert liveness_command[:2] == ["/bin/bash", "-ec"]
        assert readiness_command[:2] == ["/bin/bash", "-ec"]
        assert "127.0.0.1/9090" in liveness_command[2] and "GET /livez" in liveness_command[2]
        assert "127.0.0.1/9090" in readiness_command[2] and "GET /readyz" in readiness_command[2]
        assert pod["securityContext"] == {"fsGroup": 65532, "runAsGroup": 65532, "runAsNonRoot": True, "runAsUser": 65532, "seccompProfile": {"type": "RuntimeDefault"}}
        assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["resources"]
        assert "ports" not in container


def test_enabled_fixture_renders_no_praxis_traffic_or_credentials() -> None:
    # Given Praxis enabled, when rendered, then no Service, Ingress, Secret, or ConfigMap is chart-owned.
    manifests = _manifests(_render(FIXTURE).stdout)
    forbidden = [
        manifest
        for manifest in manifests
        if manifest.get("kind") in {"Service", "Ingress", "Secret", "ConfigMap"}
        and manifest.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "praxis"
    ]
    assert forbidden == []


def test_optional_network_policy_hook_is_egress_only(tmp_path: Path) -> None:
    # Given explicit control-plane egress, when enabled, then one egress-only policy selects each replica.
    values = deepcopy(_fixture_values())
    values["networkPolicies"] = {
        "praxis": {
            "enabled": True,
            "egress": [{"to": [{"ipBlock": {"cidr": "10.0.0.0/8"}}], "ports": [{"protocol": "TCP", "port": 443}]}],
        }
    }
    values_file = tmp_path / "network-policy.yaml"
    values_file.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    policies = [
        manifest
        for manifest in _manifests(_render(values_file).stdout)
        if manifest.get("kind") == "NetworkPolicy"
        and manifest.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component") == "praxis-networkpolicy"
    ]
    assert len(policies) == 2
    assert all(policy["spec"]["policyTypes"] == ["Egress"] and "ingress" not in policy["spec"] for policy in policies)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("duplicate_replica", "duplicate Praxis replicaId"),
        ("duplicate_secret", "duplicate Praxis credential reference"),
        ("plaintext", "tokenSecret"),
        ("http", "controlPlane/url"),
        ("missing_ca", "caSecret"),
        ("missing_token", "tokenSecret"),
        ("rwx", "storage"),
        ("traffic", "traffic/enabled"),
        ("root", "runAsUser"),
        ("grace", "terminationGracePeriodSeconds"),
    ],
    ids=str,
)
def test_invalid_praxis_mutation_fails_closed(tmp_path: Path, mutation: Mutation, reason: str) -> None:
    # Given one unsafe mutation, when Helm renders, then validation rejects that exact contract surface.
    values = deepcopy(_fixture_values())
    _mutate(values, mutation)
    values_file = tmp_path / f"{mutation}.yaml"
    values_file.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    result = _render(values_file)
    assert result.returncode != 0
    assert reason in result.stderr
