# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Redis-backed ownership and cancellable request relay for reverse-proxy WebSockets.
Audit marker: # noqa: SIZE_OK — one state machine keeps generation and task-scope invariants together.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import math
import time
from typing import assert_never, Final, TypeVar
import uuid

# Third-Party
import anyio
from anyio import TASK_STATUS_IGNORED
from anyio.abc import TaskStatus
import orjson
from pydantic import ValidationError

# First-Party
from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, JsonRpcRequest, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_relay_io import cleanup_pubsub, parse_inbound, parse_pubsub_message, parse_response, sign_envelope, unwrap_response
from mcpgateway.services.reverse_proxy_relay_models import RelayAuth, RelayCancelEnvelope, RelayDisconnectEnvelope, RelayOwner, RelayPubSub, RelayRedis, RelayRequestEnvelope, RelaySessionEntry
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId

_MAX_PAYLOAD_BYTES: Final = 1_048_576
_WORKER_HEARTBEAT_TTL_SECONDS: Final = 30
_OWNER_REFRESH_LUA: Final = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], ARGV[2]) end return 0"
_OWNER_RELEASE_LUA: Final = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"
_REGISTRATION_PROMOTE_LUA: Final = "if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3]); return 1 end return 0"
_RedisResult = TypeVar("_RedisResult")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RelayTarget:
    """A Redis-confirmed remote owner generation for one stable gateway."""

    stable_id: StableGatewayId
    owner: RelayOwner


class RelayUnavailableError(RuntimeError):
    """Code-only distributed relay infrastructure failure."""

    def __init__(self) -> None:
        """Initialize the stable code-only infrastructure error."""
        super().__init__("reverse-proxy relay unavailable")


@dataclass(frozen=True, slots=True)
class _OwnerOperation:
    """Tracked owner request authority and its cancellation scope."""

    stable_id: str
    connection_id: str
    origin_worker_id: str
    scope: anyio.CancelScope


