"""Base-aware dependency evidence for the Task 20 scope verifier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


_APPROVED_PRIOR_TASK_DIRECT = frozenset({"async-trait", "cpex", "prost", "serde_yaml"})
_APPROVED_TASK_20_DIRECT = frozenset({"nix", "praxis", "praxis-core", "praxis-filter"})
_EXPECTED_APPROVED = (
    "cryptography-existing",
    "hex",
    "nix",
    "praxis@ed46eb5",
    "sha2-existing",
    "tar",
    "tempfile-dev",
)


@dataclass(frozen=True, slots=True)
class DependencyFacts:
    """Observed dependency differences between the base and current tree."""

    python_added: frozenset[str]
    base_direct_names: frozenset[str]
    base_lock_names: frozenset[str]
    current_lock_names: frozenset[str]
    added_direct: frozenset[str]
    cryptography_existing: bool
    sha2_existing_reused: bool
    tempfile_dev_reused: bool
    tar_archive_used: bool
    praxis_source_valid: bool


@dataclass(frozen=True, slots=True)
class DependencyAudit:
    """Derived approved observations and stable unapproved dependency labels."""

    approved: tuple[str, ...]
    violations: tuple[str, ...]


def classify_dependency_facts(facts: DependencyFacts) -> DependencyAudit:
    """Derive F4 labels only when observations are complete and unapproved additions absent."""
    rust_added = facts.added_direct - facts.base_direct_names - _APPROVED_PRIOR_TASK_DIRECT - _APPROVED_TASK_20_DIRECT
    violations = tuple(sorted({*(f"rust:{name}" for name in rust_added), *(f"python:{name}" for name in facts.python_added)}))
    observed = {
        "cryptography-existing": facts.cryptography_existing,
        "hex": "hex" in facts.current_lock_names - facts.base_lock_names,
        "nix": "nix" in facts.added_direct,
        "praxis@ed46eb5": facts.praxis_source_valid and bool({"praxis", "praxis-core", "praxis-filter"} <= facts.added_direct),
        "sha2-existing": facts.sha2_existing_reused,
        "tar": facts.tar_archive_used,
        "tempfile-dev": facts.tempfile_dev_reused,
    }
    missing = tuple(f"missing:{name}" for name in _EXPECTED_APPROVED if not observed[name])
    all_violations = tuple(sorted((*violations, *missing)))
    return DependencyAudit(approved=_EXPECTED_APPROVED if not all_violations else (), violations=all_violations)


def collect_dependency_facts(
    root: Path,
    base_cargo: str,
    base_lock: str,
    base_python: str,
    manifest_paths: tuple[Path, ...],
    base_manifest_paths: tuple[Path, ...],
    load_base_manifest: Callable[[Path], str | None],
) -> DependencyFacts:
    """Collect dependency facts from current files and matching base revisions."""
    base_root = tomllib.loads(base_cargo)
    current_root = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    base_lock_names = _lock_names(base_lock)
    current_lock = (root / "Cargo.lock").read_text(encoding="utf-8")
    current_lock_names = _lock_names(current_lock)
    added_direct: set[str] = set()
    tempfile_dev_reused = False
    praxis_source_valid = False
    base_direct_names = set(base_root.get("workspace", {}).get("dependencies", {}))
    for path in base_manifest_paths:
        base_text = load_base_manifest(path)
        if base_text is None:
            continue
        base_manifest = tomllib.loads(base_text)
        base_direct_names.update(base_manifest.get("dependencies", {}))
        base_direct_names.update(base_manifest.get("build-dependencies", {}))
        base_direct_names.update(base_manifest.get("dev-dependencies", {}))
    for path in manifest_paths:
        absolute = root / path
        if not absolute.is_file():
            continue
        current = tomllib.loads(absolute.read_text(encoding="utf-8"))
        base_text = load_base_manifest(path)
        base = {} if base_text is None else tomllib.loads(base_text)
        current_direct = set(current.get("dependencies", {}))
        base_direct = set(base.get("dependencies", {}))
        added_direct.update(current_direct - base_direct)
        tempfile_dev_reused |= "tempfile" in current.get("dev-dependencies", {}) and "tempfile" in base_lock_names
        praxis_entries = [current.get("dependencies", {}).get(name) for name in ("praxis", "praxis-core", "praxis-filter")]
        praxis_source_valid |= all(isinstance(entry, dict) and entry.get("rev") == "ed46eb5" for entry in praxis_entries)
    base_python_names = _python_dependency_names(base_python)
    current_python_names = _python_dependency_names((root / "pyproject.toml").read_text(encoding="utf-8"))
    crypto_source = (root / "mcpgateway/services/praxis_bundle_crypto.py").read_text(encoding="utf-8")
    archive_source = (root / "mcpgateway/services/praxis_config_archive.py").read_text(encoding="utf-8")
    base_workspace = set(base_root.get("workspace", {}).get("dependencies", {}))
    current_workspace = set(current_root.get("workspace", {}).get("dependencies", {}))
    launcher = tomllib.loads((root / "crates/praxis_config_launcher/Cargo.toml").read_text(encoding="utf-8"))
    launcher_dependencies = set(launcher.get("dependencies", {}))
    return DependencyFacts(
        python_added=frozenset(current_python_names - base_python_names),
        base_direct_names=frozenset(base_direct_names),
        base_lock_names=base_lock_names,
        current_lock_names=current_lock_names,
        added_direct=frozenset(added_direct | (current_workspace - base_workspace)),
        cryptography_existing="cryptography" in base_python_names & current_python_names and "cryptography" in crypto_source,
        sha2_existing_reused="sha2" in base_workspace and "sha2" in launcher_dependencies,
        tempfile_dev_reused=tempfile_dev_reused,
        tar_archive_used="import tarfile" in archive_source,
        praxis_source_valid=praxis_source_valid and "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88" in current_lock,  # pragma: allowlist secret
    )


def _lock_names(content: str) -> frozenset[str]:
    document = tomllib.loads(content)
    return frozenset(str(package["name"]) for package in document.get("package", ()))


def _python_dependency_names(content: str) -> frozenset[str]:
    document = tomllib.loads(content)
    dependencies = document.get("project", {}).get("dependencies", ())
    return frozenset(re.split(r"[<>=!~;\[]", dependency, maxsplit=1)[0].strip().lower() for dependency in dependencies)


__all__ = ("classify_dependency_facts", "collect_dependency_facts", "DependencyAudit", "DependencyFacts")
