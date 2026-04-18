# -*- coding: utf-8 -*-
"""Unit tests for SessionAffinity (cluster-affinity layer for #4205).

After the #4205 refactor hollowed the pool-era machinery, ``SessionAffinity``
is the Redis-backed ownership + routing layer that keeps a downstream MCP
session pinned to one worker. No per-worker upstream-session state lives here
anymore — ``UpstreamSessionRegistry`` owns that. These tests focus on the
pure helpers, the Redis-mocked state machine, and the lifecycle hooks.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest


@pytest.fixture(autouse=True)
def _reset_affinity_singleton():
    """Clear the global singleton around every test so state doesn't leak."""
    # First-Party
    import mcpgateway.services.session_affinity as sa

    sa._mcp_session_pool = None
    yield
    sa._mcp_session_pool = None


class _FakeRedis:
    """Minimal mock for the redis asyncio client surface SessionAffinity uses.

    Stores keys in an in-memory dict, supports SET NX/EX, GET, DELETE,
    EXISTS, SETEX, EXPIRE, EVAL (the Lua CAS script), PUBSUB publish, and
    SCAN. Not a full redis emulator — the goal is test coverage, not
    semantic equivalence with real redis.
    """

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.published: list[tuple[str, bytes]] = []
        self.eval_calls: list[tuple[str, tuple, tuple]] = []
        self.fail_next_set = False

    async def set(self, key, value, nx=False, ex=None):
        if self.fail_next_set:
            self.fail_next_set = False
            raise RuntimeError("simulated redis failure")
        if nx and key in self.store:
            return None
        self.store[key] = value.encode() if isinstance(value, str) else value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0

    async def exists(self, key):
        return 1 if key in self.store else 0

    async def setex(self, key, seconds, value):  # pylint: disable=unused-argument
        self.store[key] = value.encode() if isinstance(value, str) else value
        return True

    async def expire(self, key, seconds):  # pylint: disable=unused-argument
        return 1 if key in self.store else 0

    async def eval(self, script, numkeys, *args):  # pylint: disable=unused-argument
        # Emulate the register_session_owner Lua CAS:
        #   * returns 1 if the key was missing (fresh claim)
        #   * returns 2 if the key matches the worker (refresh)
        #   * returns 0 if owned by a different worker
        self.eval_calls.append((script, args[:numkeys], args[numkeys:]))
        key = args[0]
        worker_id = args[1]
        cur = self.store.get(key)
        if cur is None:
            self.store[key] = worker_id.encode() if isinstance(worker_id, str) else worker_id
            return 1
        cur_str = cur.decode() if isinstance(cur, bytes) else cur
        if cur_str == worker_id:
            return 2
        return 0

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    async def scan_iter(self, match=None, count=100):  # pylint: disable=unused-argument
        for key in list(self.store.keys()):
            if match is None or self._glob_match(match, key):
                yield key

    @staticmethod
    def _glob_match(pattern, key):
        # Minimal glob: only ``*`` wildcard, sufficient for scan prefixes used here.
        # Standard
        import fnmatch as _fn

        return _fn.fnmatch(key, pattern)


# ---------------------------------------------------------------------------
# Pure helpers — no Redis, no lifecycle state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "session_id,expected",
    [
        ("downstream-abc-123", True),
        ("ABC_DEF_ghi-0", True),
        ("a" * 128, True),
        ("a" * 129, False),  # too long
        ("", False),  # empty
        ("has space", False),
        ("has/slash", False),
        ("has:colon", False),
    ],
)
def test_is_valid_mcp_session_id(session_id, expected):
    """Session id validator: the strict charset + 128-char limit protects Redis keys."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    assert SessionAffinity.is_valid_mcp_session_id(session_id) is expected


def test_sanitize_redis_key_component_replaces_problematic_chars():
    """Characters outside [a-zA-Z0-9_-] become underscores; empty input stays empty."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    assert affinity._sanitize_redis_key_component("") == ""  # pylint: disable=protected-access
    assert affinity._sanitize_redis_key_component("abc123") == "abc123"  # pylint: disable=protected-access
    assert affinity._sanitize_redis_key_component("abc/def:ghi jkl") == "abc_def_ghi_jkl"  # pylint: disable=protected-access
    # Underscores and hyphens are preserved.
    assert affinity._sanitize_redis_key_component("abc-def_ghi") == "abc-def_ghi"  # pylint: disable=protected-access


