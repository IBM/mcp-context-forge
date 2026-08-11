# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_praxis_container_contract.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Executable contracts for the dedicated Praxis dataplane image.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
CONTAINERFILE = ROOT / "Containerfile.praxis"
MAKEFILE = ROOT / "Makefile"
DATAPLANE_MANIFEST = ROOT / "crates/praxis_cf_dataplane/Cargo.toml"
GOLDEN_ROOT = ROOT / "crates/praxis_config_launcher/fixtures/golden"
FULL_REVISION = "ed46eb5347d99b7aaf1fe67fa40f8c9178b7aa88"  # pragma: allowlist secret
SHORT_REVISION = "ed46eb5"
PRAXIS_IMAGE = os.environ.get("PRAXIS_DATAPLANE_IMAGE", "praxis-dataplane:review-a")


def _containerfile() -> str:
    return CONTAINERFILE.read_text(encoding="utf-8")


def _assert_contract(definition: str) -> None:
    from_lines = [line for line in definition.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 2
    assert all(re.fullmatch(r"FROM [^\s:@]+(?:/[^\s:@]+)*@sha256:[0-9a-f]{64}(?: AS \w+)?", line) for line in from_lines)
    assert FULL_REVISION in definition
    assert "cargo build --locked" in definition
    assert "SOURCE_DATE_EPOCH=0" in definition
    assert "--remap-path-prefix=" in definition
    assert "USER 65532:65532" in definition
    assert 'ENTRYPOINT ["/usr/local/bin/praxis_config_launcher"]' in definition
    assert "EXPOSE" not in definition
    assert "COPY . " not in definition
    assert "COPY . /" not in definition
    assert "/run/secrets/praxis/token:ro" in definition
    assert "/run/secrets/praxis/ca.pem:ro" in definition
    assert 'VOLUME ["/var/lib/praxis"]' in definition
    for filter_name in ("mcp", "cpex", "cf_control_plane_data", "cf_tools_router", "cf_mcp_broker", "cf_upstream_proxy"):
        assert f'io.contextforge.praxis.filter.{filter_name}="registered"' in definition


def _validate_bundle(bundle_root: Path) -> subprocess.CompletedProcess[str]:
    created = subprocess.run(
        [
            "docker",
            "create",
            PRAXIS_IMAGE,
            "--validate-bundle",
            "/bundle",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    container_id = created.stdout.strip()
    try:
        subprocess.run(
            ["docker", "cp", str(bundle_root), f"{container_id}:/bundle"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return subprocess.run(
            ["docker", "start", "--attach", container_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


def _require_praxis_image() -> None:
    """Skip image-backed contract tests unless the pinned dataplane image is local."""
    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH; cannot run image-backed contract test")
    inspected = subprocess.run(
        ["docker", "image", "inspect", PRAXIS_IMAGE],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inspected.returncode != 0:
        pytest.skip(f"Local dataplane image {PRAXIS_IMAGE!r} not present — run `make docker-praxis-dataplane` first to enable this test.")


def test_dedicated_definition_satisfies_complete_contract() -> None:
    _assert_contract(_containerfile())
    assert "docker-praxis-dataplane:" in MAKEFILE.read_text(encoding="utf-8")


def test_wrong_revision_is_refused() -> None:
    mutated = _containerfile().replace(FULL_REVISION, "0" * 40)
    with pytest.raises(AssertionError):
        _assert_contract(mutated)


def test_mutable_base_is_refused() -> None:
    mutated = re.sub(r"@sha256:[0-9a-f]{64}", ":latest", _containerfile(), count=1)
    with pytest.raises(AssertionError):
        _assert_contract(mutated)


def test_missing_filter_is_refused() -> None:
    mutated = _containerfile().replace('io.contextforge.praxis.filter.cpex="registered"', 'io.contextforge.praxis.filter.cpex="missing"')
    with pytest.raises(AssertionError):
        _assert_contract(mutated)


def test_root_user_is_refused() -> None:
    mutated = _containerfile().replace("USER 65532:65532", "USER 0:0")
    with pytest.raises(AssertionError):
        _assert_contract(mutated)


def test_writable_secret_is_refused() -> None:
    mutated = _containerfile().replace("/run/secrets/praxis/token:ro", "/run/secrets/praxis/token:rw")
    with pytest.raises(AssertionError):
        _assert_contract(mutated)


def test_golden_bundle_validates_with_native_praxis() -> None:
    _require_praxis_image()
    result = _validate_bundle(GOLDEN_ROOT)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_invalid_bundle_is_refused(tmp_path: Path) -> None:
    _require_praxis_image()
    bundle_root = tmp_path / "bundle"
    shutil.copytree(GOLDEN_ROOT, bundle_root)
    config_path = bundle_root / "praxis.yaml"
    config = config_path.read_text(encoding="utf-8").replace(
        "cpex/platform--server-public.yaml",
        "cpex/missing.yaml",
        1,
    )
    config_path.write_text(config, encoding="utf-8")

    result = _validate_bundle(bundle_root)

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "Praxis process supervision failed: Praxis rejected the bundle\n"


def test_manifest_and_image_share_the_authoritative_source() -> None:
    manifest = DATAPLANE_MANIFEST.read_text(encoding="utf-8")
    definition = _containerfile()
    assert 'git = "https://github.com/praxis-proxy/praxis"' in manifest
    assert f'rev = "{SHORT_REVISION}"' in manifest
    assert FULL_REVISION in definition
