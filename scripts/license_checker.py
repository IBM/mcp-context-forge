#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repository license compliance check for Python, Go, and Rust.

This script validates:
- Python project metadata from `pyproject.toml` files
- Installed Python dependency licenses via `pip-licenses`
- Go module licenses via `go-licenses`
- Rust crate licenses via `cargo-license`
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older runtimes
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_POLICY_FILE = ROOT / "license-policy.toml"
DEFAULT_REPORT_FILE = ROOT / "docs" / "docs" / "test" / "license-check-report.json"


@dataclass(frozen=True)
class Finding:
    scope: str
    source: str
    package: str
    license_value: str
    reason: str
    is_warning: bool = False


class _Palette:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    WHITE = "\033[37m"

    @staticmethod
    def _has_color() -> bool:
        return sys.stdout.isatty() and not bool(os.environ.get("NO_COLOR"))

    @classmethod
    def wrap(cls, text: str, color: str) -> str:
        if not cls._has_color():
            return text
        return f"{color}{text}{cls.RESET}"


def _color(text: str, color: str = _Palette.WHITE) -> str:
    return _Palette.wrap(text, color)


def _section_banner(title: str) -> str:
    return _color(f"{title}", _Palette.BOLD + _Palette.CYAN)


def _status_label(is_warning: bool, is_error: bool = False) -> str:
    if is_error:
        return _color("[ERROR]", _Palette.BOLD + _Palette.RED)
    if is_warning:
        return _color("[WARN]", _Palette.BOLD + _Palette.YELLOW)
    return _color("[OK]", _Palette.BOLD + _Palette.GREEN)


def _classify_pyproject_scope(source: str, root: Path) -> str:
    try:
        file_path = Path(source)
        if not file_path.is_absolute():
            file_path = (root / file_path).resolve()
        rel_parts = file_path.relative_to(root.resolve()).parts
    except Exception:
        rel_parts = ()

    if not rel_parts:
        return "Unknown"
    if len(rel_parts) == 1 and rel_parts[0] == "pyproject.toml":
        return "mcpgateway (core)"
    if rel_parts[0] == "mcpgateway":
        return "mcpgateway (core)"
    if rel_parts[0] == "mcp-servers" and len(rel_parts) >= 3 and rel_parts[1] == "python":
        return f"mcp-servers/python/{rel_parts[2]}"
    if rel_parts[0] == "plugins" and len(rel_parts) >= 3 and rel_parts[1] == "external":
        return f"plugins/external/{rel_parts[2]}"
    if rel_parts[0] == "plugins":
        return "plugins"
    if rel_parts[0] == "agent_runtimes" and len(rel_parts) >= 2:
        return f"agents/{rel_parts[1]}"
    if rel_parts[0] == "a2a-agents" and len(rel_parts) >= 2:
        return f"a2a-agents/{rel_parts[1]}"
    if rel_parts[0] == "plugins_rust":
        return "plugins_rust"
    if rel_parts[0] == "docs":
        return "docs"
    return f"other/{rel_parts[0]}"


def _collect_pyproject_scope_index(root: Path) -> Dict[str, List[str]]:
    scopes: Dict[str, List[str]] = defaultdict(list)
    for file in _iter_files_with_name(root, "pyproject.toml"):
        scope = _classify_pyproject_scope(str(file.relative_to(root)), root)
        scopes[scope].append(str(file.relative_to(root)))
    for files in scopes.values():
        files.sort()
    return dict(sorted(scopes.items()))


def _summarize_findings(findings: Sequence[Finding]) -> Dict[str, int]:
    summary = {
        "total": len(findings),
        "errors": 0,
        "warnings": 0,
        "pyproject": 0,
        "pip": 0,
        "pip-subvenv": 0,
        "go": 0,
        "rust": 0,
    }
    for finding in findings:
        if finding.is_warning:
            summary["warnings"] += 1
        else:
            summary["errors"] += 1
        if finding.scope in {"pyproject", "pip", "pip-subvenv", "go", "rust"}:
            summary[finding.scope] += 1
    return summary


def _default_policy() -> Dict[str, Any]:
    return {
        "license": {
            "allow_unknown": False,
            "allowed_license_patterns": [
                r"^apache-2\.0$",
                r"^apache-2\.0-with-llvm-exception$",
                r"^mit$",
                r"^mit-0$",
                r"^bsd-2-clause$",
                r"^bsd-3-clause$",
                r"^bsd$",
                r"^0bsd$",
                r"^isc$",
                r"^iscl$",
                r"^bsl-1\.0$",
                r"^unlicense$",
                r"^public-domain$",
                r"^cc0-1\.0$",
                r"^cdla-permissive-2\.0$",
                r"^cdla-permissive-1\.0$",
                r"^dfsg$",
                r"^approved$",
                r"^psf-2\.0$",
                r"^mpl-2\.0$",
                r"^zpl-2\.1$",
                r"^unicode-3\.0$",
                r"^llvm-exception$",
                r"^zlib$",
                r"^openssl$",
                r"^wtfpl$",
                r"^artistic-2\.0$",
                r"^ncsa$",
                r"^postgresql$",
                r"^curl$",
                r"^x11$",
                r"^cnri-python$",
                r"^hpnd$",
                r"^dual-license$",
            ],
            "allowed_local_license_patterns": [
                r"^apache-2\.0$",
            ],
            "disallowed_license_patterns": [
                r"\bagpl",
                r"\bgpl",
                r"\blgpl",
                r"\bsspl",
                r"\brpl",
                r"\bcpal",
                r"\bosp",
                r"\bcc-by-nc",
            ],
            "allowlist": [],
        },
        "scan": {
            "check_pyproject_licenses": True,
            "check_pip_dependencies": True,
            "check_go_dependencies": True,
            "check_rust_dependencies": True,
            "ignore_unknown_scanners": False,
            "ignore_dev_dependency_group_names": [
                "dev",
                "development",
                "developer",
            ],
        },
        "report": {
            "max_unknown_terms_to_show": 5,
        },
    }


