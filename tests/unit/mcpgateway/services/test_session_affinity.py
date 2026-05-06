# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_session_affinity.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for SessionAffinity (cluster-affinity layer for #4205).
After the #4205 refactor hollowed the pool-era machinery, ``SessionAffinity``
is the Redis-backed ownership + routing layer that keeps a downstream MCP
session pinned to one worker. No per-worker upstream-session state lives here
anymore — ``UpstreamSessionRegistry`` owns that. These tests focus on the
pure helpers, the Redis-mocked state machine, and the lifecycle hooks.
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
        # Emulate the two Lua CAS scripts SessionAffinity uses. Disambiguate by arg count.
        self.eval_calls.append((script, args[:numkeys], args[numkeys:]))
        key = args[0]

        if len(args) == 3:
            # register_session_owner(worker_id, ttl):
            #   * key missing         → fresh claim, return 1
            #   * cur matches worker  → refresh, return 2
            #   * cur is other worker → no-op, return 0
            worker_id = args[1]
            cur = self.store.get(key)
            if cur is None:
                self.store[key] = worker_id.encode() if isinstance(worker_id, str) else worker_id
                return 1
            cur_str = cur.decode() if isinstance(cur, bytes) else cur
            return 2 if cur_str == worker_id else 0

        if len(args) == 4:
            # Dead-worker reclaim CAS(expected_old, new_owner, ttl):
            #   * cur matches expected_old → overwrite with new_owner, return 1
            #   * anything else            → no-op, return 0
            expected_old = args[1]
            new_owner = args[2]
            cur = self.store.get(key)
            if cur is None:
                return 0
            cur_str = cur.decode() if isinstance(cur, bytes) else cur
            if cur_str == expected_old:
                self.store[key] = new_owner.encode() if isinstance(new_owner, str) else new_owner
                return 1
            return 0

        raise AssertionError(f"unexpected Lua script arity: {len(args)}")

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


# ---------------------------------------------------------------------------
# Additional branches: _is_worker_alive / register_session_owner / _get_session_owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_worker_alive_returns_true_when_redis_is_none():
    """If get_redis_client returns None (no Redis configured), fail open — treat as alive."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None)):
        assert await affinity._is_worker_alive("worker-xyz") is True  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_register_session_owner_debug_logs_on_invalid_session_id(caplog):
    """Invalid session id short-circuits with a DEBUG log (no Redis touched)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        await affinity.register_session_owner("bad/id")
    mock_get_redis.assert_not_awaited()
    assert any("Invalid mcp_session_id for owner registration" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_register_session_owner_tolerates_redis_error(caplog):
    """Redis failure during ownership claim → logged at debug, returns cleanly."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("eval failed")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_owner("sess-1")
    assert any("Failed to register session owner in Redis" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_get_session_owner_tolerates_redis_error():
    """An exception reading the owner key → logged + returns None (caller executes locally)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("redis fetch failed")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        assert await affinity.get_session_owner("sess-1") is None


@pytest.mark.asyncio
async def test_register_session_mapping_logs_existing_owner_when_set_nx_returns_none():
    """When SET NX fails because another worker already owns the key, log the existing owner at debug."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    # Pre-populate: another worker already owns this session.
    fake.store["mcpgw:pool_owner:sess-1"] = b"worker-other"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_session_affinity_ttl = 300
        await affinity.register_session_mapping("sess-1", "http://u", "gw-1", "streamablehttp", "user@example.com")

    # Other worker's ownership preserved (SET NX didn't overwrite).
    assert fake.store["mcpgw:pool_owner:sess-1"] == b"worker-other"


# ---------------------------------------------------------------------------
# forward_request_to_owner — happy path via mocked pubsub + timeout
# ---------------------------------------------------------------------------


class _FakePubSubListenStream:
    """Async-iterable pubsub stand-in for the ``async for msg in pubsub.listen()`` loop."""

    def __init__(self, response_data: bytes | None):
        self._response = response_data
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def unsubscribe(self, *channels):
        self.unsubscribed.extend(channels)

    def listen(self):
        payload = self._response
        self._response = None

        async def _gen():
            if payload is None:
                # Hang so the outer `async with asyncio.timeout(...)` fires.
                await asyncio.Event().wait()
                return
            yield {"type": "message", "data": payload}

        return _gen()


class _FakeRedisWithListen(_FakeRedis):
    """Fake Redis whose pubsub() yields a listen-streaming mock."""

    def __init__(self, response_payload: bytes | None = None):
        super().__init__()
        self._response_payload = response_payload
        self.last_pubsub: _FakePubSubListenStream | None = None

    def pubsub(self):
        self.last_pubsub = _FakePubSubListenStream(self._response_payload)
        return self.last_pubsub


@pytest.mark.asyncio
async def test_forward_request_to_owner_happy_path_via_pubsub():
    """Happy path: other worker owns session, we forward via pub/sub and receive the response."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    # Pre-populate: session is owned by a DIFFERENT worker (so we forward, not execute locally).
    # Worker heartbeat present (so _is_worker_alive returns True).
    fake = _FakeRedisWithListen(response_payload=orjson.dumps({"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}))
    fake.store["mcpgw:pool_owner:sess-1"] = b"other-worker"
    fake.store["mcpgw:worker_heartbeat:other-worker"] = b"alive"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        mock_settings.mcpgateway_session_affinity_ttl = 300
        result = await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})

    assert result == {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}
    assert affinity._forwarded_requests == 1  # pylint: disable=protected-access
    # Check that the request was published on the owner's RPC channel.
    assert any(chan == "mcpgw:pool_rpc:other-worker" for chan, _ in fake.published)


@pytest.mark.asyncio
async def test_forward_request_to_owner_raises_and_counts_timeout_when_no_response():
    """No response from owner within timeout → metric bumped, asyncio.TimeoutError propagates."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedisWithListen(response_payload=None)  # listen hangs forever
    fake.store["mcpgw:pool_owner:sess-1"] = b"other-worker"
    fake.store["mcpgw:worker_heartbeat:other-worker"] = b"alive"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 0.05  # short
        mock_settings.mcpgateway_session_affinity_ttl = 300
        with pytest.raises(asyncio.TimeoutError):
            await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})

    assert affinity._forwarded_request_timeouts == 1  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_forward_request_to_owner_reclaims_session_from_dead_worker():
    """Dead owner worker → Lua CAS reclaims ownership to us; caller executes locally (None)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()
    fake = _FakeRedis()
    # Dead owner (no heartbeat key).
    fake.store["mcpgw:pool_owner:sess-1"] = b"dead-worker"

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        mock_settings.mcpgateway_session_affinity_ttl = 300
        result = await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})

    # We reclaimed + now own it → execute locally (None).
    assert result is None
    # Ownership was transferred to us.
    assert fake.store["mcpgw:pool_owner:sess-1"].decode() == WORKER_ID


