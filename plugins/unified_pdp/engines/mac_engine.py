# -*- coding: utf-8 -*-
"""MAC (Bell–LaPadula) engine adapter – mandatory access control.

Bell–LaPadula model
-------------------
Two core invariants govern every decision:

1. **Simple Security Property (no read-up):**
   A subject may *read* a resource only if its clearance level is ≥ the
   resource's classification level.

2. **Star Property (no write-down):**
   A subject may *write* a resource only if its clearance level is ≤ the
   resource's classification level.  (In practice, for an API gateway we
   relax this to: writes are only allowed when clearance == classification,
   unless ``settings.relaxed_star`` is ``true``.)

Classification levels
---------------------
Levels are non-negative integers.  Higher = more sensitive.  A conventional
mapping might be::

    0 = PUBLIC
    1 = INTERNAL
    2 = CONFIDENTIAL
    3 = SECRET
    4 = TOP SECRET

Both ``Subject.clearance_level`` and ``Resource.classification_level`` must
be set for this engine to produce a meaningful decision.  If either is
``None``, the engine returns DENY with an explanatory reason.

Read vs write detection
-----------------------
The adapter infers the operation type from the ``action`` string:

* Actions containing ``read``, ``get``, ``list``, ``fetch``, or ``invoke``
  are treated as *reads*.
* Everything else is treated as a *write*.

This can be overridden by adding ``"operation": "read" | "write"`` to
``Context.extra``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from ..adapter import PolicyEngineAdapter
from ..pdp_models import (
    Context,
    Decision,
    EngineDecision,
    EngineHealthReport,
    EngineStatus,
    EngineType,
    Resource,
    Subject,
)

logger = logging.getLogger(__name__)

# Actions that are considered "reads"
_READ_KEYWORDS = {"read", "get", "list", "fetch", "invoke", "call", "describe", "health"}


def _is_read(action: str, context: Context) -> bool:
    """Determine whether the action is a read or write operation.

    Uses explicit override from context.extra["operation"] if present,
    otherwise infers from action string keywords (read, get, list, etc.).

    Args:
        action: The action string to analyze.
        context: Request context, may contain explicit operation override.

    Returns:
        True if this is a read operation, False for write operations.
    """
    # Allow explicit override via context
    explicit = context.extra.get("operation")
    if explicit in ("read", "write"):
        return explicit == "read"

    # Heuristic: if any read keyword appears in the action (case-insensitive)
    action_lower = action.lower()
    return any(kw in action_lower for kw in _READ_KEYWORDS)


class MACEngineAdapter(PolicyEngineAdapter):
    """Bell-LaPadula mandatory access control engine.

    Implements the two core BLP invariants:
    - Simple Security Property (no read-up): clearance >= classification
    - Star Property (no write-down): clearance == classification (strict)
      or clearance >= classification (relaxed)

    Args:
        settings: Configuration with optional relaxed_star boolean.

    Attributes:
        _settings: Configuration dictionary.
        _relaxed_star: If True, allows writes at any level >= classification.
    """

    def __init__(self, settings: Dict[str, Any] | None = None):
        """Initialize the MAC engine adapter.

        Args:
            settings: Optional configuration. Use relaxed_star=True to allow
                writes when clearance >= classification (default False requires
                clearance == classification per standard BLP).
        """
        self._settings = settings or {}
        self._relaxed_star: bool = self._settings.get("relaxed_star", False)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> EngineType:
        """Return the engine type identifier for MAC.

        Returns:
            EngineType.MAC enum value.
        """
        return EngineType.MAC

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> EngineDecision:
        """Evaluate access using Bell-LaPadula mandatory access control.

        Applies Simple Security Property for reads (no read-up) and
        Star Property for writes (no write-down). Both subject.clearance_level
        and resource.classification_level must be set; otherwise DENY.

        Args:
            subject: User with clearance_level set.
            action: Action string used to infer read/write operation.
            resource: Resource with classification_level set.
            context: May contain operation override in extra["operation"].

        Returns:
            EngineDecision with ALLOW/DENY, BLP policy matched, and levels.
        """
        start = time.perf_counter()

        # --- Guard: both levels must be present ---
        if subject.clearance_level is None:
            duration = (time.perf_counter() - start) * 1000
            return EngineDecision(
                engine=EngineType.MAC,
                decision=Decision.DENY,
                reason="MAC: subject has no clearance_level set – denied by default",
                duration_ms=round(duration, 2),
            )

        if resource.classification_level is None:
            duration = (time.perf_counter() - start) * 1000
            return EngineDecision(
                engine=EngineType.MAC,
                decision=Decision.DENY,
                reason="MAC: resource has no classification_level set – denied by default",
                duration_ms=round(duration, 2),
            )

        subj_level = subject.clearance_level
        res_level = resource.classification_level
        read = _is_read(action, context)

        # --- BLP evaluation ---
        if read:
            # Simple Security Property: clearance >= classification
            if subj_level >= res_level:
                duration = (time.perf_counter() - start) * 1000
                return EngineDecision(
                    engine=EngineType.MAC,
                    decision=Decision.ALLOW,
                    reason=f"MAC: read allowed (clearance {subj_level} >= classification {res_level})",
                    matching_policies=["blp.simple_security"],
                    duration_ms=round(duration, 2),
                    metadata={"operation": "read", "subject_level": subj_level, "resource_level": res_level},
                )
            duration = (time.perf_counter() - start) * 1000
            return EngineDecision(
                engine=EngineType.MAC,
                decision=Decision.DENY,
                reason=f"MAC: read denied – clearance {subj_level} < classification {res_level} (no read-up)",
                matching_policies=["blp.simple_security"],
                duration_ms=round(duration, 2),
                metadata={"operation": "read", "subject_level": subj_level, "resource_level": res_level},
            )

        # Star Property: clearance <= classification (strict) or >= (relaxed)
        if self._relaxed_star:
            # Relaxed: allow if clearance >= classification
            allowed = subj_level >= res_level
        else:
            # Strict BLP: allow only if clearance == classification
            allowed = subj_level == res_level

        duration = (time.perf_counter() - start) * 1000
        if allowed:
            return EngineDecision(
                engine=EngineType.MAC,
                decision=Decision.ALLOW,
                reason=(
                    f"MAC: write allowed (clearance {subj_level} "
                    f"{'==' if not self._relaxed_star else '>='} classification {res_level})"
                ),
                matching_policies=["blp.star_property"],
                duration_ms=round(duration, 2),
                metadata={"operation": "write", "subject_level": subj_level, "resource_level": res_level},
            )
        else:
            return EngineDecision(
                engine=EngineType.MAC,
                decision=Decision.DENY,
                reason=(
                    f"MAC: write denied – clearance {subj_level} "
                    f"{'!=' if not self._relaxed_star else '<'} classification {res_level} (no write-down)"
                ),
                matching_policies=["blp.star_property"],
                duration_ms=round(duration, 2),
                metadata={"operation": "write", "subject_level": subj_level, "resource_level": res_level},
            )

    # ------------------------------------------------------------------
    # Health  (always healthy – pure in-process)
    # ------------------------------------------------------------------

    async def health_check(self) -> EngineHealthReport:
        """Return healthy status (pure in-process, no external dependencies).

        Returns:
            EngineHealthReport with HEALTHY status and relaxed_star config detail.
        """
        return EngineHealthReport(
            engine=EngineType.MAC,
            status=EngineStatus.HEALTHY,
            latency_ms=0.0,
            detail=f"relaxed_star={self._relaxed_star}",
        )
