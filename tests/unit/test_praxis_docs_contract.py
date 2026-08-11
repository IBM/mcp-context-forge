"""Executable contract between Praxis sources, deployments, and operator docs."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import subprocess
from typing import Final

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT: Final = Path(__file__).parents[2]


@dataclass(frozen=True, slots=True)
class DocumentationFixture:
    operator: str
    helm: str
    architecture: str
    crate_config: str
    crate_readme: str
    crate_architecture: str
    crate_examples: str
    environment: str

    @classmethod
    def load(cls) -> DocumentationFixture:
        paths = (
            "docs/docs/manage/configuration.md",
            "docs/docs/deployment/helm.md",
            "docs/docs/architecture/index.md",
            "crates/praxis_cf_dataplane/docs/configuration.md",
            "crates/praxis_cf_dataplane/README.md",
            "crates/praxis_cf_dataplane/docs/architecture.md",
            "crates/praxis_cf_dataplane/docs/filter-chain-examples.md",
            ".env.example",
        )
        return cls(*(ROOT.joinpath(path).read_text(encoding="utf-8") for path in paths))


@dataclass(frozen=True, slots=True)
class Mutation:
    name: str
    field: str
    fragment: str


MUTATIONS: Final = (
    Mutation("legacy_removed", "operator", "report-only and never deletes"),
    Mutation("hot_reload", "crate_config", "No hot reload exists"),
    Mutation("insecure_http", "crate_config", "HTTPS only"),
    Mutation("insecure_tls", "crate_config", "wrong SAN or an untrusted CA"),
    Mutation("shared_token", "operator", "must not share a token"),
    Mutation("missing_key_rotation", "operator", "retained decrypt keys"),
    Mutation("missing_lkg", "operator", "now >= deadline"),
    Mutation("missing_cohort", "operator", "fresh rollout cohort"),
    Mutation("missing_attestation", "operator", "complete inventory attestation"),
    Mutation("traffic_enable", "operator", "startup-fatal"),
    Mutation("source_drift", "crate_readme", "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88"),  # pragma: allowlist secret
)


def _source(path: str) -> str:
    return ROOT.joinpath(path).read_text(encoding="utf-8")


def _enum_values(path: str, class_name: str) -> set[str]:
    tree = ast.parse(_source(path))
    enum_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {
        node.value.value
        for node in enum_class.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }


def _rust_seconds(path: str, name: str) -> int:
    match = re.search(rf"{name}[^\n]*Duration::from_secs\((\d[\d_]*)\)", _source(path))
    assert match is not None
    return int(match.group(1).replace("_", ""))


def _env_values(text: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for line in text.splitlines()
        if (match := re.fullmatch(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)", line)) is not None
    }


def _render_manifests() -> list[str]:
    command = [
        "helm", "template", "docs-contract", str(ROOT / "charts/mcp-stack"),
        "--set", "praxis.enabled=true",
        "--set", "praxis.controlPlane.url=https://control.example/praxis/v1",
        "--set", "praxis.controlPlane.caSecret.name=praxis-ca",
        "--set", "praxis.controlPlane.caSecret.key=ca.pem",
        "--set", "praxis.replicas[0].replicaId=replica-a",
        "--set", "praxis.replicas[0].tokenSecret.name=token-a",
        "--set", "praxis.replicas[0].tokenSecret.key=token",
        "--set", "praxis.replicas[1].replicaId=replica-b",
        "--set", "praxis.replicas[1].tokenSecret.name=token-b",
        "--set", "praxis.replicas[1].tokenSecret.key=token",
    ]
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return [yaml.safe_dump(document) for document in yaml.safe_load_all(rendered) if document is not None]


def _documented_praxis_values(helm_docs: str) -> dict:
    section = helm_docs.split("## Praxis configuration replicas", 1)[1]
    match = re.search(r"```yaml\n(.*?)\n```", section, re.DOTALL)
    assert match is not None
    return yaml.safe_load(match.group(1))


def _validate_deployments() -> list[str]:
    errors: list[str] = []
    compose = yaml.safe_load(_source("docker-compose.yml"))
    service = compose["services"]["praxis"]
    if service.get("image") != "praxis-dataplane:${PRAXIS_IMAGE_TAG:-ed46eb5}" or service.get("ports"):
        errors.append("compose_image_or_traffic")
    if service.get("environment") != ["PRAXIS_CONTROL_PLANE_URL=https://nginx_tls/praxis/v1"] or service.get("stop_grace_period") != "45s":
        errors.append("compose_https_or_grace")
    if not service["volumes"][0].get("read_only") or "uid=65532,gid=65532,mode=0700" not in service["tmpfs"][0]:
        errors.append("compose_mounts")
    if "USER 65532:65532" not in _source("Containerfile.praxis") or "target: /run/secrets/praxis/token" not in _source("docker-compose.yml"):
        errors.append("compose_identity")

    values = yaml.safe_load(_source("charts/mcp-stack/values.yaml"))["praxis"]
    schema = json.loads(_source("charts/mcp-stack/values.schema.json"))["properties"]["praxis"]
    properties = schema["properties"]
    if (values["image"]["tag"], values["storage"]["type"], values["traffic"]["enabled"], values["terminationGracePeriodSeconds"]) != ("ed46eb5", "emptyDir", False, 45):
        errors.append("helm_values")
    if properties["image"]["properties"]["tag"]["const"] != values["image"]["tag"] or properties["traffic"]["properties"]["enabled"]["const"] is not False:
        errors.append("helm_schema")
    template = _source("charts/mcp-stack/templates/deployment-praxis.yaml")
    helpers = _source("charts/mcp-stack/templates/_helpers.tpl")
    if "type: Recreate" not in template or "readOnly: true" not in template or template.count("emptyDir: {}") != 2 or "duplicate Praxis credential reference" not in helpers:
        errors.append("helm_template")
    manifests = _render_manifests()
    praxis = [item for item in manifests if "app.kubernetes.io/component: praxis" in item]
    if len(praxis) != 2 or any("kind: Deployment" not in item for item in praxis):
        errors.append("helm_render_kinds")
    if any(re.search(r"kind: (?:Service|Ingress).*?name: .*praxis", item, re.DOTALL) for item in manifests):
        errors.append("helm_render_traffic")
    rendered_text = "\n".join(praxis)
    if not all(f"name: {name}" in rendered_text for name in ("token-a", "token-b")) or any("type: Recreate" not in item for item in praxis):
        errors.append("helm_render_replicas")
    readme = _source("charts/mcp-stack/README.md")
    for key, default in (("praxis.image.tag", '"ed46eb5"'), ("praxis.storage.type", '"emptyDir"'), ("praxis.terminationGracePeriodSeconds", "45"), ("praxis.traffic.enabled", "false")):
        if re.search(rf"\| {re.escape(key)} \| [^|]+ \| `{re.escape(default)}` \|", readme) is None:
            errors.append(f"helm_readme:{key}")
    return errors


def _validate_docs(docs: DocumentationFixture) -> list[str]:
    errors: list[str] = []
    for mutation in MUTATIONS:
        if mutation.fragment not in getattr(docs, mutation.field):
            errors.append(mutation.name)
    combined = "\n".join((docs.operator, docs.helm, docs.architecture, docs.crate_config, docs.crate_readme, docs.crate_architecture, docs.crate_examples))
    for value in _enum_values("mcpgateway/services/_praxis_reconciliation.py", "RolloutStatus") | _enum_values("mcpgateway/services/praxis_legacy_models.py", "RemovalBlockerCode"):
        if value not in combined:
            errors.append(f"enum:{value}")
    for value in ("/praxis/v1", "/v1/praxis", "praxis.manage", "praxis.artifacts.read", "praxis.reports.write"):
        if value not in combined:
            errors.append(f"path_or_permission:{value}")
    documented = ("`15` seconds desired poll", "`60` seconds heartbeat", "`30` seconds activation canary", "`180` seconds stale", "`3600` seconds", "16 MiB", "TERM to the process group for 30 seconds", "KILL for 5 seconds", "grace is 45 seconds", "after `1` day", "retained for\n`90` days", "30-day window")
    if any(fragment not in combined for fragment in documented):
        errors.append("documented_numeric_contract")
    forbidden = ("0.0.0.0:8080", "praxis-proxy -c", "CONTROL_PLANE_GRPC_ENDPOINT", "Stub implementations with TODO", "policies can be updated without restart", "enable direct Praxis traffic", "Praxis traffic is supported", "shared Praxis token", "share a token between replicas", "hot reloads Praxis", "-k https://", "--insecure", "legacy publisher is deleted", "proves authenticated MCP traffic parity")
    if any(fragment.lower() in combined.lower() for fragment in forbidden):
        errors.append("forbidden_claim")

    env = _env_values(docs.environment)
    flags = ("PRAXIS_SHADOW_RENDER_ENABLED", "PRAXIS_ARTIFACT_DELIVERY_ENABLED", "PRAXIS_ACTIVATION_ENABLED", "PRAXIS_TRAFFIC_ENABLED")
    if any(env.get(flag) != "false" for flag in flags):
        errors.append("environment_flags")
    if env.get("PRAXIS_BUNDLE_ENCRYPTION_KEYS") != "" or env.get("PRAXIS_BUNDLE_ACTIVE_KEY_ID") != "" or env.get("PRAXIS_IMAGE_TAG") != "ed46eb5":
        errors.append("environment_keys_or_image")
    if "PRAXIS_REPLICA_TOKEN" in env or env.get("PRAXIS_REPLICA_TOKEN_FILE") != "./secrets/praxis/replica-token":
        errors.append("environment_secret_material")

    documented_praxis = _documented_praxis_values(docs.helm)["praxis"]
    replica_schema = json.loads(_source("charts/mcp-stack/values.schema.json"))["properties"]["praxis"]["properties"]["replicas"]["items"]
    if any(any(Draft202012Validator(replica_schema).iter_errors(replica)) for replica in documented_praxis["replicas"]):
        errors.append("helm_replica_id")

    if _rust_seconds("crates/praxis_config_launcher/src/config.rs", "DEFAULT_DESIRED_POLL_INTERVAL") != 15 or _rust_seconds("crates/praxis_config_launcher/src/config.rs", "DEFAULT_HEARTBEAT_INTERVAL") != 60:
        errors.append("launcher_intervals")
    if _rust_seconds("crates/praxis_config_launcher/src/process.rs", "TERM_GRACE") != 30 or _rust_seconds("crates/praxis_config_launcher/src/process.rs", "KILL_GRACE") != 5:
        errors.append("launcher_grace")
    sources = "\n".join((_source("crates/praxis_config_launcher/src/runtime.rs"), _source("crates/praxis_config_launcher/src/artifact.rs"), _source("mcpgateway/services/_praxis_reconciliation.py"), _source("mcpgateway/services/praxis_legacy_telemetry.py")))
    for fragment in ('unwrap_or_else(|_| "30"', "16 * 1024 * 1024", "seconds=180", "seconds=3600", "days=1", "days=90", "days=30"):
        if fragment not in sources:
            errors.append(f"source_constant:{fragment}")
    permissions = _enum_values("mcpgateway/db.py", "Permissions")
    if not {"praxis.manage", "praxis.artifacts.read", "praxis.reports.write"} <= permissions:
        errors.append("source_permissions")
    compatibility = _source("mcpgateway/services/praxis_bundle_renderer.py")
    for value in ("praxis-bundle/v1", "1.0.0", "ed46eb5", "cpex/v1", "2025-11-25", "0.1.0"):
        if value not in compatibility or f"`{value}`" not in combined:
            errors.append(f"source_compatibility:{value}")
    revision = "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88"  # pragma: allowlist secret
    if revision not in _source("crates/praxis_config_launcher/src/build_info.rs") or f"?rev=ed46eb5#{revision}" not in _source("Cargo.lock"):
        errors.append("source_authority")
    if 'prefix="/praxis/v1"' not in _source("mcpgateway/routers/praxis_config_machine.py") or 'prefix="/praxis"' not in _source("mcpgateway/routers/praxis_config.py") or 'APIRouter(prefix="/v1")' not in _source("mcpgateway/api/v1/__init__.py") or "v1_router.include_router(praxis_config_router)" not in _source("mcpgateway/main.py"):
        errors.append("source_paths")
    errors.extend(_validate_deployments())
    if ROOT.joinpath("docs/mcpgateway-docs.html-e").exists():
        errors.append("build_artifact")
    return errors


def test_documentation_contract_matches_authoritative_sources() -> None:
    assert _validate_docs(DocumentationFixture.load()) == []


def test_documentation_contract_rejects_invalid_helm_replica_id() -> None:
    fixture = DocumentationFixture.load()
    mutated = replace(fixture, helm=fixture.helm.replace("replicaId", "id", 1))
    assert _validate_docs(mutated) == ["helm_replica_id"]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda mutation: mutation.name)
def test_documentation_contract_rejects_named_mutations(mutation: Mutation) -> None:
    fixture = DocumentationFixture.load()
    original = getattr(fixture, mutation.field)
    assert mutation.fragment in original
    mutated = replace(fixture, **{mutation.field: original.replace(mutation.fragment, "MUTATED", 1)})
    assert _validate_docs(mutated) == [mutation.name]
