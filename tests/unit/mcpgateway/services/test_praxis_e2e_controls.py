# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_praxis_e2e_controls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the default-inert Praxis E2E synchronization controls.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mcpgateway.services import praxis_e2e_controls
from mcpgateway.services.praxis_e2e_controls import PraxisE2EControlError, wait_after_revalidation

CONTROL_ROOT = praxis_e2e_controls._CONTROL_ROOT


@pytest.fixture
def control_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Arm the controls against the real control root and restore it afterwards."""
    created_root = not CONTROL_ROOT.exists()
    CONTROL_ROOT.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PRAXIS_E2E_CONTROLS_ENABLED", "true")
    monkeypatch.setenv("PRAXIS_E2E_CONTROL_DIR", str(CONTROL_ROOT))
    yield CONTROL_ROOT
    for leftover in CONTROL_ROOT.glob("gate-test-*"):
        leftover.unlink(missing_ok=True)
    if created_root:
        CONTROL_ROOT.rmdir()


def test_disarmed_control_is_inert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRAXIS_E2E_CONTROLS_ENABLED", raising=False)

    wait_after_revalidation("gate-test-disarmed")

    assert not (CONTROL_ROOT / "gate-test-disarmed.reached").exists()


def test_armed_control_rejects_foreign_directory(control_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRAXIS_E2E_CONTROL_DIR", "/tmp/praxis-e2e-control-impostor")

    with pytest.raises(PraxisE2EControlError, match="invalid Praxis E2E control directory"):
        wait_after_revalidation("gate-test-foreign")


def test_armed_control_without_arm_file_returns(control_dir: Path) -> None:
    wait_after_revalidation("gate-test-unarmed")

    assert not (control_dir / "gate-test-unarmed.reached").exists()


def test_armed_control_marks_reached_and_cleans_up_on_release(control_dir: Path) -> None:
    arm = control_dir / "gate-test-released.arm"
    release = control_dir / "gate-test-released.release"
    reached = control_dir / "gate-test-released.reached"
    arm.touch()
    release.touch()

    wait_after_revalidation("gate-test-released")

    assert not arm.exists()
    assert not reached.exists()
    assert not release.exists()


def test_armed_control_times_out_without_release(control_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(praxis_e2e_controls, "_TIMEOUT_SECONDS", 0.2)
    (control_dir / "gate-test-timeout.arm").touch()

    with pytest.raises(PraxisE2EControlError, match="Praxis E2E publication barrier timed out"):
        wait_after_revalidation("gate-test-timeout")

    assert (control_dir / "gate-test-timeout.reached").is_file()