# ---------------------------------------------------------------------------
# _execute_forwarded_request — internal HTTP call
# ---------------------------------------------------------------------------


class _FakeHttpResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int, json_body: Any = None, text_body: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text_body
        self.content = (text_body or "").encode()
        self.headers: dict[str, str] = {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class _FakeHttpxClient:
    """Async-CM httpx.AsyncClient stand-in with controllable responses."""

    def __init__(self, response: _FakeHttpResponse | None = None, raise_exc: Exception | None = None):
        self._response = response
        self._raise_exc = raise_exc
        self.last_post_kwargs: dict | None = None
        self.last_request_kwargs: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, *, json=None, headers=None, timeout=None):
        self.last_post_kwargs = {"url": url, "json": json, "headers": headers, "timeout": timeout}
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response

    async def request(self, *, method, url, headers=None, content=None, timeout=None):
        self.last_request_kwargs = {"method": method, "url": url, "headers": headers, "content": content, "timeout": timeout}
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


@pytest.mark.asyncio
async def test_execute_forwarded_request_success_returns_result():
    """200-OK JSON-RPC response → the result is unwrapped and returned."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(response=_FakeHttpResponse(200, json_body={"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request(  # pylint: disable=protected-access
            {"method": "tools/list", "params": {}, "headers": {"Authorization": "Bearer x"}, "req_id": 1, "mcp_session_id": "sess-12345678"}
        )

    assert result == {"result": {"tools": []}}
    # x-forwarded-internally header is added to prevent loops.
    assert client.last_post_kwargs["headers"].get("x-forwarded-internally") == "true"  # type: ignore[index]


@pytest.mark.asyncio
async def test_execute_forwarded_request_propagates_jsonrpc_error_in_response():
    """A JSON-RPC error in the response body is propagated verbatim."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    error_body = {"jsonrpc": "2.0", "error": {"code": -32603, "message": "internal"}, "id": 1}
    client = _FakeHttpxClient(response=_FakeHttpResponse(200, json_body=error_body))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request(  # pylint: disable=protected-access
            {"method": "tools/call", "params": {"name": "x"}, "headers": {}, "req_id": 1, "mcp_session_id": "sess-abcd"}
        )

    assert result == {"error": {"code": -32603, "message": "internal"}}


@pytest.mark.asyncio
async def test_execute_forwarded_request_maps_non_2xx_http_to_jsonrpc_error():
    """HTTP 500 with a plain error body → wrapped as a JSON-RPC error code -32603."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(response=_FakeHttpResponse(500, json_body={"detail": "database down"}, text_body=""))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "s"})  # pylint: disable=protected-access

    assert "error" in result
    assert result["error"]["code"] == -32603
    assert "HTTP 500" in result["error"]["message"]
    assert "database down" in result["error"]["message"]


@pytest.mark.asyncio
async def test_execute_forwarded_request_timeout_returns_timeout_error():
    """httpx TimeoutException → JSON-RPC timeout error envelope."""
    # Third-Party
    import httpx

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(raise_exc=httpx.TimeoutException("timed out"))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "s"})  # pylint: disable=protected-access

    assert result == {"error": {"code": -32603, "message": "Internal request timeout"}}


@pytest.mark.asyncio
async def test_execute_forwarded_request_generic_error_returns_wrapped_error():
    """Any other exception is wrapped as a JSON-RPC error (code -32603, message=str(exc))."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(raise_exc=RuntimeError("boom"))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "s"})  # pylint: disable=protected-access

    assert result == {"error": {"code": -32603, "message": "boom"}}


