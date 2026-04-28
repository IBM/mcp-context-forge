# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/runtime_state.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Runtime-mutable mode state for the public ``/mcp`` and A2A ingress paths.

Boot-time env vars (``RUST_MCP_MODE``, ``RUST_A2A_MODE``) still select the
initial transport at process start. This module layers an optional in-memory
override on top so an authorized admin can flip ``shadow ↔ edge`` for either
runtime without restarting the process.

Each runtime kind (``mcp``, ``a2a``) has its own override slot, monotonic
version counter, and last-change record. Overrides are not persisted to the
database. When Redis is available, overrides are propagated cluster-wide via
pub/sub on a single channel (each message carries a ``runtime`` field) plus a
short-lived per-runtime hint key so a freshly started pod reconciles to the
cluster's current desired override on boot. Without Redis the override is
local to the pod that received the PATCH; this is surfaced via the
``cluster_propagation`` field on the admin and ``/health`` responses.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from dataclasses import dataclass
from enum import StrEnum
import logging
import os
import time
from typing import Any, Dict, Optional, Union
import uuid

# Third-Party
import orjson

logger = logging.getLogger(__name__)

RUNTIME_STATE_CHANNEL = "contextforge:runtime:mode"
RUNTIME_STATE_HINT_KEY_PREFIX = "contextforge:runtime:mode_state"
RUNTIME_STATE_VERSION_KEY_PREFIX = "contextforge:runtime:mode_version"
RUNTIME_STATE_HINT_TTL_SECONDS = 24 * 60 * 60

# Consecutive ``get_message`` failures before the listen loop downgrades
# ``cluster_propagation`` from ``"redis"`` to ``"degraded"`` so /health and
# admin responses reflect that pub/sub is no longer healthy. A single
# successful receive re-promotes back to ``"redis"``.
LISTEN_LOOP_DEGRADE_THRESHOLD = 5


class RuntimeKind(StrEnum):
    """Runtime kinds whose public-ingress mode can be flipped at runtime.

    StrEnum members are ``str`` subclasses, so existing callers that compare
    against the literal strings (``"mcp"``, ``"a2a"``) continue to work
    transparently. The constructor (``RuntimeKind("mcp")``) doubles as a
    validator and raises ``ValueError`` on unknown values.
    """

    MCP = "mcp"
    A2A = "a2a"


class OverrideMode(StrEnum):
    """Modes that the runtime override can flip between at runtime."""

    SHADOW = "shadow"
    EDGE = "edge"


class ClusterPropagation(StrEnum):
    """Cluster-propagation status surfaced via /health and admin payloads.

    - ``REDIS``: coordinator is publishing/subscribing successfully.
    - ``DISABLED``: Redis is intentionally not configured for this deployment.
    - ``DEGRADED``: Redis is configured but the coordinator failed to attach
      (or pub/sub broke after startup, or boot reconciliation failed).
    """

    REDIS = "redis"
    DISABLED = "disabled"
    DEGRADED = "degraded"


class PublishStatus(StrEnum):
    """Outcomes reported by the admin PATCH endpoints.

    - ``PROPAGATED``: local override applied and pub/sub publish succeeded.
    - ``LOCAL_ONLY``: local override applied; coordinator not attached to Redis.
    - ``FAILED``: local override applied but the pub/sub publish failed
      (peers may not have received the change).
    - ``SUPERSEDED``: a concurrent newer change won the race; local state
      already reflects an authorized flip and this PATCH was a no-op.
    """

    PROPAGATED = "propagated"
    LOCAL_ONLY = "local-only"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class BootReconcileStatus(StrEnum):
    """Per-runtime outcome of the coordinator's boot-time reconciliation.

    - ``OK``: hint either absent or applied successfully.
    - ``REDIS_UNAVAILABLE``: Redis read failed; pod boots with stale settings.
    - ``MALFORMED_HINT``: hint key existed but contained invalid JSON.
    - ``INCOMPATIBLE_NO_DISPATCHER``: hint targeted a runtime that has no
      dispatcher mounted on this deployment (e.g. ``boot=off`` for either
      runtime). The hint is discarded; the operator must boot with the
      runtime enabled for the hint to take effect.
    - ``INCOMPATIBLE_BOOT_FULL``: hint targeted MCP on a ``boot=full`` pod.
      Full-boot mounts a plain Rust proxy with no dispatcher, so the
      override would strand. Operator action: boot with ``RUST_MCP_MODE=edge``.
    - ``INCOMPATIBLE_SAFETY_FLAG``: hint requested ``edge`` but the
      deployment did not opt into the session-auth-reuse (MCP) or
      delegate-enabled (A2A) safety flag at boot. Operator action:
      enable the corresponding flag (typically by booting with
      ``RUST_MCP_MODE=edge`` / ``RUST_A2A_MODE=edge``).
    - ``PUBSUB_UNAVAILABLE``: pub/sub subscribe failed during start; this pod
      will not receive remote overrides until restart.
    - ``COORDINATOR_OFFLINE``: coordinator was never started (e.g. test mode
      or a deployment that runs without the coordinator).
    """

    OK = "ok"
    REDIS_UNAVAILABLE = "redis_unavailable"
    MALFORMED_HINT = "malformed_hint"
    INCOMPATIBLE_NO_DISPATCHER = "incompatible_no_dispatcher"
    INCOMPATIBLE_BOOT_FULL = "incompatible_boot_full"
    INCOMPATIBLE_SAFETY_FLAG = "incompatible_safety_flag"
    PUBSUB_UNAVAILABLE = "pubsub_unavailable"
    COORDINATOR_OFFLINE = "coordinator_offline"