def test_session_mapping_redis_key_includes_hash_and_sanitised_id():
    """Mapping key shape: ``mcpgw:session_mapping:<sid>:<url-hash-16>:<transport>:<gateway>``."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    key = affinity._session_mapping_redis_key("sess-1", "https://u.example.com/mcp", "streamablehttp", "gw-1")  # pylint: disable=protected-access
    assert key.startswith("mcpgw:session_mapping:sess-1:")
    # url hash is 16 hex chars
    parts = key.split(":")
    assert len(parts[3]) == 16
    assert parts[-2] == "streamablehttp"
    assert parts[-1] == "gw-1"


def test_session_owner_key_has_expected_prefix():
    """Session-owner key is a simple ``mcpgw:pool_owner:<sid>`` prefix."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    assert SessionAffinity._session_owner_key("sess-1") == "mcpgw:pool_owner:sess-1"  # pylint: disable=protected-access


def test_worker_heartbeat_key_uses_module_worker_id():
    """Heartbeat key embeds the process-wide WORKER_ID constant (hostname+pid)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    assert affinity._worker_heartbeat_key() == f"mcpgw:worker_heartbeat:{WORKER_ID}"  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Module-level singleton accessors
# ---------------------------------------------------------------------------


def test_get_session_affinity_raises_when_not_initialised():
    """Calling the accessor before init raises RuntimeError with a clear message."""
    # First-Party
    from mcpgateway.services.session_affinity import get_session_affinity

    with pytest.raises(RuntimeError, match="not initialized"):
        get_session_affinity()


def test_init_session_affinity_sets_singleton_accessible_via_get():
    """Init sets the module singleton so get_session_affinity returns it.

    Calling init twice replaces the singleton with a fresh instance — the
    accessor ends up pointing at the second one. This matches main.py's
    lifecycle assumption that init runs exactly once at startup.
    """
    # First-Party
    from mcpgateway.services.session_affinity import get_session_affinity, init_session_affinity

    first = init_session_affinity(enable_notifications=False)
    assert get_session_affinity() is first
    second = init_session_affinity(enable_notifications=False)
    # Second init produces a fresh instance; get returns the newest.
    assert get_session_affinity() is second
    assert second is not first


@pytest.mark.asyncio
async def test_close_session_affinity_clears_singleton():
    """After close, accessor raises again; init produces a fresh instance."""
    # First-Party
    from mcpgateway.services.session_affinity import close_session_affinity, get_session_affinity, init_session_affinity

    first = init_session_affinity(enable_notifications=False)
    await close_session_affinity()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_session_affinity()

    second = init_session_affinity(enable_notifications=False)
    assert second is not first


@pytest.mark.asyncio
async def test_drain_session_affinity_noop_when_singleton_absent():
    """drain_session_affinity must tolerate the uninitialised case silently."""
    # First-Party
    from mcpgateway.services.session_affinity import drain_session_affinity

    # No init before → delegates to nothing, returns cleanly.
    await drain_session_affinity()


@pytest.mark.asyncio
async def test_drain_session_affinity_delegates_to_drain_all():
    """When a singleton exists, drain_session_affinity forwards to its drain_all."""
    # First-Party
    from mcpgateway.services.session_affinity import drain_session_affinity, init_session_affinity

    affinity = init_session_affinity(enable_notifications=False)
    affinity.drain_all = AsyncMock()  # type: ignore[method-assign]
    await drain_session_affinity()
    affinity.drain_all.assert_awaited_once()


# ---------------------------------------------------------------------------
# Class lifecycle: __init__, close_all, drain_all
# ---------------------------------------------------------------------------


def test_session_affinity_init_default_metrics_zeroed():
    """Fresh instance has all metrics at zero and no background tasks."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    assert affinity._session_affinity_local_hits == 0  # pylint: disable=protected-access
    assert affinity._session_affinity_redis_hits == 0  # pylint: disable=protected-access
    assert affinity._session_affinity_misses == 0  # pylint: disable=protected-access
    assert affinity._forwarded_requests == 0  # pylint: disable=protected-access
    assert affinity._forwarded_request_failures == 0  # pylint: disable=protected-access
    assert affinity._forwarded_request_timeouts == 0  # pylint: disable=protected-access
    assert affinity._rpc_listener_task is None  # pylint: disable=protected-access
    assert affinity._heartbeat_task is None  # pylint: disable=protected-access
    assert affinity._closed is False  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_close_all_cancels_running_background_tasks(caplog):
    """close_all cancels heartbeat and RPC listener tasks and sets _closed."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _never():
        await asyncio.Event().wait()  # hangs forever until cancelled

    affinity._heartbeat_task = asyncio.create_task(_never(), name="fake-heartbeat")  # pylint: disable=protected-access
    affinity._rpc_listener_task = asyncio.create_task(_never(), name="fake-rpc")  # pylint: disable=protected-access

    with caplog.at_level("INFO", logger="mcpgateway.services.session_affinity"):
        await affinity.close_all()

    assert affinity._closed is True  # pylint: disable=protected-access
    assert affinity._heartbeat_task is None  # pylint: disable=protected-access
    assert affinity._rpc_listener_task is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_drain_all_is_logging_only_noop(caplog):
    """drain_all has no worker-local state to clear; it's a logged no-op that keeps the service live."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with caplog.at_level("INFO", logger="mcpgateway.services.session_affinity"):
        await affinity.drain_all()
    assert any("no worker-local state" in rec.getMessage() for rec in caplog.records)
    # Service remains operational.
    assert affinity._closed is False  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# register_session_mapping — Redis-backed ownership claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_session_mapping_short_circuits_when_feature_disabled():
    """If the global feature flag is off, register_session_mapping is a no-op (no Redis touched)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = False
        await affinity.register_session_mapping("sess-1", "http://u", "gw-1", "streamablehttp", "user@example.com")

    assert fake.store == {}


@pytest.mark.asyncio
async def test_register_session_mapping_rejects_invalid_session_id(caplog):
    """An invalid session id emits a WARNING and doesn't touch Redis."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
        caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_mapping("bad/session/id", "http://u", "gw-1", "streamablehttp", "user@example.com")

    assert fake.store == {}
    assert any("Invalid mcp_session_id" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_register_session_mapping_happy_path_writes_mapping_and_claims_ownership():
    """A fresh valid session id stores the mapping JSON and claims ownership with SET NX."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_mapping("sess-1", "http://u.example/mcp", "gw-1", "streamablehttp", "user@example.com")

    # Mapping + owner key exist in the fake.
    mapping_keys = [k for k in fake.store if k.startswith("mcpgw:session_mapping:")]
    owner_keys = [k for k in fake.store if k.startswith("mcpgw:pool_owner:")]
    assert mapping_keys
    assert owner_keys == ["mcpgw:pool_owner:sess-1"]
    # Ownership value is this worker id.
    assert fake.store["mcpgw:pool_owner:sess-1"].decode() == WORKER_ID


@pytest.mark.asyncio
async def test_register_session_mapping_anonymous_user_hashes_to_literal_anonymous():
    """When no user_email is provided, user_identity is "anonymous" literal (not a hash)."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_mapping("sess-1", "http://u.example/mcp", "gw-1", "streamablehttp", None)

    mapping_key = next(k for k in fake.store if k.startswith("mcpgw:session_mapping:"))
    payload = orjson.loads(fake.store[mapping_key])
    assert payload["user_hash"] == "anonymous"


@pytest.mark.asyncio
async def test_register_session_mapping_tolerates_redis_failure(caplog):
    """Redis exceptions during mapping registration are logged at debug and swallowed."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("redis down")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_mapping("sess-1", "http://u", "gw-1", "streamablehttp", "user@example.com")

    assert any("Failed to store session mapping in Redis" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# register_session_owner — Lua CAS claim-or-refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_session_owner_noop_when_feature_disabled():
    """Feature flag off → no Redis write."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = False
        await affinity.register_session_owner("sess-1")
    assert fake.eval_calls == []


@pytest.mark.asyncio
async def test_register_session_owner_fresh_claim_sets_key():
    """A previously-unclaimed session id becomes owned by this worker (Lua CAS returns 1)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_owner("sess-1")

    assert fake.store.get("mcpgw:pool_owner:sess-1").decode() == WORKER_ID


@pytest.mark.asyncio
async def test_register_session_owner_refresh_when_same_worker():
    """If this worker already owns the session, Lua CAS refreshes TTL (returns 2) — still a no-op to the caller."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:pool_owner:sess-1"] = WORKER_ID.encode()

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_owner("sess-1")

    # Key still exists, still owned by this worker (no poison).
    assert fake.store["mcpgw:pool_owner:sess-1"].decode() == WORKER_ID