# ---------------------------------------------------------------------------
# _execute_forwarded_http_request — HTTP transport fanout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_forwarded_http_request_publishes_response_via_redis():
    """Happy path: make the internal HTTP call, hex-encode the response body, publish to Redis."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    response = _FakeHttpResponse(200, text_body="response-body")
    response.headers = {"content-type": "application/json"}
    client = _FakeHttpxClient(response=response)

    request = {
        "response_channel": "mcpgw:pool_http_response:req-1",
        "method": "POST",
        "path": "/mcp",
        "query_string": "",
        "headers": {"Authorization": "Bearer x"},
        "body": b"upstream-body".hex(),
        "original_worker": "origin-worker",
        "mcp_session_id": "sess-123456789",
    }

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        await affinity._execute_forwarded_http_request(request, fake)  # pylint: disable=protected-access

    # Response published to the requester's channel.
    assert fake.published
    chan, payload = fake.published[0]
    assert chan == "mcpgw:pool_http_response:req-1"
    # Orjson round-trips the dict — body is hex-encoded.
    # Third-Party
    import orjson

    decoded = orjson.loads(payload)
    assert decoded["status"] == 200
    assert bytes.fromhex(decoded["body"]) == b"response-body"


@pytest.mark.asyncio
async def test_execute_forwarded_http_request_publishes_500_error_on_exception():
    """If the internal HTTP call raises, a 500 error envelope is still published to Redis."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    client = _FakeHttpxClient(raise_exc=RuntimeError("internal crash"))

    request = {
        "response_channel": "mcpgw:pool_http_response:req-2",
        "method": "POST",
        "path": "/mcp",
        "headers": {},
        "body": "",
        "mcp_session_id": "sess-abcdef",
    }

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        await affinity._execute_forwarded_http_request(request, fake)  # pylint: disable=protected-access

    # Error response still published so the requester doesn't hang.
    # Third-Party
    import orjson

    chan, payload = fake.published[0]
    assert chan == "mcpgw:pool_http_response:req-2"
    decoded = orjson.loads(payload)
    assert decoded["status"] == 500


# ---------------------------------------------------------------------------
# init_session_affinity — notification-handler factory path
# ---------------------------------------------------------------------------


def test_init_session_affinity_with_notifications_enabled_wires_handler_factory():
    """When enable_notifications=True and no factory is provided, a handler factory is built from the notification service."""
    # First-Party
    from mcpgateway.services.session_affinity import init_session_affinity

    mock_notif_svc = MagicMock()
    mock_notif_svc.create_message_handler = MagicMock(return_value=lambda msg: None)

    with patch("mcpgateway.services.notification_service.init_notification_service", return_value=mock_notif_svc) as mock_init:
        affinity = init_session_affinity(enable_notifications=True, notification_debounce_seconds=5.0)

    mock_init.assert_called_once_with(debounce_seconds=5.0)
    # Exercising the handler factory exposes it to coverage on
    # `default_handler_factory` closure.
    assert affinity._message_handler_factory is not None  # pylint: disable=protected-access
    affinity._message_handler_factory("http://u", "gw-1", downstream_session_id="sess-test")  # pylint: disable=protected-access
    mock_notif_svc.create_message_handler.assert_called_once()


@pytest.mark.asyncio
async def test_close_session_affinity_also_closes_notification_service_when_present():
    """close_session_affinity forwards to close_notification_service if it imports cleanly."""
    # First-Party
    from mcpgateway.services.session_affinity import close_session_affinity, init_session_affinity

    init_session_affinity(enable_notifications=False)

    mock_close = AsyncMock()
    with patch("mcpgateway.services.notification_service.close_notification_service", mock_close):
        await close_session_affinity()
    mock_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_affinity_notification_service_initialises_with_gateway_when_service_present():
    """When the notification service is up, start_affinity_notification_service wires the gateway through."""
    # First-Party
    from mcpgateway.services.session_affinity import start_affinity_notification_service

    mock_notif_svc = MagicMock()
    mock_notif_svc.initialize = AsyncMock()
    gateway_svc = MagicMock()

    with patch("mcpgateway.services.notification_service.get_notification_service", return_value=mock_notif_svc):
        await start_affinity_notification_service(gateway_service=gateway_svc)

    mock_notif_svc.initialize.assert_awaited_once_with(gateway_svc)


# ---------------------------------------------------------------------------
# start_rpc_listener main loop — dispatch messages to executors
# ---------------------------------------------------------------------------


class _ListenerPubSub:
    """Pubsub stand-in with a controllable get_message() sequence for listener tests."""

    def __init__(self, messages: list[dict | None]):
        self._messages = list(messages)
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def unsubscribe(self, *channels):
        self.unsubscribed.extend(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):  # pylint: disable=unused-argument
        if self._messages:
            return self._messages.pop(0)
        # Signal the outer loop to exit by returning a terminator marker; the
        # test flips `_closed` after consuming the real messages.
        await asyncio.sleep(0)
        return None


