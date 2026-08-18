# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Focused tests for the isolated Redis reverse-proxy relay.
Audit marker: # noqa: SIZE_OK — deterministic fake and relay matrix stay co-located.
"""

# T6 explicitly co-locates its deterministic Redis fake and focused relay matrix.
# pylint: disable=missing-function-docstring,use-implicit-booleaness-not-comparison

# Future
from __future__ import annotations

# Standard
import builtins
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import logging
import time
from typing import Final
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import anyio
from anyio import TASK_STATUS_IGNORED
import orjson
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

# First-Party
from mcpgateway.auth_context import FORWARD_SIG_FIELD, sign_redis_forward_envelope
from mcpgateway.services import reverse_proxy_relay_io
from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, JsonRpcRequest, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_relay import RelayTarget, RelayUnavailableError, ReverseProxyRelay
from mcpgateway.services.reverse_proxy_relay_models import RelayOwner
from mcpgateway.services.reverse_proxy_sessions import ConnectionClosedError, ConnectionId, ConnectionNotFoundError, LocalSessionId, ReverseProxyEviction, ReverseProxySessionManager, StableGatewayId

OWNER_TTL: Final = 300
WORKER_A: Final = "worker-a"
WORKER_B: Final = "worker-b"
STABLE_ID: Final = StableGatewayId("stable-1")


class _FakePubSub:
    """One cancellation-safe fake Redis pub/sub subscription."""

    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._send, self._receive = anyio.create_memory_object_stream[bytes](10)
        self.channels: set[str] = set()
        self.closed = False

    async def __aenter__(self) -> _FakePubSub:
        return self

    async def __aexit__(self, *_exc: BaseException | None) -> bool:
        await self.close()
        return False

    async def subscribe(self, *channels: str) -> None:
        for channel in channels:
            self.channels.add(channel)
            self._redis.subscribers[channel].add(self)

    async def unsubscribe(self, *channels: str) -> None:
        for channel in channels:
            self.channels.discard(channel)
            self._redis.subscribers[channel].discard(self)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.unsubscribe(*tuple(self.channels))
        await self._send.aclose()
        await self._receive.aclose()

    async def aclose(self) -> None:
        await self.close()

    async def listen(self) -> AsyncIterator[dict[str, str | bytes | int | None]]:
        async with self._receive:
            async for payload in self._receive:
                yield {"type": "message", "data": payload}

    async def deliver(self, payload: bytes) -> None:
        if self.closed:
            return
        try:
            await self._send.send(payload)
        except anyio.ClosedResourceError:
            return


class _ControlFramePubSub(_FakePubSub):
    async def listen(self) -> AsyncIterator[dict[str, str | bytes | int | None]]:
        yield {"type": "subscribe", "data": 1}
        yield {"type": "message", "data": None}
        yield {"type": "message", "data": 7}
        async for entry in super().listen():
            yield entry


class _FakeRedis:
    """Deterministic Redis subset with CAS and pub/sub observability."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.sets: dict[str, set[bytes]] = defaultdict(set)
        self.subscribers: dict[str, set[_FakePubSub]] = defaultdict(set)
        self.published: list[tuple[str, bytes]] = []
        self.eval_calls: list[tuple[str, tuple[str | int, ...]]] = []
        self.publish_event = anyio.Event()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        del ex
        if nx and key in self.store:
            return None
        self.store[key] = value.encode()
        return True

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        del seconds
        self.store[key] = value.encode()
        return True

    async def exists(self, key: str) -> int:
        return int(key in self.store)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.store.pop(key, None) is not None)
        return removed

    async def sadd(self, key: str, *values: str) -> int:
        before = len(self.sets[key])
        self.sets[key].update(value.encode() for value in values)
        return len(self.sets[key]) - before

    async def srem(self, key: str, *values: str) -> int:
        removed = 0
        for value in values:
            encoded = value.encode()
            if encoded in self.sets[key]:
                self.sets[key].remove(encoded)
                removed += 1
        return removed

    async def smembers(self, key: str) -> builtins.set[bytes]:
        return builtins.set(self.sets[key])

    async def eval(self, script: str, numkeys: int, *args: str | int) -> int:
        self.eval_calls.append((script, args))
        keys = tuple(str(arg) for arg in args[:numkeys])
        argv = args[numkeys:]
        key, expected = keys[0], str(argv[0])
        current = self.store.get(key)
        if current is None or current.decode() != expected:
            return 0
        if numkeys == 2 and len(argv) == 3:
            owner_key, owner_value, _owner_ttl = keys[1], str(argv[1]), int(argv[2])
            self.store[owner_key] = owner_value.encode()
            return 1
        if len(argv) == 1:
            self.store.pop(key)
            return 1
        if len(argv) == 2:
            return 1
        raise AssertionError(f"unexpected CAS argument count: {len(argv)}")

    def pubsub(self) -> _FakePubSub:
        return _FakePubSub(self)

    async def publish(self, channel: str, message: bytes) -> int:
        self.published.append((channel, message))
        self.publish_event.set()
        subscribers = tuple(self.subscribers[channel])
        for subscriber in subscribers:
            await subscriber.deliver(message)
        return len(subscribers)

    def subscription_count(self) -> int:
        return sum(len(entries) for entries in self.subscribers.values())


class _ControlFrameRedis(_FakeRedis):
    def pubsub(self) -> _ControlFramePubSub:
        return _ControlFramePubSub(self)


class _TransientListenerPubSub(_FakePubSub):
    def __init__(self, redis: _FakeRedis, *, fail: bool, recovered: anyio.Event) -> None:
        super().__init__(redis)
        self._fail = fail
        self._recovered = recovered

    async def listen(self) -> AsyncIterator[dict[str, str | bytes | int | None]]:
        if self._fail:
            raise RedisConnectionError("transient listener failure")
        self._recovered.set()
        async for entry in super().listen():
            yield entry


