#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ContextForge build provenance resolution.
Location: ./tests/unit/mcpgateway/test_build_info.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import json
from pathlib import Path
import subprocess

# Third-Party
from pytest import CaptureFixture, MonkeyPatch

# First-Party
from mcpgateway import build_info
from mcpgateway.build_info import BuildInfo, get_build_info, main, resolve_build_info, write_build_info


def _git(repository: Path, *arguments: str) -> str:
    """Run Git in a temporary test repository and return stdout."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    """Create a repository with one tagged release commit."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "ContextForge Tests")
    _git(tmp_path, "config", "user.email", "contextforge-tests@example.invalid")
    (tmp_path / "tracked.txt").write_text("release\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "release")
    _git(tmp_path, "tag", "v1.0.6")
    return tmp_path


def test_resolve_build_info_uses_exact_release_tag(tmp_path: Path) -> None:
    """An exact release commit renders the matching release tag."""
    repository = _repository(tmp_path)
    expected_sha = _git(repository, "rev-parse", "HEAD")

    result = resolve_build_info(repository, package_version="1.0.6")

    assert result == BuildInfo(
        display_version="v1.0.6",
        commit_sha=expected_sha,
        base_version="v1.0.6",
    )


def test_resolve_build_info_combines_nearest_tag_and_build_sha(tmp_path: Path) -> None:
    """A post-release build renders the nearest tag plus its own short SHA."""
    repository = _repository(tmp_path)
    (repository / "tracked.txt").write_text("post-release\n", encoding="utf-8")
    _git(repository, "commit", "--quiet", "-am", "post release")
    expected_sha = _git(repository, "rev-parse", "HEAD")

    result = resolve_build_info(repository, package_version="1.0.6", build_sha=expected_sha)

    assert result == BuildInfo(
        display_version=f"v1.0.6+{expected_sha[:9]}",
        commit_sha=expected_sha,
        base_version="v1.0.6",
    )


def test_resolve_build_info_uses_package_version_when_no_tag_exists(tmp_path: Path) -> None:
    """An untagged repository falls back to package version plus build SHA."""
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "ContextForge Tests")
    _git(tmp_path, "config", "user.email", "contextforge-tests@example.invalid")
    (tmp_path / "tracked.txt").write_text("untagged\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "untagged")
    expected_sha = _git(tmp_path, "rev-parse", "HEAD")

    result = resolve_build_info(tmp_path, package_version="1.0.6")

    assert result == BuildInfo(
        display_version=f"v1.0.6+{expected_sha[:9]}",
        commit_sha=expected_sha,
        base_version="v1.0.6",
    )


def test_resolve_build_info_survives_missing_git_metadata(tmp_path: Path) -> None:
    """A source tree without Git metadata does not make the build fail."""
    result = resolve_build_info(tmp_path, package_version="1.0.6")

    assert result == BuildInfo(
        display_version="v1.0.6+unknown",
        commit_sha="unknown",
        base_version="v1.0.6",
    )


def test_resolve_build_info_preserves_supplied_sha_without_git(tmp_path: Path) -> None:
    """A trusted build-system SHA remains available when Git is unavailable."""
    build_sha = "a" * 40

    result = resolve_build_info(tmp_path, package_version="1.0.6", build_sha=build_sha)

    assert result == BuildInfo(
        display_version=f"v1.0.6+{build_sha[:9]}",
        commit_sha=build_sha,
        base_version="v1.0.6",
    )


def test_resolve_build_info_survives_unavailable_git(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """An unavailable Git executable produces safe fallback metadata."""

    def unavailable(*_arguments: object, **_keywords: object) -> None:
        raise OSError("git unavailable")

    monkeypatch.setattr(build_info.subprocess, "run", unavailable)

    result = resolve_build_info(tmp_path, package_version="1.0.6")

    assert result.commit_sha == "unknown"
    assert result.display_version == "v1.0.6+unknown"


def test_write_and_get_build_info_round_trip(tmp_path: Path) -> None:
    """Embedded metadata round-trips without changing fields."""
    destination = tmp_path / "_build_info.json"
    expected = BuildInfo(
        display_version="v1.0.6+abcdef123",
        commit_sha="abcdef123" + ("0" * 31),
        base_version="v1.0.6",
    )

    write_build_info(expected, destination)

    assert get_build_info(destination) == expected


def test_get_build_info_survives_missing_file(tmp_path: Path) -> None:
    """A missing embedded file returns package-version fallback metadata."""
    result = get_build_info(tmp_path / "missing.json")

    assert result.commit_sha == "unknown"
    assert result.display_version.endswith("+unknown")


def test_get_build_info_rejects_invalid_shapes(tmp_path: Path) -> None:
    """Non-object and incomplete metadata never reaches the startup banner."""
    source = tmp_path / "_build_info.json"
    invalid_payloads = [
        [],
        {"display_version": 1, "commit_sha": "a" * 40, "base_version": "v1.0.6"},
        {"display_version": "v1.0.6", "commit_sha": None, "base_version": "v1.0.6"},
        {"display_version": "v1.0.6", "commit_sha": "a" * 40, "base_version": ""},
    ]

    for payload in invalid_payloads:
        source.write_text(json.dumps(payload), encoding="utf-8")
        assert get_build_info(source).commit_sha == "unknown"


def test_get_build_info_rejects_malformed_metadata(tmp_path: Path) -> None:
    """Malformed embedded metadata falls back instead of blocking startup."""
    source = tmp_path / "_build_info.json"
    source.write_text(
        json.dumps(
            {
                "display_version": "v1.0.6+forged",
                "commit_sha": "../not-a-commit",
                "base_version": "v1.0.6",
            }
        ),
        encoding="utf-8",
    )

    result = get_build_info(source)

    assert result.commit_sha == "unknown"
    assert result.display_version.endswith("+unknown")


def test_main_writes_embedded_metadata(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """The build CLI writes JSON and reports the resolved display version."""
    repository = _repository(tmp_path / "repository")
    output = tmp_path / "_build_info.json"

    result = main(
        [
            "--repository",
            str(repository),
            "--package-version",
            "1.0.6",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert capsys.readouterr().out.strip() == "v1.0.6"
    assert get_build_info(output).display_version == "v1.0.6"