@pytest.mark.asyncio
async def test_start_rpc_listener_dispatches_rpc_forward_and_http_forward_messages():
    """Happy path: listener receives one rpc_forward + one http_forward, dispatches each, then exits."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    # Craft two incoming messages — one of each forward type — plus a terminator
    # that flips _closed so the while-loop exits after dispatch.
    rpc_req = orjson.dumps({"type": "rpc_forward", "response_channel": "resp-rpc", "method": "tools/list", "req_id": 1})
    http_req = orjson.dumps({"type": "http_forward", "response_channel": "resp-http", "method": "POST", "path": "/mcp", "headers": {}, "body": "", "mcp_session_id": "sess-1"})

    messages = [
        {"type": "message", "data": rpc_req},
        {"type": "message", "data": http_req},
    ]
    pubsub = _ListenerPubSub(messages)

    class _FakeListenerRedis:
        def __init__(self):
            self.published: list[tuple[str, bytes]] = []

        def pubsub(self):
            return pubsub

        async def publish(self, channel, payload):
            self.published.append((channel, payload))
            return 1

    redis = _FakeListenerRedis()

    # Stop the listener after both forwarded-dispatches have been called.
    dispatched: list[str] = []

    async def _record_rpc(request):
        dispatched.append("rpc")
        if "rpc" in dispatched and "http" in dispatched:
            affinity._closed = True  # pylint: disable=protected-access
        return {"result": "ok"}

    async def _record_http(request, _redis):
        dispatched.append("http")
        if "rpc" in dispatched and "http" in dispatched:
            affinity._closed = True  # pylint: disable=protected-access

    affinity._execute_forwarded_request = _record_rpc  # type: ignore[method-assign]
    affinity._execute_forwarded_http_request = _record_http  # type: ignore[method-assign]

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        # Bound the test in case of any hang.
        await asyncio.wait_for(affinity.start_rpc_listener(), timeout=3.0)

    assert set(dispatched) == {"rpc", "http"}
    # The RPC response was published back on the caller's channel.
    assert any(c == "resp-rpc" for c, _ in redis.published)


@pytest.mark.asyncio
async def test_start_rpc_listener_tolerates_unknown_forward_type(caplog):
    """An unknown `type` field gets a WARNING and the loop continues (doesn't kill the listener)."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    messages = [
        {"type": "message", "data": orjson.dumps({"type": "mystery_forward", "response_channel": "resp-x"})},
    ]
    pubsub = _ListenerPubSub(messages)

    class _StopAfterOne:
        def __init__(self):
            self.seen = 0

        def pubsub(self):
            return pubsub

        async def publish(self, _channel, _payload):  # pragma: no cover — should not be called
            return 0

    redis = _StopAfterOne()

    # Schedule the listener to close after processing the mystery message.
    original_get = pubsub.get_message

    async def _stop_after_get(*args, **kwargs):
        msg = await original_get(*args, **kwargs)
        if msg is None:
            affinity._closed = True  # pylint: disable=protected-access
        return msg

    pubsub.get_message = _stop_after_get  # type: ignore[assignment]

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis)),
        caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        await asyncio.wait_for(affinity.start_rpc_listener(), timeout=3.0)

    assert any("Unknown forward type" in rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING")


@pytest.mark.asyncio
async def test_start_rpc_listener_swallows_exception_in_message_loop(caplog):
    """If an iteration raises (e.g. bad JSON), the listener logs a warning and keeps going."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    messages = [
        {"type": "message", "data": b"not-json-at-all"},  # orjson.loads will raise
    ]
    pubsub = _ListenerPubSub(messages)

    class _FakeRedisStop:
        def pubsub(self):
            return pubsub

        async def publish(self, *_a, **_k):  # pragma: no cover
            return 0

    redis = _FakeRedisStop()

    original_get = pubsub.get_message

    async def _stop_after_bad(*args, **kwargs):
        msg = await original_get(*args, **kwargs)
        if msg is None:
            affinity._closed = True  # pylint: disable=protected-access
        return msg

    pubsub.get_message = _stop_after_bad  # type: ignore[assignment]

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=redis)),
        caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        await asyncio.wait_for(affinity.start_rpc_listener(), timeout=3.0)

    assert any("Error processing forwarded request" in rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING")


# ---------------------------------------------------------------------------
# forward_to_owner — generic exception path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_to_owner_logs_warning_and_returns_none_on_unexpected_error():
    """An unexpected Redis exception during HTTP forwarding increments failures and returns None."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("redis kaboom")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 1.0
        result = await affinity.forward_to_owner("other-worker", "sess-1", "POST", "/mcp", {}, b"")
    assert result is None
    assert affinity._forwarded_request_failures == 1  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# close_session_affinity — ImportError branch for notification service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_session_affinity_tolerates_notification_service_runtime_error():
    """If close_notification_service raises RuntimeError (not initialised), the closer swallows it."""
    # First-Party
    from mcpgateway.services.session_affinity import close_session_affinity, init_session_affinity

    init_session_affinity(enable_notifications=False)

    async def _raises():
        raise RuntimeError("notification service not initialised")

    with patch("mcpgateway.services.notification_service.close_notification_service", side_effect=_raises):
        await close_session_affinity()  # should not raise


# ---------------------------------------------------------------------------
# forward_request_to_owner — dead-worker race where another worker reclaims first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_request_to_owner_forwards_to_new_owner_when_reclaim_lost():
    """Dead owner + CAS reclaim returns 0 (another worker won) → re-read owner and forward to them."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    # Custom fake that flips the owner key between GET and EVAL to simulate the race:
    # 1. First GET of owner key returns dead-worker
    # 2. EVAL CAS fails (returns 0) because the key has already been overwritten
    # 3. Second GET returns the new owner (not us)
    # We then forward to that new owner.
    class _RaceRedis(_FakeRedisWithListen):
        def __init__(self):
            super().__init__(response_payload=orjson.dumps({"result": {"race": "forwarded"}}))
            self.store["mcpgw:pool_owner:sess-1"] = b"dead-worker"
            # No heartbeat for dead-worker → _is_worker_alive returns False.
            self.get_call_count = 0

        async def get(self, key):
            self.get_call_count += 1
            if key == "mcpgw:pool_owner:sess-1":
                if self.get_call_count == 1:
                    return b"dead-worker"
                # After CAS fails, simulate the key being overwritten by another worker.
                self.store[key] = b"new-owner"
                return b"new-owner"
            return self.store.get(key)

        async def eval(self, script, numkeys, *args):
            # Dead-worker reclaim CAS: simulate "another worker already won the race" by returning 0
            # regardless of input.
            if len(args) == 4:
                self.eval_calls.append((script, args[:numkeys], args[numkeys:]))
                return 0
            return await super().eval(script, numkeys, *args)

    fake = _RaceRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        mock_settings.mcpgateway_session_affinity_ttl = 300
        result = await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})

    assert result == {"result": {"race": "forwarded"}}
    # Forwarded to the new owner's channel (not the dead one).
    assert any(c == "mcpgw:pool_rpc:new-owner" for c, _ in fake.published)


# ---------------------------------------------------------------------------
# start_rpc_listener — outer-except branch (Redis raises during setup)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_rpc_listener_logs_warning_when_setup_raises(caplog):
    """If the initial Redis access throws, the outer `except` swallows and logs at WARNING."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    async def _raises():
        raise RuntimeError("redis client failed to construct")

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=_raises),
        caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        await affinity.start_rpc_listener()
    assert any("RPC/HTTP listener failed" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# _execute_forwarded_request — edge cases for non-2xx response bodies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_forwarded_request_propagates_jsonrpc_error_from_non_2xx_response():
    """500 response with a JSON-RPC error body → propagate the inner error verbatim."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    error_body = {"jsonrpc": "2.0", "error": {"code": -32601, "message": "method not found"}, "id": 1}
    client = _FakeHttpxClient(response=_FakeHttpResponse(500, json_body=error_body))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "sess"})  # pylint: disable=protected-access

    assert result == {"error": {"code": -32601, "message": "method not found"}}


@pytest.mark.asyncio
async def test_execute_forwarded_request_handles_non_dict_non_2xx_json_body():
    """A 500 response with a JSON LIST (not dict) still produces a wrapped JSON-RPC error."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    # JSON is a list, not a dict — triggers the `if not isinstance(response_data, dict): response_data = {}`
    # defensive path.
    client = _FakeHttpxClient(response=_FakeHttpResponse(500, json_body=["unexpected", "array", "body"], text_body="Unexpected JSON array"))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "s"})  # pylint: disable=protected-access

    assert "error" in result
    assert result["error"]["code"] == -32603
    assert "HTTP 500" in result["error"]["message"]


