"""Default-inert synchronization controls for the isolated Praxis E2E stack."""

from __future__ import annotations

import os
from pathlib import Path
import time


_CONTROL_ROOT = Path("/tmp/praxis-e2e-control")
_TIMEOUT_SECONDS = 60


class PraxisE2EControlError(RuntimeError):
    """Raised when an armed E2E synchronization control cannot complete safely."""


def wait_after_revalidation(target_id: str) -> None:
    """Block an explicitly armed E2E publication after source revalidation."""
    if os.getenv("PRAXIS_E2E_CONTROLS_ENABLED") != "true":
        return
    configured_root = os.getenv("PRAXIS_E2E_CONTROL_DIR")
    if configured_root != str(_CONTROL_ROOT):
        raise PraxisE2EControlError("invalid Praxis E2E control directory")
    arm = _CONTROL_ROOT / f"{target_id}.arm"
    if not arm.is_file():
        return
    reached = _CONTROL_ROOT / f"{target_id}.reached"
    release = _CONTROL_ROOT / f"{target_id}.release"
    reached.touch(exist_ok=True)
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while not release.is_file():
        if time.monotonic() >= deadline:
            raise PraxisE2EControlError("Praxis E2E publication barrier timed out")
        time.sleep(0.05)
    for path in (arm, reached, release):
        path.unlink(missing_ok=True)


__all__ = ("PraxisE2EControlError", "wait_after_revalidation")