class _TransientListenerRedis(_FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.listener_failed = False
        self.listener_recovered = anyio.Event()

    def pubsub(self) -> _TransientListenerPubSub:
        fail = not self.listener_failed
        self.listener_failed = True
        return _TransientListenerPubSub(self, fail=fail, recovered=self.listener_recovered)


class _SubscribeFailurePubSub(_FakePubSub):
    async def subscribe(self, *channels: str) -> None:
        await super().subscribe(*channels)
        raise RedisConnectionError("transient subscribe failure")


class _SubscribeFailureRedis(_FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.pubsubs: list[_SubscribeFailurePubSub] = []

    def pubsub(self) -> _SubscribeFailurePubSub:
        pubsub = _SubscribeFailurePubSub(self)
        self.pubsubs.append(pubsub)
        return pubsub


class _TransientFactoryRedis(_FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.pubsub_calls = 0
        self.listener_recovered = anyio.Event()

    def pubsub(self) -> _TransientListenerPubSub:
        self.pubsub_calls += 1
        if self.pubsub_calls == 2:
            raise RedisConnectionError("transient pubsub factory failure")
        return _TransientListenerPubSub(self, fail=self.pubsub_calls == 1, recovered=self.listener_recovered)


@dataclass(frozen=True, slots=True)
class _CleanupFailure:
    unsubscribe: bool = False
    aclose: bool = False


class _FailingCleanupPubSub(_FakePubSub):
    def __init__(self, redis: _FakeRedis, failure: _CleanupFailure) -> None:
        super().__init__(redis)
        self._failure = failure
        self.unsubscribe_attempts = 0
        self.aclose_attempts = 0

    async def unsubscribe(self, *channels: str) -> None:
        self.unsubscribe_attempts += 1
        await super().unsubscribe(*channels)
        if self._failure.unsubscribe:
            raise RedisConnectionError("unsubscribe failed")

    async def aclose(self) -> None:
        self.aclose_attempts += 1
        if self._failure.aclose:
            raise RedisConnectionError("aclose failed")
        if self.closed:
            return
        self.closed = True
        await _FakePubSub.unsubscribe(self, *tuple(self.channels))
        await self._send.aclose()
        await self._receive.aclose()


class _FailingCleanupRedis(_FakeRedis):
    def __init__(self, failure: _CleanupFailure) -> None:
        super().__init__()
        self._failure = failure
        self.pubsubs: list[_FailingCleanupPubSub] = []

    def pubsub(self) -> _FailingCleanupPubSub:
        pubsub = _FailingCleanupPubSub(self, self._failure)
        self.pubsubs.append(pubsub)
        return pubsub


class _FailingCancelRedis(_FakeRedis):
    """Redis fake whose request publish succeeds but cancel publish disconnects."""

    def __init__(self) -> None:
        super().__init__()
        self.cancel_attempts = 0

    async def publish(self, channel: str, message: bytes) -> int:
        if orjson.loads(message).get("type") == "rp_cancel":
            self.cancel_attempts += 1
            raise RedisConnectionError("cancel publish failed")
        return await super().publish(channel, message)


class _RespondingWebSocket:
    """Recording socket that immediately resolves typed manager requests."""

    def __init__(self, manager: ReverseProxySessionManager) -> None:
        self.manager = manager
        self.connection_id: ConnectionId | None = None
        self.frames: list[str] = []

    async def send_text(self, data: str) -> None:
        self.frames.append(data)
        frame = json.loads(data)
        connection_id = self.connection_id
        assert connection_id is not None
        response = ResponseMessage(
            type="response",
            payload=JsonRpcSuccessResponse(jsonrpc="2.0", id=frame["payload"]["id"], result={"worker": WORKER_A}),
        )
        assert self.manager.resolve_response(connection_id, response)

    async def close(self) -> None:
        return


class _BlockingWebSocket:
    def __init__(self) -> None:
        self.sent = anyio.Event()
        self.frames: list[str] = []

    async def send_text(self, data: str) -> None:
        self.frames.append(data)
        self.sent.set()
        await anyio.sleep_forever()

    async def close(self) -> None:
        return


class _OneWayWebSocket:
    """Recording socket that never synthesizes a downstream response."""

    def __init__(self) -> None:
        self.frames: list[str] = []
        self.closed = anyio.Event()

    async def send_text(self, data: str) -> None:
        self.frames.append(data)

    async def close(self) -> None:
        self.closed.set()


class _GatedOneWayWebSocket(_OneWayWebSocket):
    """One-way socket whose write completion is controlled by the test."""

    def __init__(self) -> None:
        super().__init__()
        self.sent = anyio.Event()
        self.release = anyio.Event()

    async def send_text(self, data: str) -> None:
        self.frames.append(data)
        self.sent.set()
        await self.release.wait()


class _SyntheticOwnerError(RuntimeError):
    """Synthetic owner failure used to verify secret-safe error boundaries."""


class _SecretFailureWebSocket:
    async def send_text(self, data: str) -> None:
        del data
        raise _SyntheticOwnerError("Bearer oracle-secret-must-not-escape")

    async def close(self) -> None:
        return


def _request(request_id: str = "request-1") -> JsonRpcRequest:
    return JsonRpcRequest(jsonrpc="2.0", id=request_id, method="tools/call", params={"name": "echo"})


async def _local_manager() -> tuple[ReverseProxySessionManager, _RespondingWebSocket, ConnectionId]:
    manager = ReverseProxySessionManager()
    websocket = _RespondingWebSocket(manager)
    session = await manager.connect(websocket, LocalSessionId("local-a"))
    websocket.connection_id = session.connection_id
    await manager.promote_stable_id(STABLE_ID, session.connection_id)
    return manager, websocket, session.connection_id


def _relay(manager: ReverseProxySessionManager, redis: _FakeRedis | None, worker_id: str) -> ReverseProxyRelay:
    return ReverseProxyRelay(manager, redis=redis, worker_id=lambda: worker_id, owner_ttl_seconds=OWNER_TTL)


def _signed_response(request_id: str, correlation_id: str) -> bytes:
    envelope = {
        "type": "rp_response",
        "request_id": correlation_id,
        "response": {"type": "response", "payload": {"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}}},
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    return orjson.dumps(envelope)


@pytest.mark.asyncio
async def test_owner_claim_is_single_writer_and_old_generation_cannot_release_replacement() -> None:
    redis = _FakeRedis()
    manager_a, _, connection_a = await _local_manager()
    manager_b, _, connection_b = await _local_manager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(manager_b, redis, WORKER_B)
    claims: list[bool] = []

    async def claim(relay: ReverseProxyRelay, connection_id: ConnectionId) -> None:
        claims.append(await relay.claim_owner(STABLE_ID, connection_id))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(claim, relay_a, connection_a)
        task_group.start_soon(claim, relay_b, connection_b)

    assert sorted(claims) == [False, True]
    redis.store[relay_a.owner_key(STABLE_ID)] = relay_b.owner_value(connection_b).encode()
    assert await relay_a.release_owner(STABLE_ID, connection_a) is False
    assert redis.store[relay_a.owner_key(STABLE_ID)] == relay_b.owner_value(connection_b).encode()


@pytest.mark.asyncio
async def test_registration_lease_is_single_writer_and_only_holder_can_promote_owner() -> None:
    redis = _FakeRedis()
    manager_a, _, connection_a = await _local_manager()
    manager_b, _, connection_b = await _local_manager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(manager_b, redis, WORKER_B)

    assert await relay_a.claim_registration(STABLE_ID, connection_a)
    assert not await relay_b.claim_registration(STABLE_ID, connection_b)
    assert await relay_a.heartbeat_registration(STABLE_ID, connection_a)
    assert not await relay_b.promote_registration(STABLE_ID, connection_b)
    assert await relay_a.promote_registration(STABLE_ID, connection_a)
    promote_args = redis.eval_calls[-1][1]
    assert promote_args == (
        relay_a.registration_key(STABLE_ID),
        relay_a.owner_key(STABLE_ID),
        relay_a.owner_value(connection_a),
        relay_a.owner_value(connection_a),
        OWNER_TTL,
    )

    assert relay_a.registration_key(STABLE_ID) in redis.store
    assert redis.store[relay_a.owner_key(STABLE_ID)] == relay_a.owner_value(connection_a).encode()
    assert not await relay_b.release_registration(STABLE_ID, connection_b)
    assert await relay_a.release_registration(STABLE_ID, connection_a)
    assert relay_a.registration_key(STABLE_ID) not in redis.store


@pytest.mark.asyncio
async def test_unreachable_write_guard_denies_while_replacement_registration_lease_is_held() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    relay_a = _relay(manager, redis, WORKER_A)
    relay_b = _relay(manager, redis, WORKER_B)
    replacement_connection = ConnectionId("replacement")
    eviction = ReverseProxyEviction(STABLE_ID, ConnectionId("evicted-generation"))

    assert await relay_b.claim_registration(STABLE_ID, replacement_connection)

    async with relay_a.unreachable_write_guard(eviction) as permitted:
        assert permitted is False

    # The denied guard never disturbs the replacement's in-flight lease.
    assert redis.store[relay_b.registration_key(STABLE_ID)] == relay_b.owner_value(replacement_connection).encode()


@pytest.mark.asyncio
async def test_unreachable_write_guard_denies_live_owner_and_releases_lease_on_exit() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    relay_a = _relay(manager, redis, WORKER_A)
    relay_b = _relay(manager, redis, WORKER_B)
    connection_a = ConnectionId("guard-writer")
    replacement_connection = ConnectionId("replacement")
    eviction = ReverseProxyEviction(STABLE_ID, ConnectionId("evicted-generation"))

    # A promoted owner survives its registration window, so the lease is free but ownership is live.
    assert await relay_b.claim_registration(STABLE_ID, replacement_connection)
    assert await relay_b.promote_registration(STABLE_ID, replacement_connection)
    assert await relay_b.release_registration(STABLE_ID, replacement_connection)

    async with relay_a.unreachable_write_guard(eviction) as permitted:
        assert permitted is False
        # The guard holds its own lease for the whole decision window.
        assert not await relay_a.claim_registration(STABLE_ID, connection_a)

    # The lease is released on exit, so later registrations are not blocked.
    assert await relay_a.claim_registration(STABLE_ID, connection_a)


@pytest.mark.asyncio
async def test_unreachable_write_guard_serializes_permitted_write_and_releases_on_exit() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    relay_a = _relay(manager, redis, WORKER_A)
    relay_b = _relay(manager, redis, WORKER_B)
    replacement_connection = ConnectionId("replacement")
    eviction = ReverseProxyEviction(STABLE_ID, ConnectionId("evicted-generation"))

    async with relay_a.unreachable_write_guard(eviction) as permitted:
        assert permitted is True
        # While the write holds the lease, a replacement registration cannot start...
        assert not await relay_b.claim_registration(STABLE_ID, replacement_connection)
        # ...and another generation cannot release the guard's fenced lease value.
        assert not await relay_b.release_registration(STABLE_ID, replacement_connection)

    # After the commit window the lease is gone and a registration proceeds.
    assert await relay_b.claim_registration(STABLE_ID, replacement_connection)


@pytest.mark.asyncio
async def test_unreachable_write_guard_release_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    class _ReleaseFailureRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: str | int) -> int:
            if numkeys == 1:
                raise RedisConnectionError("release lost")
            return await super().eval(script, numkeys, *args)

    redis = _ReleaseFailureRedis()
    manager = ReverseProxySessionManager()
    relay_a = _relay(manager, redis, WORKER_A)
    eviction = ReverseProxyEviction(STABLE_ID, ConnectionId("evicted-generation"))

    with caplog.at_level(logging.WARNING):
        async with relay_a.unreachable_write_guard(eviction) as permitted:
            assert permitted is True

    assert "unreachable-write lease release failed" in caplog.text


@pytest.mark.asyncio
async def test_unreachable_write_guard_without_redis_falls_back_to_owner_absence() -> None:
    manager = ReverseProxySessionManager()
    relay = _relay(manager, None, WORKER_A)
    eviction = ReverseProxyEviction(STABLE_ID, ConnectionId("evicted-generation"))

    async with relay.unreachable_write_guard(eviction) as permitted:
        assert permitted is True


@pytest.mark.asyncio
async def test_distributed_session_directory_round_trips_and_removes_typed_metadata() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    websocket = _OneWayWebSocket()
    session = await manager.connect(websocket, LocalSessionId("directory"), owner_email="owner@example.com")
    await manager.record_server_info(session.connection_id, {"name": "directory-server"})
    await manager.promote_stable_id(STABLE_ID, session.connection_id)
    relay = _relay(manager, redis, WORKER_A)
    assert await relay.claim_owner(STABLE_ID, session.connection_id)

    published = await relay.publish_session(STABLE_ID, session.connection_id)
    assert published.connection_id == str(session.connection_id)
    assert published.owner_email == "owner@example.com"
    assert published.server_info == {"name": "directory-server"}
    assert await relay.get_session_entry(session.connection_id) == published
    assert await relay.list_session_entries() == (published,)

    await relay.remove_session(session.connection_id)
    assert await relay.get_session_entry(session.connection_id) is None
    assert await relay.list_session_entries() == ()


@pytest.mark.asyncio
async def test_owner_heartbeat_refreshes_only_matching_generation_and_release_deletes_match() -> None:
    redis = _FakeRedis()
    manager, _, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)

    assert await relay.claim_owner(STABLE_ID, connection_id)
    assert await relay.heartbeat_owner(STABLE_ID, connection_id)
    assert not await relay.heartbeat_owner(STABLE_ID, ConnectionId("replacement"))
    assert await relay.heartbeat_worker()
    assert redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] == b"alive"
    assert await relay.release_owner(STABLE_ID, connection_id)
    assert relay.owner_key(STABLE_ID) not in redis.store


@pytest.mark.asyncio
async def test_local_connection_bypasses_redis_relay() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)

    resolved = relay.resolve_connection_id(STABLE_ID)
    assert resolved is not None
    response = await relay.send_request(resolved, _request(), timeout_seconds=1)

    assert resolved == connection_id
    assert isinstance(response.payload, JsonRpcSuccessResponse)
    assert response.payload.result == {"worker": WORKER_A}
    assert len(websocket.frames) == 1
    assert redis.published == []


@pytest.mark.asyncio
async def test_remote_signed_relay_correlates_one_response_without_reforwarding_or_secret_logs(caplog: pytest.LogCaptureFixture) -> None:
    redis = _FakeRedis()
    manager_a, websocket, connection_id = await _local_manager()
    manager_b = ReverseProxySessionManager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(manager_b, redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, connection_id)
    assert await relay_a.heartbeat_worker()
    caplog.set_level(logging.DEBUG)
    response: ResponseMessage | None = None

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        response = await relay_b.send_request_by_stable_id(
            STABLE_ID,
            _request(),
            timeout_seconds=1,
            auth=DownstreamAuth(headers={"Authorization": "Bearer relay-secret"}, auth_type="bearer"),
        )
        task_group.cancel_scope.cancel()

    assert response is not None
    assert isinstance(response.payload, JsonRpcSuccessResponse)
    assert response.payload.result == {"worker": WORKER_A}
    assert len(websocket.frames) == 1
    assert json.loads(websocket.frames[0])["authentication"] == {"Authorization": "Bearer relay-secret"}
    assert [channel for channel, _ in redis.published].count(f"mcpgw:pool_rp:{WORKER_A}") == 1
    assert redis.subscription_count() == 0
    assert "relay-secret" not in caplog.text


@pytest.mark.asyncio
async def test_wrong_and_duplicate_responses_are_ignored_until_matching_response() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    owner = relay.owner_value(ConnectionId("owner-generation"), worker_id=WORKER_A)
    redis.store[relay.owner_key(STABLE_ID)] = owner.encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"
    result: list[ResponseMessage] = []
    response_channel = ""
    matching = b""

    async def invoke() -> None:
        result.append(await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=1))

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(invoke)
        await redis.publish_event.wait()
        channel, raw_request = redis.published[-1]
        assert channel == f"mcpgw:pool_rp:{WORKER_A}"
        request_envelope = orjson.loads(raw_request)
        correlation_id = request_envelope["request_id"]
        response_channel = relay.response_channel(correlation_id)
        await redis.publish(response_channel, _signed_response("request-1", "wrong"))
        await redis.publish(response_channel, _signed_response("wrong-json-rpc-id", correlation_id))
        matching = _signed_response("request-1", correlation_id)
        await redis.publish(response_channel, matching)
        await redis.publish(response_channel, matching)

    assert isinstance(result[0].payload, JsonRpcSuccessResponse)
    assert result[0].payload.result == {"ok": True}
    assert redis.subscription_count() == 0
    assert response_channel
    assert matching
    assert await redis.publish(response_channel, matching) == 0


@pytest.mark.asyncio
async def test_dead_owner_is_compare_deleted_and_reclaim_race_fails_closed() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    owner_key = relay.owner_key(STABLE_ID)
    redis.store[owner_key] = relay.owner_value(ConnectionId("dead-generation"), worker_id="dead-worker").encode()

    with pytest.raises(ConnectionNotFoundError):
        await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=1)
    assert owner_key not in redis.store
    assert redis.eval_calls

    class _LostReclaimRedis(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: str | int) -> int:
            self.store[owner_key] = relay.owner_value(ConnectionId("new-generation"), worker_id=WORKER_A).encode()
            return await super().eval(script, numkeys, *args)

    raced_redis = _LostReclaimRedis()
    raced_relay = _relay(ReverseProxySessionManager(), raced_redis, WORKER_B)
    raced_redis.store[owner_key] = relay.owner_value(ConnectionId("dead-again"), worker_id="dead-worker").encode()
    with pytest.raises(ConnectionNotFoundError):
        await raced_relay.send_request_by_stable_id(STABLE_ID, _request("request-2"), timeout_seconds=1)
    assert raced_redis.store[owner_key].decode() == relay.owner_value(ConnectionId("new-generation"), worker_id=WORKER_A)


