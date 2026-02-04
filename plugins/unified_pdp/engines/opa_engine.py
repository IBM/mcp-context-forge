"""OPA (Open Policy Agent) engine adapter.

How it works
------------
The gateway already ships an OPA sidecar (see ``plugins/opa``) that exposes
the standard OPA REST API.  This adapter does **not** re-implement OPA; it
speaks to the sidecar over HTTP using ``httpx``.

OPA evaluation endpoint::

    POST  /v1/data/{policy_path}
    Body: { "input": { ... } }
    →     { "result": { "allow": true | false, "deny": [...reasons] } }

Policy path
-----------
Configurable via ``settings.policy_path`` (default ``mcpgateway``).  The
adapter POSTs to ``/v1/data/{policy_path}/allow``.

Retry
-----
On connection errors or 5xx responses the adapter retries up to
``settings.max_retries`` times (default 3) with exponential back-off capped
at 1 s.  A ``PolicyEngineUnavailableError`` is raised only after all retries
are exhausted.
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

# Default OPA settings – all overridable via EngineConfig.settings
_DEFAULTS: Dict[str, Any] = {
    "opa_url": "http://localhost:8181",
    "policy_path": "mcpgateway",
    "timeout_ms": 5000,
    "max_retries": 3,
}


def _merge_settings(user: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user-provided settings with default OPA configuration.

    Args:
        user: User-provided settings dictionary (may be empty).

    Returns:
        Combined settings with user values overriding defaults.
    """
    return {**_DEFAULTS, **user}