def _merge_dicts(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dicts(base[key], value)
        else:
            base[key] = value
    return base


def load_policy(path: Path) -> Dict[str, Any]:
    policy = _default_policy()
    if not path.exists():
        return policy
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    _merge_dicts(policy, loaded)
    return policy


def _compile_patterns(values: Sequence[str]) -> List[re.Pattern[str]]:
    patterns = []
    for value in values:
        if isinstance(value, str) and value.strip():
            patterns.append(re.compile(value.strip(), re.IGNORECASE))
    return patterns


@dataclass(frozen=True)
class CompiledPatterns:
    allowed: List[re.Pattern[str]]
    allowed_local: List[re.Pattern[str]]
    disallowed: List[re.Pattern[str]]


def _compile_all_patterns(policy: Dict[str, Any]) -> CompiledPatterns:
    license_block = policy["license"]
    return CompiledPatterns(
        allowed=_compile_patterns(license_block.get("allowed_license_patterns", [])),
        allowed_local=_compile_patterns(license_block.get("allowed_local_license_patterns", [r"^apache-2\.0$"])),
        disallowed=_compile_patterns(license_block.get("disallowed_license_patterns", [])),
    )


def _normalize_terms(raw_license: str) -> List[str]:
    if not raw_license:
        return []

    raw = raw_license.strip()
    raw = re.sub(r"\bpublic\s+domain\b", "public-domain", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\blesser\s+general\s+public\s+license\b", "LGPL", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\baffero\s+general\s+public\s+license\b", "AGPL", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bgeneral\s+public\s+license\b", "GPL", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bmozilla\s+public\s+license\b", "MPL", raw, flags=re.IGNORECASE)
    raw = raw.replace(",", " OR ").replace("+", " OR ")
    raw = raw.replace(";", " OR ")
    raw = raw.replace("/", " ")
    raw = raw.replace("(", " ").replace(")", " ")
    raw = raw.replace("]", " ").replace("[", " ")

    split_terms = re.split(r"\b(?:OR|AND)\b", raw, flags=re.IGNORECASE)
    terms: Set[str] = set()
    for part in split_terms:
        for token in part.split():
            token = token.strip().strip("`\"'").strip(".")
            token = token.lower().replace("_", "-")
            if not token or token in {
                "a",
                "and",
                "as",
                "for",
                "for-the",
                "is",
                "it",
                "of",
                "the",
                "with",
                "later",
                "later-than",
                "license",
                "version",
                "versioned",
                "v1",
                "v2",
                "v3",
                "2.0",
                "3.0",
            }:
                continue
            if token in {"python-2.0", "python2.0"}:
                token = "psf-2.0"
            elif token == "mpl":
                token = "mpl-2.0"
            terms.add(token)

    return sorted(terms)


def _find_license_in_obj(data: Any) -> Optional[str]:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("text", "name", "id", "file"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _canonicalize_pkg_name(value: str) -> str:
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    for sep in (";", " ", "["):
        if sep in raw:
            raw = raw.split(sep, 1)[0].strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0].strip()

    for op in ("==", ">=", "<=", "!=", ">", "<", "~=", "==="):
        if op in raw:
            raw = raw.split(op, 1)[0].strip()
    return raw.replace("_", "-").lower()


def _normalize_package_name(value: str) -> str:
    name = _canonicalize_pkg_name(value)
    if not name:
        return ""
    return re.sub(r"[^a-z0-9-]", "", name.replace("+", "-"))


def _extract_dependency_names(data: Any) -> Set[str]:
    names: Set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                name = _normalize_package_name(item)
                if name:
                    names.add(name)
        return names
    if isinstance(data, dict):
        for name, value in data.items():
            if name == "python":
                continue
            if name and isinstance(name, str):
                names.add(_normalize_package_name(name))
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        child_name = _normalize_package_name(item)
                        if child_name:
                            names.add(child_name)
        return names
    return names


def _group_name_is_dev(name: str, ignore_names: Set[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9-]", "", name.strip().lower().replace("_", "-"))
    if not normalized:
        return False
    for ignore in ignore_names:
        token = ignore.strip().lower().replace("_", "-")
        if not token:
            continue
        if normalized == token:
            return True
        if normalized.startswith(f"{token}-") or normalized.endswith(f"-{token}"):
            return True
        if f"-{token}-" in normalized:
            return True
    return False


def _collect_dev_dependencies(root: Path, ignore_group_names: Set[str]) -> Set[str]:
    dev_packages: Set[str] = set()
    if not ignore_group_names:
        return dev_packages

    for file in _iter_files_with_name(root, "pyproject.toml"):
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue

        dependency_groups = data.get("dependency-groups")
        if isinstance(dependency_groups, dict):
            for group_name, group_deps in dependency_groups.items():
                if not isinstance(group_name, str):
                    continue
                if not _group_name_is_dev(group_name, ignore_group_names):
                    continue
                dev_packages.update(_extract_dependency_names(group_deps))

        project = data.get("project", {})
        optional_dependencies = project.get("optional-dependencies") if isinstance(project, dict) else None
        if isinstance(optional_dependencies, dict):
            for group_name, group_deps in optional_dependencies.items():
                if isinstance(group_name, str) and _group_name_is_dev(group_name, ignore_group_names):
                    dev_packages.update(_extract_dependency_names(group_deps))

        tools = data.get("tool", {})
        poetry = tools.get("poetry") if isinstance(tools, dict) else None
        if isinstance(poetry, dict):
            if _group_name_is_dev("dev", ignore_group_names):
                dev_deps = poetry.get("dev-dependencies")
                if isinstance(dev_deps, dict):
                    for name in dev_deps.keys():
                        if isinstance(name, str):
                            dev_packages.add(_normalize_package_name(name))

            groups = poetry.get("group")
            if isinstance(groups, dict):
                for group_name, group_data in groups.items():
                    if not isinstance(group_name, str) or not _group_name_is_dev(group_name, ignore_group_names):
                        continue
                    if isinstance(group_data, dict):
                        group_deps = group_data.get("dependencies")
                        if group_deps:
                            dev_packages.update(_extract_dependency_names(group_deps))

    return dev_packages


def _read_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def _find_spdx_from_text(text: str) -> str:
    if re.search(r"apache\s*[- ]?\s*2\.0|apache\s+license", text, re.IGNORECASE):
        return "Apache-2.0"
    if re.search(r"\bMIT\b", text):
        return "MIT"
    if re.search(r"Permission is hereby granted,?\s+free of charge", text, re.IGNORECASE):
        return "MIT"
    if "BSD-3" in text or "3-Clause BSD" in text:
        return "BSD-3-Clause"
    if "BSD-2" in text or "2-Clause BSD" in text:
        return "BSD-2-Clause"
    if re.search(r"Redistribution and use in source and binary forms", text, re.IGNORECASE):
        return "BSD-3-Clause"
    return ""


def _find_spdx_from_license_file(path: Path) -> str:
    return _find_spdx_from_text(_read_file_text(path))


def _normalize_license_expression(raw_license: str) -> str:
    text = (raw_license or "").strip()
    if not text:
        return text

    if len(text) > 180:
        detected = _find_spdx_from_text(text)
        if detected:
            return detected

    text = " ".join(text.split())

    replacements = [
        (r"\bApache\s+Software\s+License\b", "Apache-2.0"),
        (r"\bApache\s+License\b", "Apache-2.0"),
        (r"\bApache[- ]2\b(?!\.)", "Apache-2.0"),
        (r"\bApache\s+2\.0(?:\s+License)?\b", "Apache-2.0"),
        (r"\bMIT\s+License\b", "MIT"),
        (r"\bThe\s+MIT\s+License\b", "MIT"),
        (r"\bMIT License with Apple Exception\b", "MIT"),
        (r"\bMIT[- ]style\b", "MIT"),
        (r"\bMIT[- ]CMU\b", "MIT"),
        (r"\bModified\s+BSD(?:\s+License)?\b", "BSD-3-Clause"),
        (r"\bNew\s+BSD(?:\s+License)?\b", "BSD-3-Clause"),
        (r"\bRevised\s+BSD(?:\s+License)?\b", "BSD-3-Clause"),
        (r"\bSimplified\s+BSD(?:\s+License)?\b", "BSD-2-Clause"),
        (r"\bBSD\s*[- ]?\s*3[- ]?Clause\b", "BSD-3-Clause"),
        (r"\bBSD\s*[- ]?\s*2[- ]?Clause\b", "BSD-2-Clause"),
        (r"\b3[- ]Clause\s+BSD\s+License\b", "BSD-3-Clause"),
        (r"\b2[- ]Clause\s+BSD(?:\s+License)?\b", "BSD-2-Clause"),
        (r"\bBSD\b", "BSD"),
        (r"\bISC\s+License\s*\(ISCL\)\b", "ISC"),
        (r"\bISCL\b", "ISC"),
        (r"\bThe\s+Unlicense\s*\(Unlicense\)\b", "Unlicense"),
        (r"\bCC0-1\.0\b", "CC0-1.0"),
        (r"\bPublic\s+Domain\b", "Public-Domain"),
        (r"\bZlib\b", "Zlib"),
        (r"\bUnicode[- ]?3\.0\b", "Unicode-3.0"),
        (r"\bBSD-3-Clause\s+Clear\b", "BSD-3-Clause"),
        (r"\bBsl-1\.0\b", "BSL-1.0"),
        (r"\bBouncy\s+Castle\s+License\b", "MIT"),
        (r"\bApache-2\.0\s+or\s+MIT\b", "Apache-2.0 OR MIT"),
        (r"\bApache-2\.0\s+OR\s+ISC\b", "Apache-2.0 OR ISC"),
        (r"\bApache-2\.0\s+WITH\s+LLVM-exception\b", "Apache-2.0 WITH LLVM-exception"),
        (r"\bPython Software Foundation License\b", "PSF-2.0"),
        (r"\bThe Unlicense \(Unlicense\)\b", "Unlicense"),
        (r"\bMozilla Public License 2\.0 \(MPL 2\.0\)\b", "MPL-2.0"),
        (r"\bMPL-2\.0\b", "MPL-2.0"),
        (r"\bZope Public License\b", "ZPL-2.1"),
        (r"\bGNU\s+Affero\s+General\s+Public\s+License\s+v?3(?:\.0)?\b", "AGPL-3.0"),
        (r"\bGNU\s+Lesser\s+General\s+Public\s+License\s+v?3(?:\.0)?\b", "LGPL-3.0"),
        (r"\bGNU\s+Lesser\s+General\s+Public\s+License\s+v?2(?:\.1)?\b", "LGPL-2.1"),
        (r"\bGNU\s+General\s+Public\s+License\s+v?3(?:\.0)?\b", "GPL-3.0"),
        (r"\bGNU\s+General\s+Public\s+License\s+v?2(?:\.0)?\b", "GPL-2.0"),
        (r"\bAGPLv?3(?:\.0)?\b", "AGPL-3.0"),
        (r"\bLGPLv?3(?:\.0)?\b", "LGPL-3.0"),
        (r"\bLGPLv?2(?:\.1)?\b", "LGPL-2.1"),
        (r"\bGPLv?3(?:\.0)?\b", "GPL-3.0"),
        (r"\bGPLv?2(?:\.0)?\b", "GPL-2.0"),
        (r"\bMozilla\s+Public\s+License\s+v?2(?:\.0)?\b", "MPL-2.0"),
        (r"\bArtistic\s+License(?:\s+2(?:\.0)?)?\b", "Artistic-2.0"),
        (r"\bDual\s+License\b", "Dual-License"),
        (r"\bHistorical Permission Notice and Disclaimer\b", "HPND"),
        (r"^Apache$", "Apache-2.0"),
    ]

    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    return text


def _find_repo_spdx(path: Path, root: Path) -> str:
    candidate = path / "LICENSE"
    if candidate.is_file():
        spdx = _find_spdx_from_license_file(candidate)
        if spdx:
            return spdx
    for candidate in path.glob("LICENSE.*"):
        if candidate.is_file():
            spdx = _find_spdx_from_license_file(candidate)
            if spdx:
                return spdx
    if path == root or path.parent == path:
        return ""
    return _find_repo_spdx(path.parent, root)


def _extract_cargo_license(manifest_path: Path) -> str:
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ""

    package_section = data.get("package", {})
    if isinstance(package_section, dict):
        value = _find_license_in_obj(package_section.get("license"))
        if value:
            return value
        license_file = package_section.get("license-file")
        if isinstance(license_file, str):
            result = _find_spdx_from_license_file(manifest_path.parent / license_file)
            if result:
                return result

    workspace = data.get("workspace", {})
    if isinstance(workspace, dict):
        workspace_package = workspace.get("package", {})
        if isinstance(workspace_package, dict):
            value = _find_license_in_obj(workspace_package.get("license"))
            if value:
                return value
            license_file = workspace_package.get("license-file")
            if isinstance(license_file, str):
                result = _find_spdx_from_license_file(manifest_path.parent / license_file)
                if result:
                    return result
    return ""


def _extract_go_module_name(go_mod_path: Path) -> str:
    try:
        for line in go_mod_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("module "):
                return stripped.split(maxsplit=1)[1].strip()
    except (OSError, UnicodeDecodeError):
        return ""
    return ""


def _is_local_go_package(package: str, module_name: str) -> bool:
    module_name = module_name.strip()
    if not module_name or not package:
        return False
    prefix = module_name.rstrip("/")
    return package == module_name or package.startswith(prefix + "/")


def _find_match(name: str, raw_license: str, allowlist: Sequence[Dict[str, str]]) -> Optional[str]:
    normalized = name.lower()
    normalized_license = raw_license.lower()
    for entry in allowlist:
        if not isinstance(entry, dict):
            continue
        entry_name = str(entry.get("name", "")).strip().lower()
        if not entry_name:
            continue
        if entry_name.endswith("*"):
            if not normalized.startswith(entry_name[:-1]):
                continue
        elif normalized != entry_name:
            continue
        allowed_license = str(entry.get("license", "")).strip().lower()
        if allowed_license and allowed_license not in normalized_license:
            continue
        return str(entry.get("reason", "allowlisted")).strip() or "allowlisted"
    return None


def _matches_any(term: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(term) for pattern in patterns)


def evaluate_license(
    scope: str,
    source: str,
    package: str,
    license_value: str,
    policy: Dict[str, Any],
    is_local: bool = False,
    compiled_patterns: Optional[CompiledPatterns] = None,
) -> Optional[Finding]:
    license_block = policy["license"]
    allow_unknown = bool(license_block.get("allow_unknown", False))
    if compiled_patterns is not None:
        allowed_patterns = compiled_patterns.allowed_local if is_local else compiled_patterns.allowed
        disallowed_patterns = compiled_patterns.disallowed
    else:
        if is_local:
            allowed_patterns = _compile_patterns(license_block.get("allowed_local_license_patterns", ["^apache-2\\.0$"]))
        else:
            allowed_patterns = _compile_patterns(license_block.get("allowed_license_patterns", []))
        disallowed_patterns = _compile_patterns(license_block.get("disallowed_license_patterns", []))
    allowlist = list(license_block.get("allowlist", []))

    normalized_license = _normalize_license_expression(license_value or "").strip()

    allowlist_reason = _find_match(package, normalized_license, allowlist)
    if allowlist_reason:
        return None

    if normalized_license.lower() in {"", "unknown", "n/a", "not available", "not specified", "none"}:
        if allow_unknown:
            return None
        return Finding(scope, source, package, normalized_license or "unknown", "license metadata is missing")

    # Handle OR expressions: package is OK if ANY alternative is fully allowed.
    # SPDX uses " OR " for disjunction; pip metadata also uses ";" and ",".
    or_parts = re.split(r"\s+OR\s+|;\s*", normalized_license, flags=re.IGNORECASE)
    or_parts = [p.strip() for p in or_parts if p.strip()]
    if len(or_parts) > 1:
        for part in or_parts:
            part_terms = _normalize_terms(part)
            if not part_terms:
                continue
            if any(_matches_any(t, disallowed_patterns) for t in part_terms):
                continue
            if allowed_patterns and any(not _matches_any(t, allowed_patterns) for t in part_terms):
                continue
            return None  # This OR alternative is fully clean

    terms = _normalize_terms(normalized_license)
    if not terms:
        if allow_unknown:
            return None
        return Finding(
            scope,
            source,
            package,
            normalized_license,
            f"license could not be normalized for policy check: {normalized_license}",
        )

    disallowed_terms = [term for term in terms if _matches_any(term, disallowed_patterns)]
    if disallowed_terms:
        return Finding(
            scope,
            source,
            package,
            normalized_license,
            f"disallowed license term(s): {', '.join(disallowed_terms)}",
        )

    if allowed_patterns:
        unknown_terms = [term for term in terms if not _matches_any(term, allowed_patterns)]
        if unknown_terms:
            max_unknown = int(policy.get("report", {}).get("max_unknown_terms_to_show", 5))
            shown = ", ".join(unknown_terms[:max_unknown])
            extra = ""
            if len(unknown_terms) > max_unknown:
                extra = f" (+{len(unknown_terms) - max_unknown} more)"
            return Finding(
                scope,
                source,
                package,
                normalized_license,
                f"unapproved license term(s): {shown}{extra}",
            )

    return None


def _iter_files_with_name(root: Path, filename: str) -> Iterable[Path]:
    ignored = {".git", ".github", ".tox", ".venv", "node_modules", ".ruff_cache", ".mypy_cache", ".pytest_cache", "todo"}
    for path in root.rglob(filename):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts[:-1])
        if parts.intersection(ignored):
            continue
        yield path


def _run_command(command: Sequence[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, returncode=124, stdout="", stderr=f"timed out after {timeout}s")


def scan_pyprojects(
    root: Path, policy: Dict[str, Any], compiled_patterns: Optional[CompiledPatterns] = None
) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []
    stats = {"manifests": 0, "evaluated": 0}
    for file in _iter_files_with_name(root, "pyproject.toml"):
        stats["manifests"] += 1
        data = tomllib.loads(file.read_text(encoding="utf-8"))
        project = data.get("project", {})
        if not isinstance(project, dict):
            continue
        name = str(project.get("name", file.parent.name)).strip()
        license_value = _find_license_in_obj(project.get("license"))
        if license_value is None:
            stats["evaluated"] += 1
            finding = evaluate_license(
                "pyproject",
                str(file.relative_to(root)),
                name,
                "",
                policy,
                is_local=True,
                compiled_patterns=compiled_patterns,
            )
            if finding:
                findings.append(finding)
            continue
        stats["evaluated"] += 1
        finding = evaluate_license(
            "pyproject",
            str(file.relative_to(root)),
            name,
            license_value,
            policy,
            is_local=True,
            compiled_patterns=compiled_patterns,
        )
        if finding:
            findings.append(finding)

    return findings, stats


def scan_pip_dependencies(
    root: Path,
    policy: Dict[str, Any],
    ignore_dev_dependencies: bool,
    dev_dependency_names: Optional[Set[str]] = None,
    compiled_patterns: Optional[CompiledPatterns] = None,
) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []
    stats = {"dependencies": 0, "dependencies_ignored_as_dev": 0}
    scan_cfg = policy.get("scan", {})
    ignore_group_names = {
        name.strip().lower()
        for name in scan_cfg.get("ignore_dev_dependency_group_names", ["dev", "development", "developer"])
        if isinstance(name, str) and name.strip()
    }
    ignored = dev_dependency_names or set()
    if ignore_dev_dependencies and ignored:
        ignored = {name.lower() for name in ignored if name}

    if not shutil.which("pip-licenses"):
        return (
            [
                Finding(
                    "pip",
                    "environment",
                    "pip-licenses",
                    "",
                    "`pip-licenses` binary is not available",
                )
            ],
            stats,
        )

    result = _run_command(["pip-licenses", "--format=csv"], root)
    if result.returncode != 0 and not result.stdout:
        return (
            [
                Finding(
                    "pip",
                    "environment",
                    "pip-licenses",
                    "",
                    f"command failed: {result.stderr.strip() or 'unknown error'}",
                )
            ],
            stats,
        )

    text = result.stdout.strip()
    if not text:
        return (
            [
                Finding(
                    "pip",
                    "environment",
                    "pip-licenses",
                    "",
                    "no dependency rows were returned",
                )
            ],
            stats,
        )

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return findings, stats

    header = [header.strip() for header in rows[0]]
    name_idx = None
    lic_idx = None
    for idx, name in enumerate(header):
        if name.lower() in {"name", "package", "package name", "module"}:
            name_idx = idx
        if name.lower() in {"license", "licence"}:
            lic_idx = idx
        if name_idx is not None and lic_idx is not None:
            break

    if name_idx is None or lic_idx is None:
        return (
            [
                Finding(
                    "pip",
                    "environment",
                    "pip-licenses",
                    "",
                    "unable to parse CSV header from `pip-licenses` output",
                )
            ],
            stats,
        )

    for row in rows[1:]:
        if len(row) <= max(name_idx, lic_idx):
            continue
        dependency = row[name_idx].strip()
        normalized_dependency = _normalize_package_name(dependency)
        if ignore_dev_dependencies and normalized_dependency and normalized_dependency in ignored:
            stats["dependencies_ignored_as_dev"] += 1
            continue
        license_value = row[lic_idx].strip()
        stats["dependencies"] += 1
        finding = evaluate_license("pip", "pip-licenses", dependency, license_value, policy, compiled_patterns=compiled_patterns)
        if finding:
            findings.append(finding)

    return findings, stats


_SUBVENV_INLINE_SCRIPT = """\
import importlib.metadata, json, sys
pkgs = []
for dist in importlib.metadata.distributions():
    meta = dist.metadata
    name = meta.get("Name", "")
    lic = meta.get("License-Expression") or meta.get("License") or ""
    if not lic:
        classifiers = meta.get_all("Classifier") or []
        for c in classifiers:
            if c.startswith("License ::"):
                parts = c.split(" :: ")
                lic = parts[-1] if len(parts) > 2 else ""
                break
    pkgs.append({"name": name, "license": lic})
json.dump(pkgs, sys.stdout)
"""


def scan_pip_subvenvs(
    root: Path,
    policy: Dict[str, Any],
    ignore_dev_dependencies: bool,
    dev_dependency_names: Optional[Set[str]] = None,
    compiled_patterns: Optional[CompiledPatterns] = None,
) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []
    stats = {"venvs": 0, "packages": 0, "dependencies_ignored_as_dev": 0}
    ignored = {name.lower() for name in (dev_dependency_names or set()) if name} if ignore_dev_dependencies else set()
    root_venv = (root / ".venv").resolve()
    ignored_dirs = {".git", ".github", ".tox", "node_modules", ".ruff_cache", ".mypy_cache", ".pytest_cache", "todo"}

    for venv_dir in sorted(root.rglob(".venv")):
        if not venv_dir.is_dir():
            continue
        if venv_dir.resolve() == root_venv:
            continue
        rel_parts = set(venv_dir.relative_to(root).parts[:-1])
        if rel_parts.intersection(ignored_dirs):
            continue
        python_bin = venv_dir / "bin" / "python"
        if not python_bin.exists():
            continue

        stats["venvs"] += 1
        subproject = str(venv_dir.parent.relative_to(root))
        result = _run_command([str(python_bin), "-c", _SUBVENV_INLINE_SCRIPT], venv_dir.parent)
        if result.returncode != 0 or not result.stdout.strip():
            findings.append(
                Finding(
                    "pip-subvenv",
                    subproject,
                    venv_dir.name,
                    "",
                    f"failed to enumerate packages: {result.stderr.strip()[:200] or 'no output'}",
                    is_warning=True,
                )
            )
            continue

        try:
            packages = json.loads(result.stdout)
        except json.JSONDecodeError:
            findings.append(
                Finding(
                    "pip-subvenv",
                    subproject,
                    venv_dir.name,
                    "",
                    "failed to parse JSON from sub-venv enumeration",
                    is_warning=True,
                )
            )
            continue

        for pkg in packages:
            name = str(pkg.get("name", "")).strip()
            if not name:
                continue
            normalized_name = _normalize_package_name(name)
            if ignore_dev_dependencies and normalized_name and normalized_name in ignored:
                stats["dependencies_ignored_as_dev"] += 1
                continue
            license_value = str(pkg.get("license", "")).strip()
            stats["packages"] += 1
            finding = evaluate_license("pip-subvenv", subproject, name, license_value, policy, compiled_patterns=compiled_patterns)
            if finding:
                findings.append(finding)

    return findings, stats


def scan_go_modules(root: Path, policy: Dict[str, Any], compiled_patterns: Optional[CompiledPatterns] = None) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []
    stats = {"modules": 0, "packages": 0}

    if not shutil.which("go-licenses"):
        return (
            [
                Finding(
                    "go",
                    "go modules",
                    "go-licenses",
                    "",
                    "`go-licenses` binary is not available",
                )
            ],
            stats,
        )

    module_meta: Dict[Path, Tuple[str, str]] = {}
    for module_file in _iter_files_with_name(root, "go.mod"):
        module_root = module_file.parent
        module_name = _extract_go_module_name(module_file)
        module_license = _find_repo_spdx(module_root, root)
        if not module_license:
            module_license = "unknown"
        module_meta[module_root] = (module_name, module_license)

        finding = evaluate_license(
            "go",
            str(module_root.relative_to(root)),
            module_root.name,
            module_license,
            policy,
            is_local=True,
            compiled_patterns=compiled_patterns,
        )
        if finding:
            findings.append(finding)

    for module_file in _iter_files_with_name(root, "go.mod"):
        module_root = module_file.parent
        stats["modules"] += 1
        module_name, module_license = module_meta.get(module_root, ("", "unknown"))
        result = _run_command(["go-licenses", "report", "./..."], module_root)
        parsed_any = False
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) < 3:
                continue
            package = row[0].strip()
            package_license = row[2].strip()
            if is_local_package := _is_local_go_package(package, module_name):
                if not package_license or package_license.lower() in {"unknown", "n/a", ""}:
                    package_license = module_license
            if package or package_license:
                parsed_any = True
            first_segment = package.split("/", 1)[0]
            if "." not in first_segment and not is_local_package:
                continue
            if package in {"go", "gopkg.in", "golang.org/x"}:
                continue
            if first_segment == "internal" and not is_local_package:
                continue

            stats["packages"] += 1
            finding = evaluate_license(
                "go",
                str(module_root.relative_to(root)),
                package,
                package_license,
                policy,
                is_local=is_local_package,
                compiled_patterns=compiled_patterns,
            )
            if finding:
                findings.append(finding)

        if result.returncode != 0 and not parsed_any:
            stderr_lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
            if stderr_lines:
                if len(stderr_lines) > 3:
                    stderr_summary = "; ".join(stderr_lines[-3:])
                else:
                    stderr_summary = "; ".join(stderr_lines)
            else:
                stderr_summary = ""
            reason = "go-licenses returned non-zero exit code (warnings/partial scan possible)"
            if stderr_summary:
                reason = f"{reason}: {stderr_summary[:300]}"
            findings.append(
                Finding(
                    "go",
                    str(module_root.relative_to(root)),
                    module_root.name,
                    "",
                    reason,
                    is_warning=True,
                )
            )

    return findings, stats


def scan_rust_modules(root: Path, policy: Dict[str, Any], compiled_patterns: Optional[CompiledPatterns] = None) -> Tuple[List[Finding], Dict[str, int]]:
    findings: List[Finding] = []
    stats = {"manifests": 0, "crates": 0}

    if not shutil.which("cargo-license"):
        return (
            [
                Finding(
                    "rust",
                    "cargo",
                    "cargo-license",
                    "",
                    "`cargo-license` binary is not available",
                )
            ],
            stats,
        )

    local_crate_licenses: Dict[str, str] = {}
    for cargo_file in _iter_files_with_name(root, "Cargo.toml"):
        crate_root = cargo_file.parent
        crate_name = str(crate_root.name)
        license_value = _extract_cargo_license(cargo_file)
        if not license_value:
            license_value = _find_repo_spdx(crate_root, root)
        if not license_value:
            license_value = "unknown"
        local_crate_licenses[crate_name] = license_value
        finding = evaluate_license(
            "rust",
            str(crate_root.relative_to(root)),
            crate_name,
            license_value,
            policy,
            is_local=True,
            compiled_patterns=compiled_patterns,
        )
        if finding:
            findings.append(finding)

    seen: Set[Tuple[str, str, str]] = set()
    for cargo_file in _iter_files_with_name(root, "Cargo.toml"):
        crate_root = cargo_file.parent
        crate_name = str(crate_root.name)
        stats["manifests"] += 1
        result = _run_command(["cargo", "license", "--json", "--avoid-dev-deps"], crate_root)
        if result.returncode != 0 and not result.stdout:
            findings.append(
                Finding(
                    "rust",
                    str(crate_root.relative_to(root)),
                    cargo_file.name,
                    "",
                    f"`cargo license` failed: {result.stderr.strip() or 'unknown error'}",
                )
            )
            continue

        try:
            entries = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            findings.append(
                Finding(
                    "rust",
                    str(crate_root.relative_to(root)),
                    "cargo-license",
                    "",
                    "failed to parse JSON output from `cargo license`",
                )
            )
            continue

        for entry in entries:
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            license_value = str(entry.get("license", "")).strip()
            is_local_dependency = name in local_crate_licenses
            key = (str(crate_root), name, license_value)
            if key in seen:
                continue
            seen.add(key)
            stats["crates"] += 1
            finding = evaluate_license(
                "rust",
                str(crate_root.relative_to(root)),
                name,
                license_value,
                policy,
                is_local=is_local_dependency,
                compiled_patterns=compiled_patterns,
            )
            if finding:
                findings.append(finding)

    return findings, stats


def print_summary(
    findings: Sequence[Finding], stats: Dict[str, Dict[str, int]], root: Path, summary_only: bool = False
) -> None:
    warnings = sum(1 for finding in findings if finding.is_warning)
    errors = len(findings) - warnings

    status = _color("FAILED", _Palette.BOLD + _Palette.RED) if errors else _color(
        "PASS", _Palette.BOLD + _Palette.GREEN
    )
    print(_section_banner(f"\nLicense compliance report ({status})"))
    print(_color("═" * 60, _Palette.DIM + _Palette.WHITE))
    print(
        "Checked pyproject manifests:"
        f" {stats['pyproject']['manifests']} files, {stats['pyproject']['evaluated']} evaluated"
    )
    print(f"Checked pip deps: {stats['pip']['dependencies']} entries")
    subvenv_stats = stats.get("pip-subvenv", {})
    if subvenv_stats.get("venvs", 0):
        print(f"Checked pip sub-venvs: {subvenv_stats['venvs']} venvs, {subvenv_stats['packages']} packages")
    print(f"Checked Go modules: {stats['go']['modules']} modules, {stats['go']['packages']} packages")
    print(f"Checked Rust manifests: {stats['rust']['manifests']} manifests, {stats['rust']['crates']} crates")
    print(f"Findings: {_color(str(errors), _Palette.BOLD + _Palette.RED)} "
          f"error(s), {_color(str(warnings), _Palette.BOLD + _Palette.YELLOW)} warning(s)\n")

    if summary_only:
        counts = _summarize_findings(findings)
        print(_section_banner("Findings summary"))
        print(f"  python manifest files: {counts['pyproject']} finding(s)")
        print(f"  pip third-party: {counts['pip']} finding(s)")
        print(f"  pip sub-venvs: {counts['pip-subvenv']} finding(s)")
        print(f"  go modules: {counts['go']} finding(s)")
        print(f"  rust manifests: {counts['rust']} finding(s)")
        if not findings:
            print(f"\n  {_status_label(False)} no findings")
            return

        top_findings = sorted(
            findings,
            key=lambda item: (item.is_warning, item.scope, item.source, item.package),
        )
        print(f"\n  Top findings ({min(20, len(top_findings))} of {len(top_findings)}):")
        for item in top_findings[:20]:
            label = _status_label(item.is_warning, is_error=not item.is_warning)
            print(f"    {label} {item.scope}::{item.source} :: {item.package}")
            print(f"      reason: {item.reason}")
        if len(top_findings) > 20:
            print(f"    ... {len(top_findings) - 20} additional findings not shown")
        ignored_dev = stats.get("pip", {}).get("dependencies_ignored_as_dev", 0)
        if ignored_dev:
            print(f"    PyPI dev group dependencies skipped: {ignored_dev}")
        return

    print(_section_banner("# PYTHON"))
    py_scopes = _collect_pyproject_scope_index(root)
    py_findings = [finding for finding in findings if finding.scope == "pyproject"]
    grouped_py_findings: Dict[str, List[Finding]] = defaultdict(list)
    for finding in py_findings:
        scope = _classify_pyproject_scope(finding.source, root)
        grouped_py_findings[scope].append(finding)

    for scope in sorted(set(py_scopes.keys()) | set(grouped_py_findings.keys())):
        scope_findings = grouped_py_findings.get(scope, [])
        file_count = len(py_scopes.get(scope, []))
        error_count = sum(1 for f in scope_findings if not f.is_warning)
        warn_count = sum(1 for f in scope_findings if f.is_warning)
        if error_count:
            status = _status_label(False, is_error=True)
            stat_text = _color(f"{error_count}", _Palette.BOLD + _Palette.RED)
            warn_text = _color(f"{warn_count}", _Palette.BOLD + _Palette.YELLOW)
            print(f"  {status} {scope} ({file_count} file(s), {stat_text} error(s), {warn_text} warning(s))")
            for item in scope_findings:
                label = _status_label(item.is_warning, is_error=not item.is_warning)
                print(f"    {label} package={item.package}")
                print(f"      license: {item.license_value or 'n/a'}")
                print(f"      reason: {item.reason}")
                if item.source:
                    print(f"      source: {item.source}")
            print("")
        elif warn_count:
            warn_label = _status_label(True)
            print(f"  {warn_label} {scope} ({file_count} file(s), {warn_count} warning(s))")
            for item in scope_findings:
                label = _status_label(item.is_warning, is_error=not item.is_warning)
                print(f"    {label} package={item.package}")
                print(f"      license: {item.license_value or 'n/a'}")
                print(f"      reason: {item.reason}")
                if item.source:
                    print(f"      source: {item.source}")
            print("")
        else:
            print(
                f"  {_status_label(False, is_error=False)} "
                f"{scope} ({file_count} file(s), no local license issues)"
            )

    pip_findings = [finding for finding in findings if finding.scope == "pip"]
    print(_section_banner("# PYTHON THIRD-PARTY (pip)"))
    if pip_findings:
        for item in pip_findings:
            label = _status_label(item.is_warning, is_error=not item.is_warning)
            print(f"  {label} {item.package}")
            print(f"    license: {item.license_value or 'n/a'}")
            print(f"    source: {item.source}")
            print(f"    reason: {item.reason}")
        print("")
    else:
        print(f"  {_status_label(False)} no issues detected\n")

    subvenv_findings = [finding for finding in findings if finding.scope == "pip-subvenv"]
    if subvenv_findings or stats.get("pip-subvenv", {}).get("venvs", 0):
        print(_section_banner("# PYTHON THIRD-PARTY (sub-venvs)"))
        if subvenv_findings:
            subvenv_by_source: Dict[str, List[Finding]] = defaultdict(list)
            for item in subvenv_findings:
                subvenv_by_source[item.source].append(item)
            for source in sorted(subvenv_by_source.keys()):
                for item in subvenv_by_source[source]:
                    label = _status_label(item.is_warning, is_error=not item.is_warning)
                    print(f"  {label} {source} :: {item.package}")
                    print(f"    license: {item.license_value or 'n/a'}")
                    print(f"    reason: {item.reason}")
            print("")
        else:
            print(f"  {_status_label(False)} no issues detected\n")

    print(_section_banner("# GO"))
    go_findings = [finding for finding in findings if finding.scope == "go"]
    go_by_source: Dict[str, List[Finding]] = defaultdict(list)
    for finding in go_findings:
        go_by_source[finding.source].append(finding)
    for source in sorted(go_by_source.keys()):
        scope_findings = go_by_source[source]
        if not scope_findings:
            continue
        for item in scope_findings:
            label = _status_label(item.is_warning, is_error=not item.is_warning)
            print(f"  {label} {source} :: {item.package}")
            print(f"    license: {item.license_value or 'n/a'}")
            print(f"    reason: {item.reason}")
        print("")
    if not go_by_source:
        print(f"  {_status_label(False)} no go license issues found")
        print("")

    print(_section_banner("# RUST"))
    rust_findings = [finding for finding in findings if finding.scope == "rust"]
    rust_by_source: Dict[str, List[Finding]] = defaultdict(list)
    for finding in rust_findings:
        rust_by_source[finding.source].append(finding)
    for source in sorted(rust_by_source.keys()):
        scope_findings = rust_by_source[source]
        if not scope_findings:
            continue
        for item in scope_findings:
            label = _status_label(item.is_warning, is_error=not item.is_warning)
            print(f"  {label} {source} :: {item.package}")
            print(f"    license: {item.license_value or 'n/a'}")
            print(f"    reason: {item.reason}")
        print("")
    if not rust_by_source:
        print(f"  {_status_label(False)} no rust license issues found")
        print("")

    ignored_dev = stats.get("pip", {}).get("dependencies_ignored_as_dev", 0)
    if ignored_dev:
        print(_color(f"PyPI dev group dependencies skipped: {ignored_dev}", _Palette.BOLD + _Palette.YELLOW))


def write_json_report(path: Path, findings: Sequence[Finding], stats: Dict[str, Dict[str, int]]) -> None:
    payload = {
        "stats": stats,
        "findings": [
            {
                "scope": finding.scope,
                "source": finding.source,
                "package": finding.package,
                "license": finding.license_value,
                "reason": finding.reason,
                "is_warning": finding.is_warning,
            }
            for finding in findings
        ],
        "summary": {
            "total_findings": len(findings),
            "errors": len([finding for finding in findings if not finding.is_warning]),
            "warnings": len([finding for finding in findings if finding.is_warning]),
            "ok": not any(not finding.is_warning for finding in findings),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"JSON report written to: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check licenses used in the repository.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_POLICY_FILE),
        help="Path to license policy file",
    )
    parser.add_argument(
        "--report-json",
        default=str(DEFAULT_REPORT_FILE),
        help="Write JSON report to this path",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Disable JSON report output",
    )
    parser.add_argument(
        "--include-dev-groups",
        action="store_true",
        help="Include dev/developer dependency groups from pyproject.toml",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print a compact summary instead of the full per-scope findings",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = load_policy(Path(args.config))
    scan_cfg = policy.get("scan", {})
    ignore_group_names = {
        name.strip().lower()
        for name in scan_cfg.get("ignore_dev_dependency_group_names", ["dev", "development", "developer"])
        if isinstance(name, str) and name.strip()
    }
    include_dev_groups = bool(args.include_dev_groups)

    dev_dependency_names: Set[str] = set()
    if not include_dev_groups and scan_cfg.get("check_pip_dependencies", True):
        dev_dependency_names = _collect_dev_dependencies(ROOT, ignore_group_names)

    compiled_patterns = _compile_all_patterns(policy)

    stats = {
        "pyproject": {"manifests": 0, "evaluated": 0},
        "pip": {"dependencies": 0, "dependencies_ignored_as_dev": 0},
        "pip-subvenv": {"venvs": 0, "packages": 0, "dependencies_ignored_as_dev": 0},
        "go": {"modules": 0, "packages": 0},
        "rust": {"manifests": 0, "crates": 0},
    }

    findings: List[Finding] = []
    if scan_cfg.get("check_pyproject_licenses", True):
        scope_findings, scope_stats = scan_pyprojects(ROOT, policy, compiled_patterns=compiled_patterns)
        findings.extend(scope_findings)
        stats["pyproject"].update(scope_stats)

    if scan_cfg.get("check_pip_dependencies", True):
        scope_findings, scope_stats = scan_pip_dependencies(
            ROOT,
            policy,
            ignore_dev_dependencies=not include_dev_groups,
            dev_dependency_names=dev_dependency_names,
            compiled_patterns=compiled_patterns,
        )
        findings.extend(scope_findings)
        stats["pip"].update(scope_stats)

        scope_findings, scope_stats = scan_pip_subvenvs(
            ROOT,
            policy,
            ignore_dev_dependencies=not include_dev_groups,
            dev_dependency_names=dev_dependency_names,
            compiled_patterns=compiled_patterns,
        )
        findings.extend(scope_findings)
        stats["pip-subvenv"].update(scope_stats)

    if scan_cfg.get("check_go_dependencies", True):
        scope_findings, scope_stats = scan_go_modules(ROOT, policy, compiled_patterns=compiled_patterns)
        findings.extend(scope_findings)
        stats["go"].update(scope_stats)

    if scan_cfg.get("check_rust_dependencies", True):
        scope_findings, scope_stats = scan_rust_modules(ROOT, policy, compiled_patterns=compiled_patterns)
        findings.extend(scope_findings)
        stats["rust"].update(scope_stats)

    # De-duplicate findings by signature to avoid noisy duplicates from nested workspaces.
    deduped = []
    seen_signatures: Set[Tuple[str, str, str, str, str, bool]] = set()
    for finding in findings:
        signature = (
            finding.scope,
            finding.source,
            finding.package,
            finding.license_value,
            finding.reason,
            finding.is_warning,
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        deduped.append(finding)

    print_summary(deduped, stats, ROOT, summary_only=args.summary_only)

    if not args.no_report:
        write_json_report(Path(args.report_json), deduped, stats)

    errors = [finding for finding in deduped if not finding.is_warning]
    warnings = [finding for finding in deduped if finding.is_warning]
    if errors:
        print(f"License check failed: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print("License check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