@pytest.mark.asyncio
async def test_register_session_owner_yields_to_existing_other_worker():
    """When another worker owns the session, Lua CAS returns 0 — we must not overwrite."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:pool_owner:sess-1"] = b"other-worker:12345"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_owner("sess-1")

    # Other worker's ownership preserved.
    assert fake.store["mcpgw:pool_owner:sess-1"] == b"other-worker:12345"


# ---------------------------------------------------------------------------
# _get_session_owner / get_session_owner (public wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_owner_returns_stored_worker_id():
    """Reads the owner worker id from the Redis key."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:pool_owner:sess-1"] = b"worker-42"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        owner = await affinity.get_session_owner("sess-1")
    assert owner == "worker-42"


@pytest.mark.asyncio
async def test_get_session_owner_returns_none_for_unclaimed():
    """Unclaimed session id → None."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        owner = await affinity.get_session_owner("never-seen")
    assert owner is None


@pytest.mark.asyncio
async def test_get_session_owner_none_when_feature_disabled():
    """Feature flag off → always returns None (no Redis)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = False
        assert await affinity.get_session_owner("sess-1") is None


@pytest.mark.asyncio
async def test_get_session_owner_rejects_invalid_session_id():
    """Invalid session id short-circuits to None."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = True
        assert await affinity.get_session_owner("has space") is None


# ---------------------------------------------------------------------------
# cleanup_session_owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_session_owner_rejects_invalid_session_id(caplog):
    """Invalid input short-circuits with a debug log (no Redis call)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        await affinity.cleanup_session_owner("bad/id")
    mock_get_redis.assert_not_awaited()
    assert any("Invalid mcp_session_id for owner cleanup" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_cleanup_session_owner_only_deletes_keys_this_worker_owns():
    """Don't delete another worker's claim — only our own."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:pool_owner:ours"] = WORKER_ID.encode()
    fake.store["mcpgw:pool_owner:theirs"] = b"other-worker:5555"

    with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)):
        await affinity.cleanup_session_owner("ours")
        await affinity.cleanup_session_owner("theirs")

    # Our key got deleted, theirs is preserved.
    assert "mcpgw:pool_owner:ours" not in fake.store
    assert fake.store["mcpgw:pool_owner:theirs"] == b"other-worker:5555"


@pytest.mark.asyncio
async def test_cleanup_session_owner_tolerates_redis_failure(caplog):
    """Redis errors during cleanup are swallowed at debug level."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("cleanup redis error")

    with (
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        await affinity.cleanup_session_owner("sess-1")
    assert any("Failed to cleanup session owner" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# start_heartbeat — background task scheduling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_heartbeat_noop_when_feature_disabled():
    """Feature flag off → no task scheduled."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = False
        affinity.start_heartbeat()
    assert affinity._heartbeat_task is None  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_start_heartbeat_schedules_task_once():
    """Calling twice doesn't stack two tasks; the second call is a no-op while the first is still running."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = True
        affinity.start_heartbeat()
        first_task = affinity._heartbeat_task  # pylint: disable=protected-access
        affinity.start_heartbeat()
        second_task = affinity._heartbeat_task  # pylint: disable=protected-access

    assert first_task is second_task
    # Clean up: cancel so pytest doesn't complain about hanging tasks.
    first_task.cancel()
    try:
        await first_task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# _is_worker_alive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_worker_alive_returns_true_when_heartbeat_key_exists():
    """If the heartbeat key is present in Redis, the worker is considered alive."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:worker_heartbeat:worker-xyz"] = b"alive"

    with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)):
        assert await affinity._is_worker_alive("worker-xyz") is True  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_is_worker_alive_returns_false_when_heartbeat_absent():
    """Missing heartbeat key → treat worker as dead."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)):
        assert await affinity._is_worker_alive("ghost-worker") is False  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_is_worker_alive_fails_open_on_redis_error():
    """Redis unavailable → assume alive (don't reclaim sessions on network hiccups)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("redis error")

    with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises):
        assert await affinity._is_worker_alive("worker-xyz") is True  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# forward_request_to_owner — cross-worker RPC routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_request_to_owner_noop_when_feature_disabled():
    """Feature off → None (caller executes locally)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = False
        assert await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"}) is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_invalid_session_id_returns_none():
    """Invalid session id → None short-circuit."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        assert await affinity.forward_request_to_owner("bad id", {"method": "x"}) is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_none_when_redis_unavailable():
    """No Redis → None (caller executes locally)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        assert await affinity.forward_request_to_owner("sess-1", {"method": "x"}) is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_no_owner_returns_none():
    """Unclaimed session → None (caller treats as new session, claims locally)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        assert await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"}) is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_returns_none_when_we_own_the_session():
    """Self-owned session → None (caller executes locally, no forwarding needed)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    fake.store["mcpgw:pool_owner:sess-1"] = WORKER_ID.encode()

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        assert await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"}) is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_swallows_unexpected_errors_as_none():
    """An unexpected error during forwarding increments the failure counter and returns None."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("unexpected redis kaboom")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        assert await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"}) is None
    assert affinity._forwarded_request_failures == 1  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Heartbeat loop (drive one iteration, then exit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_heartbeat_loop_writes_key_then_exits_on_close():
    """A single iteration writes the heartbeat key via SETEX; closing the service ends the loop."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()

    # Patch sleep to unblock the loop instantly, and close the service after first iteration.
    iterations = {"n": 0}
    original_sleep = asyncio.sleep

    async def _fast_sleep(_seconds):
        iterations["n"] += 1
        affinity._closed = True  # pylint: disable=protected-access
        await original_sleep(0)

    with (
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
        patch("mcpgateway.services.session_affinity.asyncio.sleep", _fast_sleep),
    ):
        await affinity._run_heartbeat_loop()  # pylint: disable=protected-access

    assert iterations["n"] == 1
    # Heartbeat key was written.
    assert affinity._worker_heartbeat_key() in fake.store  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_run_heartbeat_loop_swallows_redis_errors_and_keeps_going():
    """A Redis error in the loop is logged at debug and doesn't stop the heartbeat."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    calls = {"n": 0}

    async def _sometimes_raises():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("redis blip")
        return _FakeRedis()

    original_sleep = asyncio.sleep

    async def _stop_after_two(_seconds):
        if calls["n"] >= 2:
            affinity._closed = True  # pylint: disable=protected-access
        await original_sleep(0)

    with (
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_sometimes_raises),
        patch("mcpgateway.services.session_affinity.asyncio.sleep", _stop_after_two),
    ):
        await affinity._run_heartbeat_loop()  # pylint: disable=protected-access

    # Two iterations: one with an error, one without.
    assert calls["n"] >= 2


# ---------------------------------------------------------------------------
# Notification integration helpers — tolerate missing notification service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_affinity_notification_service_tolerates_missing_notification_service():
    """When the notification service can't be reached, this helper logs and returns cleanly."""
    # First-Party
    from mcpgateway.services.session_affinity import start_affinity_notification_service

    with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not configured")):
        await start_affinity_notification_service(gateway_service=None)  # should not raise


def test_register_gateway_capabilities_for_notifications_tolerates_missing_service():
    """Early-boot races where notification service isn't up yet: swallow the RuntimeError."""
    # First-Party
    from mcpgateway.services.session_affinity import register_gateway_capabilities_for_notifications

    with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not initialised")):
        # Should not raise.
        register_gateway_capabilities_for_notifications("gw-1", {"tools": {"listChanged": True}})


def test_unregister_gateway_from_notifications_tolerates_missing_service():
    """Mirror of the register helper — no notification service → silent no-op."""
    # First-Party
    from mcpgateway.services.session_affinity import unregister_gateway_from_notifications

    with patch("mcpgateway.services.notification_service.get_notification_service", side_effect=RuntimeError("not initialised")):
        unregister_gateway_from_notifications("gw-1")


def test_register_gateway_capabilities_for_notifications_forwards_to_service_when_available():
    """When the notification service is up, this helper forwards the capabilities through to it."""
    # First-Party
    from mcpgateway.services.session_affinity import register_gateway_capabilities_for_notifications

    mock_svc = MagicMock()
    with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_svc):
        register_gateway_capabilities_for_notifications("gw-1", {"tools": {"listChanged": True}})
    mock_svc.register_gateway_capabilities.assert_called_once_with("gw-1", {"tools": {"listChanged": True}})


def test_unregister_gateway_from_notifications_forwards_to_service_when_available():
    """Mirror of the register forwarding test."""
    # First-Party
    from mcpgateway.services.session_affinity import unregister_gateway_from_notifications

    mock_svc = MagicMock()
    with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_svc):
        unregister_gateway_from_notifications("gw-1")
    mock_svc.unregister_gateway.assert_called_once_with("gw-1")


# ---------------------------------------------------------------------------
# forward_to_owner — HTTP transport pub/sub forwarding
# ---------------------------------------------------------------------------


class _FakePubSub:
    """Minimal pubsub mock returning one fake message then yielding nothing (simulates timeout)."""

    def __init__(self, response_payload: bytes | None = None):
        self._response = response_payload
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def unsubscribe(self, *channels):
        self.unsubscribed.extend(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.1):  # pylint: disable=unused-argument
        if self._response is not None:
            msg = {"type": "message", "data": self._response}
            self._response = None
            return msg
        # No more messages — mimic timeout poll.
        await asyncio.sleep(0)
        return None

    async def listen(self):
        if self._response is not None:
            yield {"type": "message", "data": self._response}
            self._response = None


class _FakeRedisWithPubSub(_FakeRedis):
    """FakeRedis that returns controllable pubsub instances (one per call)."""

    def __init__(self, response_payload: bytes | None = None):
        super().__init__()
        self._response_payload = response_payload
        self.last_pubsub: _FakePubSub | None = None

    def pubsub(self):
        self.last_pubsub = _FakePubSub(self._response_payload)
        return self.last_pubsub


@pytest.mark.asyncio
async def test_forward_to_owner_noop_when_feature_disabled():
    """Feature off → None from HTTP-forward path too."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = False
        result = await affinity.forward_to_owner("other-worker", "sess-1", "POST", "/mcp", {}, b"")
    assert result is None


@pytest.mark.asyncio
async def test_forward_to_owner_invalid_session_id_returns_none():
    """Invalid session id → None."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.services.session_affinity.settings") as mock_settings:
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity.forward_to_owner("w-1", "bad id", "POST", "/mcp", {}, b"")
    assert result is None