@pytest.mark.asyncio
async def test_execute_forwarded_request_handles_non_2xx_with_non_json_body():
    """A 500 response whose body is NOT valid JSON → wrapped error with truncated text fallback."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(response=_FakeHttpResponse(500, json_body=None, text_body="Internal Server Error HTML page"))

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        result = await affinity._execute_forwarded_request({"method": "tools/list", "params": {}, "headers": {}, "req_id": 1, "mcp_session_id": "s"})  # pylint: disable=protected-access

    assert "error" in result
    assert result["error"]["code"] == -32603
    assert "HTTP 500" in result["error"]["message"]


# ---------------------------------------------------------------------------
# _execute_forwarded_http_request — redis/channel missing guard + error-publish failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_forwarded_http_request_skips_publish_when_redis_is_none():
    """If redis is None, don't try to publish — just execute and return without logging an error."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    response = _FakeHttpResponse(200, text_body="ok")
    client = _FakeHttpxClient(response=response)

    request = {
        "response_channel": None,  # no channel → skip publish
        "method": "POST",
        "path": "/mcp",
        "headers": {},
        "body": "",
        "mcp_session_id": "sess-no-channel",
    }

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        # Should complete without raising and without a redis.publish call.
        await affinity._execute_forwarded_http_request(request, redis=None)  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_forward_request_to_owner_returns_none_when_reclaimed_key_vanishes():
    """Reclaim CAS lost AND the subsequent re-read shows the owner key gone → execute locally (None)."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()

    class _VanishingRedis(_FakeRedis):
        def __init__(self):
            super().__init__()
            self.store["mcpgw:pool_owner:sess-1"] = b"dead-worker"
            self.get_call_count = 0

        async def get(self, key):
            self.get_call_count += 1
            if key == "mcpgw:pool_owner:sess-1":
                if self.get_call_count == 1:
                    return b"dead-worker"
                # Key vanished between the CAS fail and the re-read.
                return None
            return self.store.get(key)

        async def eval(self, script, numkeys, *args):
            # Reclaim CAS always returns 0 (another worker reclaimed then lost + cleaned up).
            if len(args) == 4:
                self.eval_calls.append((script, args[:numkeys], args[numkeys:]))
                return 0
            return await super().eval(script, numkeys, *args)

    fake = _VanishingRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        mock_settings.mcpgateway_session_affinity_ttl = 300
        result = await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})
    assert result is None


@pytest.mark.asyncio
async def test_forward_request_to_owner_returns_none_when_reclaim_race_makes_us_owner():
    """Reclaim CAS lost, but the re-read shows we ended up as owner → execute locally."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity, WORKER_ID

    affinity = SessionAffinity()

    class _WeAreOwnerRedis(_FakeRedis):
        def __init__(self):
            super().__init__()
            self.store["mcpgw:pool_owner:sess-1"] = b"dead-worker"
            self.get_call_count = 0

        async def get(self, key):
            self.get_call_count += 1
            if key == "mcpgw:pool_owner:sess-1":
                if self.get_call_count == 1:
                    return b"dead-worker"
                # After losing the CAS, the re-read shows WE are now the owner (via concurrent claim).
                return WORKER_ID.encode()
            return self.store.get(key)

        async def eval(self, script, numkeys, *args):
            if len(args) == 4:
                self.eval_calls.append((script, args[:numkeys], args[numkeys:]))
                return 0
            return await super().eval(script, numkeys, *args)

    fake = _WeAreOwnerRedis()
    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake)),
    ):
        mock_settings.mcpgateway_session_affinity_enabled = True
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        mock_settings.mcpgateway_session_affinity_ttl = 300
        result = await affinity.forward_request_to_owner("sess-1", {"method": "tools/list"})
    assert result is None