@pytest.mark.asyncio
async def test_timeout_cancellation_and_late_response_leave_no_subscriptions() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("owner-generation"), worker_id=WORKER_A).encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"

    with pytest.raises(TimeoutError):
        await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=0)
    assert redis.published == []
    assert redis.subscription_count() == 0

    cancelled = anyio.Event()

    async def cancel_me() -> None:
        try:
            await relay.send_request_by_stable_id(STABLE_ID, _request("cancelled"), timeout_seconds=60)
        finally:
            cancelled.set()

    redis.publish_event = anyio.Event()
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(cancel_me)
        await redis.publish_event.wait()
        task_group.cancel_scope.cancel()
    assert cancelled.is_set()
    assert redis.subscription_count() == 0


@pytest.mark.asyncio
async def test_listener_rejects_unsigned_forged_malformed_and_oversized_envelopes() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(
        manager,
        redis,
        WORKER_A,
    )
    base = {
        "type": "rp_request",
        "request_id": "correlation",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "response_channel": "mcpgw:rp_response:correlation",
        "payload": _request().model_dump(mode="json", exclude_none=True),
        "auth": None,
        "timeout_seconds": 1.0,
    }
    signed = dict(base)
    signed[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(signed)
    forged = dict(signed)
    forged["owner_connection_id"] = "forged"

    assert not await relay.handle_message(orjson.dumps(base))
    assert not await relay.handle_message(orjson.dumps(forged))
    assert not await relay.handle_message(b"not-json")
    assert not await relay.handle_message(b"[]")
    assert not await relay.handle_message(b"{" + b"x" * (relay.max_payload_bytes + 1))
    assert websocket.frames == []
    assert redis.published == []


@pytest.mark.asyncio
async def test_redis_absent_preserves_process_local_resolution_only() -> None:
    manager, _, connection_id = await _local_manager()
    relay = _relay(manager, None, WORKER_A)

    assert relay.resolve_connection_id(STABLE_ID) == connection_id
    response = await relay.send_request(connection_id, _request(), timeout_seconds=1)
    assert isinstance(response.payload, JsonRpcSuccessResponse)
    assert response.payload.result == {"worker": WORKER_A}
    assert relay.resolve_connection_id(StableGatewayId("remote-only")) is None
    assert not await relay.claim_owner(STABLE_ID, connection_id)


@pytest.mark.asyncio
async def test_listener_cancellation_cleans_subscription_and_can_restart() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_A)

    for _ in range(2):
        async with anyio.create_task_group() as task_group:
            await task_group.start(relay.listen)
            assert redis.subscription_count() == 1
            task_group.cancel_scope.cancel()
        assert redis.subscription_count() == 0


