# -*- coding: utf-8 -*-
"""Upstream MCP session registry (1:1 per downstream session).

Replaces the previous ``SessionAffinity`` which keyed upstream sessions by
``(user_identity, url, identity_hash, transport_type, gateway_id)``. That
sharing leaked state between downstream MCP sessions whose callers happened
to share the same identity (issue #4205): two chat tabs opened by the same
user would receive the same counter state, because both were wired to the
same pooled upstream session.

This registry enforces 1:1 binding between a downstream MCP session (as
identified by its ``Mcp-Session-Id``) and each upstream gateway it talks to.
Within one downstream session, tool calls still reuse a single upstream
session per gateway — so the per-call latency win of pooling survives — but
nothing is ever shared across downstream sessions.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Jonathan Springer, Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from types import MappingProxyType
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, Optional

# Third-Party
import anyio
import httpx
from mcp import ClientSession, McpError
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.session import RequestResponder
import mcp.types as mcp_types

# First-Party
from mcpgateway.transports.context import request_headers_var
from mcpgateway.utils.url_auth import sanitize_url_for_logging

logger = logging.getLogger(__name__)

# JSON-RPC error code meaning the server does not implement the requested method.
_METHOD_NOT_FOUND = -32601

# Default knobs. Override via UpstreamSessionRegistry constructor kwargs.
_DEFAULT_IDLE_VALIDATION_SECONDS = 60.0
_DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0
_DEFAULT_SESSION_CREATE_TIMEOUT_SECONDS = 30.0
_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_HEALTH_CHECK_CHAIN = ("ping", "list_tools", "list_prompts", "list_resources", "skip")


class TransportType(str, Enum):
    """Supported upstream MCP transports."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamablehttp"


HttpxClientFactory = Callable[
    [Optional[dict[str, str]], Optional[httpx.Timeout], Optional[httpx.Auth]],
    httpx.AsyncClient,
]

# Factory building a per-session MCP message handler. Optional; if absent, no
# handler is wired and server-initiated messages will be dropped.
MessageHandlerFactory = Callable[
    [str, Optional[str]],  # (url, gateway_id)
    Callable[
        [RequestResponder[mcp_types.ServerRequest, mcp_types.ClientResult] | mcp_types.ServerNotification | Exception],
        Any,
    ],
]

# Factory for constructing an upstream MCP session.
#
# Return shape is ``(ClientSession, _unused)``. The second slot is vestigial —
# the owner task attaches ``_cf_owner_task`` and ``_cf_shutdown_event`` onto
# the ClientSession object itself, so ``_create_session()`` ignores the second
# return value. Kept in the signature because (a) fake factories in the test
# suite mirror the shape and (b) collapsing to a single return is a breaking
# change for any downstream overrides — safe to do in the same commit that
# replaces the attribute-smuggling convention with a typed handle (separate
# follow-up).
#
# Defaults to the real MCP transports; tests inject a fake so no network is
# touched.
SessionFactory = Callable[
    ["SessionCreateRequest"],
    Awaitable[tuple[ClientSession, Any]],
]


@dataclass
class RegistrySnapshot:
    """Point-in-time snapshot of registry metrics (for /admin and logs)."""

    active_sessions: int
    creates: int
    reuses: int
    health_check_failures: int
    health_check_recreates: int
    evictions: int


@dataclass
class _RegistryMetrics:
    """Internal mutable counters; exposed via RegistrySnapshot.snapshot()."""

    creates: int = 0
    reuses: int = 0
    health_check_failures: int = 0
    health_check_recreates: int = 0
    evictions: int = 0


