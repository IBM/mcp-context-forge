#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build provenance resolution for ContextForge.
Location: ./mcpgateway/build_info.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Resolve release-tag and source-revision metadata before a container build, then
read the embedded result at runtime without requiring Git or network access.
"""

# Future
from __future__ import annotations

# Standard
import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Sequence

# First-Party
from mcpgateway import __version__

_BUILD_INFO_PATH = Path(__file__).with_name("_build_info.json")
_COMMIT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_RELEASE_TAG_PATTERN = "v[0-9]*"


@dataclass(frozen=True)
class BuildInfo:
    """Immutable version and source-revision metadata."""

    display_version: str
    commit_sha: str
    base_version: str


def _package_tag(package_version: str) -> str:
    """Return the package version in the repository's release-tag form."""
    return package_version if package_version.startswith("v") else f"v{package_version}"


def _git_output(repository: Path, arguments: Sequence[str]) -> str | None:
    """Run a read-only Git query and return its stripped output when available."""
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    output = result.stdout.strip()
    return output if result.returncode == 0 and output else None


def resolve_build_info(
    repository: Path,
    *,
    package_version: str = __version__,
    build_sha: str | None = None,
) -> BuildInfo:
    """Resolve deterministic display and full-SHA metadata for one source tree."""
    package_tag = _package_tag(package_version)
    revision = build_sha or "HEAD"
    full_sha = _git_output(repository, ["rev-parse", f"{revision}^{{commit}}"])

    if full_sha is None:
        supplied_sha = (build_sha or "").lower()
        if _COMMIT_PATTERN.fullmatch(supplied_sha):
            return BuildInfo(
                display_version=f"{package_tag}+{supplied_sha[:9]}",
                commit_sha=supplied_sha,
                base_version=package_tag,
            )
        return BuildInfo(
            display_version=f"{package_tag}+unknown",
            commit_sha="unknown",
            base_version=package_tag,
        )

    full_sha = full_sha.lower()
    exact_tag = _git_output(
        repository,
        ["describe", "--tags", "--exact-match", "--match", _RELEASE_TAG_PATTERN, full_sha],
    )
    if exact_tag is not None:
        return BuildInfo(
            display_version=exact_tag,
            commit_sha=full_sha,
            base_version=exact_tag,
        )

    nearest_tag = _git_output(
        repository,
        ["describe", "--tags", "--abbrev=0", "--match", _RELEASE_TAG_PATTERN, full_sha],
    )
    base_version = nearest_tag or package_tag
    return BuildInfo(
        display_version=f"{base_version}+{full_sha[:9]}",
        commit_sha=full_sha,
        base_version=base_version,
    )


def write_build_info(build_info: BuildInfo, destination: Path = _BUILD_INFO_PATH) -> None:
    """Atomically write build metadata for inclusion in an image or package."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(asdict(build_info), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def get_build_info(source: Path = _BUILD_INFO_PATH) -> BuildInfo:
    """Read embedded metadata, falling back safely when it is absent or invalid."""
    fallback = BuildInfo(
        display_version=f"{_package_tag(__version__)}+unknown",
        commit_sha="unknown",
        base_version=_package_tag(__version__),
    )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback

    if not isinstance(payload, dict):
        return fallback

    display_version = payload.get("display_version")
    commit_sha = payload.get("commit_sha")
    base_version = payload.get("base_version")
    if not isinstance(display_version, str) or not display_version:
        return fallback
    if not isinstance(commit_sha, str) or not commit_sha:
        return fallback
    if not isinstance(base_version, str) or not base_version:
        return fallback
    if commit_sha != "unknown" and _COMMIT_PATTERN.fullmatch(commit_sha) is None:
        return fallback

    return BuildInfo(
        display_version=display_version,
        commit_sha=commit_sha,
        base_version=base_version,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Generate embedded build metadata and print the display version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--package-version", default=__version__)
    parser.add_argument("--build-sha")
    parser.add_argument("--output", type=Path, default=_BUILD_INFO_PATH)
    parsed = parser.parse_args(arguments)

    build_info = resolve_build_info(
        parsed.repository,
        package_version=parsed.package_version,
        build_sha=parsed.build_sha,
    )
    write_build_info(build_info, parsed.output)
    print(build_info.display_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
