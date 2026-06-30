# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_leader_election.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for the primary-worker elector (filelock + redis backends).
"""

# Standard
import asyncio

# Third-Party
import fakeredis
import fakeredis.aioredis as fakeredis_async

# First-Party
from mcpgateway.services.leader_election import PrimaryWorkerElector


def _client(server):
    """Build an async fakeredis client bound to a shared server."""
    return fakeredis_async.FakeRedis(server=server, decode_responses=True)


def _redis_elector(server, **kw):
    """Build a redis-backed elector sharing ``server``, heartbeat off by default."""
    kw.setdefault("lease_ttl", 5)
    kw.setdefault("heartbeat_interval", 10)
    return PrimaryWorkerElector(backend="redis", redis_key="k", redis_client=_client(server), **kw)


# --- filelock backend --------------------------------------------------------


async def test_filelock_backend_one_primary(tmp_path):
    """With the same lock file, exactly one elector is primary."""
    path = str(tmp_path / "x.lock")
    a = PrimaryWorkerElector(backend="filelock", lock_path=path)
    b = PrimaryWorkerElector(backend="filelock", lock_path=path)
    await a.start()
    await b.start()
    assert a.is_primary is True
    assert b.is_primary is False
    await a.stop()
    await b.stop()


# --- redis backend -----------------------------------------------------------


async def test_redis_single_primary_across_instances():
    """N electors sharing one Redis elect exactly one primary."""
    server = fakeredis.FakeServer()
    electors = [_redis_elector(server) for _ in range(3)]
    for e in electors:
        await e.start()
    try:
        assert sum(e.is_primary for e in electors) == 1
    finally:
        for e in electors:
            await e.stop()


async def test_redis_release_on_stop_lets_another_acquire():
    """Stopping the primary frees the lease for a new elector."""
    server = fakeredis.FakeServer()
    a = _redis_elector(server, lease_ttl=30)
    await a.start()
    assert a.is_primary is True
    await a.stop()  # if-owner release
    b = _redis_elector(server, lease_ttl=30)
    await b.start()
    assert b.is_primary is True
    await b.stop()


async def test_redis_renew_keeps_leadership():
    """The heartbeat renews the lease, so the primary stays primary."""
    server = fakeredis.FakeServer()
    e = _redis_elector(server, lease_ttl=1, heartbeat_interval=0.2)
    await e.start()
    assert e.is_primary is True
    await asyncio.sleep(0.5)  # past the TTL window had it not renewed
    assert e.is_primary is True
    await e.stop()


async def test_redis_follower_takes_over_after_primary_stops():
    """A follower's loop re-acquires once the primary releases."""
    server = fakeredis.FakeServer()
    a = _redis_elector(server, heartbeat_interval=0.2)
    b = _redis_elector(server, heartbeat_interval=0.2)
    await a.start()
    await b.start()
    assert a.is_primary is True
    assert b.is_primary is False
    await a.stop()  # releases the lease
    await asyncio.sleep(0.5)  # b's follower loop picks it up
    assert b.is_primary is True
    await b.stop()


# --- redis-unavailable policies ----------------------------------------------


class _BoomRedis:
    """Async Redis stand-in that always errors."""

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def aclose(self):
        pass


async def test_redis_unavailable_fail_closed():
    """fail_closed: Redis errors leave the elector non-primary, no crash."""
    e = PrimaryWorkerElector(backend="redis", unavailable_policy="fail_closed", heartbeat_interval=10, redis_client=_BoomRedis())
    await e.start()
    assert e.is_primary is False
    await e.stop()


async def test_redis_unavailable_filelock_fallback(tmp_path):
    """filelock_fallback: Redis errors fall back to a per-host file lock."""
    e = PrimaryWorkerElector(
        backend="redis",
        unavailable_policy="filelock_fallback",
        lock_path=str(tmp_path / "x.lock"),
        heartbeat_interval=10,
        redis_client=_BoomRedis(),
    )
    await e.start()
    assert e.is_primary is True  # acquired the fallback file lock
    await e.stop()