@dataclass(frozen=True)
class SessionCreateRequest:
    """Inputs for creating a single upstream session (used by SessionFactory).

    Frozen so a SessionFactory — which typically runs inside a spawned owner
    task — can't accidentally rewrite the caller's request mid-flight and
    silently point the upstream session at a different URL/transport than the
    registry keyed it under. ``headers`` is additionally wrapped in a
    ``MappingProxyType`` in ``__post_init__`` so in-place dict mutation can't
    bypass the freeze.
    """

    url: str
    transport_type: TransportType
    headers: Mapping[str, str]
    gateway_id: Optional[str]
    downstream_session_id: str
    httpx_client_factory: Optional[HttpxClientFactory]
    message_handler_factory: Optional[MessageHandlerFactory]
    timeout_seconds: float

    def __post_init__(self) -> None:
        """Validate invariants the registry relies on at creation time."""
        if not self.url:
            raise ValueError("SessionCreateRequest.url must be a non-empty string")
        if not self.downstream_session_id:
            raise ValueError("SessionCreateRequest.downstream_session_id must be a non-empty string")
        if self.gateway_id is not None and not self.gateway_id:
            # Optional[str] allows None, but "" would be a silent alias for None with
            # different bucketing in log messages and registry keys. Reject it.
            raise ValueError("SessionCreateRequest.gateway_id must be non-empty when provided")
        if self.timeout_seconds <= 0:
            raise ValueError("SessionCreateRequest.timeout_seconds must be positive")
        # Defensively freeze the headers mapping. `object.__setattr__` is the
        # standard workaround for mutating a frozen dataclass from inside
        # __post_init__.
        if not isinstance(self.headers, MappingProxyType):
            object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


_IDENTITY_FIELDS = frozenset({"downstream_session_id", "gateway_id", "url", "transport_type"})


# ---------------------------------------------------------------------------
# MCP SDK-internals probe                                                     #
#                                                                             #
# Detecting "transport is broken but nobody told us" requires reaching into   #
# ClientSession's private anyio streams. That coupling is fragile across MCP  #
# SDK versions, so this is the ONE place allowed to touch those internals.   #
# Keep it narrow: if this probe needs to grow, add a new helper rather than  #
# scattering `getattr(session, "_write_stream", ...)` through the module.     #
# ---------------------------------------------------------------------------

# MCP SDK versions this probe has been validated against. Bump when validated,
# or rewrite the probe if the SDK private surface has shifted.
_MCP_SDK_TRANSPORT_PROBE_COMPATIBLE_VERSIONS = ">=1.27.0,<2.0.0"

# One-shot guard for the SDK-drift log: WARNING on first occurrence per process
# (so operators can't miss "the SDK shape just changed under us") then DEBUG on
# every subsequent call (so a sustained mismatch doesn't flood logs — this probe
# runs on every acquire()). Mutable module state, not a constant — pylint's
# all-caps convention doesn't fit.
_sdk_drift_warning_emitted = False  # pylint: disable=invalid-name


def _mcp_transport_is_broken(session: ClientSession) -> bool:
    """Peek at a ``ClientSession``'s internal anyio streams to detect a dead transport.

    Returns True only when we can positively confirm the transport is gone
    (closed write stream, or receive channels fully drained). Returns False on
    any ambiguity — including when SDK internals have shifted shape — so that
    callers degrade to owner-task liveness rather than evicting a session
    that might still be usable.

    Validated MCP SDK range lives in
    ``_MCP_SDK_TRANSPORT_PROBE_COMPATIBLE_VERSIONS``; bump that marker after
    revalidating when the SDK changes.
    """
    global _sdk_drift_warning_emitted  # pylint: disable=global-statement
    try:
        write_stream = getattr(session, "_write_stream", None)
        if write_stream is None:
            return False
        if getattr(write_stream, "_closed", False) is True:
            return True
        state = getattr(write_stream, "_state", None)
        if state is None:
            return False
        open_rx = getattr(state, "open_receive_channels", 1)
        if isinstance(open_rx, int) and open_rx == 0:
            return True
    except Exception as exc:  # noqa: BLE001 — degrade gracefully if MCP internals shift
        if not _sdk_drift_warning_emitted:
            _sdk_drift_warning_emitted = True
            logger.warning(
                "MCP transport-broken probe raised %s: %s; validated against SDK %s. Next acquires will fall back to owner-task liveness only; subsequent probe failures logged at DEBUG.",
                type(exc).__name__,
                exc,
                _MCP_SDK_TRANSPORT_PROBE_COMPATIBLE_VERSIONS,
            )
        else:
            logger.debug(
                "MCP transport-broken probe raised %s: %s; next acquire will fall back to owner-task liveness only",
                type(exc).__name__,
                exc,
            )
    return False


