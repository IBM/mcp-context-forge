"""Abstract base class that every policy-engine adapter must implement.

Design notes
------------
* Every public method is ``async`` – the gateway is fully async and we never
  want a blocking engine call to stall the event loop.
* ``evaluate`` is the only method that *must* do real work.  ``health_check``
  has a sensible default (try a trivial evaluate); subclasses may override.
* Exceptions are intentionally narrow so the PDP orchestrator can catch and
  handle them uniformly regardless of which engine raised them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from .pdp_models import (
    EngineDecision,
    EngineHealthReport,
    EngineType,
    Permission,
    Subject,
    Context,
    Resource,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PolicyEvaluationError(Exception):
    """Raised when an engine fails to evaluate a request (network, timeout, etc.).

    Args:
        engine: The engine type that raised the error.
        message: Human-readable error description.
        cause: Optional underlying exception that caused this error.

    Attributes:
        engine: The engine type that raised the error.
        cause: The underlying exception, if any.
    """

    def __init__(self, engine: EngineType, message: str, cause: Exception | None = None):
        self.engine = engine
        self.cause = cause
        super().__init__(f"[{engine.value}] {message}")


class PolicyEngineUnavailableError(PolicyEvaluationError):
    """Specialisation: the engine back-end is completely unreachable."""


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------


class PolicyEngineAdapter(ABC):
    """Adapter interface for a single policy engine.

    Concrete subclasses
    -------------------
    * ``OPAEngineAdapter``     – wraps the existing OPA sidecar plugin
    * ``CedarEngineAdapter``   – wraps the Cedar RBAC plugin (PR #1499)
    * ``NativeRBACAdapter``    – pure-Python rule evaluator (no external dep)
    * ``MACEngineAdapter``     – Bell–LaPadula mandatory access-control
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def engine_type(self) -> EngineType:
        """Return the engine type identifier for this adapter.

        Returns:
            EngineType enum value identifying which policy engine this adapter wraps.
        """

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    @abstractmethod
    async def evaluate(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> EngineDecision:
        """Evaluate a single access request against this policy engine.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed (e.g., "tools.invoke.db-query").
            resource: The resource being accessed (tool, prompt, server, etc.).
            context: Request context including IP, timestamp, session info.

        Returns:
            EngineDecision containing the verdict (ALLOW/DENY), reason,
            matching policies, and timing information.

        Raises:
            PolicyEvaluationError: On any failure (network, timeout, invalid response).
        """

    # ------------------------------------------------------------------
    # Permissions enumeration  (optional – not all engines support it)
    # ------------------------------------------------------------------

    async def get_permissions(self, subject: Subject, context: Context) -> List[Permission]:
        """Return all permissions the subject holds according to this engine.

        The default implementation returns an empty list. Engines that can
        enumerate permissions (e.g., Native RBAC) should override this method.

        Args:
            subject: The authenticated user/principal to enumerate permissions for.
            context: Request context for conditional permission evaluation.

        Returns:
            List of Permission objects representing all granted permissions.
            Empty list if the engine does not support enumeration.
        """
        return []

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> EngineHealthReport:
        """Probe the engine and return its health status.

        The default implementation issues a trivial evaluate() call with
        dummy data and times it. Subclasses that have a cheaper probe
        (e.g., OPA's /health endpoint) should override this method.

        Returns:
            EngineHealthReport containing status (HEALTHY/UNHEALTHY),
            latency in milliseconds, and optional detail message on failure.
        """
        import time
        from .pdp_models import EngineStatus

        start = time.perf_counter()
        try:
            await self.evaluate(
                subject=Subject(email="__health__@pdp.internal"),
                action="pdp.health_check",
                resource=Resource(type="tool", id="__health__"),
                context=Context(),
            )
            latency = (time.perf_counter() - start) * 1000
            return EngineHealthReport(
                engine=self.engine_type,
                status=EngineStatus.HEALTHY,
                latency_ms=round(latency, 2),
            )
        except Exception as exc:  # noqa: BLE001
            return EngineHealthReport(
                engine=self.engine_type,
                status=EngineStatus.UNHEALTHY,
                detail=str(exc),
            )