@pytest.mark.asyncio
async def test_pubsub_control_and_malformed_entries_are_ignored_for_response_and_listener() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)

    assert relay.parse_pubsub_message({"type": "subscribe", "data": 1}) is None
    assert relay.parse_pubsub_message({"type": "unsubscribe", "data": 0}) is None
    assert relay.parse_pubsub_message({"type": "message"}) is None
    assert relay.parse_pubsub_message({"type": "message", "data": 7}) is None
    assert relay.parse_pubsub_message("not-a-mapping") is None


@pytest.mark.asyncio
async def test_async_target_resolution_requires_a_current_redis_owner() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)

    assert relay.resolve_connection_id(STABLE_ID) is None
    assert await relay.resolve_target(STABLE_ID) is None
    assert redis.published == []


@pytest.mark.asyncio
async def test_timeout_at_or_below_zero_publishes_nothing() -> None:
    redis = _FakeRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("remote"), worker_id=WORKER_A).encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"

    with pytest.raises(TimeoutError):
        await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=0)
    assert redis.published == []


@pytest.mark.asyncio
async def test_owner_rejects_signed_request_after_exact_ownership_moves() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    request_id = "stale-owner-request"
    envelope = {
        "type": "rp_request",
        "request_id": request_id,
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "payload": _request().model_dump(mode="json", exclude_none=True),
        "auth": None,
        "deadline_utc": time.time() + 30,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("moved"), worker_id="worker-c").encode()

    assert not await relay.handle_message(orjson.dumps(envelope))
    assert websocket.frames == []
    assert redis.published == []