@dataclass
class UpstreamSession:
    """A single upstream MCP session bound to one downstream session.

    The four identity fields (downstream_session_id, gateway_id, url,
    transport_type) are logically immutable after construction: the registry
    keys its session map on (downstream_session_id, gateway_id), and routing
    decisions depend on url + transport_type. Re-assigning any of them would
    leave the registry indexing a session under one key while the session
    itself thought it belonged to another — a split-brain that violates the
    1:1 invariant this class exists to enforce. ``__setattr__`` refuses such
    assignments at runtime so the invariant can't drift silently. The
    remaining fields (last_used, use_count, _closed, …) are mutable bookkeeping.
    """

    downstream_session_id: str
    gateway_id: str
    url: str
    transport_type: TransportType
    session: ClientSession
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    use_count: int = 0
    _closed: bool = field(default=False, repr=False)
    _owner_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _shutdown_event: Optional[asyncio.Event] = field(default=None, repr=False)

    def __setattr__(self, name: str, value: Any) -> None:
        """Reject post-construction reassignment of identity fields."""
        if name in _IDENTITY_FIELDS and name in self.__dict__:
            raise AttributeError(f"{name!r} is immutable on UpstreamSession after construction")
        super().__setattr__(name, value)

    @property
    def idle_seconds(self) -> float:
        """Seconds since this session was last used."""
        return time.time() - self.last_used

    @property
    def age_seconds(self) -> float:
        """Seconds since this session was created."""
        return time.time() - self.created_at

    @property
    def is_closed(self) -> bool:
        """Whether the session has been marked closed or its transport has broken."""
        if self._closed:
            return True
        if self._owner_task is not None and self._owner_task.done():
            return True
        return _mcp_transport_is_broken(self.session)


async def _default_session_factory(req: SessionCreateRequest) -> tuple[ClientSession, Any]:
    """Owner-task wrapper that builds the real transport + ClientSession.

    Runs inside a dedicated asyncio.Task so the transport's anyio cancel scope
    is bound to that task, not to whichever request handler happens to be
    making the acquire() call. If the request task is cancelled (client
    disconnect, timeout), the upstream transport is NOT torn down with it.
    """
    if req.transport_type is TransportType.SSE:
        if req.httpx_client_factory is not None:
            transport_ctx = sse_client(
                url=req.url,
                headers=req.headers,
                httpx_client_factory=req.httpx_client_factory,
                timeout=req.timeout_seconds,
            )
        else:
            transport_ctx = sse_client(
                url=req.url,
                headers=req.headers,
                timeout=req.timeout_seconds,
            )
    else:
        if req.httpx_client_factory is not None:
            transport_ctx = streamablehttp_client(
                url=req.url,
                headers=req.headers,
                httpx_client_factory=req.httpx_client_factory,
                timeout=req.timeout_seconds,
            )
        else:
            transport_ctx = streamablehttp_client(
                url=req.url,
                headers=req.headers,
                timeout=req.timeout_seconds,
            )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    ready: asyncio.Future[tuple[ClientSession, Any]] = loop.create_future()

    async def owner() -> None:
        """Own the transport + ClientSession lifecycle; unblock on shutdown_event."""
        try:
            async with transport_ctx as streams:
                read_stream, write_stream = streams[0], streams[1]
                message_handler = None
                if req.message_handler_factory is not None:
                    try:
                        message_handler = req.message_handler_factory(req.url, req.gateway_id)
                    except Exception as exc:  # noqa: BLE001 — handler failure is not fatal
                        logger.warning(
                            "Failed to build message handler for %s: %s",
                            sanitize_url_for_logging(req.url),
                            exc,
                        )
                async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
                    await session.initialize()
                    if not ready.done():
                        ready.set_result((session, transport_ctx))
                    # Block until the registry signals shutdown; do NOT rely on
                    # task cancellation from a request handler (see class docs).
                    await shutdown_event.wait()
        except Exception as exc:  # noqa: BLE001 — see below
            # Broad catch on purpose: the upstream-setup path runs many
            # third-party coroutines (httpx, anyio, MCP SDK) whose exception
            # classes we cannot enumerate. BaseException is deliberately NOT
            # caught — SystemExit / KeyboardInterrupt / CancelledError must
            # propagate so the task exits promptly during shutdown.
            if not ready.done():
                ready.set_exception(RuntimeError(f"Failed to create upstream MCP session for {req.url}: {exc}"))

    task = asyncio.create_task(owner(), name=f"upstream-session-{sanitize_url_for_logging(req.url)}")

    def _log_owner_exit(done_task: asyncio.Task) -> None:
        """Surface unexpected owner-task deaths so an orphaned upstream session is visible to ops."""
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.warning(
                "Upstream MCP owner task for %s exited with %s: %s — upstream session may be orphaned",
                sanitize_url_for_logging(req.url),
                type(exc).__name__,
                exc,
            )

    task.add_done_callback(_log_owner_exit)

    success = False
    try:
        session, transport_ctx_ref = await asyncio.wait_for(ready, timeout=req.timeout_seconds)
        success = True
    finally:
        if not success:
            shutdown_event.set()
            task.cancel()
            with anyio.move_on_after(_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS):
                try:
                    await task
                except asyncio.CancelledError:
                    # The owner task itself got cancelled during cleanup — expected after task.cancel().
                    pass
                except Exception as exc:  # noqa: BLE001 — cleanup unwind after failed ready  # pragma: no cover
                    # Defensive: the owner's own `except Exception` swallows all Exception
                    # subclasses before they can escape the task, so reaching this branch
                    # would require a BaseException that slipped through — unreachable
                    # in practice but kept to narrow against future refactors.
                    logger.debug(
                        "Owner-task cleanup after failed session create raised %s: %s",
                        type(exc).__name__,
                        exc,
                    )

    # Smuggle the owner task + shutdown event onto the ClientSession object so
    # _create_session() (which only gets back `(session, transport_ctx)` from
    # the factory) can recover them without a wider factory return contract.
    # Tests that replace the factory must mirror this convention.
    setattr(session, "_cf_owner_task", task)  # type: ignore[attr-defined]
    setattr(session, "_cf_shutdown_event", shutdown_event)  # type: ignore[attr-defined]
    return session, transport_ctx_ref


