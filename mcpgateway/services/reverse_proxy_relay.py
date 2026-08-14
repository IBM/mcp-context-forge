# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Redis-backed ownership and cancellable request relay for reverse-proxy WebSockets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Final
import uuid

import anyio
from anyio import TASK_STATUS_IGNORED
from anyio.abc import TaskStatus
import orjson
from pydantic import ValidationError

from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, JsonRpcRequest, ResponseMessage
from mcpgateway.services.reverse_proxy_relay_io import cleanup_pubsub, parse_inbound, parse_pubsub_message, parse_response, sign_envelope, unwrap_response
from mcpgateway.services.reverse_proxy_relay_models import RelayAuth, RelayCancelEnvelope, RelayOwner, RelayRedis, RelayRequestEnvelope
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError, ReverseProxySessionManager, StableGatewayId


_MAX_PAYLOAD_BYTES: Final = 1_048_576
_WORKER_HEARTBEAT_TTL_SECONDS: Final = 30
_OWNER_REFRESH_LUA: Final = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('EXPIRE', KEYS[1], ARGV[2]) end return 0"
_OWNER_RELEASE_LUA: Final = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"


@dataclass(frozen=True, slots=True)
class RelayTarget:
    """A Redis-confirmed remote owner generation for one stable gateway."""

    stable_id: StableGatewayId
    owner: RelayOwner


@dataclass(frozen=True, slots=True)
class _OwnerOperation:
    """Tracked owner request authority and its cancellation scope."""

    stable_id: str
    connection_id: str
    origin_worker_id: str
    scope: anyio.CancelScope