@pytest.mark.parametrize("nowait", [False, True])
@pytest.mark.asyncio
async def test_local_connection_id_dispatch_requires_current_redis_generation(nowait: bool) -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    redis.store[relay.owner_key(STABLE_ID)] = RelayOwner(worker_id=WORKER_B, connection_id="replacement").model_dump_json().encode()

    with pytest.raises(ConnectionNotFoundError):
        if nowait:
            await relay.send_request_by_connection_id_nowait(connection_id, _request("moved-owner"), timeout_seconds=1)
        else:
            await relay.send_request_by_connection_id(connection_id, _request("moved-owner"), timeout_seconds=1)

    assert websocket.frames == []


@pytest.mark.parametrize("nowait", [False, True])
@pytest.mark.asyncio
async def test_local_connection_id_dispatch_fails_closed_when_redis_is_unavailable(nowait: bool) -> None:
    redis = _FakeRedis()
    redis.get = AsyncMock(side_effect=RedisConnectionError("unavailable"))
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)

    with pytest.raises(RelayUnavailableError):
        if nowait:
            await relay.send_request_by_connection_id_nowait(connection_id, _request("redis-down"), timeout_seconds=1)
        else:
            await relay.send_request_by_connection_id(connection_id, _request("redis-down"), timeout_seconds=1)

    assert websocket.frames == []


@pytest.mark.asyncio
async def test_owner_consumes_signed_request_id_before_dispatch() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    assert await relay.claim_owner(STABLE_ID, connection_id)
    envelope = {
        "type": "rp_request",
        "request_id": "single-use-request",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "payload": _request("single-use-request").model_dump(mode="json", exclude_none=True),
        "auth": None,
        "deadline_utc": time.time() + 30,
        "expect_response": True,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    raw = orjson.dumps(envelope)

    assert await relay.handle_message(raw)
    assert not await relay.handle_message(raw)
    assert len(websocket.frames) == 1


@pytest.mark.asyncio
async def test_listener_consumes_duplicate_signed_request_before_owner_dispatch() -> None:
    # Given a listening owner and one valid request envelope delivered twice.
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    websocket = _GatedOneWayWebSocket()
    session = await manager.connect(websocket, LocalSessionId("listener-replay"))
    await manager.promote_stable_id(STABLE_ID, session.connection_id)
    relay = _relay(manager, redis, WORKER_A)
    assert await relay.claim_owner(STABLE_ID, session.connection_id)
    envelope = {
        "type": "rp_request",
        "request_id": "listener-single-use-request",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(session.connection_id),
        "origin_worker_id": WORKER_B,
        "payload": _request("listener-single-use-request").model_dump(mode="json", exclude_none=True),
        "auth": None,
        "deadline_utc": time.time() + 30,
        "expect_response": False,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    raw = orjson.dumps(envelope)

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay.listen)

        # When Redis redelivers the exact authenticated request while its first dispatch is active.
        assert await redis.publish(f"mcpgw:pool_rp:{WORKER_A}", raw) == 1
        assert await redis.publish(f"mcpgw:pool_rp:{WORKER_A}", raw) == 1
        with anyio.fail_after(1):
            await websocket.sent.wait()
        websocket.release.set()
        with anyio.fail_after(1):
            await relay.wait_for_idle()

        # Then only the consumed request reaches the downstream connection.
        assert len(websocket.frames) == 1
        assert relay.owner_request_count == 0
        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_owner_derives_response_channel_and_rejects_attacker_channel() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    assert await relay.claim_owner(STABLE_ID, connection_id)
    envelope = {
        "type": "rp_request",
        "request_id": "derived-channel",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "response_channel": "attacker:chosen:channel",
        "payload": _request().model_dump(mode="json", exclude_none=True),
        "auth": None,
        "deadline_utc": time.time() + 30,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)

    assert not await relay.handle_message(orjson.dumps(envelope))
    assert websocket.frames == []
    assert redis.published == []


@pytest.mark.parametrize(("unsubscribe_fails", "aclose_fails"), [(True, False), (False, True), (True, True)])
@pytest.mark.asyncio
async def test_completed_response_survives_redis_cleanup_connection_errors(unsubscribe_fails: bool, aclose_fails: bool) -> None:
    redis = _FailingCleanupRedis(_CleanupFailure(unsubscribe=unsubscribe_fails, aclose=aclose_fails))
    manager_a, _, connection_id = await _local_manager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, connection_id)
    assert await relay_a.heartbeat_worker()
    response: ResponseMessage | None = None
    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        response = await relay_b.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=1)
        task_group.cancel_scope.cancel()

    assert response is not None
    assert isinstance(response.payload, JsonRpcSuccessResponse)
    assert response.payload.result == {"worker": WORKER_A}
    assert all(pubsub.unsubscribe_attempts >= 1 for pubsub in redis.pubsubs)
    assert all(pubsub.aclose_attempts == 1 for pubsub in redis.pubsubs)


@pytest.mark.asyncio
async def test_cancel_publish_connection_error_does_not_mask_timeout() -> None:
    redis = _FailingCancelRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("owner-generation"), worker_id=WORKER_A).encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"

    with pytest.raises(TimeoutError):
        await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=0.01)

    assert redis.cancel_attempts == 1


@pytest.mark.asyncio
async def test_cancel_publish_connection_error_does_not_mask_anyio_cancellation() -> None:
    redis = _FailingCancelRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("owner-generation"), worker_id=WORKER_A).encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"
    cancellation_observed = anyio.Event()

    async def cancel_remote_request() -> None:
        try:
            await relay.send_request_by_stable_id(STABLE_ID, _request("cancel-publish"), timeout_seconds=60)
        except anyio.get_cancelled_exc_class():
            cancellation_observed.set()
            raise

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(cancel_remote_request)
        await redis.publish_event.wait()
        task_group.cancel_scope.cancel()

    assert cancellation_observed.is_set()
    assert redis.cancel_attempts == 1


