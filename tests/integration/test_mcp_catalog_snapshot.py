# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_mcp_catalog_snapshot.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify atomic catalog admission and snapshot lifetime with an isolated Redis instance.
"""

# Standard
import asyncio
import os
import uuid

# Third-Party
import orjson
import pytest
import pytest_asyncio
from redis.asyncio import Redis

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils import mcp_catalog_snapshot as snapshots
from mcpgateway.validation.jsonrpc import JSONRPCError


@pytest_asyncio.fixture
async def snapshot_store(monkeypatch):
    """Connect to an explicitly configured Redis and isolate every test namespace."""
    url = os.getenv("MCP_CATALOG_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set MCP_CATALOG_TEST_REDIS_URL to an isolated Redis instance")
    monkeypatch.setattr(settings, "cache_prefix", f"catalog-test-{uuid.uuid4().hex}:")
    monkeypatch.setattr(settings, "mcp_proxy_list_max_snapshot_bytes", 4096)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", 8192)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_collectors", 2)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_snapshots", 4)
    client = Redis.from_url(url)
    sentinel = f"{settings.cache_prefix}unrelated-session"
    await client.set(sentinel, "preserved")
    try:
        yield client
    finally:
        assert await client.get(sentinel) == b"preserved"
        await client.delete(snapshots.snapshot_key(), sentinel)
        await client.aclose()


async def _admit(client, reservation, *, ttl=30):
    """Request admission without process-local state to simulate independent workers.

    Args:
        client: Shared Redis connection.
        reservation: Unique reservation identifier.
        ttl: Reservation lifetime in seconds.

    Returns:
        Atomic admission result.
    """
    return await client.eval(
        snapshots._ADMIT,
        1,
        snapshots.snapshot_key(),
        reservation,
        settings.mcp_proxy_list_max_collectors,
        settings.mcp_proxy_list_max_snapshots,
        ttl,
    )


@pytest.mark.asyncio
async def test_concurrent_workers_obey_admission_limits(snapshot_store):
    """Admit only two collectors under concurrent cross-worker requests."""
    admitted = await asyncio.gather(*(_admit(snapshot_store, f"worker-{index}") for index in range(20)))
    assert sum(admitted) == 2
    state = orjson.loads(await snapshot_store.hget(snapshots.snapshot_key(), "leases"))
    assert len(state) == 2
    assert sum(lease[1] for lease in state.values()) == 0
    assert await snapshot_store.dbsize() >= 2


@pytest.mark.asyncio
async def test_retained_bytes_and_snapshot_count_reject_new_collection(snapshot_store, monkeypatch):
    """Reject new collection when retained snapshots consume admission capacity."""
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", 1600)
    async with snapshots.reserve_collection(snapshot_store) as snapshot:
        await snapshots.publish_snapshot(snapshot_store, snapshot, "scope", [b"[]", b"[]"])
    with pytest.raises(JSONRPCError, match="reservation"):
        async with snapshots.reserve_collection(snapshot_store) as another:
            await snapshots.publish_snapshot(snapshot_store, another, "scope", [b"[]", b"[]"])
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", 8192)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_snapshots", 1)
    with pytest.raises(JSONRPCError, match="capacity"):
        async with snapshots.reserve_collection(snapshot_store):
            pytest.fail("Snapshot count must reject collection")
    manifest, page = await snapshots.read_snapshot(snapshot_store, snapshot, 1)
    assert orjson.loads(manifest) == {"scope": "scope", "pages": 2}
    assert page == b"[]"


@pytest.mark.asyncio
async def test_expired_worker_reservation_is_reclaimed(snapshot_store):
    """Recover reservations after worker failure without deleting unrelated Redis keys."""
    assert await _admit(snapshot_store, "crashed-worker", ttl=1) == 1
    await asyncio.sleep(1.1)
    admitted = await asyncio.gather(*(_admit(snapshot_store, f"replacement-{index}") for index in range(3)))
    assert sum(admitted) == 2
    state = orjson.loads(await snapshot_store.hget(snapshots.snapshot_key(), "leases"))
    assert "crashed-worker" not in state
    with pytest.raises(JSONRPCError, match="reservation"):
        await snapshots.publish_snapshot(snapshot_store, "crashed-worker", "scope", [b"[]"])


@pytest.mark.asyncio
async def test_cancellation_releases_collection_capacity(snapshot_store):
    """Release collector and byte reservations when a request is cancelled."""
    started = asyncio.Event()

    async def collect():
        """Hold a reservation until cancellation."""
        async with snapshots.reserve_collection(snapshot_store):
            started.set()
            await asyncio.Future()

    task = asyncio.create_task(collect())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert orjson.loads(await snapshot_store.hget(snapshots.snapshot_key(), "leases")) == {}
    async with snapshots.reserve_collection(snapshot_store):
        pass


@pytest.mark.asyncio
async def test_eviction_removes_snapshots_and_accounting_together(snapshot_store):
    """Reject evicted continuation and admit fresh work without orphaned snapshot pages."""
    async with snapshots.reserve_collection(snapshot_store) as snapshot:
        await snapshots.publish_snapshot(snapshot_store, snapshot, "scope", [b"[]", b"[]"])
    await snapshot_store.delete(snapshots.snapshot_key())
    assert await snapshots.read_snapshot(snapshot_store, snapshot, 1) == (None, None)
    async with snapshots.reserve_collection(snapshot_store) as replacement:
        await snapshots.publish_snapshot(snapshot_store, replacement, "scope", [b"[]", b"[]"])
    fields = await snapshot_store.hkeys(snapshots.snapshot_key())
    assert all(snapshot.encode() not in field for field in fields)


@pytest.mark.asyncio
async def test_memory_headroom_rejects_without_eviction(snapshot_store, monkeypatch):
    """Reject publication near Redis maxmemory while preserving unrelated keys."""
    info = await snapshot_store.info("memory")
    maximum = info["maxmemory"]
    assert maximum > 0, "Configure a finite maxmemory on the isolated test Redis"
    before = (await snapshot_store.info("stats"))["evicted_keys"]
    monkeypatch.setattr(settings, "mcp_proxy_list_max_snapshot_bytes", maximum)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", maximum * 2)
    with pytest.raises(JSONRPCError, match="reservation"):
        async with snapshots.reserve_collection(snapshot_store) as snapshot:
            await snapshots.publish_snapshot(snapshot_store, snapshot, "scope", [b"x" * (maximum // 2)])
    assert (await snapshot_store.info("stats"))["evicted_keys"] == before


@pytest.mark.asyncio
async def test_oversized_publication_releases_reservation(snapshot_store):
    """Reject page overhead beyond the reservation without retaining partial pages."""
    with pytest.raises(JSONRPCError, match="byte limit"):
        async with snapshots.reserve_collection(snapshot_store) as snapshot:
            await snapshots.publish_snapshot(snapshot_store, snapshot, "scope", [b"x" * 4096])
    assert await snapshot_store.hkeys(snapshots.snapshot_key()) == [b"leases"]


@pytest.mark.asyncio
async def test_denied_info_allows_bounded_snapshots(snapshot_store, monkeypatch):
    """Serve bounded snapshots when Redis ACL denies memory information."""
    # Third-Party
    from redis.exceptions import NoPermissionError

    username = f"catalog-acl-{uuid.uuid4().hex}"
    await snapshot_store.acl_setuser(username, enabled=True, nopass=True, commands=["+@all", "-info"], keys=[f"{settings.cache_prefix}*"])
    restricted = Redis.from_url(os.environ["MCP_CATALOG_TEST_REDIS_URL"], username=username)
    monkeypatch.setattr(settings, "mcp_proxy_list_max_total_bytes", 1600)
    try:
        with pytest.raises(NoPermissionError):
            await restricted.info("memory")
        async with snapshots.reserve_collection(restricted) as snapshot:
            await snapshots.publish_snapshot(restricted, snapshot, "scope", [b"[]", b"[]"])
        with pytest.raises(JSONRPCError, match="reservation"):
            async with snapshots.reserve_collection(restricted) as another:
                await snapshots.publish_snapshot(restricted, another, "scope", [b"[]", b"[]"])
        assert (await snapshots.read_snapshot(restricted, snapshot, 1))[1] == b"[]"
    finally:
        await restricted.aclose()
        await snapshot_store.acl_deluser(username)
