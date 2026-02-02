"""Cedar engine adapter.

How it works
------------
AWS Cedar is a policy language designed for fine-grained authorisation.
The gateway ships (or will ship, via PR #1499) a ``cedar-agent`` sidecar
that exposes an HTTP authorization endpoint::

    POST  /v1/authorize
    Body: {
        "principal":  { "type": "User",     "id": "user@example.com" },
        "action":     { "type": "Action",   "id": "tools.invoke" },
        "resource":   { "type": "Tool",     "id": "db-query" },
        "context":    { "ip": "…", … },
        "entities":   [ … ]        ← optional entity graph
    }
    →     { "decision": "Allow" | "Deny", "reasons": [ … ] }

Entity graph
------------
Cedar's ``entities`` block lets you express role-hierarchy and group
membership outside the policy itself.  This adapter builds a minimal entity
list from ``Subject.roles`` so that Cedar policies can reference roles
directly::

    { "type": "Role", "id": "admin", "parents": [] }

Configuration
-------------
All tunables live in ``EngineConfig.settings``::

    cedar_url   – base URL of the cedar-agent sidecar   (default localhost:8700)
    timeout_ms  – per-request timeout                   (default 5000)
    max_retries – retry count on 5xx / network failure  (default 3)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

import httpx

from ..adapter import PolicyEngineAdapter, PolicyEvaluationError, PolicyEngineUnavailableError
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

_DEFAULTS: Dict[str, Any] = {
    "cedar_url": "http://localhost:8700",
    "timeout_ms": 5000,
    "max_retries": 3,
}


def _merge(user: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user-provided settings with default Cedar configuration.

    Args:
        user: User-provided settings dictionary (may be empty).

    Returns:
        Combined settings with user values overriding defaults.
    """
    return {**_DEFAULTS, **user}


# Cedar type mappings – kept as module-level constants for clarity
_RESOURCE_TYPE_MAP = {
    "tool": "Tool",
    "resource": "Resource",
    "prompt": "Prompt",
    "server": "Server",
}


