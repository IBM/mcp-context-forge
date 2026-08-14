# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_reverse_proxy_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Focused tests for the isolated Redis reverse-proxy relay.
"""
# T6 explicitly co-locates its deterministic Redis fake and focused relay matrix.
# pylint: disable=missing-function-docstring,use-implicit-booleaness-not-comparison

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import logging
import time
from typing import Final

import anyio
import orjson
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from mcpgateway.auth_context import FORWARD_SIG_FIELD, sign_redis_forward_envelope
from mcpgateway.services.reverse_proxy_protocol import DownstreamAuth, JsonRpcRequest, JsonRpcSuccessResponse, ResponseMessage
from mcpgateway.services.reverse_proxy_relay import ReverseProxyRelay
from mcpgateway.services import reverse_proxy_relay_io
from mcpgateway.services.reverse_proxy_sessions import ConnectionId, ConnectionNotFoundError, LocalSessionId, ReverseProxySessionManager, StableGatewayId


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

    async def eval(self, script: str, numkeys: int, *args: str | int) -> int:
        del numkeys
        self.eval_calls.append((script, args))
        key, expected = str(args[0]), str(args[1])
        current = self.store.get(key)
        if current is None or current.decode() != expected:
            return 0
        if len(args) == 2:
            self.store.pop(key)
            return 1
        if len(args) == 3:
            return 1
        raise AssertionError(f"unexpected CAS argument count: {len(args)}")

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


@dataclass
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


class _SecretFailureWebSocket:
    async def send_text(self, data: str) -> None:
        del data
        raise RuntimeError("Bearer oracle-secret-must-not-escape")

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
    relay = _relay(manager, redis, WORKER_A,)
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