class MoveCompatibility(StrEnum):
    """Why a runtime override is or is not safely applicable on this deployment.

    Returned by ``version.deployment_allows_override_mode`` and consumed both
    by the boot-hint reconciliation path and the admin router. Carrying the
    structured reason (instead of a bare bool) lets the coordinator surface
    a granular ``BootReconcileStatus`` and the router emit operator-actionable
    409 details that name the exact env var or flag to flip.
    """

    OK = "ok"
    NO_DISPATCHER = "no_dispatcher"
    BOOT_FULL_STRANDS = "boot_full_strands"
    EDGE_NEEDS_SAFETY_FLAG = "edge_needs_safety_flag"


def _move_compat_to_reconcile_status(compat: "MoveCompatibility") -> "BootReconcileStatus":
    """Map a ``MoveCompatibility`` rejection reason to its ``BootReconcileStatus`` peer.

    Args:
        compat: A non-OK ``MoveCompatibility`` value.

    Returns:
        The matching ``BootReconcileStatus``. ``OK`` maps to ``OK`` for symmetry.
    """
    if compat == MoveCompatibility.OK:  # pragma: no cover — caller filters OK upstream
        return BootReconcileStatus.OK
    if compat == MoveCompatibility.NO_DISPATCHER:
        return BootReconcileStatus.INCOMPATIBLE_NO_DISPATCHER
    if compat == MoveCompatibility.BOOT_FULL_STRANDS:
        return BootReconcileStatus.INCOMPATIBLE_BOOT_FULL
    if compat == MoveCompatibility.EDGE_NEEDS_SAFETY_FLAG:
        return BootReconcileStatus.INCOMPATIBLE_SAFETY_FLAG
    return BootReconcileStatus.INCOMPATIBLE_NO_DISPATCHER  # pragma: no cover — defensive default for future MoveCompatibility variants


# Backward-compat aliases for callers that consume the bare string set or the
# string constants. Built from the enums so they cannot drift.
SUPPORTED_OVERRIDE_MODES: frozenset[str] = frozenset(OverrideMode)
RUNTIME_KINDS: frozenset[str] = frozenset(RuntimeKind)
PROPAGATION_REDIS: str = ClusterPropagation.REDIS.value
PROPAGATION_DISABLED: str = ClusterPropagation.DISABLED.value
PROPAGATION_DEGRADED: str = ClusterPropagation.DEGRADED.value


class RuntimeStateError(Exception):
    """Raised when a runtime-mode change cannot be safely applied or propagated."""


def _coerce_runtime(value: Union[str, RuntimeKind]) -> RuntimeKind:
    """Coerce a string or RuntimeKind into a canonical RuntimeKind.

    Args:
        value: Either the bare string (``"mcp"``/``"a2a"``) or a ``RuntimeKind`` member.

    Returns:
        The matching ``RuntimeKind`` member.

    Raises:
        ValueError: If ``value`` is not a recognized runtime kind.
    """
    return value if isinstance(value, RuntimeKind) else RuntimeKind(value)


def _coerce_mode(value: Union[str, OverrideMode]) -> OverrideMode:
    """Coerce a string or OverrideMode into a canonical OverrideMode.

    Args:
        value: Either the bare string (``"shadow"``/``"edge"``) or an ``OverrideMode`` member.

    Returns:
        The matching ``OverrideMode`` member.

    Raises:
        ValueError: If ``value`` is not a supported override mode.
    """
    return value if isinstance(value, OverrideMode) else OverrideMode(value)


def _hint_key(runtime: Union[str, RuntimeKind]) -> str:
    """Return the Redis hint key for a runtime kind.

    Args:
        runtime: Runtime kind.

    Returns:
        Fully qualified Redis key for the per-runtime override hint.
    """
    return f"{RUNTIME_STATE_HINT_KEY_PREFIX}:{_coerce_runtime(runtime).value}"