def test_oversized_signed_response_is_rejected_before_json_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    relay = _relay(ReverseProxySessionManager(), _FakeRedis(), WORKER_B)
    envelope = {
        "type": "rp_response",
        "request_id": "oversized-response",
        "response": {"type": "response", "payload": {"jsonrpc": "2.0", "id": "request-1", "result": {"padding": "x" * relay.max_payload_bytes}}},
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)
    raw = orjson.dumps(envelope)
    assert len(raw) > relay.max_payload_bytes

    def fail_if_parsed(_raw: str | bytes) -> None:
        raise AssertionError("oversized response reached JSON parser")

    monkeypatch.setattr(reverse_proxy_relay_io.orjson, "loads", fail_if_parsed)
    assert reverse_proxy_relay_io.parse_response(raw, "oversized-response", "request-1", relay.max_payload_bytes) is None


@pytest.mark.asyncio
async def test_origin_cancellation_cancels_owner_manager_pending_call() -> None:
    redis = _FakeRedis()
    manager_a = ReverseProxySessionManager()
    websocket = _BlockingWebSocket()
    session = await manager_a.connect(websocket, LocalSessionId("blocking"))
    await manager_a.promote_stable_id(STABLE_ID, session.connection_id)
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, session.connection_id)
    assert await relay_a.heartbeat_worker()

    async with anyio.create_task_group() as listeners:
        await listeners.start(relay_a.listen)
        async with anyio.create_task_group() as callers:
            callers.start_soon(relay_b.send_request_by_stable_id, STABLE_ID, _request("cancel-me"), 60)
            await websocket.sent.wait()
            callers.cancel_scope.cancel()
        with anyio.fail_after(1):
            await relay_a.wait_for_idle()
        listeners.cancel_scope.cancel()

    assert manager_a.pending_count(session.connection_id) == 0
    assert relay_a.owner_request_count == 0


@pytest.mark.asyncio
async def test_listener_processes_second_request_while_first_owner_call_is_blocked() -> None:
    redis = _FakeRedis()
    manager_a = ReverseProxySessionManager()
    blocking = _BlockingWebSocket()
    blocked_session = await manager_a.connect(blocking, LocalSessionId("blocked"))
    responding = _RespondingWebSocket(manager_a)
    responsive_session = await manager_a.connect(responding, LocalSessionId("responsive"))
    responding.connection_id = responsive_session.connection_id
    await manager_a.promote_stable_id(StableGatewayId("blocked-stable"), blocked_session.connection_id)
    await manager_a.promote_stable_id(StableGatewayId("responsive-stable"), responsive_session.connection_id)
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(StableGatewayId("blocked-stable"), blocked_session.connection_id)
    assert await relay_a.claim_owner(StableGatewayId("responsive-stable"), responsive_session.connection_id)
    assert await relay_a.heartbeat_worker()

    response: ResponseMessage | None = None
    async with anyio.create_task_group() as listeners:
        await listeners.start(relay_a.listen)
        async with anyio.create_task_group() as blocked_call:
            blocked_call.start_soon(relay_b.send_request_by_stable_id, StableGatewayId("blocked-stable"), _request("blocked"), 60)
            await blocking.sent.wait()
            response = await relay_b.send_request_by_stable_id(StableGatewayId("responsive-stable"), _request("responsive"), 1)
            blocked_call.cancel_scope.cancel()
        listeners.cancel_scope.cancel()

    assert response is not None
    assert isinstance(response.payload, JsonRpcSuccessResponse)


@pytest.mark.asyncio
async def test_unexpected_owner_exception_returns_code_only_internal_error_without_secret(caplog: pytest.LogCaptureFixture) -> None:
    redis = _FakeRedis()
    manager_a = ReverseProxySessionManager()
    session = await manager_a.connect(_SecretFailureWebSocket(), LocalSessionId("secret-failure"))
    await manager_a.promote_stable_id(STABLE_ID, session.connection_id)
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, session.connection_id)
    assert await relay_a.heartbeat_worker()
    caplog.set_level(logging.DEBUG)

    caught: pytest.ExceptionInfo[ConnectionNotFoundError] | None = None
    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        with pytest.raises(ConnectionNotFoundError) as caught:
            await relay_b.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=1)
        task_group.cancel_scope.cancel()

    assert caught is not None
    assert "oracle-secret" not in str(caught.value)
    assert "oracle-secret" not in caplog.text


@pytest.mark.asyncio
async def test_nested_unknown_auth_and_response_fields_are_rejected() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    assert await relay.claim_owner(STABLE_ID, connection_id)
    envelope = {
        "type": "rp_request",
        "request_id": "nested-extra",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "payload": _request().model_dump(mode="json", exclude_none=True),
        "auth": {"headers": {}, "unknown": "must-fail"},
        "deadline_utc": time.time() + 30,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)

    assert not await relay.handle_message(orjson.dumps(envelope))
    assert websocket.frames == []


@pytest.mark.asyncio
async def test_realistic_control_frames_do_not_stop_listener_or_response_waiter() -> None:
    redis = _ControlFrameRedis()
    manager_a, _, connection_id = await _local_manager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, connection_id)
    assert await relay_a.heartbeat_worker()
    response: ResponseMessage | None = None

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        response = await relay_b.send_request_by_stable_id(STABLE_ID, _request(), 1)
        task_group.cancel_scope.cancel()

    assert response is not None
    assert isinstance(response.payload, JsonRpcSuccessResponse)


@pytest.mark.asyncio
async def test_expired_signed_request_is_rejected_before_owner_dispatch() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: WORKER_A, owner_ttl_seconds=OWNER_TTL, utc_now=lambda: 100.0)
    assert await relay.claim_owner(STABLE_ID, connection_id)
    envelope = {
        "type": "rp_request",
        "request_id": "expired",
        "stable_id": str(STABLE_ID),
        "owner_connection_id": str(connection_id),
        "origin_worker_id": WORKER_B,
        "payload": _request().model_dump(mode="json", exclude_none=True),
        "auth": None,
        "deadline_utc": 99.0,
    }
    envelope[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(envelope)

    assert not await relay.handle_message(orjson.dumps(envelope))
    assert websocket.frames == []


@pytest.mark.asyncio
async def test_forged_cancel_cannot_cancel_another_origin_operation() -> None:
    redis = _FakeRedis()
    manager_a = ReverseProxySessionManager()
    websocket = _BlockingWebSocket()
    session = await manager_a.connect(websocket, LocalSessionId("cancel-authority"))
    await manager_a.promote_stable_id(STABLE_ID, session.connection_id)
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, session.connection_id)
    assert await relay_a.heartbeat_worker()

    async with anyio.create_task_group() as listeners:
        await listeners.start(relay_a.listen)
        async with anyio.create_task_group() as callers:
            callers.start_soon(relay_b.send_request_by_stable_id, STABLE_ID, _request("cancel-auth"), 60)
            await websocket.sent.wait()
            request = orjson.loads(next(payload for channel, payload in redis.published if channel == f"mcpgw:pool_rp:{WORKER_A}"))
            forged = {
                "type": "rp_cancel",
                "request_id": request["request_id"],
                "stable_id": str(STABLE_ID),
                "owner_connection_id": str(session.connection_id),
                "origin_worker_id": "attacker-worker",
            }
            forged[FORWARD_SIG_FIELD] = sign_redis_forward_envelope(forged)
            await redis.publish(f"mcpgw:pool_rp:{WORKER_A}", orjson.dumps(forged))
            assert relay_a.owner_request_count == 1
            callers.cancel_scope.cancel()
        listeners.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_decode_responses_string_payload_and_dynamic_worker_identity() -> None:
    redis = _FakeRedis()
    worker = [WORKER_A]
    relay = ReverseProxyRelay(ReverseProxySessionManager(), redis=redis, worker_id=lambda: worker[0], owner_ttl_seconds=OWNER_TTL)
    assert relay.parse_pubsub_message({"type": "message", "data": "{}"}) == "{}"
    first = relay.owner_value(ConnectionId("generation"))
    worker[0] = "worker-after-fork"
    second = relay.owner_value(ConnectionId("generation"))
    assert WORKER_A in first
    assert "worker-after-fork" in second


