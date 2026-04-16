#!/usr/bin/env python3
"""Pre-commit hook: verify Rust workspace layout and build configuration.

Checks that:
- Legacy tools_rust/ tree is removed
- Workspace Cargo.toml covers all crates
- Common dependencies are inherited from workspace
- Crate package metadata inherits from workspace
- Makefile and Containerfile patterns are correct

Exit codes:
    0 - all checks pass
    1 - violations detected (printed to stderr)
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CARGO_TOML = REPO_ROOT / "Cargo.toml"
MAKEFILE = REPO_ROOT / "Makefile"
DENY_TOML = REPO_ROOT / "deny.toml"
COMMON_WORKSPACE_DEPS = {"pyo3", "serde", "serde_json", "tokio"}
COMMON_WORKSPACE_PACKAGE_KEYS = {"version", "edition", "rust-version", "authors", "license", "repository"}


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def _top_level_crate_dirs() -> list[Path]:
    crates_dir = REPO_ROOT / "crates"
    return sorted(path for path in crates_dir.iterdir() if path.is_dir())


def _tool_cargo_files() -> list[Path]:
    return sorted(path / "Cargo.toml" for path in _top_level_crate_dirs() if (path / "Cargo.toml").exists())


def main() -> int:
    violations: list[str] = []

    # Legacy tools_rust tree should be removed
    legacy_dir = REPO_ROOT / "tools_rust"
    if legacy_dir.exists():
        legacy_files = sorted(p for p in legacy_dir.rglob("*") if p.is_file() and "target" not in p.parts and ".venv" not in p.parts)
        if legacy_files:
            violations.append(f"Legacy tools_rust/ tree should be removed ({len(legacy_files)} files remain)")

    if not ROOT_CARGO_TOML.exists():
        violations.append("Root Cargo.toml not found")
        print("Rust workspace violations:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    workspace = _load_toml(ROOT_CARGO_TOML).get("workspace", {})

    # Workspace members
    members = set(workspace.get("members", []))
    default_members = set(workspace.get("default-members", []))
    if members != {"crates/*"}:
        violations.append(f'Workspace members should be {{"crates/*"}}, got {members}')
    if default_members != {"crates/*"}:
        violations.append(f'Workspace default-members should be {{"crates/*"}}, got {default_members}')

    # Crates directory is flat
    crate_names = [p.name for p in _top_level_crate_dirs()]
    expected_crates = ["a2a_runtime", "mcp_runtime", "request_logging_masking_native_extension", "wrapper"]
    if crate_names != expected_crates:
        violations.append(f"Expected crates: {expected_crates}, got {crate_names}")

    # gateway_rs services should not exist
    if (REPO_ROOT / "crates" / "gateway_rs" / "services").exists():
        violations.append("crates/gateway_rs/services directory should be removed")

    # Common deps inherited from workspace
    workspace_deps = workspace.get("dependencies", {})
    if not COMMON_WORKSPACE_DEPS.issubset(workspace_deps.keys()):
        missing = COMMON_WORKSPACE_DEPS - set(workspace_deps.keys())
        violations.append(f"Workspace missing common dependencies: {missing}")

    for cargo_toml in _tool_cargo_files():
        rel = cargo_toml.relative_to(REPO_ROOT)
        manifest = _load_toml(cargo_toml)

        # Check dep inheritance
        for section_name in ("dependencies", "dev-dependencies"):
            section = manifest.get(section_name, {})
            for dep_name in COMMON_WORKSPACE_DEPS:
                dep_value = section.get(dep_name)
                if dep_value is not None and dep_value != {"workspace": True}:
                    violations.append(f"{rel}::{section_name}.{dep_name}: should inherit from workspace")

        # Check package metadata inheritance
        package = manifest.get("package", {})
        for key in COMMON_WORKSPACE_PACKAGE_KEYS:
            if package.get(key) != {"workspace": True}:
                violations.append(f"{rel}::package.{key}: should inherit from workspace")

    # Makefile checks
    if MAKEFILE.exists():
        makefile = MAKEFILE.read_text(encoding="utf-8")
        if "find mcp-servers/rust" not in makefile:
            violations.append("Makefile: missing 'find mcp-servers/rust'")
        if "RUST_SUPPORT_EXCLUDES" in makefile:
            violations.append("Makefile: should not contain RUST_SUPPORT_EXCLUDES")

    # Containerfile / dockerignore checks
    containerfile = REPO_ROOT / "Containerfile.lite"
    dockerignore = REPO_ROOT / ".dockerignore"

    if containerfile.exists():
        cf_text = containerfile.read_text(encoding="utf-8")
        if "COPY mcp-servers/rust/ /build/mcp-servers/rust/" in cf_text:
            violations.append("Containerfile.lite: should not COPY mcp-servers/rust/")

    if dockerignore.exists():
        di_text = dockerignore.read_text(encoding="utf-8")
        for pattern in ("!mcp-servers/rust/", "!mcp-servers/rust/**"):
            if pattern in di_text:
                violations.append(f".dockerignore: should not contain {pattern}")

    # deny.toml advisory checks
    if DENY_TOML.exists():
        deny_config = _load_toml(DENY_TOML)
        expected_advisories = {
            "RUSTSEC-2025-0075",
            "RUSTSEC-2025-0080",
            "RUSTSEC-2025-0081",
            "RUSTSEC-2025-0090",
            "RUSTSEC-2025-0098",
            "RUSTSEC-2025-0100",
        }
        actual_advisories = set(deny_config.get("advisories", {}).get("ignore", []))
        missing_advisories = expected_advisories - actual_advisories
        if missing_advisories:
            violations.append(f"deny.toml: missing advisory ignores: {missing_advisories}")

    if violations:
        print("Rust workspace violations:", file=sys.stderr)
        for v in sorted(violations):
            print(f"  {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