@pytest.mark.asyncio
async def test_execute_forwarded_http_request_appends_query_string():
    """Query string from forwarded request is appended to the internal URL."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    fake = _FakeRedis()
    client = _FakeHttpxClient(response=_FakeHttpResponse(200, text_body="ok"))

    request = {
        "response_channel": "r",
        "method": "GET",
        "path": "/mcp",
        "query_string": "foo=bar&baz=qux",
        "headers": {},
        "body": "",
        "mcp_session_id": "sess-qs",
    }

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        await affinity._execute_forwarded_http_request(request, fake)  # pylint: disable=protected-access

    assert client.last_request_kwargs["url"] == "http://localhost:4444/mcp?foo=bar&baz=qux"  # type: ignore[index]


@pytest.mark.asyncio
async def test_execute_forwarded_http_request_logs_debug_when_error_publish_also_fails(caplog):
    """If the internal call fails AND the error-response publish also fails, swallow at debug."""
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    affinity = SessionAffinity()
    client = _FakeHttpxClient(raise_exc=RuntimeError("internal crash"))

    class _FailingPublishRedis:
        async def publish(self, *_a, **_k):
            raise RuntimeError("publish lost redis")

    request = {
        "response_channel": "resp-err",
        "method": "POST",
        "path": "/mcp",
        "headers": {},
        "body": "",
        "mcp_session_id": "sess-fail",
    }

    with (
        patch("mcpgateway.services.session_affinity.settings") as mock_settings,
        patch("mcpgateway.services.session_affinity.httpx.AsyncClient", return_value=client),
        patch("mcpgateway.services.session_affinity.internal_loopback_base_url", return_value="http://localhost:4444"),
        patch("mcpgateway.services.session_affinity.internal_loopback_verify", return_value=False),
        caplog.at_level("DEBUG", logger="mcpgateway.services.session_affinity"),
    ):
        mock_settings.mcpgateway_pool_rpc_forward_timeout = 5.0
        await affinity._execute_forwarded_http_request(request, _FailingPublishRedis())  # pylint: disable=protected-access

    assert any("Failed to publish error response" in rec.getMessage() for rec in caplog.records)


# --------------------------------------------------------------------------
# GET-stream listener claims (ADR-052)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_claim_first_wins_second_loses(monkeypatch):
    """Two GETs for the same session: first claim wins, second sees CONFLICT (ADR-052)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 30, raising=False)
    affinity = SessionAffinity()
    sid = "sess-listener-1"

    assert await affinity.claim_listener(sid, "conn-A") is ListenerClaimResult.WON
    assert await affinity.claim_listener(sid, "conn-B") is ListenerClaimResult.CONFLICT


