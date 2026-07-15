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
from filelock import FileLock

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


# --- properties --------------------------------------------------------------


async def test_started_and_instance_id_properties():
    """``started`` tracks the lifecycle and ``instance_id`` is a stable non-empty id."""
    server = fakeredis.FakeServer()
    e = _redis_elector(server, lease_ttl=30)
    assert e.started is False
    ident = e.instance_id
    assert isinstance(ident, str) and ident
    await e.start()
    assert e.started is True
    assert e.instance_id == ident  # stable across the lifecycle
    await e.stop()
    assert e.started is False


# --- redis maintenance loop --------------------------------------------------


async def test_redis_lost_lease_demotes_primary():
    """The heartbeat's compare-and-renew returns 0 once the lease is stolen, demoting us."""
    server = fakeredis.FakeServer()
    e = _redis_elector(server, lease_ttl=30, heartbeat_interval=0.1)
    await e.start()
    assert e.is_primary is True
    # Overwrite the lease with a different owner so compare-and-renew fails.
    await _client(server).set("k", "someone-else")
    await asyncio.sleep(0.3)  # a heartbeat runs the renew, sees the mismatch
    assert e.is_primary is False
    await e.stop()


class _RenewBoomRedis:
    """Async Redis stand-in whose initial acquire works but every ``eval`` errors."""

    def __init__(self):
        """Start with no lease held."""
        self._store = {}

    async def set(self, key, value, nx=False, ex=None):
        """SET NX EX: acquire only if the key is unset.

        Args:
            key: Lease key.
            value: Instance id to store.
            nx: Only set when absent.
            ex: TTL in seconds (ignored by this stand-in).

        Returns:
            True on acquire, else None.
        """
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True

    async def eval(self, *args, **kwargs):
        """Always fail, simulating Redis dropping mid-heartbeat.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            ConnectionError: Always.
        """
        raise ConnectionError("redis down mid-heartbeat")

    async def aclose(self):
        """No-op close."""


async def test_redis_maintenance_error_fail_closed():
    """fail_closed: a Redis error during the heartbeat demotes us to non-primary."""
    e = PrimaryWorkerElector(
        backend="redis",
        redis_key="k",
        unavailable_policy="fail_closed",
        lease_ttl=30,
        heartbeat_interval=0.1,
        redis_client=_RenewBoomRedis(),
    )
    await e.start()
    assert e.is_primary is True  # initial acquire succeeded
    await asyncio.sleep(0.3)  # heartbeat calls eval -> raises -> fail closed
    assert e.is_primary is False
    await e.stop()


async def test_redis_maintenance_error_filelock_fallback_demotes_when_lock_held(tmp_path):
    """Regression: filelock_fallback must NOT keep a stale primary when Redis dies mid-heartbeat.

    A Redis-primary loses Redis; the per-host file lock is already held by another
    process. Fallback cannot acquire it, so the elector must go non-primary --
    otherwise its lease expires unrenewed, a follower takes it, and two processes
    both report primary (the split-brain this backend exists to prevent).
    """
    path = str(tmp_path / "x.lock")
    holder = FileLock(path)
    holder.acquire(timeout=0)  # pre-hold the fallback lock from "another process"
    try:
        e = PrimaryWorkerElector(
            backend="redis",
            redis_key="k",
            unavailable_policy="filelock_fallback",
            lock_path=path,
            lease_ttl=30,
            heartbeat_interval=0.1,
            redis_client=_RenewBoomRedis(),
        )
        await e.start()
        assert e.is_primary is True  # initial Redis acquire succeeded
        await asyncio.sleep(0.3)  # heartbeat eval raises -> fallback can't get lock
        assert e.is_primary is False  # demoted, not left stale-primary
        await e.stop()
    finally:
        holder.release()


async def test_redis_maintenance_error_filelock_fallback_reelects_when_lock_free(tmp_path):
    """filelock_fallback: when Redis dies mid-heartbeat and the file lock is free, re-elect per host."""
    e = PrimaryWorkerElector(
        backend="redis",
        redis_key="k",
        unavailable_policy="filelock_fallback",
        lock_path=str(tmp_path / "x.lock"),
        lease_ttl=30,
        heartbeat_interval=0.1,
        redis_client=_RenewBoomRedis(),
    )
    await e.start()
    assert e.is_primary is True  # initial Redis acquire succeeded
    await asyncio.sleep(0.3)  # heartbeat eval raises -> fallback grabs the free lock
    assert e.is_primary is True  # still primary, now via the per-host file lock
    await e.stop()


# --- own redis client (built from url, closed on stop) -----------------------


async def test_redis_builds_own_client_and_closes_on_stop(monkeypatch):
    """When no client is injected, the elector builds one via ``from_url`` and closes it."""
    # Third-Party
    import redis.asyncio as aioredis  # pylint: disable=import-outside-toplevel

    server = fakeredis.FakeServer()
    closed = {"count": 0}

    class _Tracked(fakeredis_async.FakeRedis):
        async def aclose(self):
            closed["count"] += 1
            await super().aclose()

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: _Tracked(server=server, decode_responses=True))
    e = PrimaryWorkerElector(backend="redis", redis_key="k", lease_ttl=30, heartbeat_interval=10)  # no redis_client -> owns it
    await e.start()
    assert e.is_primary is True
    await e.stop()  # owns_redis -> aclose()
    assert closed["count"] == 1


# --- module singleton --------------------------------------------------------


async def test_singleton_start_get_stop():
    """The module-level helpers create, expose, reuse, and clear one elector."""
    # First-Party
    from mcpgateway.services.leader_election import (  # pylint: disable=import-outside-toplevel
        get_primary_worker_elector,
        start_primary_worker_elector,
        stop_primary_worker_elector,
    )

    assert get_primary_worker_elector() is None
    try:
        elector = await start_primary_worker_elector()
        assert elector.started is True
        assert get_primary_worker_elector() is elector
        # A second start reuses the same singleton rather than replacing it.
        assert await start_primary_worker_elector() is elector
    finally:
        await stop_primary_worker_elector()
    assert get_primary_worker_elector() is None


# --- shutdown robustness -----------------------------------------------------


async def test_stop_swallows_maintenance_task_error(tmp_path):
    """stop() is best-effort: a maintenance-task error (not CancelledError) must not propagate."""
    e = PrimaryWorkerElector(backend="filelock", lock_path=str(tmp_path / "x.lock"))

    async def _boom():
        raise RuntimeError("maintenance blew up")

    e._task = asyncio.create_task(_boom())  # pylint: disable=protected-access
    await asyncio.sleep(0.05)  # let the task run and fail before stop() awaits it
    await e.stop()  # must not raise
    assert e.started is False