def _version_key(runtime: Union[str, RuntimeKind]) -> str:
    """Return the Redis monotonic version counter key for a runtime kind.

    Args:
        runtime: Runtime kind.

    Returns:
        Fully qualified Redis key for the per-runtime version counter.
    """
    return f"{RUNTIME_STATE_VERSION_KEY_PREFIX}:{_coerce_runtime(runtime).value}"


@dataclass(frozen=True)
class ModeChange:
    """Snapshot of the most recent mode change applied locally for one runtime."""

    runtime: RuntimeKind
    version: int
    mode: OverrideMode
    initiator_user: Optional[str]
    initiator_pod: str
    timestamp: float

    def __post_init__(self) -> None:
        """Coerce string inputs to canonical enum members and validate.

        Raises:
            ValueError: If ``runtime`` is not one of ``RuntimeKind`` or ``mode``
                is not one of ``OverrideMode``.
        """
        if not isinstance(self.runtime, RuntimeKind):
            object.__setattr__(self, "runtime", _coerce_runtime(self.runtime))
        if not isinstance(self.mode, OverrideMode):
            object.__setattr__(self, "mode", _coerce_mode(self.mode))


class RuntimeState:
    """In-memory snapshot of runtime-mutable mode overrides for one process.

    Reads happen on every public-ingress request, so they must stay lock-free.
    Writes (local PATCH or remote pub/sub) take per-runtime locks and enforce
    monotonic versioning.
    """

    def __init__(self) -> None:
        """Create an empty runtime state with no active overrides."""
        self._locks: Dict[RuntimeKind, asyncio.Lock] = {kind: asyncio.Lock() for kind in RuntimeKind}
        self._override: Dict[RuntimeKind, Optional[OverrideMode]] = {kind: None for kind in RuntimeKind}
        self._version: Dict[RuntimeKind, int] = {kind: 0 for kind in RuntimeKind}
        self._last_change: Dict[RuntimeKind, Optional[ModeChange]] = {kind: None for kind in RuntimeKind}
        self._pod_id = os.environ.get("HOSTNAME") or uuid.uuid4().hex
        self._cluster_propagation: ClusterPropagation = ClusterPropagation.DISABLED
        self._boot_reconcile_status: Dict[RuntimeKind, BootReconcileStatus] = {kind: BootReconcileStatus.COORDINATOR_OFFLINE for kind in RuntimeKind}

    @property
    def pod_id(self) -> str:
        """Stable identifier for this pod, used to dedupe self-published events.

        Returns:
            Stable pod identifier (HOSTNAME if set, otherwise a random UUID).
        """
        return self._pod_id

    @property
    def cluster_propagation(self) -> ClusterPropagation:
        """Current cluster-propagation status.

        Returns:
            A ``ClusterPropagation`` enum member. Because the enum is a
            ``StrEnum``, callers may continue to compare against the literal
            strings (``"redis"``/``"disabled"``/``"degraded"``).
        """
        return self._cluster_propagation

    def set_cluster_propagation(self, status: Union[str, ClusterPropagation]) -> None:
        """Update the cluster-propagation status surfaced via diagnostics.

        ``RuntimeState`` owns the storage so a freshly-constructed instance
        (used in unit tests without a coordinator) has a sensible default,
        but the only legitimate production writer is
        ``RuntimeStateCoordinator``. ``cluster_propagation_enabled`` derives
        from this value, so the status is the single source of truth for
        "is propagation healthy?" decisions.

        Args:
            status: A ``ClusterPropagation`` member or matching string.

        Raises:
            ValueError: If ``status`` is not a recognized ClusterPropagation value.
        """
        self._cluster_propagation = status if isinstance(status, ClusterPropagation) else ClusterPropagation(status)

    def boot_reconcile_status(self, runtime: Union[str, RuntimeKind]) -> BootReconcileStatus:
        """Return the boot-time reconciliation outcome for ``runtime``.

        Args:
            runtime: Runtime kind.

        Returns:
            A ``BootReconcileStatus`` member; ``COORDINATOR_OFFLINE`` when no
            coordinator has run, ``OK`` when the coordinator started cleanly
            (with or without a hint), or one of the failure values when boot
            reconciliation hit an issue that left the pod with stale settings.
        """
        try:
            kind = _coerce_runtime(runtime)
        except ValueError:
            return BootReconcileStatus.COORDINATOR_OFFLINE
        return self._boot_reconcile_status[kind]

    def set_boot_reconcile_status(self, runtime: Union[str, RuntimeKind], status: Union[str, BootReconcileStatus]) -> None:
        """Update the boot-reconciliation status for ``runtime``.

        Like ``set_cluster_propagation``, ``RuntimeState`` owns storage but the
        only legitimate writer is ``RuntimeStateCoordinator``.

        Args:
            runtime: Runtime kind.
            status: A ``BootReconcileStatus`` member or matching string.

        Raises:
            ValueError: If ``runtime`` or ``status`` is not recognized.
        """
        kind = _coerce_runtime(runtime)
        self._boot_reconcile_status[kind] = status if isinstance(status, BootReconcileStatus) else BootReconcileStatus(status)

    def override_mode(self, runtime: Union[str, RuntimeKind]) -> Optional[OverrideMode]:
        """Return the active override for ``runtime``, or ``None`` if no override is set.

        Args:
            runtime: Runtime kind.

        Returns:
            ``OverrideMode.SHADOW``/``OverrideMode.EDGE`` when an override is
            active, else ``None``. Result compares equal to its string literal.
        """
        try:
            kind = _coerce_runtime(runtime)
        except ValueError:
            return None
        return self._override[kind]

    def version(self, runtime: Union[str, RuntimeKind]) -> int:
        """Return the monotonic version of the most recent applied override.

        Args:
            runtime: Runtime kind.

        Returns:
            The current monotonic version (``0`` when no override has been applied).
        """
        try:
            kind = _coerce_runtime(runtime)
        except ValueError:
            return 0
        return self._version[kind]

    def last_change(self, runtime: Union[str, RuntimeKind]) -> Optional[ModeChange]:
        """Return the most recent applied mode change for ``runtime``, if any.

        Args:
            runtime: Runtime kind.

        Returns:
            A ``ModeChange`` describing the last applied override, else ``None``.
        """
        try:
            kind = _coerce_runtime(runtime)
        except ValueError:
            return None
        return self._last_change[kind]

    async def apply_local(
        self,
        runtime: Union[str, RuntimeKind],
        mode: Union[str, OverrideMode],
        *,
        initiator_user: Optional[str],
        version: int,
    ) -> Optional[ModeChange]:
        """Apply an override originating from this pod.

        Args:
            runtime: Runtime kind.
            mode: Target override mode.
            initiator_user: Authenticated user email that requested the change.
            version: Monotonic version for the change (must be strictly greater than the current version).

        Returns:
            A ``ModeChange`` describing the applied override, or ``None`` if a
            concurrent newer change has already been applied (rare race when
            two PATCHes on the same pod allocate adjacent versions and land
            out of order).

        Raises:
            ValueError: If ``runtime`` is unknown or ``mode`` is not a supported override mode.
        """
        kind = _coerce_runtime(runtime)
        target_mode = _coerce_mode(mode)
        async with self._locks[kind]:
            if version <= self._version[kind]:
                return None
            self._override[kind] = target_mode
            self._version[kind] = version
            change = ModeChange(
                runtime=kind,
                version=version,
                mode=target_mode,
                initiator_user=initiator_user,
                initiator_pod=self._pod_id,
                timestamp=time.time(),
            )
            self._last_change[kind] = change
            return change

    async def apply_remote(self, payload: Dict[str, Any]) -> Optional[ModeChange]:
        """Apply an override message received from another pod.

        Args:
            payload: Decoded pub/sub payload.

        Returns:
            The applied ``ModeChange`` when the message advanced local state,
            otherwise ``None`` (stale, self-originated, or invalid).
        """
        try:
            kind = _coerce_runtime(payload["runtime"])
            target_mode = _coerce_mode(payload["mode"])
            version = int(payload["version"])
            initiator_pod = str(payload.get("initiator_pod", "unknown"))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("RuntimeState: discarding malformed or invalid runtime-mode payload (%s): %r", exc, payload)
            return None

        if initiator_pod == self._pod_id:
            return None

        async with self._locks[kind]:
            if version <= self._version[kind]:
                return None
            self._override[kind] = target_mode
            self._version[kind] = version
            change = ModeChange(
                runtime=kind,
                version=version,
                mode=target_mode,
                initiator_user=payload.get("initiator_user"),
                initiator_pod=initiator_pod,
                timestamp=float(payload.get("timestamp", time.time())),
            )
            self._last_change[kind] = change
            return change


