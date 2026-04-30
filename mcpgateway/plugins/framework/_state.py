# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/_state.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Module-local runtime state for the plugin framework.

Keeping this state in a leaf module (rather than in ``framework/__init__.py``)
breaks what would otherwise be a ``framework -> framework.manager -> framework``
import cycle: ``manager.py`` needs the in-process override map to resolve the
Redis MGET fallback, and importing it from ``__init__.py`` would close the loop.
See ``scripts/pre-commit/check_framework_imports.py`` for the isolation-hook
context that motivates keeping framework internals free of upward dependencies.
"""

# Standard
from typing import Optional

# ---------------------------------------------------------------------------
# Per-plugin mode override map
# ---------------------------------------------------------------------------
# Each entry is ``(mode, expires_at)`` where ``expires_at`` is a monotonic
# clock deadline or ``None`` to mean "no expiry". Redis-synced entries carry
# an expiry that matches the Redis 24 h TTL so the local copy clears at the
# same time the Redis key does — otherwise a worker with a stale in-memory
# entry would keep applying an override the cluster has let expire. Local-only
# entries (Redis write failed, or no Redis provider registered) carry ``None``
# so single-node deployments don't lose the override at 24 h.
_local_mode_overrides: dict[str, tuple[str, Optional[float]]] = {}


def set_local_mode_override(plugin_name: str, mode: str, expires_at: Optional[float]) -> None:
    """Write a local-override entry; ``expires_at=None`` means durable."""
    _local_mode_overrides[plugin_name] = (mode, expires_at)


def clear_local_mode_overrides() -> None:
    """Test-only reset hook."""
    _local_mode_overrides.clear()


def prune_expired_local_overrides(now: float) -> None:
    """Drop entries whose monotonic deadline has passed.

    Callers pass ``time.monotonic()`` so the pruning condition stays monotonic
    across calls (wall-clock would skew under NTP adjustments). Entries with
    ``expires_at is None`` are durable and never pruned.
    """
    expired = [name for name, (_, exp) in _local_mode_overrides.items() if exp is not None and now >= exp]
    for name in expired:
        _local_mode_overrides.pop(name, None)


def active_local_mode_overrides(now: float) -> dict[str, str]:
    """Return a ``{name: mode}`` snapshot of non-expired entries.

    Pure read — callers that also want the dict cleaned should call
    ``prune_expired_local_overrides(now)`` first. Snapshot semantics decouple
    ``manager.py``'s rebuild hot path from mutation races with the pub/sub
    listener that concurrently writes via ``set_local_mode_override``.
    """
    return {name: mode for name, (mode, exp) in _local_mode_overrides.items() if exp is None or exp > now}


def get_local_mode_overrides_live() -> dict[str, tuple[str, Optional[float]]]:
    """Return the live backing dict for in-module reads (tests, helpers).

    Previously named ``get_local_mode_overrides_raw``; renamed to ``_live`` to
    admit what the return value really is. Production writers MUST go through
    ``set_local_mode_override`` / ``clear_local_mode_overrides``, not mutate
    the returned dict — the helper APIs are the module's single write seam.
    """
    return _local_mode_overrides


# ---------------------------------------------------------------------------
# Degraded-boot flag
# ---------------------------------------------------------------------------
# Two bools encode three reachable states: healthy (False, False),
# degraded-not-yet-logged (True, False), degraded-logged (True, True). The
# fourth combination is unreachable by construction — the logged bool is only
# flipped after the degraded bool. A future refactor that flips either flag
# independently must preserve "logged implies degraded".
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
    """Test-only reset hook (underscore-prefixed so production callers can't suppress the one-shot ERROR)."""
    global _FACTORY_INIT_DEGRADED, _FACTORY_INIT_DEGRADED_LOGGED
    _FACTORY_INIT_DEGRADED = False
    _FACTORY_INIT_DEGRADED_LOGGED = False