@pytest.mark.asyncio
async def test_runtime_factory_flag_off_uses_local_manager_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime

    manager = ReverseProxySessionManager()
    get_redis = AsyncMock(side_effect=AssertionError("disabled relay requested Redis"))
    monkeypatch.setattr(reverse_proxy_relay_runtime.settings, "mcpgateway_reverse_proxy_distributed_enabled", False)
    monkeypatch.setattr(reverse_proxy_relay_runtime, "get_reverse_proxy_session_manager", AsyncMock(return_value=manager))
    monkeypatch.setattr(reverse_proxy_relay_runtime, "get_redis_client", get_redis)
    reverse_proxy_relay_runtime.reset_reverse_proxy_relay()

    relay = await reverse_proxy_relay_runtime.get_reverse_proxy_relay()

    assert relay.resolve_connection_id(STABLE_ID) is None
    get_redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_factory_flag_on_fails_when_canonical_redis_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime

    monkeypatch.setattr(reverse_proxy_relay_runtime.settings, "mcpgateway_reverse_proxy_distributed_enabled", True)
    monkeypatch.setattr(reverse_proxy_relay_runtime, "get_redis_client", AsyncMock(return_value=None))
    reverse_proxy_relay_runtime.reset_reverse_proxy_relay()

    with pytest.raises(RelayUnavailableError, match="reverse-proxy relay unavailable"):
        await reverse_proxy_relay_runtime.get_reverse_proxy_relay()


def test_runtime_worker_identity_rebinds_after_process_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime

    pids = iter((101, 101, 202))
    monkeypatch.setattr(reverse_proxy_relay_runtime.os, "getpid", lambda: next(pids))
    reverse_proxy_relay_runtime.reset_reverse_proxy_relay()

    first = reverse_proxy_relay_runtime.current_reverse_proxy_worker_id()
    same_process = reverse_proxy_relay_runtime.current_reverse_proxy_worker_id()
    after_fork = reverse_proxy_relay_runtime.current_reverse_proxy_worker_id()

    assert first == same_process
    assert first != after_fork


@pytest.mark.parametrize("method", ["tools/call", "resources/read", "prompts/get"])
@pytest.mark.asyncio
async def test_two_worker_fake_redis_relays_all_dispatch_methods(method: str) -> None:
    redis = _FakeRedis()
    manager_a, websocket, connection_id = await _local_manager()
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, connection_id)
    assert await relay_a.heartbeat_worker()
    request = JsonRpcRequest(jsonrpc="2.0", id=f"request-{method.replace('/', '-')}", method=method, params={})
    response: ResponseMessage | None = None

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        response = await relay_b.send_request_by_stable_id(STABLE_ID, request, timeout_seconds=1)
        task_group.cancel_scope.cancel()

    assert response is not None
    assert isinstance(response.payload, JsonRpcSuccessResponse)
    assert json.loads(websocket.frames[0])["payload"]["method"] == method


@pytest.mark.asyncio
async def test_two_worker_session_directory_supports_one_way_send_and_disconnect() -> None:
    redis = _FakeRedis()
    manager_a = ReverseProxySessionManager()
    websocket = _GatedOneWayWebSocket()
    session = await manager_a.connect(websocket, LocalSessionId("one-way"), owner_email="owner@example.com")
    await manager_a.record_server_info(session.connection_id, {"name": "remote-server"})
    await manager_a.promote_stable_id(STABLE_ID, session.connection_id)
    relay_a = _relay(manager_a, redis, WORKER_A)
    relay_b = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    assert await relay_a.claim_owner(STABLE_ID, session.connection_id)
    assert await relay_a.heartbeat_worker()
    published = await relay_a.publish_session(STABLE_ID, session.connection_id)

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay_a.listen)
        listed = await relay_b.list_session_entries()
        resolved = await relay_b.get_session_entry(session.connection_id)
        delivery_completed = anyio.Event()

        async def deliver() -> None:
            await relay_b.send_request_by_connection_id_nowait(session.connection_id, _request("http-1"), timeout_seconds=1)
            delivery_completed.set()

        task_group.start_soon(deliver)
        with anyio.fail_after(1):
            await websocket.sent.wait()
        assert not delivery_completed.is_set()
        websocket.release.set()
        with anyio.fail_after(1):
            await delivery_completed.wait()
        assert await relay_b.disconnect_session(session.connection_id)
        with anyio.fail_after(1):
            await websocket.closed.wait()
        assert resolved == published
        assert listed == (published,)
        assert json.loads(websocket.frames[0])["payload"]["id"] == "http-1"
        assert manager_a.pending_count(session.connection_id) == 0
        assert manager_a.get_session(session.connection_id) is None
        assert await relay_b.get_session_entry(session.connection_id) is None
        assert await relay_b._read_owner(STABLE_ID) is None
        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_listener_reconnects_after_post_start_redis_failure() -> None:
    redis = _TransientListenerRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_A)

    async with anyio.create_task_group() as task_group:
        await task_group.start(relay.listen)
        with anyio.fail_after(2):
            await redis.listener_recovered.wait()
        task_group.cancel_scope.cancel()

    assert redis.listener_failed is True


@pytest.mark.asyncio
async def test_remote_subscribe_failure_closes_partially_subscribed_pubsub() -> None:
    # Given a remote owner and a pub/sub object whose subscribe call fails after registration.
    redis = _SubscribeFailureRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_B)
    owner = RelayOwner(worker_id=WORKER_A, connection_id="owner-generation")
    redis.store[relay.owner_key(STABLE_ID)] = owner.model_dump_json().encode()
    redis.store[f"mcpgw:worker_heartbeat:{WORKER_A}"] = b"alive"

    # When a remote request attempts to subscribe for its response.
    with pytest.raises(RelayUnavailableError):
        await relay.send_request_by_stable_id(STABLE_ID, _request(), timeout_seconds=1)

    # Then the partially subscribed pub/sub resource is fully closed.
    assert len(redis.pubsubs) == 1
    assert redis.pubsubs[0].closed is True
    assert redis.subscription_count() == 0


