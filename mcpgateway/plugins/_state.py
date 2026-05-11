# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/_state.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module-local runtime state for the gateway plugin layer.

Keeping this state in a leaf module breaks import cycles between
``__init__.py`` and ``gateway_plugin_manager.py``.
"""

# Standard
from typing import Optional

# ---------------------------------------------------------------------------
# Per-plugin mode override map
# ---------------------------------------------------------------------------
_local_mode_overrides: dict[str, tuple[str, Optional[float]]] = {}


def set_local_mode_override(plugin_name: str, mode: str, expires_at: Optional[float]) -> None:
    """Write a local-override entry; ``expires_at=None`` means durable."""
    _local_mode_overrides[plugin_name] = (mode, expires_at)


def clear_local_mode_overrides() -> None:
    """Test-only reset hook."""
    _local_mode_overrides.clear()


def prune_expired_local_overrides(now: float) -> None:
    """Drop entries whose monotonic deadline has passed."""
    expired = [name for name, (_, exp) in _local_mode_overrides.items() if exp is not None and now >= exp]
    for name in expired:
        _local_mode_overrides.pop(name, None)


def active_local_mode_overrides(now: float) -> dict[str, str]:
    """Return a ``{name: mode}`` snapshot of non-expired entries."""
    return {name: mode for name, (mode, exp) in _local_mode_overrides.items() if exp is None or exp > now}


def get_local_mode_overrides_live() -> dict[str, tuple[str, Optional[float]]]:
    """Return the live backing dict for in-module reads (tests, helpers)."""
    return _local_mode_overrides


# ---------------------------------------------------------------------------
# Degraded-boot flag
# ---------------------------------------------------------------------------
_FACTORY_INIT_DEGRADED = False
_FACTORY_INIT_DEGRADED_LOGGED = False


def mark_factory_init_degraded() -> None:
    """Record that opportunistic factory init failed on this node."""
    global _FACTORY_INIT_DEGRADED
    _FACTORY_INIT_DEGRADED = True


def is_factory_init_degraded() -> bool:
    """Return True when the node booted with a failed opportunistic factory init."""
    return _FACTORY_INIT_DEGRADED


def mark_factory_init_degraded_logged() -> None:
    """Record that the one-shot ERROR has already been emitted."""
    global _FACTORY_INIT_DEGRADED_LOGGED
    _FACTORY_INIT_DEGRADED_LOGGED = True


def is_factory_init_degraded_logged() -> bool:
    """Return True once the one-shot ERROR has fired."""
    return _FACTORY_INIT_DEGRADED_LOGGED


def _reset_factory_init_degraded_for_tests() -> None:
    """Test-only reset hook."""
    global _FACTORY_INIT_DEGRADED, _FACTORY_INIT_DEGRADED_LOGGED
    _FACTORY_INIT_DEGRADED = False
    _FACTORY_INIT_DEGRADED_LOGGED = False
