# -*- coding: utf-8 -*-
"""Cross-target payload normalization for drift detection.

Location: ./tests/live_gateway/a2a_compliance/helpers/drift.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The harness compares responses from ``reference``, ``gateway_proxy``,
and ``gateway_virtual`` and asserts that — after accounting for
legitimate gateway decoration — they're structurally equal. Divergence
that survives normalization is drift.

Phase 1 status: gateway targets are entirely ``xfail`` pending native
A2A passthrough (see A2A-GAP-001), so drift comparison has only one
data point (``reference``) per probe. The helpers here are minimal
stubs that ``assert_drift_free`` will skip cleanly when fewer than two
targets are available. When gateway targets land, fill in the
agent-card / task / message normalization the same way
``protocol_compliance/helpers/drift.py`` does for MCP.
"""

from __future__ import annotations

from typing import Any


def _to_dict(payload: Any) -> dict[str, Any]:
    """Coerce a pydantic model / dict / mapping into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="python", exclude_none=True)
    if isinstance(payload, dict):
        return dict(payload)
    return dict(payload)


def normalize_agent_card(card: Any) -> dict[str, Any]:
    """Reduce an AgentCard to fields that encode protocol behavior.

    Strips transient / decoration fields the gateway is allowed to
    rewrite (currently a no-op pending gateway target support).
    """
    return _to_dict(card)


def normalize_task(task: Any) -> dict[str, Any]:
    """Reduce a Task to behavior-encoding fields. Strips ``meta`` / ``_meta``."""
    payload = _to_dict(task)
    payload.pop("meta", None)
    payload.pop("_meta", None)
    return payload


def assert_drift_free(results_by_target: dict[str, Any], *, probe: str) -> None:
    """Pairwise-compare normalized results, skipping unavailable targets.

    Raises ``AssertionError`` with a readable diff if any two available
    targets disagree. Silently returns if fewer than two targets are
    available — drift can't be assessed from one data point.
    """
    available = {k: v for k, v in results_by_target.items() if v is not None}
    if len(available) < 2:
        return

    items = list(available.items())
    first_name, first_value = items[0]
    for other_name, other_value in items[1:]:
        assert first_value == other_value, f"drift on probe {probe!r} between {first_name} and {other_name}:\n" f"  {first_name}: {first_value!r}\n" f"  {other_name}: {other_value!r}"