@pytest.mark.asyncio
async def test_listener_heartbeat_refreshes_only_for_owner(monkeypatch):
    """Heartbeat must succeed for the holder and fail for any other connection."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 30, raising=False)
    affinity = SessionAffinity()
    sid = "sess-listener-2"

    await affinity.claim_listener(sid, "conn-owner")
    assert await affinity.heartbeat_listener(sid, "conn-owner") is True
    assert await affinity.heartbeat_listener(sid, "conn-intruder") is False


@pytest.mark.asyncio
async def test_listener_release_only_owner_then_new_can_claim(monkeypatch):
    """Release is owner-conditional; after release, a new connection can claim."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 30, raising=False)
    affinity = SessionAffinity()
    sid = "sess-listener-3"

    await affinity.claim_listener(sid, "conn-A")
    # Wrong connection-id can't release someone else's claim.
    assert await affinity.release_listener(sid, "conn-other") is False
    assert await affinity.claim_listener(sid, "conn-other") is ListenerClaimResult.CONFLICT
    # Owner releases successfully and a new claim can land.
    assert await affinity.release_listener(sid, "conn-A") is True
    assert await affinity.claim_listener(sid, "conn-B") is ListenerClaimResult.WON


@pytest.mark.asyncio
async def test_listener_claim_expires_with_ttl(monkeypatch):
    """An expired in-memory claim is reclaimable without explicit release."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 0, raising=False)
    affinity = SessionAffinity()
    sid = "sess-listener-4"

    assert await affinity.claim_listener(sid, "conn-old") is ListenerClaimResult.WON
    # ttl=0 → claim expires immediately on the next purge sweep.
    await asyncio.sleep(0.05)
    assert await affinity.claim_listener(sid, "conn-new") is ListenerClaimResult.WON


@pytest.mark.asyncio
async def test_listener_claim_concurrent_race_exactly_one_winner(monkeypatch):
    """Concurrent claim_listener calls on the same session: exactly one returns WON.

    Pins the in-memory backend's ``asyncio.Lock`` contract — accidentally
    removing the lock would only break under load, which a sequential test
    would never catch.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 30, raising=False)
    affinity = SessionAffinity()
    sid = "sess-race"

    results = await asyncio.gather(
        affinity.claim_listener(sid, "conn-A"),
        affinity.claim_listener(sid, "conn-B"),
        affinity.claim_listener(sid, "conn-C"),
    )
    won = [r for r in results if r is ListenerClaimResult.WON]
    conflict = [r for r in results if r is ListenerClaimResult.CONFLICT]
    assert len(won) == 1, f"expected exactly one WON, got {results}"
    assert len(conflict) == 2, f"expected two CONFLICT, got {results}"


@pytest.mark.asyncio
async def test_listener_claim_invalid_session_id_rejected(monkeypatch):
    """Malformed session ids return UNAVAILABLE (defence-in-depth — caller shouldn't 409 a bad input)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "memory", raising=False)
    affinity = SessionAffinity()

    assert await affinity.claim_listener("bad/id!", "conn-X") is ListenerClaimResult.UNAVAILABLE
    assert await affinity.heartbeat_listener("bad/id!", "conn-X") is False
    assert await affinity.release_listener("bad/id!", "conn-X") is False


def test_log_redis_listener_error_classifies_by_exception_type(caplog):
    """Operator-facing log levels: transient/config/unknown classification matrix.

    The classifier is the operator's only signal during a Redis incident
    — a regression that conflated config errors with transient blips
    would quietly mute the warning needed to spot credential rotations
    or Lua script drift.
    """
    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity  # pylint: disable=import-outside-toplevel

    pytest.importorskip("redis")
    # Third-Party
    from redis import exceptions as redis_exc  # pylint: disable=import-outside-toplevel

    sid = "sess-classify"

    # Transient errors stay at debug — should NOT appear in WARNING capture.
    with caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"):
        SessionAffinity._log_redis_listener_error("claim", sid, redis_exc.ConnectionError("conn refused"))
        SessionAffinity._log_redis_listener_error("heartbeat", sid, redis_exc.TimeoutError("redis timeout"))
    assert "ConnectionError" not in caplog.text
    assert "TimeoutError" not in caplog.text
    caplog.clear()

    # Config / protocol errors escalate to warning.
    with caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"):
        SessionAffinity._log_redis_listener_error("claim", sid, redis_exc.AuthenticationError("invalid creds"))
        SessionAffinity._log_redis_listener_error("release", sid, redis_exc.ResponseError("WRONGTYPE"))
        SessionAffinity._log_redis_listener_error("heartbeat", sid, redis_exc.NoScriptError("script unknown"))
    assert "AuthenticationError" in caplog.text
    assert "ResponseError" in caplog.text
    assert "NoScriptError" in caplog.text
    caplog.clear()

    # Unknown / programming errors get warning + traceback.
    with caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"):
        SessionAffinity._log_redis_listener_error("claim", sid, OSError("unexpected"))
    assert "OSError" in caplog.text or "unexpected" in caplog.text


# --------------------------------------------------------------------------
# Redis-backed listener-claim coverage. The earlier listener-claim tests
# all use cache_type=memory; the Redis branches (the authoritative
# multi-node path) had zero coverage. Stub out get_redis_client so we
# exercise the SET-NX / Lua-eval call shapes without a real Redis.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listener_claim_redis_won_when_set_nx_returns_true(monkeypatch):
    """Redis SET NX returning truthy → WON."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)
    monkeypatch.setattr(settings, "mcp_get_stream_listener_ttl_seconds", 30, raising=False)

    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.claim_listener("sess-x", "conn-1") is ListenerClaimResult.WON
    fake_redis.set.assert_awaited_once()
    args, kwargs = fake_redis.set.call_args
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 30