_runtime_state: Optional[RuntimeState] = None


def get_runtime_state() -> RuntimeState:
    """Return the process-wide ``RuntimeState`` singleton, creating it if needed.

    Returns:
        The shared ``RuntimeState`` instance for this process.
    """
    global _runtime_state
    if _runtime_state is None:
        _runtime_state = RuntimeState()
    return _runtime_state


def reset_runtime_state_for_tests() -> None:
    """Clear the runtime state singleton. Tests only.

    Production code must not call this — it intentionally drops any active
    override and leaks the prior coordinator's pubsub task if one is running.
    """
    global _runtime_state
    _runtime_state = None


class RuntimeStateCoordinator:
    """Cluster-wide propagation for runtime-mutable mode overrides.

    On startup the coordinator reads any persisted per-runtime override hint
    from Redis and reconciles local state. It then subscribes to a single
    pub/sub channel and applies remote overrides as they arrive (each message
    carries a ``runtime`` field).

    When Redis is unavailable the coordinator degrades to single-pod scope:
    local overrides still apply on the pod that received the PATCH, but the
    rest of the cluster is unaware. This is surfaced via ``cluster_propagation``
    on ``/health`` and admin responses.
    """

    def __init__(self) -> None:
        """Initialize an inactive coordinator. Call :meth:`start` to activate."""
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._pubsub: Optional[Any] = None
        self._redis: Optional[Any] = None
        self._started = False

    @property
    def started(self) -> bool:
        """Whether the coordinator's listener task is running.

        Returns:
            ``True`` after a successful :meth:`start`, else ``False``.
        """
        return self._started

    @property
    def cluster_propagation_enabled(self) -> bool:
        """Whether cluster-wide propagation is currently healthy.

        Derived from ``RuntimeState.cluster_propagation`` (the single source of
        truth) so that a permanent pub/sub failure that downgraded the status
        to ``degraded`` is correctly reported as "not enabled" — even though
        the ``_pubsub`` handle is still bound waiting for ``stop()``.

        Returns:
            ``True`` only when the propagation status is ``REDIS``.
        """
        return get_runtime_state().cluster_propagation == ClusterPropagation.REDIS

    async def start(self) -> None:
        """Subscribe to the runtime-mode pub/sub channel and reconcile boot state.

        Sets ``cluster_propagation`` to one of:

        - ``"redis"`` — pub/sub attached and listener running.
        - ``"disabled"`` — Redis is intentionally not configured for this deployment.
        - ``"degraded"`` — Redis is configured but the coordinator failed to attach;
          the pod will still serve PATCH locally, but operators should treat
          ``"degraded"`` as an alertable condition (e.g. fail readiness or page).
        """
        if self._started:
            return

        state = get_runtime_state()
        # If Redis is not configured for this deployment, propagation is
        # intentionally off — distinct from "configured but broken".
        try:
            # First-Party
            from mcpgateway.utils.redis_client import get_redis_client  # pylint: disable=import-outside-toplevel

            redis = await get_redis_client()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("RuntimeStateCoordinator: Redis client raised at startup; cluster propagation is degraded: %s", exc)
            state.set_cluster_propagation(PROPAGATION_DEGRADED)
            for kind in RuntimeKind:
                state.set_boot_reconcile_status(kind, BootReconcileStatus.REDIS_UNAVAILABLE)
            self._started = True
            return

        if redis is None:
            logger.info("RuntimeStateCoordinator: Redis disabled, runtime mode override is per-pod only")
            state.set_cluster_propagation(PROPAGATION_DISABLED)
            for kind in RuntimeKind:
                state.set_boot_reconcile_status(kind, BootReconcileStatus.OK)
            self._started = True
            return

        self._redis = redis
        try:
            for kind in RuntimeKind:
                await self._reconcile_from_hint(kind)
            self._stop_event = asyncio.Event()
            self._pubsub = redis.pubsub()
            await self._pubsub.subscribe(RUNTIME_STATE_CHANNEL)
            self._task = asyncio.create_task(self._listen_loop())
            # Only promote to "redis" if the per-runtime reconciliation didn't
            # already mark us "degraded" (e.g. malformed hint, Redis read fail).
            if state.cluster_propagation != PROPAGATION_DEGRADED:
                state.set_cluster_propagation(PROPAGATION_REDIS)
            self._started = True
            logger.info("RuntimeStateCoordinator subscribed to %s", RUNTIME_STATE_CHANNEL)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("RuntimeStateCoordinator failed to attach pub/sub; cluster propagation is degraded: %s", exc)
            await self._cleanup_pubsub()
            state.set_cluster_propagation(PROPAGATION_DEGRADED)
            for kind in RuntimeKind:
                # Reconcile-specific failures (REDIS_UNAVAILABLE, MALFORMED_HINT)
                # are more specific than "pub/sub down" — keep them. Otherwise
                # mark PUBSUB_UNAVAILABLE so /health distinguishes "we attached
                # to Redis but the listener is dead" from "Redis is intentionally
                # off" or "the hint read failed".
                if state.boot_reconcile_status(kind) in (BootReconcileStatus.OK, BootReconcileStatus.COORDINATOR_OFFLINE):
                    state.set_boot_reconcile_status(kind, BootReconcileStatus.PUBSUB_UNAVAILABLE)
            self._started = True

    async def stop(self) -> None:
        """Unsubscribe and cancel the listener task."""
        if not self._started:
            return
        self._started = False

        if self._stop_event is not None:
            self._stop_event.set()

        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        await self._cleanup_pubsub()
        self._redis = None
        get_runtime_state().set_cluster_propagation(PROPAGATION_DISABLED)

    async def publish(self, change: ModeChange) -> bool:
        """Publish a local override to the cluster.

        The local override is already applied before this is called. We report
        whether the publish (and hint persistence) succeeded so the admin
        endpoint can surface a per-PATCH propagation status — without a
        successful publish, peer pods will silently keep the previous mode.

        Args:
            change: ``ModeChange`` produced by ``RuntimeState.apply_local``.

        Returns:
            ``True`` when both the pub/sub publish and the hint write succeeded
            (or when the coordinator is not attached to Redis, in which case
            propagation was never expected). ``False`` when Redis was
            attached but the publish or hint write failed.
        """
        if self._redis is None:
            return True
        payload = {
            "runtime": change.runtime,
            "mode": change.mode,
            "version": change.version,
            "initiator_user": change.initiator_user,
            "initiator_pod": change.initiator_pod,
            "timestamp": change.timestamp,
        }
        encoded = orjson.dumps(payload)
        try:
            await self._redis.publish(RUNTIME_STATE_CHANNEL, encoded)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "RuntimeStateCoordinator: publish failed for %s mode=%s version=%d (local override still applied; peers may not have received the change): %s",
                change.runtime,
                change.mode,
                change.version,
                exc,
            )
            return False

        try:
            await self._redis.set(_hint_key(change.runtime), encoded, ex=RUNTIME_STATE_HINT_TTL_SECONDS)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "RuntimeStateCoordinator: failed to persist override hint for %s (peers received the pub/sub message, but newly started pods will not reconcile): %s",
                change.runtime,
                exc,
            )
            return False
        return True

    async def next_version(self, runtime: str, current_version: int) -> int:
        """Allocate the next monotonic version for ``runtime``.

        When Redis is attached we ``INCR`` a per-runtime counter — this gives
        the only guarantee that two pods racing on PATCH allocate distinct
        versions. When Redis is intentionally not configured we fall back to
        the local floor; that's safe per-pod because there is only one pod's
        worth of state to track.

        Args:
            runtime: Runtime kind (``"mcp"`` or ``"a2a"``).
            current_version: The local pod's current version, used as the floor when Redis is not configured.

        Returns:
            A version strictly greater than both the Redis counter (if attached) and ``current_version``.

        Raises:
            RuntimeStateError: When Redis is attached but ``INCR`` fails. We
                deliberately do not fall back to ``current_version + 1`` here:
                a local fallback can collide with a concurrent PATCH on
                another pod and silently lose one of the two flips at peer
                dedup time.
        """
        if self._redis is not None:
            try:
                value = await self._redis.incr(_version_key(runtime))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeStateError(
                    f"Redis INCR failed for {_version_key(runtime)} ({exc!r}); refusing to allocate a local version that could collide with a concurrent PATCH on another pod. "
                    "Check Redis connectivity (REDIS_URL, network reachability, auth) before retrying."
                ) from exc
            if int(value) > current_version:
                return int(value)
            # Redis counter was reset/deleted while pods were live; raise so
            # the operator sees the inconsistency rather than silently
            # publishing a version that peers will dedup as stale.
            raise RuntimeStateError(
                f"Redis counter at {_version_key(runtime)}={value} is not greater than local version {current_version}; "
                "the counter may have been deleted, rolled back, or rotated under live pods. "
                "Restart the coordinator or restore the counter manually (e.g. SET the key to a value greater than the local floor); "
                "if Redis itself is unhealthy, also check connectivity (REDIS_URL, network reachability, auth)."
            )
        return current_version + 1

    async def _reconcile_from_hint(self, runtime: Union[str, RuntimeKind]) -> None:
        """Read the persisted override hint for ``runtime`` and apply it locally if newer.

        A failed reconciliation is operationally significant: the pod will boot
        with stale settings and continue serving the boot mode until the next
        published flip corrects it. We log at ERROR, mark the per-runtime
        ``boot_reconcile_status`` so ``/health`` records the cause, and
        downgrade ``cluster_propagation`` to ``"degraded"`` so dashboards key
        on a single field.

        Args:
            runtime: Runtime kind (``"mcp"`` or ``"a2a"``).
        """
        kind = _coerce_runtime(runtime)
        state = get_runtime_state()
        if self._redis is None:
            state.set_boot_reconcile_status(kind, BootReconcileStatus.OK)
            return
        try:
            raw = await self._redis.get(_hint_key(kind))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "RuntimeStateCoordinator: failed to read boot hint for %s on pod %s; pod will boot with stale settings until a new override is published: %s",
                kind.value,
                state.pod_id,
                exc,
            )
            state.set_cluster_propagation(PROPAGATION_DEGRADED)
            state.set_boot_reconcile_status(kind, BootReconcileStatus.REDIS_UNAVAILABLE)
            return
        if not raw:
            state.set_boot_reconcile_status(kind, BootReconcileStatus.OK)
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            logger.error(
                "RuntimeStateCoordinator: discarding malformed boot hint for %s on pod %s; pod will boot with stale settings until a new override is published: %s",
                kind.value,
                state.pod_id,
                exc,
            )
            state.set_cluster_propagation(PROPAGATION_DEGRADED)
            state.set_boot_reconcile_status(kind, BootReconcileStatus.MALFORMED_HINT)
            return
        # Hints persisted before this code knew about per-runtime keys may
        # omit the "runtime" field — fill it in based on the key we read.
        payload.setdefault("runtime", kind.value)

        # Discard hints whose target mode cannot safely take effect on this
        # deployment. Without this guard, a hint written by a former
        # edge-boot pod would linger in Redis and be applied on every
        # shadow-boot pod that starts up — state would claim "edge" while
        # the transport layer refuses to honor it, and the admin API would
        # not be able to clear state on the new deployment's terms.
        #
        # The Redis hint key is intentionally NOT deleted here: a future
        # compatible-boot pod (e.g. the operator restores RUST_MCP_MODE=edge
        # in a later deploy) must still be able to read it for boot
        # reconciliation. Stale hints expire on their own via the 24h TTL
        # set at publish time; an operator who wants to clear immediately
        # can DEL the contextforge:runtime:mode_state:{runtime} key.
        try:
            hint_mode = _coerce_mode(payload.get("mode", ""))
        except ValueError:
            hint_mode = None
        if hint_mode is not None:
            # First-Party: lazy to avoid the version <-> runtime_state import cycle.
            # First-Party
            from mcpgateway.version import _deployment_allows_override_mode  # pylint: disable=import-outside-toplevel,cyclic-import

            compat = _deployment_allows_override_mode(kind, hint_mode)
            if compat != MoveCompatibility.OK:
                logger.warning(
                    "RuntimeStateCoordinator: discarding incompatible boot hint for %s (mode=%s) on pod %s; "
                    "reason=%s. Hint key is left in Redis for future compatible-boot pods; an operator can "
                    "DEL the hint key to force-clear cluster state.",
                    kind.value,
                    hint_mode.value,
                    state.pod_id,
                    compat.value,
                )
                state.set_boot_reconcile_status(kind, _move_compat_to_reconcile_status(compat))
                return

        applied = await state.apply_remote(payload)
        state.set_boot_reconcile_status(kind, BootReconcileStatus.OK)
        if applied is not None:
            logger.info(
                "RuntimeStateCoordinator: reconciled %s boot state to %s (version=%d, initiator_pod=%s)",
                applied.runtime.value,
                applied.mode.value,
                applied.version,
                applied.initiator_pod,
            )

    async def _listen_loop(self) -> None:
        """Background loop that applies remote runtime-mode messages.

        Tracks consecutive ``get_message`` failures so that a permanent pub/sub
        outage (Redis restart, network partition, auth lapse) is reflected in
        ``cluster_propagation`` rather than silently busy-spinning while admin
        responses keep advertising healthy propagation.
        """
        consecutive_errors = 0
        state = get_runtime_state()
        # asyncio.CancelledError is BaseException in 3.8+ — the inner
        # ``except Exception`` won't swallow a task cancel; it propagates
        # naturally out of this coroutine.
        while self._started and not (self._stop_event and self._stop_event.is_set()):
            if self._pubsub is None:
                break
            try:
                message = await asyncio.wait_for(
                    self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                # Idle timeout is the normal path when no messages arrive;
                # treat it as evidence the subscriber is alive.
                if consecutive_errors > 0:
                    consecutive_errors = 0
                    if state.cluster_propagation == PROPAGATION_DEGRADED:
                        state.set_cluster_propagation(PROPAGATION_REDIS)
                        logger.info("RuntimeStateCoordinator: pub/sub recovered, cluster_propagation back to %s", PROPAGATION_REDIS)
                continue
            except Exception as exc:  # pylint: disable=broad-exception-caught
                consecutive_errors += 1
                if consecutive_errors == LISTEN_LOOP_DEGRADE_THRESHOLD:
                    state.set_cluster_propagation(PROPAGATION_DEGRADED)
                    logger.error(
                        "RuntimeStateCoordinator: %d consecutive pub/sub receive failures; cluster_propagation downgraded to %s. Last error: %s",
                        consecutive_errors,
                        PROPAGATION_DEGRADED,
                        exc,
                    )
                else:
                    logger.debug("RuntimeStateCoordinator: receive error (%d consecutive): %s", consecutive_errors, exc)
                await asyncio.sleep(0.1)
                continue
            # A non-exception return without a real message (e.g. ``None`` from
            # a pubsub that's broken in a way that doesn't raise) is NOT
            # evidence the subscriber is alive — the idle-timeout branch above
            # handles the legit silence case. Only count real messages as
            # "subscriber is healthy" for the recovery promotion.
            if not message or message.get("type") != "message":
                continue
            if consecutive_errors > 0:
                consecutive_errors = 0
                if state.cluster_propagation == PROPAGATION_DEGRADED:
                    state.set_cluster_propagation(PROPAGATION_REDIS)
                    logger.info("RuntimeStateCoordinator: pub/sub recovered, cluster_propagation back to %s", PROPAGATION_REDIS)
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            if not data:
                continue
            try:
                payload = orjson.loads(data)
            except orjson.JSONDecodeError as exc:
                logger.warning("RuntimeStateCoordinator: discarding malformed pub/sub payload: %s", exc)
                continue
            # Mirror _reconcile_from_hint's compatibility check: a remote pod
            # may publish a flip that this pod cannot safely honor (e.g. an
            # edge-boot pod publishes ``edge`` and a shadow-boot peer
            # receives it). Without this guard the override would land in
            # local state, the transport layer would refuse to honor it,
            # and diagnostics would lie. Discard with a WARN.
            try:
                remote_mode = _coerce_mode(payload.get("mode", ""))
                remote_runtime = _coerce_runtime(payload.get("runtime", ""))
            except ValueError:
                # apply_remote will log the malformed payload; let it run.
                remote_mode = None
                remote_runtime = None
            if remote_mode is not None and remote_runtime is not None:
                # First-Party: lazy to avoid the version <-> runtime_state import cycle.
                # First-Party
                from mcpgateway.version import _deployment_allows_override_mode  # pylint: disable=import-outside-toplevel,cyclic-import

                remote_compat = _deployment_allows_override_mode(remote_runtime, remote_mode)
                if remote_compat != MoveCompatibility.OK:
                    logger.warning(
                        "RuntimeStateCoordinator: discarding incompatible remote override for %s (mode=%s) from pod=%s; "
                        "reason=%s. The publishing pod's flags allow this mode but this pod's do not.",
                        remote_runtime.value,
                        remote_mode.value,
                        payload.get("initiator_pod", "unknown"),
                        remote_compat.value,
                    )
                    continue
            applied = await get_runtime_state().apply_remote(payload)
            if applied is not None:
                logger.info(
                    "RuntimeStateCoordinator: applied remote %s override mode=%s version=%d from pod=%s",
                    applied.runtime,
                    applied.mode,
                    applied.version,
                    applied.initiator_pod,
                )

    async def _cleanup_pubsub(self) -> None:
        """Unsubscribe and close the pubsub connection if open."""
        if self._pubsub is None:
            return
        try:
            try:
                await asyncio.wait_for(self._pubsub.unsubscribe(RUNTIME_STATE_CHANNEL), timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug("RuntimeStateCoordinator: unsubscribe timed out")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("RuntimeStateCoordinator: error during unsubscribe: %s", exc)
        try:
            try:
                await asyncio.wait_for(self._pubsub.aclose(), timeout=2.0)
            except AttributeError:
                await asyncio.wait_for(self._pubsub.close(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.debug("RuntimeStateCoordinator: pubsub close timed out")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("RuntimeStateCoordinator: error closing pubsub: %s", exc)
        self._pubsub = None


_coordinator: Optional[RuntimeStateCoordinator] = None


def get_runtime_state_coordinator() -> RuntimeStateCoordinator:
    """Return the process-wide ``RuntimeStateCoordinator`` singleton.

    Returns:
        The shared ``RuntimeStateCoordinator`` for this process.
    """
    global _coordinator
    if _coordinator is None:
        _coordinator = RuntimeStateCoordinator()
    return _coordinator


def reset_runtime_state_coordinator_for_tests() -> None:
    """Clear the coordinator singleton. Tests only."""
    global _coordinator
    _coordinator = None
