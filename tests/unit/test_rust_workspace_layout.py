from __future__ import annotations

from pathlib import Path
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_CARGO_TOML = REPO_ROOT / "Cargo.toml"
MAKEFILE = REPO_ROOT / "Makefile"
DENY_TOML = REPO_ROOT / "deny.toml"
COMMON_WORKSPACE_DEPS = {"pyo3", "serde", "serde_json", "tokio"}
COMMON_WORKSPACE_PACKAGE_KEYS = {"version", "edition", "rust-version", "authors", "license", "repository"}


def _tracked_rust_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and "target" not in path.parts and ".venv" not in path.parts)


def _top_level_crate_dirs() -> list[Path]:
    crates_dir = REPO_ROOT / "crates"
    return sorted(path for path in crates_dir.iterdir() if path.is_dir())


def _tool_cargo_files() -> list[Path]:
    return sorted(path / "Cargo.toml" for path in _top_level_crate_dirs() if (path / "Cargo.toml").exists())


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_legacy_tools_rust_tree_is_removed() -> None:
    legacy_files = _tracked_rust_paths(REPO_ROOT / "tools_rust")
    assert legacy_files == [], f"Legacy tools_rust tree should be removed: {[str(path.relative_to(REPO_ROOT)) for path in legacy_files]}"


def test_root_workspace_covers_all_crates() -> None:
    workspace = _load_toml(ROOT_CARGO_TOML)["workspace"]
    members = set(workspace["members"])
    default_members = set(workspace["default-members"])

    expected_members = {
        "crates/*",
    }
    expected_default_members = {
        "crates/*",
    }

    assert expected_members == members
    assert expected_default_members == default_members


def test_makefile_keeps_rust_server_helpers_outside_workspace_commands() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "find mcp-servers/rust" in makefile
    assert "RUST_SUPPORT_EXCLUDES" not in makefile


def test_dockerignore_and_containerfile_keep_rust_servers_out_of_workspace_image() -> None:
    containerfile = (REPO_ROOT / "Containerfile.lite").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "COPY mcp-servers/rust/ /build/mcp-servers/rust/" not in containerfile
    assert "!mcp-servers/rust/" not in dockerignore
    assert "!mcp-servers/rust/**" not in dockerignore


def test_crates_directory_is_flat() -> None:
    remaining = [path.name for path in _top_level_crate_dirs()]
    assert remaining == ["a2a_runtime", "mcp_runtime", "request_logging_masking_native_extension", "wrapper"], f"Expected only direct crate folders under crates/: {remaining}"


def test_gateway_rs_services_directory_is_empty() -> None:
    gateway_services_dir = REPO_ROOT / "crates" / "gateway_rs" / "services"
    assert not gateway_services_dir.exists(), "Gateway Rust services directory should be removed"


def test_common_dependencies_are_inherited_from_workspace() -> None:
    workspace_dependencies = _load_toml(ROOT_CARGO_TOML)["workspace"]["dependencies"]
    assert COMMON_WORKSPACE_DEPS.issubset(workspace_dependencies.keys())

    offenders: list[str] = []
    for cargo_toml in _tool_cargo_files():
        rel = cargo_toml.relative_to(REPO_ROOT)

        manifest = _load_toml(cargo_toml)
        dependencies = manifest.get("dependencies", {})
        dev_dependencies = manifest.get("dev-dependencies", {})

        for section_name, section in (("dependencies", dependencies), ("dev-dependencies", dev_dependencies)):
            for dep_name in COMMON_WORKSPACE_DEPS:
                dep_value = section.get(dep_name)
                if dep_value is None:
                    continue
                if dep_value == {"workspace": True}:
                    continue
                offenders.append(f"{rel}::{section_name}.{dep_name}")

    assert offenders == [], f"Common Rust dependencies should be inherited from workspace: {offenders}"


def test_workspace_crates_inherit_common_package_metadata() -> None:
    offenders: list[str] = []

    for cargo_toml in _tool_cargo_files():
        rel = cargo_toml.relative_to(REPO_ROOT)
        manifest = _load_toml(cargo_toml)
        package = manifest.get("package", {})

        for key in COMMON_WORKSPACE_PACKAGE_KEYS:
            if package.get(key) != {"workspace": True}:
                offenders.append(f"{rel}::package.{key}")

    assert offenders == [], f"Workspace crate package metadata should be inherited from workspace: {offenders}"


def test_deny_config_tracks_stub_gen_unmaintained_unicode_advisories() -> None:
    workspace_dependencies = _load_toml(ROOT_CARGO_TOML)["workspace"]["dependencies"]
    deny_config = _load_toml(DENY_TOML)

    assert workspace_dependencies["pyo3-stub-gen"] == "0.19"
    assert set(deny_config["advisories"]["ignore"]) >= {
        "RUSTSEC-2025-0075",
        "RUSTSEC-2025-0080",
        "RUSTSEC-2025-0081",
        "RUSTSEC-2025-0090",
        "RUSTSEC-2025-0098",
        "RUSTSEC-2025-0100",
    }