@pytest.mark.asyncio
async def test_listener_claim_redis_conflict_when_set_nx_returns_false(monkeypatch):
    """Redis SET NX returning falsy → CONFLICT (slot already held)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=None)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.claim_listener("sess-y", "conn-2") is ListenerClaimResult.CONFLICT


@pytest.mark.asyncio
async def test_listener_claim_redis_unavailable_when_client_missing(monkeypatch):
    """``cache_type=redis`` but ``get_redis_client`` returns None → UNAVAILABLE."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))

    affinity = SessionAffinity()
    assert await affinity.claim_listener("sess-z", "conn-3") is ListenerClaimResult.UNAVAILABLE


@pytest.mark.asyncio
async def test_listener_claim_redis_unavailable_when_set_raises(monkeypatch):
    """Any exception from ``redis.set`` → UNAVAILABLE (NOT CONFLICT). Critical: 503 vs 409 split."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import ListenerClaimResult, SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.claim_listener("sess-q", "conn-4") is ListenerClaimResult.UNAVAILABLE


@pytest.mark.asyncio
async def test_listener_heartbeat_redis_eval_round_trips(monkeypatch):
    """Redis heartbeat eval returning 1 → True (still owner); 0 → False (lost)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.eval = AsyncMock(return_value=1)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.heartbeat_listener("sess-h", "conn-1") is True

    fake_redis.eval = AsyncMock(return_value=0)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))
    assert await affinity.heartbeat_listener("sess-h", "conn-1") is False


@pytest.mark.asyncio
async def test_listener_heartbeat_redis_returns_false_on_exception(monkeypatch):
    """A heartbeat that raises returns False (caller closes the stream)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.eval = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.heartbeat_listener("sess-h", "conn-1") is False


@pytest.mark.asyncio
async def test_listener_release_redis_eval_round_trips(monkeypatch):
    """Redis release eval returning 1 → True (released); 0 → False (not owner)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.eval = AsyncMock(return_value=1)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.release_listener("sess-r", "conn-1") is True

    fake_redis.eval = AsyncMock(return_value=0)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))
    assert await affinity.release_listener("sess-r", "conn-1") is False


@pytest.mark.asyncio
async def test_listener_release_redis_returns_false_on_exception(monkeypatch):
    """A release that raises returns False (best-effort cleanup)."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)

    fake_redis = MagicMock()
    fake_redis.eval = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=fake_redis))

    affinity = SessionAffinity()
    assert await affinity.release_listener("sess-r", "conn-1") is False


@pytest.mark.asyncio
async def test_listener_heartbeat_returns_false_when_redis_client_none(monkeypatch):
    """``get_redis_client`` returning ``None`` short-circuits heartbeat to False."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))

    affinity = SessionAffinity()
    assert await affinity.heartbeat_listener("sess-none", "conn-1") is False


@pytest.mark.asyncio
async def test_listener_release_returns_false_when_redis_client_none(monkeypatch):
    """``get_redis_client`` returning ``None`` short-circuits release to False."""
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services.session_affinity import SessionAffinity

    monkeypatch.setattr(settings, "cache_type", "redis", raising=False)
    monkeypatch.setattr("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None))

    affinity = SessionAffinity()
    assert await affinity.release_listener("sess-none", "conn-1") is False


def test_log_redis_listener_error_falls_back_when_redis_module_absent(monkeypatch, caplog):
    """If the ``redis`` package is not importable, fall back to a plain warning.

    This branch fires only on a degraded install where redis-py was removed
    but cache_type=redis was left configured — an operator-visible edge case
    that still needs to surface the original exception.
    """
    # Standard
    import builtins
    import sys

    # First-Party
    from mcpgateway.services.session_affinity import SessionAffinity

    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "redis" and fromlist and "exceptions" in fromlist:
            raise ImportError("redis not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setattr(builtins, "__import__", blocked_import)

    sid = "sess-noredis"
    with caplog.at_level("WARNING", logger="mcpgateway.services.session_affinity"):
        SessionAffinity._log_redis_listener_error("claim", sid, RuntimeError("boom"))
    assert "Listener-claim" in caplog.text
    assert sid in caplog.text