@pytest.mark.asyncio
async def test_listener_retries_post_start_pubsub_factory_failure() -> None:
    # Given a listener that first loses its stream and then cannot create one replacement.
    redis = _TransientFactoryRedis()
    relay = _relay(ReverseProxySessionManager(), redis, WORKER_A)

    # When the supervised listener reconnects.
    async with anyio.create_task_group() as task_group:
        await task_group.start(relay.listen)
        with anyio.fail_after(3):
            await redis.listener_recovered.wait()
        task_group.cancel_scope.cancel()

    # Then acquisition was retried through the transient factory failure.
    assert redis.pubsub_calls == 3


@pytest.mark.asyncio
async def test_claim_owner_replaces_stale_same_worker_generation() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    relay = _relay(manager, redis, WORKER_A)
    redis.store[relay.owner_key(STABLE_ID)] = relay.owner_value(ConnectionId("stale-generation")).encode()

    claimed = await relay.claim_owner(STABLE_ID, ConnectionId("replacement-generation"))

    assert claimed is True
    assert await relay._read_owner(STABLE_ID) == RelayOwner(worker_id=WORKER_A, connection_id="replacement-generation")


@pytest.mark.asyncio
async def test_local_mapping_is_retired_when_redis_owner_generation_moves() -> None:
    redis = _FakeRedis()
    manager, websocket, connection_id = await _local_manager()
    relay = _relay(manager, redis, WORKER_A)
    replacement = RelayOwner(worker_id=WORKER_B, connection_id="replacement-generation")
    redis.store[relay.owner_key(STABLE_ID)] = replacement.model_dump_json().encode()

    target = await relay.resolve_target(STABLE_ID)

    assert isinstance(target, RelayTarget)
    assert target.owner == replacement
    assert manager.resolve_connection_id(STABLE_ID) is None
    assert manager.get_session(connection_id) is None
    assert websocket.frames == []


@pytest.mark.asyncio
async def test_redis_operation_failure_raises_code_only_relay_unavailable() -> None:
    secret = "redis://user:synthetic-secret@cache.invalid/0"  # pragma: allowlist secret

    class _UnavailableRedis(_FakeRedis):
        async def get(self, key: str) -> bytes | None:
            del key
            raise RedisConnectionError(secret)

    relay = _relay(ReverseProxySessionManager(), _UnavailableRedis(), WORKER_A)

    with pytest.raises(RuntimeError) as caught:
        await relay.resolve_target(STABLE_ID)

    assert type(caught.value).__name__ == "RelayUnavailableError"
    assert str(caught.value) == "reverse-proxy relay unavailable"
    assert "synthetic-secret" not in repr(caught.value)


@pytest.mark.asyncio
async def test_runtime_lifespan_propagates_listener_subscribe_failure_without_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime

    relay = _relay(ReverseProxySessionManager(), _FakeRedis(), WORKER_A)
    relay.listen = AsyncMock(side_effect=RelayUnavailableError())
    monkeypatch.setattr(reverse_proxy_relay_runtime, "get_reverse_proxy_relay", AsyncMock(return_value=relay))

    with anyio.fail_after(1):
        with pytest.raises(BaseExceptionGroup) as caught:
            async with reverse_proxy_relay_runtime.reverse_proxy_relay_lifespan():
                pytest.fail("listener startup unexpectedly succeeded")

    assert len(caught.value.exceptions) == 1
    assert str(caught.value.exceptions[0]) == "reverse-proxy relay unavailable"


@pytest.mark.asyncio
async def test_release_outage_is_best_effort_for_every_eviction() -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime
    from mcpgateway.services.reverse_proxy_sessions import ReverseProxyEviction

    relay = MagicMock(release_owner=AsyncMock(side_effect=RedisConnectionError("redis://user:synthetic-secret@cache.invalid/0")))  # pragma: allowlist secret
    evictions = (
        ReverseProxyEviction(STABLE_ID, ConnectionId("generation-a")),
        ReverseProxyEviction(StableGatewayId("stable-2"), ConnectionId("generation-b")),
    )

    await reverse_proxy_relay_runtime.release_reverse_proxy_owners_best_effort(relay, evictions)

    assert relay.release_owner.await_count == 2


@pytest.mark.asyncio
async def test_runtime_lifespan_retries_heartbeat_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # First-Party
    from mcpgateway.services import reverse_proxy_relay_runtime

    relay = _relay(ReverseProxySessionManager(), _FakeRedis(), WORKER_A)

    async def listen(*, task_status=TASK_STATUS_IGNORED) -> None:
        task_status.started()
        await anyio.sleep_forever()

    heartbeat_calls = 0
    heartbeat_recovered = anyio.Event()

    async def heartbeat() -> None:
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        if heartbeat_calls == 2:
            raise RelayUnavailableError
        if heartbeat_calls == 3:
            heartbeat_recovered.set()

    monkeypatch.setattr(relay, "listen", listen)
    monkeypatch.setattr(relay, "heartbeat", heartbeat)
    monkeypatch.setattr(reverse_proxy_relay_runtime, "_OWNER_TTL_SECONDS", 0.03)
    monkeypatch.setattr(reverse_proxy_relay_runtime, "get_reverse_proxy_relay", AsyncMock(return_value=relay))

    with anyio.fail_after(2):
        async with reverse_proxy_relay_runtime.reverse_proxy_relay_lifespan():
            await heartbeat_recovered.wait()

    assert heartbeat_calls >= 3
    assert reverse_proxy_relay_runtime._default_relay is None


@pytest.mark.asyncio
async def test_owner_heartbeat_loss_retires_generation_fails_pending_and_reports_eviction() -> None:
    redis = _FakeRedis()
    manager = ReverseProxySessionManager()
    websocket = _BlockingWebSocket()
    session = await manager.connect(websocket, LocalSessionId("heartbeat-loss"))
    await manager.promote_stable_id(STABLE_ID, session.connection_id)
    ownership_lost = AsyncMock()
    relay = ReverseProxyRelay(manager, redis=redis, worker_id=lambda: WORKER_A, owner_ttl_seconds=OWNER_TTL, ownership_lost=ownership_lost)
    caller_failed = anyio.Event()

    async def invoke() -> None:
        try:
            await manager.send_request(session.connection_id, _request("heartbeat-loss"), 60)
        except ConnectionClosedError:
            caller_failed.set()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(invoke)
        await websocket.sent.wait()
        await relay.heartbeat()
        await caller_failed.wait()
        task_group.cancel_scope.cancel()

    assert manager.resolve_connection_id(STABLE_ID) is None
    assert manager.get_session(session.connection_id) is None
    ownership_lost.assert_awaited_once()
    lost_call = ownership_lost.await_args
    assert lost_call is not None
    assert lost_call.args[0] == (ReverseProxyEviction(STABLE_ID, session.connection_id),)
