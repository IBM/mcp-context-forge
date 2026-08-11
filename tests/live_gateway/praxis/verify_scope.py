"""Read-only deterministic scope verification for Praxis configuration delivery."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Final

ROOT: Final = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from tests.live_gateway.praxis.scope_dependencies import classify_dependency_facts, collect_dependency_facts  # noqa: E402
from tests.live_gateway.praxis.scope_git import added_lines_for_untracked, added_lines_from_patch, parse_changed_inventory  # noqa: E402
ALLOWED_PREFIXES: Final = (
    "charts/mcp-stack/",
    "crates/praxis_cf_dataplane/",
    "crates/praxis_config_launcher/",
    "mcpgateway/alembic/versions/f5a6b7c8d9e0_add_praxis_bundle_persistence.py",
    "mcpgateway/middleware/praxis_",
    "mcpgateway/plugins/binding_compiler.py",
    "mcpgateway/praxis_feature_gates.py",
    "mcpgateway/routers/praxis_",
    "mcpgateway/services/_praxis_",
    "mcpgateway/services/praxis_",
    "tests/fixtures/praxis_",
    "tests/helpers/praxis_",
    "tests/integration/test_praxis_",
    "tests/live_gateway/praxis/",
    "tests/security/test_praxis_",
    "tests/unit/charts/fixtures/praxis-",
    "tests/unit/charts/test_deployment_praxis.py",
    "tests/unit/mcpgateway/db/test_praxis_",
    "tests/unit/mcpgateway/middleware/test_praxis_",
    "tests/unit/mcpgateway/plugins/test_binding_compiler.py",
    "tests/unit/mcpgateway/routers/test_praxis_",
    "tests/unit/mcpgateway/services/test_praxis_",
    "tests/unit/mcpgateway/test_praxis_",
    "tests/unit/test_praxis_",
)
ALLOWED_FILES: Final = frozenset(
    {
        ".env.example",
        ".dockerignore",
        ".github/workflows/linting-full.yml",
        ".gitignore",
        ".ignore",
        ".secrets.baseline",
        "Cargo.lock",
        "Cargo.toml",
        "Containerfile.praxis",
        "Makefile",
        "docker-compose.yml",
        "docker-entrypoint.sh",
        "docs/Makefile",
        "docs/docs/architecture/index.md",
        "docs/docs/deployment/helm.md",
        "docs/docs/manage/configuration.md",
        "infra/nginx/nginx-tls.conf",
        "scripts/build_local_native_extensions.py",
        "mcpgateway/bootstrap_db.py",
        "mcpgateway/config.py",
        "mcpgateway/db.py",
        "mcpgateway/main.py",
        "mcpgateway/middleware/request_logging_middleware.py",
        "mcpgateway/plugins/gateway_plugin_manager.py",
        "mcpgateway/services/gateway_service.py",
        "mcpgateway/services/prompt_service.py",
        "mcpgateway/services/resource_service.py",
        "mcpgateway/services/server_service.py",
        "mcpgateway/services/tool_plugin_binding_service.py",
        "mcpgateway/services/tool_service.py",
        "mcpgateway/services/dataplane_publisher.py",
        "tests/unit/mcpgateway/plugins/test_gateway_plugin_manager.py",
        "tests/unit/mcpgateway/plugins/test_plugin_runtime_management.py",
        "tests/unit/mcpgateway/test_bootstrap_db.py",
        "tests/unit/mcpgateway/test_main.py",
        "tests/unit/mcpgateway/test_main_extended.py",
        "tests/unit/mcpgateway/middleware/test_request_logging_query_redaction.py",
    }
)
TASK_21_FILES: Final = frozenset(
    {
        "mcpgateway/alembic/versions/a6b7c8d9e0f1_extend_praxis_legacy_telemetry.py",
        "mcpgateway/routers/praxis_legacy_telemetry.py",
        "mcpgateway/services/praxis_legacy_models.py",
        "mcpgateway/services/praxis_legacy_observability.py",
        "mcpgateway/services/praxis_legacy_telemetry.py",
        "tests/live_gateway/praxis/test_live_legacy_telemetry.py",
        "tests/unit/mcpgateway/routers/test_praxis_legacy_telemetry.py",
        "tests/unit/mcpgateway/services/test_praxis_legacy_telemetry.py",
    }
)


@dataclass(frozen=True, slots=True)
class Violation:
    """One stable scope violation."""

    category: str
    path: str
    detail: str


def is_allowed_path(path: Path) -> bool:
    """Return whether a changed path belongs to Tasks 1 through 22."""
    value = path.as_posix()
    if "legacy_telemetry" in value:
        return value in TASK_21_FILES
    return value in ALLOWED_FILES or any(value.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def classify_added_line(path: Path, line: str) -> str | None:
    """Classify one added line, honoring explicit proof-only allowances."""
    stripped = line.strip()
    if path.as_posix().startswith("tests/"):
        return None
    if "scope-allow:" in stripped:
        return None
    lowered = stripped.lower()
    if path.as_posix() == "mcpgateway/services/dataplane_publisher.py" and "userconfig" in lowered:
        return None
    checks = (
        ("praxis_forge", "praxis_forge_import"),
        ("/users/", "per_user_bundle"),
        ("userconfig", "per_user_bundle"),
        ("type: nfs", "rwx_storage"),
        ("readwritemany", "rwx_storage"),
        ("plaintext_bundle", "plaintext_bundle"),
        ("praxis_traffic_enabled = true", "praxis_traffic"),
        ("praxis_traffic_enabled=true", "praxis_traffic"),
        ("associated_a2a", "a2a_serialization"),
        ("remove_auth", "auth_removal"),
        ("delete_legacy", "legacy_deletion"),
    )
    return next((category for marker, category in checks if marker in lowered), None)


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "GIT_MASTER": "1"},
    )
    return completed.stdout


def _changed_paths(base: str) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    tracked = _git("diff", "--name-status", "-z", "--diff-filter=ACDMRTUXB", base, "--")
    untracked_output = _git("ls-files", "--others", "--exclude-standard", "-z")
    untracked = parse_changed_inventory("", untracked_output)
    return parse_changed_inventory(tracked, untracked_output), untracked


def _added_lines(base: str, untracked: tuple[Path, ...]) -> tuple[tuple[Path, str], ...]:
    patch = _git("diff", "--unified=0", "--no-ext-diff", base, "--")
    return (*added_lines_from_patch(patch), *added_lines_for_untracked(ROOT, untracked))


def _python_import_violations(paths: tuple[Path, ...]) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for path in paths:
        absolute = ROOT / path
        if not path.as_posix().startswith("mcpgateway/") or path.suffix != ".py" or not absolute.exists():
            continue
        try:
            tree = ast.parse(absolute.read_text(encoding="utf-8"), filename=path.as_posix())
        except SyntaxError as error:
            violations.append(Violation("python_parse", path.as_posix(), f"line {error.lineno or 0}"))
            continue
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        if any(module == "praxis_forge" or module.startswith("praxis_forge.") for module in modules):
            violations.append(Violation("praxis_forge_import", path.as_posix(), "production import"))
    return tuple(violations)


def _dependency_audit(base: str, paths: tuple[Path, ...]):
    metadata = json.loads(subprocess.run(["cargo", "metadata", "--locked", "--format-version", "1"], cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    workspace_names = {package["name"] for package in metadata["packages"] if package["id"] in metadata["workspace_members"]}
    violations: list[Violation] = []
    if not {"praxis_cf_dataplane", "praxis_config_launcher"} <= workspace_names:
        violations.append(Violation("cargo_metadata_drift", "Cargo.toml", "Praxis workspace members missing"))
    manifest_paths = tuple(path for path in paths if path.name == "Cargo.toml" and (ROOT / path).is_file())
    base_manifest_paths = tuple(
        Path(line)
        for line in _git("ls-tree", "-r", "--name-only", base).splitlines()
        if line.endswith("Cargo.toml") and line != "Cargo.toml"
    )

    def load_base_manifest(path: Path) -> str | None:
        completed = subprocess.run(["git", "show", f"{base}:{path.as_posix()}"], cwd=ROOT, check=False, capture_output=True, text=True, env={**__import__("os").environ, "GIT_MASTER": "1"})
        return completed.stdout if completed.returncode == 0 else None

    facts = collect_dependency_facts(
        ROOT,
        _git("show", f"{base}:Cargo.toml"),
        _git("show", f"{base}:Cargo.lock"),
        _git("show", f"{base}:pyproject.toml"),
        manifest_paths,
        base_manifest_paths,
        load_base_manifest,
    )
    audit = classify_dependency_facts(facts)
    violations.extend(Violation("dependency_drift", "Cargo.toml", detail) for detail in audit.violations)
    return tuple(violations), audit.approved


def verify(base: str) -> dict[str, str | list[str] | list[dict[str, str]]]:
    """Return a stable JSON-compatible verification result."""
    paths, untracked = _changed_paths(base)
    violations = [Violation("prohibited_path", path.as_posix(), "outside Tasks 1-22") for path in paths if not is_allowed_path(path)]
    violations.extend(_python_import_violations(paths))
    violations.extend(Violation(category, path.as_posix(), "forbidden added pattern") for path, line in _added_lines(base, untracked) if (category := classify_added_line(path, line)) is not None)
    dependency_violations, approved_dependencies = _dependency_audit(base, paths)
    violations.extend(dependency_violations)
    unique = sorted({(item.category, item.path, item.detail) for item in violations})
    encoded = [asdict(Violation(*item)) for item in unique]
    return {"status": "pass" if not encoded else "fail", "violations": encoded, "approved_dependencies": list(approved_dependencies)}


def main() -> int:
    """Parse arguments, write deterministic JSON, and return status."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--json", required=True, type=Path)
    arguments = parser.parse_args()
    result = verify(arguments.base)
    arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