class CedarEngineAdapter(PolicyEngineAdapter):
    """Adapter that delegates policy evaluation to a cedar-agent sidecar.

    Communicates with Cedar via HTTP POST to /v1/authorize, with automatic
    retry on 5xx errors and network failures using exponential backoff.

    Args:
        settings: Configuration dictionary with cedar_url, timeout_ms, max_retries.

    Attributes:
        _settings: Merged configuration with defaults.
        _base_url: Cedar agent base URL.
        _timeout: Request timeout in seconds.
        _max_retries: Maximum retry attempts on failure.
        _client: Lazy-initialized async HTTP client.
    """

    def __init__(self, settings: Dict[str, Any] | None = None):
        """Initialize the Cedar engine adapter.

        Args:
            settings: Optional configuration overrides for cedar_url (default
                localhost:8700), timeout_ms (default 5000), max_retries (default 3).
        """
        self._settings = _merge(settings or {})
        self._base_url: str = self._settings["cedar_url"].rstrip("/")
        self._timeout: float = self._settings["timeout_ms"] / 1000.0
        self._max_retries: int = self._settings["max_retries"]
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> EngineType:
        """Return the engine type identifier for Cedar.

        Returns:
            EngineType.CEDAR enum value.
        """
        return EngineType.CEDAR

    # ------------------------------------------------------------------
    # Shared client
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx client, creating it lazily if needed.

        Creates the client on first call to avoid needing an event loop at
        initialization time.

        Returns:
            Configured AsyncClient for Cedar agent communication.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_entities(subject: Subject) -> List[Dict[str, Any]]:
        """Build Cedar's entity graph from the subject's roles.

        Each role becomes a Role entity. The User entity lists all roles as
        parents so Cedar can traverse the hierarchy for role-based policies.

        Args:
            subject: The authenticated user with roles to convert to entities.

        Returns:
            List of Cedar entity dictionaries (Role entities + User entity).
        """
        entities: List[Dict[str, Any]] = []

        # Role entities
        for role in subject.roles:
            entities.append({
                "identifier": {"type": "Role", "id": role},
                "attrs": {},
                "parents": [],
            })

        # User entity – parents are the roles
        entities.append({
            "identifier": {"type": "User", "id": subject.email},
            "attrs": {
                "team_id": subject.team_id or "",
                "mfa_verified": subject.mfa_verified,
                **(subject.attributes or {}),
            },
            "parents": [{"type": "Role", "id": r} for r in subject.roles],
        })

        return entities

    @staticmethod
    def _build_request(subject: Subject, action: str, resource: Resource, context: Context) -> Dict[str, Any]:
        """Build the Cedar authorization request payload for POST /v1/authorize.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed (becomes Action entity).
            resource: The resource being accessed (becomes typed Resource entity).
            context: Request context (IP, timestamp, session, etc.).

        Returns:
            Dictionary matching Cedar's authorization request schema with
            principal, action, resource, context, and entities.
        """
        cedar_resource_type = _RESOURCE_TYPE_MAP.get(resource.type, "Resource")

        return {
            "principal": {"type": "User", "id": subject.email},
            "action": {"type": "Action", "id": action},
            "resource": {
                "type": cedar_resource_type,
                "id": resource.id,
                "attrs": {
                    "server": resource.server or "",
                    "classification_level": resource.classification_level,
                    **(resource.annotations or {}),
                },
            },
            "context": {
                "ip": context.ip or "",
                "timestamp": context.timestamp.isoformat(),
                "user_agent": context.user_agent or "",
                "session_id": context.session_id or "",
                **(context.extra or {}),
            },
            "entities": CedarEngineAdapter._build_entities(subject),
        }

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
        """Evaluate a policy decision against the Cedar agent with retries.

        POSTs to /v1/authorize with exponential backoff on 5xx/network errors.
        Retries up to max_retries times before raising an error.

        Args:
            subject: The authenticated user/principal requesting access.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.

        Returns:
            EngineDecision with ALLOW/DENY verdict, reasons, and timing.

        Raises:
            PolicyEvaluationError: On 4xx client errors (no retry).
            PolicyEngineUnavailableError: After all retries exhausted.
        """
        payload = self._build_request(subject, action, resource, context)
        start = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._get_client().post("/v1/authorize", json=payload)

                if resp.status_code == 200:
                    duration = (time.perf_counter() - start) * 1000
                    return self._parse_response(resp.json(), duration)

                if resp.status_code >= 500:
                    last_error = PolicyEvaluationError(
                        EngineType.CEDAR,
                        f"Cedar returned HTTP {resp.status_code}: {resp.text[:200]}",
                    )
                else:
                    raise PolicyEvaluationError(
                        EngineType.CEDAR,
                        f"Cedar returned HTTP {resp.status_code}: {resp.text[:200]}",
                    )

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = PolicyEngineUnavailableError(EngineType.CEDAR, str(exc), cause=exc)

            if attempt < self._max_retries:
                wait = min(0.1 * (2 ** (attempt - 1)), 1.0)
                logger.warning("Cedar attempt %d/%d failed – retrying in %.1fs", attempt, self._max_retries, wait)
                await asyncio.sleep(wait)

        raise last_error or PolicyEngineUnavailableError(EngineType.CEDAR, "All retries exhausted")

    @staticmethod
    def _parse_response(body: Dict[str, Any], duration_ms: float) -> EngineDecision:
        """Interpret cedar-agent's authorization response.

        Expected format: { "decision": "Allow" | "Deny", "reasons": ["..."] }

        Args:
            body: JSON response body from Cedar agent.
            duration_ms: Request duration in milliseconds for timing info.

        Returns:
            EngineDecision with parsed verdict, reasons, and metadata.
        """
        raw_decision = body.get("decision", "Deny")
        reasons: List[str] = body.get("reasons", [])
        allowed = raw_decision.lower() == "allow"

        return EngineDecision(
            engine=EngineType.CEDAR,
            decision=Decision.ALLOW if allowed else Decision.DENY,
            reason="; ".join(reasons) if reasons else ("Cedar: allowed" if allowed else "Cedar: denied"),
            matching_policies=reasons if not allowed else [],
            duration_ms=round(duration_ms, 2),
            metadata={"raw_decision": raw_decision, "reasons": reasons},
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> EngineHealthReport:
        """Check Cedar agent health via GET /health endpoint.

        Returns:
            EngineHealthReport with HEALTHY status on 200 response,
            UNHEALTHY with detail message on any error or non-200 status.
        """
        start = time.perf_counter()
        try:
            resp = await self._get_client().get("/health")
            latency = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                return EngineHealthReport(
                    engine=EngineType.CEDAR,
                    status=EngineStatus.HEALTHY,
                    latency_ms=round(latency, 2),
                )
            return EngineHealthReport(
                engine=EngineType.CEDAR,
                status=EngineStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                detail=f"Cedar /health returned {resp.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return EngineHealthReport(
                engine=EngineType.CEDAR,
                status=EngineStatus.UNHEALTHY,
                detail=str(exc),
            )

    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the HTTP client and release network resources.

        Should be called during shutdown to cleanly close connections.
        Safe to call multiple times (idempotent).
        """
        if self._client:
            await self._client.aclose()
            self._client = None