class UpstreamSessionRegistry:
    """Maps ``(downstream_session_id, gateway_id)`` to a single upstream session.

    Isolation is structural: two downstream sessions cannot share an upstream
    session, even when they carry the same user identity. Within one downstream
    session, concurrent calls to acquire() for the same gateway return the same
    underlying MCP ClientSession — connection reuse stays intact.

    Lifetime of an upstream session follows the downstream session: callers
    evict via evict_session() on DELETE /mcp (or session expiry). There is no
    wall-clock TTL; staleness is handled by a health probe on reuse after the
    idle validation window.

    The registry is purely in-process. Multi-worker stickiness for a given
    downstream session is provided by the session-affinity layer in
    streamablehttp_transport; the registry on each worker only sees requests
    that have already been routed to the owning worker.
    """

    def __init__(
        self,
        *,
        session_factory: Optional[SessionFactory] = None,
        message_handler_factory: Optional[MessageHandlerFactory] = None,
        idle_validation_seconds: float = _DEFAULT_IDLE_VALIDATION_SECONDS,
        health_check_timeout_seconds: float = _DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS,
        session_create_timeout_seconds: float = _DEFAULT_SESSION_CREATE_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        """Build a registry. ``session_factory`` is injectable for tests."""
        self._session_factory: SessionFactory = session_factory or _default_session_factory
        self._message_handler_factory = message_handler_factory
        self._idle_validation_seconds = idle_validation_seconds
        self._health_check_timeout_seconds = health_check_timeout_seconds
        self._session_create_timeout_seconds = session_create_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds

        self._sessions: dict[tuple[str, str], UpstreamSession] = {}
        self._key_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._metrics = _RegistryMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(
        self,
        *,
        downstream_session_id: str,
        gateway_id: str,
        url: str,
        headers: Optional[dict[str, str]],
        transport_type: TransportType,
        httpx_client_factory: Optional[HttpxClientFactory] = None,
    ) -> AsyncIterator[UpstreamSession]:
        """Get or create the upstream session for ``(downstream_session_id, gateway_id)``.

        Concurrent acquires for the same key serialize on the per-key lock only
        across the check-or-create phase. Once a session is chosen, the lock is
        released and the yielded ClientSession multiplexes concurrent requests
        over its transport via MCP request ids.
        """
        if not downstream_session_id:
            raise ValueError("downstream_session_id is required; caller must pin an upstream session to a downstream one")
        if not gateway_id:
            raise ValueError("gateway_id is required")

        key = (downstream_session_id, gateway_id)
        key_lock = await self._get_key_lock(key)

        async with key_lock:
            session = self._sessions.get(key)
            reason = _AcquireDecision.REUSE

            if session is None or session.is_closed:
                reason = _AcquireDecision.CREATE
            elif session.idle_seconds > self._idle_validation_seconds:
                healthy = await self._probe_health(session)
                if not healthy:
                    logger.info(
                        "Upstream session health probe failed, recreating (gateway=%s)",
                        gateway_id,
                    )
                    await self._close_session(session)
                    self._sessions.pop(key, None)
                    self._metrics.health_check_recreates += 1
                    reason = _AcquireDecision.CREATE

            if reason is _AcquireDecision.CREATE:
                session = await self._create_session(
                    downstream_session_id=downstream_session_id,
                    gateway_id=gateway_id,
                    url=url,
                    headers=headers,
                    transport_type=transport_type,
                    httpx_client_factory=httpx_client_factory,
                )
                self._sessions[key] = session
                self._metrics.creates += 1
            else:
                self._metrics.reuses += 1

            assert session is not None
            session.last_used = time.time()
            session.use_count += 1

        # Hand out the session with no lock held: MCP ClientSession multiplexes
        # concurrent requests over its transport via JSON-RPC ids, so there's no
        # reason to serialize callers. If the caller's body raises a transport-
        # level error (server closed the stream, socket broke), evict so the
        # next acquire rebuilds instead of handing out a dead session.
        try:
            yield session
        except (OSError, anyio.ClosedResourceError, anyio.BrokenResourceError) as exc:
            logger.info(
                "acquire() caller raised %s for gateway=%s; evicting upstream so next acquire rebuilds",
                type(exc).__name__,
                gateway_id,
            )
            await self._evict_key(key)
            raise
        # All other exceptions (tool-level errors from the upstream, caller
        # application errors) intentionally leave the session in place — the
        # transport is fine, the caller just didn't like the result.

    async def evict_session(self, downstream_session_id: str) -> int:
        """Close and remove every upstream session owned by this downstream session id.

        Returns the number of sessions evicted. Safe to call when no sessions
        exist. Evictions fire concurrently so a downstream session with many
        gateways doesn't block on the slowest-draining upstream.
        """
        async with self._global_lock:
            keys = [k for k in self._sessions if k[0] == downstream_session_id]
        return await self._evict_keys_in_parallel(keys)

    async def evict_gateway(self, gateway_id: str) -> int:
        """Close and remove every upstream session pointing at a given gateway.

        Intended for gateway-removal/rotation; downstream sessions survive but
        will rebuild upstream state on the next acquire() call. Evictions run
        concurrently — fires post-commit on admin update/delete, so a slow
        drain must not stall the response.
        """
        async with self._global_lock:
            keys = [k for k in self._sessions if k[1] == gateway_id]
        return await self._evict_keys_in_parallel(keys)

    async def _evict_keys_in_parallel(self, keys: list[tuple[str, str]]) -> int:
        """Run _evict_key concurrently for a set of keys; returns the count that succeeded."""
        if not keys:
            return 0
        results = await asyncio.gather(*[self._evict_key(k) for k in keys], return_exceptions=True)
        return sum(1 for r in results if r is True)

    async def close_all(self) -> None:
        """Drain every upstream session concurrently. Intended for app shutdown.

        Each ``_evict_key`` can take up to ``shutdown_timeout_seconds`` waiting
        for the owner task to exit; running them in series on a worker with
        dozens of downstream sessions would turn shutdown into a multi-minute
        stall. ``asyncio.gather`` caps the total drain at roughly
        ``shutdown_timeout_seconds`` plus a small constant.
        """
        async with self._global_lock:
            keys = list(self._sessions.keys())
        if not keys:
            return
        await asyncio.gather(*[self._evict_key(k) for k in keys], return_exceptions=True)

    def snapshot(self) -> RegistrySnapshot:
        """Return a point-in-time copy of the registry's counters."""
        return RegistrySnapshot(
            active_sessions=len(self._sessions),
            creates=self._metrics.creates,
            reuses=self._metrics.reuses,
            health_check_failures=self._metrics.health_check_failures,
            health_check_recreates=self._metrics.health_check_recreates,
            evictions=self._metrics.evictions,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_key_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        """Return (creating if needed) the per-key lock used to serialize check-or-create."""
        async with self._global_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    async def _evict_key(self, key: tuple[str, str]) -> bool:
        """Close the session at ``key`` (if any) and drop its entry. Returns True on eviction."""
        lock = await self._get_key_lock(key)
        async with lock:
            session = self._sessions.pop(key, None)
            if session is None:
                self._key_locks.pop(key, None)
                return False
            await self._close_session(session)
            self._metrics.evictions += 1
        # Drop the key lock after release; safe because we hold _global_lock
        # only briefly and any new acquire() will recreate the lock lazily.
        async with self._global_lock:
            self._key_locks.pop(key, None)
        return True

    async def _create_session(
        self,
        *,
        downstream_session_id: str,
        gateway_id: str,
        url: str,
        headers: Optional[dict[str, str]],
        transport_type: TransportType,
        httpx_client_factory: Optional[HttpxClientFactory],
    ) -> UpstreamSession:
        """Build a fresh upstream session via the configured SessionFactory."""
        merged_headers = {"Accept": "application/json, text/event-stream"}
        if headers:
            merged_headers.update(headers)
        # Strip gateway-internal session affinity headers; they must not be
        # forwarded upstream. Upstream sees its own session id, which it
        # assigns via its initialize response.
        for hdr in list(merged_headers):
            if hdr.lower() in ("x-mcp-session-id", "mcp-session-id"):
                del merged_headers[hdr]

        req = SessionCreateRequest(
            url=url,
            transport_type=transport_type,
            headers=merged_headers,
            gateway_id=gateway_id,
            downstream_session_id=downstream_session_id,
            httpx_client_factory=httpx_client_factory,
            message_handler_factory=self._message_handler_factory,
            timeout_seconds=self._session_create_timeout_seconds,
        )
        session, _transport_ctx = await self._session_factory(req)
        owner_task = getattr(session, "_cf_owner_task", None)
        shutdown_event = getattr(session, "_cf_shutdown_event", None)
        return UpstreamSession(
            downstream_session_id=downstream_session_id,
            gateway_id=gateway_id,
            url=url,
            transport_type=transport_type,
            session=session,
            _owner_task=owner_task,
            _shutdown_event=shutdown_event,
        )

    async def _probe_health(self, upstream: UpstreamSession) -> bool:
        """Run the health check chain against an idle session. Returns False if all probes fail.

        Exception policy: we ADVANCE on ``TimeoutError`` and on
        ``McpError(METHOD_NOT_FOUND)`` (the server chose not to implement
        this probe), and we FAIL FAST on everything else transport- or
        protocol-level (``OSError`` / anyio stream errors / other ``McpError``s)
        — recreating a session on "permission denied" or "request too large"
        would loop against the same failure. Genuinely unexpected exceptions
        (``AttributeError`` from SDK drift, etc.) propagate so they surface in
        telemetry instead of silently triggering a reconnect loop.
        """
        for method in _HEALTH_CHECK_CHAIN:
            try:
                if method == "skip":
                    return True
                with anyio.fail_after(self._health_check_timeout_seconds):
                    if method == "ping":
                        await upstream.session.send_ping()
                    elif method == "list_tools":
                        await upstream.session.list_tools()
                    elif method == "list_prompts":
                        await upstream.session.list_prompts()
                    elif method == "list_resources":
                        await upstream.session.list_resources()
                return True
            except McpError as exc:
                if exc.error.code == _METHOD_NOT_FOUND:
                    continue  # Server doesn't support this probe; try the next one.
                self._metrics.health_check_failures += 1
                return False
            except TimeoutError:
                continue
            except OSError:
                # Socket / stream error — upstream is dead.
                self._metrics.health_check_failures += 1
                return False
        self._metrics.health_check_failures += 1
        return False

    async def _close_session(self, upstream: UpstreamSession) -> None:
        """Signal the owner task to shut down and wait, with a timeout fallback.

        Uses ``asyncio.wait`` rather than ``await task`` so a rogue owner
        that catches CancelledError without re-raising cannot hang shutdown.
        The caller's cancellation cannot be used to interrupt ``await task``
        in that case: asyncio chains the cancel into the awaited task, but
        if the awaited task refuses to die, the ``await`` is stuck waiting
        for it to complete. ``asyncio.wait`` returns once its own timer
        fires, regardless of the awaited task's state.

        The leading-underscore fields on ``UpstreamSession`` are private to
        this module — the registry owns the session lifecycle and is the
        only legitimate mutator of ``_closed`` / ``_shutdown_event`` /
        ``_owner_task``. Pylint's ``protected-access`` rule is disabled
        inline for each access because the alternative (a public setter
        per field) would leak lifecycle mechanics to any caller that
        happened to import ``UpstreamSession``.
        """
        # pylint: disable=protected-access
        if upstream._closed:
            return
        upstream._closed = True
        if upstream._shutdown_event is not None:
            upstream._shutdown_event.set()
        if upstream._owner_task is None or upstream._owner_task.done():
            return

        owner_task = upstream._owner_task
        # Give the task its graceful window — it should notice shutdown_event
        # and exit cleanly.
        done, _pending = await asyncio.wait({owner_task}, timeout=self._shutdown_timeout_seconds)
        if owner_task in done:
            # Task finished cleanly; consume any exception so asyncio doesn't
            # warn "Task exception was never retrieved".
            if not owner_task.cancelled():
                exc = owner_task.exception()
                if exc is not None:
                    logger.debug(
                        "Owner task for %s (gateway=%s) exited during _close_session with %s: %s",
                        sanitize_url_for_logging(upstream.url),
                        upstream.gateway_id,
                        type(exc).__name__,
                        exc,
                    )
            return

        # Grace period elapsed — force-cancel and give one more bounded wait.
        logger.warning(
            "Upstream session owner cleanup timed out for session=%s gateway=%s url=%s; force-cancelling",
            upstream.downstream_session_id,
            upstream.gateway_id,
            sanitize_url_for_logging(upstream.url),
        )
        owner_task.cancel()
        done, _pending = await asyncio.wait({owner_task}, timeout=self._shutdown_timeout_seconds)
        if owner_task not in done:
            logger.warning(
                "Force-cancel of owner task did not complete within %.1fs for session=%s gateway=%s — task is orphaned but shutdown is proceeding",
                self._shutdown_timeout_seconds,
                upstream.downstream_session_id,
                upstream.gateway_id,
            )
            return
        # Consume any final exception.
        if not owner_task.cancelled():
            with contextlib.suppress(Exception):  # noqa: BLE001 — final retrieval
                owner_task.result()


class _AcquireDecision(Enum):
    """Why acquire() chose to reuse vs create (internal only, aids reasoning)."""

    REUSE = "reuse"
    CREATE = "create"


# ----------------------------------------------------------------------
# Module-level singleton accessors (mirrors the shape of get_session_affinity)
# ----------------------------------------------------------------------

_registry: Optional[UpstreamSessionRegistry] = None


class RegistryNotInitializedError(RuntimeError):
    """Raised when ``get_upstream_session_registry()`` is called before startup init.

    Callers that need to distinguish "registry not available yet" from other
    runtime errors (so they can silently no-op in tests / early bootstrap
    without also swallowing unrelated ``RuntimeError``s like "Event loop is
    closed") should catch this type specifically. Inherits ``RuntimeError``
    for backwards compatibility with catch-sites written before the split.
    """


def init_upstream_session_registry(
    *,
    message_handler_factory: Optional[MessageHandlerFactory] = None,
    **overrides: Any,
) -> UpstreamSessionRegistry:
    """Install the process-wide registry. Call once at app startup."""
    global _registry
    _registry = UpstreamSessionRegistry(message_handler_factory=message_handler_factory, **overrides)
    return _registry


def get_upstream_session_registry() -> UpstreamSessionRegistry:
    """Return the process-wide registry or raise ``RegistryNotInitializedError``."""
    if _registry is None:
        raise RegistryNotInitializedError("UpstreamSessionRegistry has not been initialized; call init_upstream_session_registry() first")
    return _registry


async def shutdown_upstream_session_registry() -> None:
    """Drain and clear the process-wide registry."""
    global _registry
    if _registry is not None:
        await _registry.close_all()
        _registry = None


def downstream_session_id_from_request_context() -> Optional[str]:
    """Return the downstream Mcp-Session-Id for the current request, or None.

    Reads from the neutral ``mcpgateway.transports.context`` module's
    per-request ContextVar. Service-layer callers (tool_service,
    prompt_service, resource_service) use this to key the registry so that
    an upstream session is bound 1:1 to the downstream MCP session that
    initiated the call.
    """
    headers = request_headers_var.get() or {}
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get("x-mcp-session-id") or lowered.get("mcp-session-id") or None