class OPAEngineAdapter(PolicyEngineAdapter):
    """Adapter that delegates policy evaluation to an OPA sidecar via HTTP.

    Communicates with OPA via POST to /v1/data/{policy_path}, with automatic
    retry on 5xx errors and network failures using exponential backoff.

    Args:
        settings: Configuration with opa_url, policy_path, timeout_ms, max_retries.

    Attributes:
        _settings: Merged configuration with defaults.
        _base_url: OPA sidecar base URL.
        _policy_path: Rego policy path for evaluation.
        _timeout: Request timeout in seconds.
        _max_retries: Maximum retry attempts on failure.
        _client: Lazy-initialized async HTTP client.
    """

    def __init__(self, settings: Dict[str, Any] | None = None):
        """Initialize the OPA engine adapter.

        Args:
            settings: Optional configuration overrides for opa_url (default
                localhost:8181), policy_path (default "mcpgateway"),
                timeout_ms (default 5000), max_retries (default 3).
        """
        self._settings = _merge_settings(settings or {})
        self._base_url: str = self._settings["opa_url"].rstrip("/")
        self._policy_path: str = self._settings["policy_path"]
        self._timeout: float = self._settings["timeout_ms"] / 1000.0
        self._max_retries: int = self._settings["max_retries"]
        # Shared async client – created lazily so __init__ doesn't need an event loop
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> EngineType:
        """Return the engine type identifier for OPA.

        Returns:
            EngineType.OPA enum value.
        """
        return EngineType.OPA

    # ------------------------------------------------------------------
    # Shared client
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx client, creating it lazily if needed.

        Creates the client on first call to avoid needing an event loop at
        initialization time.

        Returns:
            Configured AsyncClient for OPA sidecar communication.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_input(subject: Subject, action: str, resource: Resource, context: Context) -> Dict[str, Any]:
        """Translate PDP request types into the flat dict OPA expects as input.

        Args:
            subject: The authenticated user/principal.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.

        Returns:
            Dictionary with subject, action, resource, context keys matching
            OPA's expected input document structure.
        """
        return {
            "subject": {
                "email": subject.email,
                "roles": subject.roles,
                "team_id": subject.team_id,
                "mfa_verified": subject.mfa_verified,
                "clearance_level": subject.clearance_level,
                **subject.attributes,
            },
            "action": action,
            "resource": {
                "type": resource.type,
                "id": resource.id,
                "server": resource.server,
                "classification_level": resource.classification_level,
                **resource.annotations,
            },
            "context": {
                "ip": context.ip,
                "timestamp": context.timestamp.isoformat(),
                "user_agent": context.user_agent,
                "session_id": context.session_id,
                **context.extra,
            },
        }

    async def evaluate(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> EngineDecision:
        """POST to OPA's data API and interpret the response.

        Sends request to /v1/data/{policy_path} with exponential backoff on
        5xx/network errors. Retries up to max_retries times.

        Args:
            subject: The authenticated user/principal.
            action: The action being performed.
            resource: The resource being accessed.
            context: Request context.

        Returns:
            EngineDecision with ALLOW/DENY verdict, reasons, and timing.

        Raises:
            PolicyEvaluationError: On 4xx client errors (no retry).
            PolicyEngineUnavailableError: After all retries exhausted.
        """
        input_doc = self._build_input(subject, action, resource, context)
        url = f"/v1/data/{self._policy_path}"
        payload = {"input": input_doc}

        start = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._get_client().post(url, json=payload)

                if resp.status_code == 200:
                    duration = (time.perf_counter() - start) * 1000
                    return self._parse_response(resp.json(), duration)

                if resp.status_code >= 500:
                    last_error = PolicyEvaluationError(
                        EngineType.OPA,
                        f"OPA returned HTTP {resp.status_code}: {resp.text[:200]}",
                    )
                else:
                    # 4xx – don't retry, these are caller errors
                    raise PolicyEvaluationError(
                        EngineType.OPA,
                        f"OPA returned HTTP {resp.status_code}: {resp.text[:200]}",
                    )

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = PolicyEngineUnavailableError(EngineType.OPA, str(exc), cause=exc)

            # Exponential back-off: 0.1s, 0.2s, 0.4s …  capped at 1s
            if attempt < self._max_retries:
                wait = min(0.1 * (2 ** (attempt - 1)), 1.0)
                logger.warning("OPA attempt %d/%d failed – retrying in %.1fs", attempt, self._max_retries, wait)
                await asyncio.sleep(wait)

        # All retries exhausted
        raise last_error or PolicyEngineUnavailableError(EngineType.OPA, "All retries exhausted")

    @staticmethod
    def _parse_response(body: Dict[str, Any], duration_ms: float) -> EngineDecision:
        """Interpret OPA's response document.

        Expected shapes:
        - Allowed: { "result": { "allow": true } }
        - Denied: { "result": { "allow": false, "deny": ["reason1", ...] } }
        - Undefined: { "result": {} } or {} (fail-closed to DENY)

        Args:
            body: JSON response body from OPA.
            duration_ms: Request duration in milliseconds for timing info.

        Returns:
            EngineDecision with parsed verdict, reasons, and metadata.
        """
        result = body.get("result", {})

        # If OPA returned no result at all, treat as deny (fail-closed)
        if not result:
            return EngineDecision(
                engine=EngineType.OPA,
                decision=Decision.DENY,
                reason="OPA: no matching policy (undefined result – fail closed)",
                duration_ms=round(duration_ms, 2),
            )

        allowed = result.get("allow", False)
        deny_reasons: List[str] = result.get("deny", [])

        return EngineDecision(
            engine=EngineType.OPA,
            decision=Decision.ALLOW if allowed else Decision.DENY,
            reason="; ".join(deny_reasons) if deny_reasons else ("OPA: allowed" if allowed else "OPA: denied"),
            matching_policies=deny_reasons if not allowed else [],
            duration_ms=round(duration_ms, 2),
            metadata={"raw_result": result},
        )

    # ------------------------------------------------------------------
    # Health check  (uses OPA's dedicated /health endpoint)
    # ------------------------------------------------------------------

    async def health_check(self) -> EngineHealthReport:
        """Check OPA health via GET /health endpoint.

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
                    engine=EngineType.OPA,
                    status=EngineStatus.HEALTHY,
                    latency_ms=round(latency, 2),
                )
            return EngineHealthReport(
                engine=EngineType.OPA,
                status=EngineStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                detail=f"OPA /health returned {resp.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return EngineHealthReport(
                engine=EngineType.OPA,
                status=EngineStatus.UNHEALTHY,
                detail=str(exc),
            )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the shared httpx client and release network resources.

        Should be called during shutdown to cleanly close connections.
        Safe to call multiple times (idempotent).
        """
        if self._client:
            await self._client.aclose()
            self._client = None