@pytest.mark.asyncio
async def test_forward_to_owner_returns_none_when_redis_unavailable():
    """No Redis → local fallback (None)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity.forward_to_owner("w-1", "sess-1", "POST", "/mcp", {}, b"")
    assert result is None


@pytest.mark.asyncio
async def test_forward_to_owner_decodes_hex_body_from_response():
    """Happy path: fake pubsub yields one message; the hex-encoded body is decoded back to bytes."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    # Upstream response: status=200, body=b"hello" (encoded as hex in the JSON envelope).
    response = orjson.dumps({"status": 200, "headers": {"Content-Type": "application/json"}, "body": b"hello".hex()})
    fake = _FakeRedisWithPubSub(response_payload=response)

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity.forward_to_owner("other-worker", "sess-1", "POST", "/mcp", {"h": "v"}, b"req-body")

    assert result is not None
    assert result["status"] == 200
    assert result["body"] == b"hello"
    # Published to the owner's HTTP channel.
    assert any(chan == "mcpgw:pool_http:other-worker" for chan, _ in fake.published)
    # Forward metrics bumped.
    assert affinity._forwarded_requests == 1  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_forward_to_owner_times_out_and_returns_none_with_metric_bump():
    """No message arrives → asyncio.timeout fires → metric incremented, None returned."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedisWithPubSub(response_payload=None)  # no response ever

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 0.05  # short timeout
        result = await affinity.forward_to_owner("other-worker", "sess-1", "POST", "/mcp", {}, b"")

    assert result is None
    assert affinity._forwarded_request_timeouts == 1  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# start_rpc_listener — early-exit when Redis unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_rpc_listener_returns_when_feature_disabled():
    """Feature off → listener doesn't start (no Redis touched)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
    ):
        mock_settings.mcpgateway_session_affinity_enabled = False
        await affinity.start_rpc_listener()
    mock_get_redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_rpc_listener_returns_cleanly_when_redis_unavailable(caplog):
    """No Redis → log at debug and return (don't retry forever in a tight loop)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None)),
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        await affinity.start_rpc_listener()
    assert any("RPC listener not started" in rec.getMessage() for rec in caplog.records)