class ReverseProxyRelay:
    """Relay-aware wrapper over one process-local reverse-proxy session manager."""

    def __init__(
        self,
        manager: ReverseProxySessionManager,
        *,
        redis: RelayRedis | None,
        worker_id: Callable[[], str],
        owner_ttl_seconds: int,
        utc_now: Callable[[], float] = time.time,
        ownership_lost: Callable[[tuple[ReverseProxyEviction, ...]], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize relay state around a process-local session manager."""
        self._manager = manager
        self._redis = redis
        self._worker_id = worker_id
        self._owner_ttl_seconds = owner_ttl_seconds
        self._utc_now = utc_now
        self._ownership_lost = ownership_lost
        self.max_payload_bytes = _MAX_PAYLOAD_BYTES
        self._owner_scopes: dict[str, _OwnerOperation] = {}
        self._idle_event = anyio.Event()
        self._idle_event.set()
        self._listening_event = anyio.Event()

    @property
    def owner_request_count(self) -> int:
        """Return active owner-side request tasks."""
        return len(self._owner_scopes)

    async def wait_for_idle(self) -> None:
        """Wait until all tracked owner-side work has ended."""
        await self._idle_event.wait()

    async def wait_until_listening(self) -> None:
        """Wait until the worker channel subscription is active."""
        await self._listening_event.wait()

    @staticmethod
    def owner_key(stable_id: StableGatewayId) -> str:
        """Return the Redis ownership key for a stable gateway."""
        return f"mcpgw:rp_owner:{stable_id}"

    @staticmethod
    def registration_key(stable_id: StableGatewayId) -> str:
        """Return the Redis registration-lease key for a stable gateway."""
        return f"mcpgw:rp_registration:{stable_id}"

    @staticmethod
    def session_key(connection_id: ConnectionId) -> str:
        """Return the Redis directory key for one connection generation."""
        return f"mcpgw:rp_session:{connection_id}"

    @staticmethod
    def session_index_key() -> str:
        """Return the global Redis set containing active connection IDs."""
        return "mcpgw:rp_sessions"

    @staticmethod
    def response_channel(request_id: str) -> str:
        """Derive the only permitted response channel from a server request ID."""
        return f"mcpgw:rp_response:{request_id}"

    def owner_value(self, connection_id: ConnectionId, *, worker_id: str | None = None) -> str:
        """Serialize one exact worker and connection ownership generation."""
        return RelayOwner(worker_id=worker_id or self._worker_id(), connection_id=str(connection_id)).model_dump_json()

    async def claim_registration(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Acquire the single-writer lease before any catalog mutation."""
        if self._redis is None:
            return False
        return bool(
            await self._redis_operation(
                self._redis.set(
                    self.registration_key(stable_id),
                    self.owner_value(connection_id),
                    nx=True,
                    ex=self._owner_ttl_seconds,
                )
            )
        )

    async def heartbeat_registration(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Refresh the registration lease only for its exact generation."""
        if self._redis is None:
            return False
        return (
            await self._redis_operation(
                self._redis.eval(
                    _OWNER_REFRESH_LUA,
                    1,
                    self.registration_key(stable_id),
                    self.owner_value(connection_id),
                    self._owner_ttl_seconds,
                )
            )
            == 1
        )

    async def release_registration(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Release only the matching registration generation."""
        if self._redis is None:
            return False
        return (
            await self._redis_operation(
                self._redis.eval(
                    _OWNER_RELEASE_LUA,
                    1,
                    self.registration_key(stable_id),
                    self.owner_value(connection_id),
                )
            )
            == 1
        )

    async def promote_registration(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Atomically replace active ownership only for the matching lease holder.

        The lease remains held until all post-commit publication and client
        acknowledgement succeeds, preventing a replacement registration from
        racing failure compensation.
        """
        if self._redis is None:
            return False
        return (
            await self._redis_operation(
                self._redis.eval(
                    _REGISTRATION_PROMOTE_LUA,
                    2,
                    self.registration_key(stable_id),
                    self.owner_key(stable_id),
                    self.owner_value(connection_id),
                    self.owner_value(connection_id),
                    self._owner_ttl_seconds,
                )
            )
            == 1
        )

    async def maintain_registration(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> None:
        """Refresh a held registration lease until cancelled or authority is lost."""
        refresh_interval = max(self._owner_ttl_seconds / 3, 0.1)
        while True:
            await anyio.sleep(refresh_interval)
            if not await self.heartbeat_registration(stable_id, connection_id):
                raise RuntimeError("reverse-proxy registration authority was lost")

    async def claim_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Claim ownership when no generation currently owns the stable gateway."""
        if self._redis is None:
            return False
        owner_key = self.owner_key(stable_id)
        owner_value = self.owner_value(connection_id)
        if await self._redis_operation(self._redis.set(owner_key, owner_value, nx=True, ex=self._owner_ttl_seconds)):
            return True
        current = await self._read_owner(stable_id)
        if current is None or current.worker_id != self._worker_id() or self._manager.get_session(ConnectionId(current.connection_id)) is not None:
            return False
        released = await self._redis_operation(self._redis.eval(_OWNER_RELEASE_LUA, 1, owner_key, current.model_dump_json()))
        return released == 1 and bool(await self._redis_operation(self._redis.set(owner_key, owner_value, nx=True, ex=self._owner_ttl_seconds)))

    async def heartbeat_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Refresh ownership only when the exact generation still owns it."""
        if self._redis is None:
            return False
        return await self._redis_operation(self._redis.eval(_OWNER_REFRESH_LUA, 1, self.owner_key(stable_id), self.owner_value(connection_id), self._owner_ttl_seconds)) == 1

    async def release_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Release ownership only when the exact generation still owns it."""
        if self._redis is None:
            return False
        return await self._redis_operation(self._redis.eval(_OWNER_RELEASE_LUA, 1, self.owner_key(stable_id), self.owner_value(connection_id))) == 1

    async def is_unowned(self, eviction: ReverseProxyEviction) -> bool:
        """Return whether Redis has no owner after one exact generation was evicted."""
        return await self._read_owner(eviction.stable_id) is None

    @asynccontextmanager
    async def unreachable_write_guard(self, eviction: ReverseProxyEviction) -> AsyncIterator[bool]:
        """Serialize one unreachable write against concurrent replacement registration.

        Acquiring ``mcpgw:rp_registration:{stable_id}`` for the evicted
        generation closes the check-then-commit race: while a replacement holds
        the lease the guard denies the write, and while the guard holds the
        lease no replacement can publish its owner through
        ``promote_registration``. The owner-absence decision therefore stays
        valid through the caller's persistence commit. The lease carries the
        owner TTL and is released fenced on exit, best-effort.
        """
        if self._redis is None:
            yield await self.is_unowned(eviction)
            return
        claimed = await self._redis_operation(
            self._redis.set(
                self.registration_key(eviction.stable_id),
                self.owner_value(eviction.connection_id),
                nx=True,
                ex=self._owner_ttl_seconds,
            )
        )
        if not claimed:
            yield False
            return
        try:
            yield await self.is_unowned(eviction)
        finally:
            try:
                await self._redis_operation(self._redis.eval(_OWNER_RELEASE_LUA, 1, self.registration_key(eviction.stable_id), self.owner_value(eviction.connection_id)))
            except RelayUnavailableError:
                # The lease still expires by TTL; a lost release must not mask the write outcome.
                LOGGER.warning("Reverse-proxy unreachable-write lease release failed", extra={"stable_id": str(eviction.stable_id)})

    async def publish_session(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> RelaySessionEntry:
        """Publish typed session metadata for worker-independent control-plane lookup."""
        if self._redis is None:
            raise RelayUnavailableError
        session = self._manager.get_session(connection_id)
        if session is None:
            raise ConnectionNotFoundError(connection_id)
        entry = RelaySessionEntry(
            connection_id=str(connection_id),
            stable_id=str(stable_id),
            owner=RelayOwner(worker_id=self._worker_id(), connection_id=str(connection_id)),
            owner_email=session.owner_email,
            connected_at=session.connected_at.isoformat(),
            last_activity=session.last_activity.isoformat(),
            message_count=session.message_count,
            bytes_transferred=session.bytes_transferred,
            server_info=dict(session.server_info),
        )
        await self._redis_operation(self._redis.setex(self.session_key(connection_id), self._owner_ttl_seconds, entry.model_dump_json()))
        await self._redis_operation(self._redis.sadd(self.session_index_key(), str(connection_id)))
        return entry

    async def remove_session(self, connection_id: ConnectionId) -> None:
        """Remove one exact connection from the distributed session directory."""
        if self._redis is None:
            return
        await self._redis_operation(self._redis.delete(self.session_key(connection_id)))
        await self._redis_operation(self._redis.srem(self.session_index_key(), str(connection_id)))

    async def get_session_entry(self, connection_id: ConnectionId) -> RelaySessionEntry | None:
        """Resolve one connection's typed distributed directory entry."""
        if self._redis is None:
            return None
        raw = await self._redis_operation(self._redis.get(self.session_key(connection_id)))
        try:
            return RelaySessionEntry.model_validate_json(raw) if raw is not None else None
        except ValidationError:
            await self.remove_session(connection_id)
            return None

    async def list_session_entries(self) -> tuple[RelaySessionEntry, ...]:
        """List live typed entries and prune expired index members."""
        if self._redis is None:
            return ()
        raw_members = await self._redis_operation(self._redis.smembers(self.session_index_key()))
        entries: list[RelaySessionEntry] = []
        for raw_member in raw_members:
            connection_id = ConnectionId(raw_member.decode() if isinstance(raw_member, bytes) else raw_member)
            entry = await self.get_session_entry(connection_id)
            if entry is None:
                await self._redis_operation(self._redis.srem(self.session_index_key(), str(connection_id)))
            else:
                entries.append(entry)
        return tuple(entries)

    async def heartbeat_worker(self) -> bool:
        """Publish liveness for the current worker with a bounded TTL."""
        if self._redis is None:
            return False
        return bool(await self._redis_operation(self._redis.setex(f"mcpgw:worker_heartbeat:{self._worker_id()}", _WORKER_HEARTBEAT_TTL_SECONDS, "alive")))

    async def heartbeat(self) -> None:
        """Refresh this worker and only the exact local ownership generations."""
        mappings = self._manager.stable_connections()
        try:
            if not await self.heartbeat_worker():
                raise RelayUnavailableError
            for stable_id, connection_id in mappings:
                if not await self.heartbeat_owner(stable_id, connection_id):
                    await self._retire_lost_authority(stable_id, connection_id)
                else:
                    await self.publish_session(stable_id, connection_id)
        except RelayUnavailableError:
            await self._retire_all_local_authority(mappings)
            raise

    def resolve_connection_id(self, stable_id: StableGatewayId) -> ConnectionId | None:
        """Resolve process-local state only; remote authority requires Redis I/O."""
        return self._manager.resolve_connection_id(stable_id)

    async def resolve_target(self, stable_id: StableGatewayId) -> ConnectionId | RelayTarget | None:
        """Resolve local state or a currently existing Redis owner generation."""
        local = self._manager.resolve_connection_id(stable_id)
        if self._redis is None:
            return local
        try:
            owner = await self._read_owner(stable_id)
        except RelayUnavailableError:
            if local is not None:
                await self._retire_lost_authority(stable_id, local)
            raise
        if local is not None:
            expected = RelayOwner(worker_id=self._worker_id(), connection_id=str(local))
            if owner == expected:
                return local
            await self._retire_lost_authority(stable_id, local)
        return RelayTarget(stable_id, owner) if owner is not None else None

    async def _retire_lost_authority(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> None:
        """Retire only the still-current local generation after Redis authority loss."""
        if self._manager.resolve_connection_id(stable_id) != connection_id:
            return
        evictions = await self._manager.retire_connection(connection_id)
        if evictions and self._ownership_lost is not None:
            await self._ownership_lost(evictions)

    async def _retire_all_local_authority(self, mappings: tuple[tuple[StableGatewayId, ConnectionId], ...]) -> None:
        """Retire each snapshot generation only while it remains locally current."""
        for stable_id, connection_id in mappings:
            await self._retire_lost_authority(stable_id, connection_id)

    @staticmethod
    async def _redis_operation(operation: Awaitable[_RedisResult]) -> _RedisResult:
        """Convert Redis implementation failures into one code-only relay error."""
        try:
            return await operation
        except Exception:  # Redis implementations expose multiple backend-specific failure classes
            raise RelayUnavailableError from None

    @staticmethod
    def _redis_sync_operation(operation: Callable[[], _RedisResult]) -> _RedisResult:
        """Convert synchronous Redis factory failures into the code-only error."""
        try:
            return operation()
        except Exception:  # Redis factory implementations expose backend-specific failure classes
            raise RelayUnavailableError from None

    async def send_request(self, connection_id: ConnectionId, payload: JsonRpcRequest, timeout_seconds: float, auth: DownstreamAuth | None = None) -> ResponseMessage:
        """Preserve direct typed-manager sending for an already-local connection."""
        return await self._manager.send_request(connection_id, payload, timeout_seconds, auth=auth)

    async def send_request_by_stable_id(self, stable_id: StableGatewayId, payload: JsonRpcRequest, timeout_seconds: float, auth: DownstreamAuth | None = None) -> ResponseMessage:
        """Resolve current authority and send locally or through the distributed relay."""
        if timeout_seconds <= 0:
            raise TimeoutError
        target = await self.resolve_target(stable_id)
        if target is None:
            raise ConnectionNotFoundError(ConnectionId(str(stable_id)))
        if isinstance(target, str):
            return await self._manager.send_request(ConnectionId(target), payload, timeout_seconds, auth=auth)
        return await self._send_remote(target, payload, timeout_seconds, auth)

    async def send_request_by_connection_id(self, connection_id: ConnectionId, payload: JsonRpcRequest, timeout_seconds: float) -> ResponseMessage:
        """Dispatch to one exact local or remote connection generation."""
        target = await self._resolve_connection_target(connection_id)
        if isinstance(target, str):
            return await self._manager.send_request(connection_id, payload, timeout_seconds)
        return await self._send_remote(target, payload, timeout_seconds, None)

    async def send_request_by_connection_id_nowait(self, connection_id: ConnectionId, payload: JsonRpcRequest, timeout_seconds: float) -> None:
        """Emit one exact-connection request and await only owner-side frame delivery."""
        if timeout_seconds <= 0:
            raise TimeoutError
        target = await self._resolve_connection_target(connection_id)
        if isinstance(target, str):
            await self._manager.send_request_nowait(connection_id, payload, timeout_seconds)
            return
        await self._send_remote(target, payload, timeout_seconds, None, expect_response=False)

    async def _resolve_connection_target(self, connection_id: ConnectionId) -> ConnectionId | RelayTarget:
        """Resolve one exact connection through Redis generation authority."""
        if self._redis is None:
            raise RelayUnavailableError
        if self._manager.get_session(connection_id) is not None:
            stable_id = next((stable for stable, current in self._manager.stable_connections() if current == connection_id), None)
            if stable_id is None:
                raise ConnectionNotFoundError(connection_id)
            target = await self.resolve_target(stable_id)
            if target == connection_id:
                return connection_id
            raise ConnectionNotFoundError(connection_id)
        entry = await self.get_session_entry(connection_id)
        if entry is None:
            raise ConnectionNotFoundError(connection_id)
        stable_id = StableGatewayId(entry.stable_id)
        owner = await self._read_owner(stable_id)
        if owner is None or owner != entry.owner or owner.connection_id != str(connection_id):
            await self.remove_session(connection_id)
            raise ConnectionNotFoundError(connection_id)
        return RelayTarget(stable_id, owner)

    async def disconnect_session(self, connection_id: ConnectionId) -> bool:
        """Retire one exact local generation or publish a signed owner command."""
        local_session = self._manager.get_session(connection_id)
        if local_session is not None:
            stable_id = next((stable for stable, current in self._manager.stable_connections() if current == connection_id), None)
            if stable_id is None:
                return False
            return await self._execute_disconnect(
                RelayDisconnectEnvelope(
                    type="rp_disconnect",
                    request_id=uuid.uuid4().hex,
                    stable_id=str(stable_id),
                    owner_connection_id=str(connection_id),
                    origin_worker_id=self._worker_id(),
                    forward_sig="0" * 64,
                )
            )
        entry = await self.get_session_entry(connection_id)
        if entry is None:
            return False
        owner = await self._read_owner(StableGatewayId(entry.stable_id))
        if owner is None or owner != entry.owner:
            await self.remove_session(connection_id)
            return False
        redis = self._redis
        if redis is None:
            return False
        envelope = RelayDisconnectEnvelope(
            type="rp_disconnect",
            request_id=uuid.uuid4().hex,
            stable_id=entry.stable_id,
            owner_connection_id=str(connection_id),
            origin_worker_id=self._worker_id(),
            forward_sig="0" * 64,
        )
        published = await self._redis_operation(
            redis.publish(
                f"mcpgw:pool_rp:{owner.worker_id}",
                orjson.dumps(sign_envelope(envelope.model_dump(mode="json", exclude={"forward_sig"}))),
            )
        )
        return bool(published)

    async def _send_remote(
        self,
        target: RelayTarget,
        payload: JsonRpcRequest,
        timeout_seconds: float,
        auth: DownstreamAuth | None,
        *,
        expect_response: bool = True,
    ) -> ResponseMessage:
        """Publish one remote request and await its correlated response."""
        redis = self._redis
        if redis is None:
            raise ConnectionNotFoundError(ConnectionId(str(target.stable_id)))
        owner = target.owner
        if not await self._redis_operation(redis.exists(f"mcpgw:worker_heartbeat:{owner.worker_id}")):
            await self._redis_operation(redis.eval(_OWNER_RELEASE_LUA, 1, self.owner_key(target.stable_id), owner.model_dump_json()))
            raise ConnectionNotFoundError(ConnectionId(owner.connection_id))
        request_id = uuid.uuid4().hex
        deadline = self._utc_now() + timeout_seconds
        envelope = RelayRequestEnvelope(
            type="rp_request",
            request_id=request_id,
            stable_id=str(target.stable_id),
            owner_connection_id=owner.connection_id,
            origin_worker_id=self._worker_id(),
            payload=payload,
            auth=RelayAuth(headers=dict(auth.headers), auth_type=auth.auth_type) if auth else None,
            deadline_utc=deadline,
            expect_response=expect_response,
            forward_sig="0" * 64,
        )
        outbound = sign_envelope(envelope.model_dump(mode="json", exclude={"forward_sig"}))
        channel = self.response_channel(request_id)
        pubsub = self._redis_sync_operation(redis.pubsub)
        completed = False
        try:
            await self._redis_operation(pubsub.subscribe(channel))
            await self._redis_operation(redis.publish(f"mcpgw:pool_rp:{owner.worker_id}", orjson.dumps(outbound)))
            with anyio.fail_after(max(0.0, deadline - self._utc_now())):
                async for entry in self._listen_pubsub(pubsub):
                    raw = parse_pubsub_message(entry)
                    if raw is None:
                        continue
                    response = parse_response(raw, request_id, payload.id, self.max_payload_bytes)
                    if response is not None:
                        completed = True
                        return unwrap_response(response, owner.connection_id)
        finally:
            if not completed:
                await self._publish_cancel(target, request_id)
            await cleanup_pubsub(pubsub, channel)
        raise TimeoutError

    async def _publish_cancel(self, target: RelayTarget, request_id: str) -> None:
        """Best-effort publish cancellation to the exact owner generation."""
        redis = self._redis
        if redis is None:
            return
        cancel = RelayCancelEnvelope(
            type="rp_cancel", request_id=request_id, stable_id=str(target.stable_id), owner_connection_id=target.owner.connection_id, origin_worker_id=self._worker_id(), forward_sig="0" * 64
        )
        with anyio.move_on_after(1, shield=True):
            try:
                await redis.publish(f"mcpgw:pool_rp:{target.owner.worker_id}", orjson.dumps(sign_envelope(cancel.model_dump(mode="json", exclude={"forward_sig"}))))
            except Exception:  # pylint: disable=broad-exception-caught  # best-effort cancellation publication
                return

    async def listen(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        """Consume Redis entries while owner requests execute concurrently."""
        redis = self._redis
        if redis is None:
            task_status.started()
            return
        channel = f"mcpgw:pool_rp:{self._worker_id()}"
        started = False
        while True:
            pubsub = None
            reconnect = False
            try:
                pubsub = self._redis_sync_operation(redis.pubsub)
                await self._redis_operation(pubsub.subscribe(channel))
                if not started:
                    self._listening_event.set()
                    task_status.started()
                    started = True
                try:
                    async with anyio.create_task_group() as tasks:
                        async for entry in self._listen_pubsub(pubsub):
                            raw = parse_pubsub_message(entry)
                            if raw is None:
                                continue
                            envelope = parse_inbound(raw, self.max_payload_bytes)
                            match envelope:
                                case RelayCancelEnvelope():
                                    operation = self._owner_scopes.get(envelope.request_id)
                                    if operation is not None and (operation.stable_id, operation.connection_id, operation.origin_worker_id) == (
                                        envelope.stable_id,
                                        envelope.owner_connection_id,
                                        envelope.origin_worker_id,
                                    ):
                                        operation.scope.cancel()
                                case RelayRequestEnvelope():
                                    if not await self._claim_request(envelope):
                                        continue
                                    scope = anyio.CancelScope()
                                    self._owner_scopes[envelope.request_id] = _OwnerOperation(envelope.stable_id, envelope.owner_connection_id, envelope.origin_worker_id, scope)
                                    self._idle_event = anyio.Event()
                                    tasks.start_soon(self._run_owner_request, envelope, scope, True)
                                case RelayDisconnectEnvelope():
                                    tasks.start_soon(self._execute_disconnect, envelope)
                                case None:
                                    continue
                                case unreachable:
                                    assert_never(unreachable)
                    reconnect = True
                except* RelayUnavailableError:
                    reconnect = True
            except RelayUnavailableError:
                if not started:
                    raise
                reconnect = True
            finally:
                if pubsub is not None:
                    await cleanup_pubsub(pubsub, channel)
            if reconnect:
                LOGGER.warning("Reverse-proxy relay listener unavailable; retrying")
                await anyio.sleep(1)

    async def handle_message(self, raw: str | bytes) -> bool:
        """Verify and synchronously dispatch one request for focused use/tests."""
        envelope = parse_inbound(raw, self.max_payload_bytes)
        if isinstance(envelope, RelayRequestEnvelope):
            return await self._execute_owner_request(envelope)
        if isinstance(envelope, RelayDisconnectEnvelope):
            return await self._execute_disconnect(envelope)
        return False

    async def _execute_disconnect(self, envelope: RelayDisconnectEnvelope) -> bool:
        """Revalidate and retire one exact owner generation."""
        stable_id = StableGatewayId(envelope.stable_id)
        connection_id = ConnectionId(envelope.owner_connection_id)
        expected = RelayOwner(worker_id=self._worker_id(), connection_id=envelope.owner_connection_id)
        if await self._read_owner(stable_id) != expected or self._manager.resolve_connection_id(stable_id) != connection_id:
            return False
        evictions = await self._manager.retire_connection(connection_id)
        await self.release_owner(stable_id, connection_id)
        await self.remove_session(connection_id)
        if evictions and self._ownership_lost is not None:
            await self._ownership_lost(evictions)
        return True

    async def _run_owner_request(self, envelope: RelayRequestEnvelope, scope: anyio.CancelScope, request_claimed: bool = False) -> None:
        """Run one owner request within its tracked cancellation scope."""
        try:
            with scope:
                await self._execute_owner_request(envelope, request_claimed=request_claimed)
        finally:
            self._owner_scopes.pop(envelope.request_id, None)
            if not self._owner_scopes:
                self._idle_event.set()

    async def _execute_owner_request(self, envelope: RelayRequestEnvelope, *, request_claimed: bool = False) -> bool:
        """Revalidate authority and dispatch one request to the local manager."""
        redis = self._redis
        if redis is None or envelope.deadline_utc <= self._utc_now():
            return False
        if not request_claimed and not await self._claim_request(envelope):
            return False
        stable_id = StableGatewayId(envelope.stable_id)
        expected = RelayOwner(worker_id=self._worker_id(), connection_id=envelope.owner_connection_id)
        current = await self._read_owner(stable_id)
        local = self._manager.resolve_connection_id(stable_id)
        if current != expected or local is None or str(local) != envelope.owner_connection_id:
            return False
        remaining = envelope.deadline_utc - self._utc_now()
        try:
            if not envelope.expect_response:
                await self._manager.send_request_nowait(local, envelope.payload, remaining)
                response = ResponseMessage(
                    type="response",
                    payload=JsonRpcSuccessResponse(jsonrpc="2.0", id=envelope.payload.id, result={"sent": True}),
                )
            else:
                response = await self._manager.send_request(
                    local, envelope.payload, remaining, auth=DownstreamAuth(headers=envelope.auth.headers, auth_type=envelope.auth.auth_type) if envelope.auth else None
                )
        except TimeoutError:
            await self._publish_outcome(envelope.request_id, error="timeout")
            return False
        except ConnectionClosedError:
            await self._publish_outcome(envelope.request_id, error="connection_closed")
            return False
        except ConnectionNotFoundError:
            await self._publish_outcome(envelope.request_id, error="connection_not_found")
            return False
        except Exception:  # pylint: disable=broad-exception-caught  # owner boundary emits code-only failures
            await self._publish_outcome(envelope.request_id, error="internal_error")
            return False
        await self._publish_outcome(envelope.request_id, response=response)
        return True

    async def _claim_request(self, envelope: RelayRequestEnvelope) -> bool:
        """Atomically consume one signed request ID until its deadline passes."""
        redis = self._redis
        remaining = envelope.deadline_utc - self._utc_now()
        if redis is None or remaining <= 0:
            return False
        claimed = await self._redis_operation(
            redis.set(
                f"mcpgw:rp_consumed:{envelope.origin_worker_id}:{envelope.request_id}",
                envelope.forward_sig,
                nx=True,
                ex=max(1, math.ceil(remaining)),
            )
        )
        return bool(claimed)

    async def _publish_outcome(self, request_id: str, *, response: ResponseMessage | None = None, error: str | None = None) -> None:
        """Publish one signed response or code-only relay error."""
        redis = self._redis
        if redis is None:
            return
        raw = {"type": "rp_response", "request_id": request_id, "response": response.model_dump(mode="json") if response else None, "error": error}
        await self._redis_operation(redis.publish(self.response_channel(request_id), orjson.dumps(sign_envelope({key: value for key, value in raw.items() if value is not None}))))

    async def _read_owner(self, stable_id: StableGatewayId) -> RelayOwner | None:
        """Read and strictly parse the current Redis owner generation."""
        if self._redis is None:
            return None
        raw = await self._redis_operation(self._redis.get(self.owner_key(stable_id)))
        try:
            return RelayOwner.model_validate_json(raw) if raw is not None else None
        except ValidationError:
            return None

    @staticmethod
    async def _listen_pubsub(pubsub: RelayPubSub) -> AsyncIterator[dict[str, str | bytes | int | None]]:
        """Convert pub/sub transport failures without exposing Redis details."""
        try:
            async for entry in pubsub.listen():
                yield entry
        except Exception:  # pub/sub adapters expose backend-specific iterator failures
            raise RelayUnavailableError from None

    @staticmethod
    def parse_pubsub_message(entry: Mapping[str, str | bytes | int | None] | str) -> str | bytes | None:
        """Return data only from real Redis message entries."""
        return parse_pubsub_message(entry)