class ReverseProxyRelay:
    """Relay-aware wrapper over one process-local reverse-proxy session manager."""

    def __init__(self, manager: ReverseProxySessionManager, *, redis: RelayRedis | None, worker_id: Callable[[], str], owner_ttl_seconds: int, utc_now: Callable[[], float] = time.time) -> None:
        """Initialize relay state around a process-local session manager."""
        self._manager = manager
        self._redis = redis
        self._worker_id = worker_id
        self._owner_ttl_seconds = owner_ttl_seconds
        self._utc_now = utc_now
        self.max_payload_bytes = _MAX_PAYLOAD_BYTES
        self._owner_scopes: dict[str, _OwnerOperation] = {}
        self._idle_event = anyio.Event()
        self._idle_event.set()

    @property
    def owner_request_count(self) -> int:
        """Return active owner-side request tasks."""
        return len(self._owner_scopes)

    async def wait_for_idle(self) -> None:
        """Wait until all tracked owner-side work has ended."""
        await self._idle_event.wait()

    @staticmethod
    def owner_key(stable_id: StableGatewayId) -> str:
        """Return the Redis ownership key for a stable gateway."""
        return f"mcpgw:rp_owner:{stable_id}"

    @staticmethod
    def response_channel(request_id: str) -> str:
        """Derive the only permitted response channel from a server request ID."""
        return f"mcpgw:rp_response:{request_id}"

    def owner_value(self, connection_id: ConnectionId, *, worker_id: str | None = None) -> str:
        """Serialize one exact worker and connection ownership generation."""
        return RelayOwner(worker_id=worker_id or self._worker_id(), connection_id=str(connection_id)).model_dump_json()

    async def claim_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Claim ownership when no generation currently owns the stable gateway."""
        if self._redis is None:
            return False
        return bool(await self._redis.set(self.owner_key(stable_id), self.owner_value(connection_id), nx=True, ex=self._owner_ttl_seconds))

    async def heartbeat_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Refresh ownership only when the exact generation still owns it."""
        if self._redis is None:
            return False
        return await self._redis.eval(_OWNER_REFRESH_LUA, 1, self.owner_key(stable_id), self.owner_value(connection_id), self._owner_ttl_seconds) == 1

    async def release_owner(self, stable_id: StableGatewayId, connection_id: ConnectionId) -> bool:
        """Release ownership only when the exact generation still owns it."""
        if self._redis is None:
            return False
        return await self._redis.eval(_OWNER_RELEASE_LUA, 1, self.owner_key(stable_id), self.owner_value(connection_id)) == 1

    async def heartbeat_worker(self) -> bool:
        """Publish liveness for the current worker with a bounded TTL."""
        if self._redis is None:
            return False
        return bool(await self._redis.setex(f"mcpgw:worker_heartbeat:{self._worker_id()}", _WORKER_HEARTBEAT_TTL_SECONDS, "alive"))

    def resolve_connection_id(self, stable_id: StableGatewayId) -> ConnectionId | None:
        """Resolve process-local state only; remote authority requires Redis I/O."""
        return self._manager.resolve_connection_id(stable_id)

    async def resolve_target(self, stable_id: StableGatewayId) -> ConnectionId | RelayTarget | None:
        """Resolve local state or a currently existing Redis owner generation."""
        local = self._manager.resolve_connection_id(stable_id)
        if local is not None:
            return local
        owner = await self._read_owner(stable_id)
        return RelayTarget(stable_id, owner) if owner is not None else None

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

    async def _send_remote(self, target: RelayTarget, payload: JsonRpcRequest, timeout_seconds: float, auth: DownstreamAuth | None) -> ResponseMessage:
        """Publish one remote request and await its correlated response."""
        redis = self._redis
        if redis is None:
            raise ConnectionNotFoundError(ConnectionId(str(target.stable_id)))
        owner = target.owner
        if not await redis.exists(f"mcpgw:worker_heartbeat:{owner.worker_id}"):
            await redis.eval(_OWNER_RELEASE_LUA, 1, self.owner_key(target.stable_id), owner.model_dump_json())
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
            forward_sig="0" * 64,
        )
        outbound = sign_envelope(envelope.model_dump(mode="json", exclude={"forward_sig"}))
        channel = self.response_channel(request_id)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        completed = False
        try:
            await redis.publish(f"mcpgw:pool_rp:{owner.worker_id}", orjson.dumps(outbound))
            with anyio.fail_after(max(0.0, deadline - self._utc_now())):
                async for entry in pubsub.listen():
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
            except Exception:  # pylint: disable=broad-exception-caught
                return

    async def listen(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        """Consume Redis entries while owner requests execute concurrently."""
        redis = self._redis
        if redis is None:
            task_status.started()
            return
        channel = f"mcpgw:pool_rp:{self._worker_id()}"
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        task_status.started()
        try:
            async with anyio.create_task_group() as tasks:
                async for entry in pubsub.listen():
                    raw = parse_pubsub_message(entry)
                    if raw is None:
                        continue
                    envelope = parse_inbound(raw, self.max_payload_bytes)
                    if isinstance(envelope, RelayCancelEnvelope):
                        operation = self._owner_scopes.get(envelope.request_id)
                        if operation is not None and (operation.stable_id, operation.connection_id, operation.origin_worker_id) == (
                            envelope.stable_id,
                            envelope.owner_connection_id,
                            envelope.origin_worker_id,
                        ):
                            operation.scope.cancel()
                    elif isinstance(envelope, RelayRequestEnvelope):
                        scope = anyio.CancelScope()
                        self._owner_scopes[envelope.request_id] = _OwnerOperation(envelope.stable_id, envelope.owner_connection_id, envelope.origin_worker_id, scope)
                        self._idle_event = anyio.Event()
                        tasks.start_soon(self._run_owner_request, envelope, scope)
        finally:
            await cleanup_pubsub(pubsub, channel)

    async def handle_message(self, raw: str | bytes) -> bool:
        """Verify and synchronously dispatch one request for focused use/tests."""
        envelope = parse_inbound(raw, self.max_payload_bytes)
        if not isinstance(envelope, RelayRequestEnvelope):
            return False
        return await self._execute_owner_request(envelope)

    async def _run_owner_request(self, envelope: RelayRequestEnvelope, scope: anyio.CancelScope) -> None:
        """Run one owner request within its tracked cancellation scope."""
        try:
            with scope:
                await self._execute_owner_request(envelope)
        finally:
            self._owner_scopes.pop(envelope.request_id, None)
            if not self._owner_scopes:
                self._idle_event.set()

    async def _execute_owner_request(self, envelope: RelayRequestEnvelope) -> bool:
        """Revalidate authority and dispatch one request to the local manager."""
        redis = self._redis
        if redis is None or envelope.deadline_utc <= self._utc_now():
            return False
        stable_id = StableGatewayId(envelope.stable_id)
        expected = RelayOwner(worker_id=self._worker_id(), connection_id=envelope.owner_connection_id)
        current = await self._read_owner(stable_id)
        local = self._manager.resolve_connection_id(stable_id)
        if current != expected or local is None or str(local) != envelope.owner_connection_id:
            return False
        remaining = envelope.deadline_utc - self._utc_now()
        try:
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
        except Exception:  # pylint: disable=broad-exception-caught
            await self._publish_outcome(envelope.request_id, error="internal_error")
            return False
        await self._publish_outcome(envelope.request_id, response=response)
        return True

    async def _publish_outcome(self, request_id: str, *, response: ResponseMessage | None = None, error: str | None = None) -> None:
        """Publish one signed response or code-only relay error."""
        redis = self._redis
        if redis is None:
            return
        raw = {"type": "rp_response", "request_id": request_id, "response": response.model_dump(mode="json") if response else None, "error": error}
        await redis.publish(self.response_channel(request_id), orjson.dumps(sign_envelope({key: value for key, value in raw.items() if value is not None})))

    async def _read_owner(self, stable_id: StableGatewayId) -> RelayOwner | None:
        """Read and strictly parse the current Redis owner generation."""
        if self._redis is None:
            return None
        raw = await self._redis.get(self.owner_key(stable_id))
        try:
            return RelayOwner.model_validate_json(raw) if raw is not None else None
        except ValidationError:
            return None

    @staticmethod
    def parse_pubsub_message(entry: Mapping[str, str | bytes | int | None] | str) -> str | bytes | None:
        """Return data only from real Redis message entries."""
        return parse_pubsub_message(entry)
