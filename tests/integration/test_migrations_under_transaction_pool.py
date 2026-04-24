# -*- coding: utf-8 -*-
"""Integration test documenting the mechanism behind issue #4051.

PgBouncer in ``pool_mode=transaction`` shares one Postgres server backend
across many pgbouncer "client" connections. Session-scoped Postgres advisory
locks (``pg_advisory_lock``) live on the server backend, not on the pgbouncer
client connection — so when a client disconnects, the server backend goes
back into pgbouncer's pool *with the lock still held*. A subsequent client
that happens to land on a different backend cannot take the same lock: from
Postgres's point of view, the lock is held by the orphaned session.

That is the mechanism that makes ``mcpgateway.bootstrap_db.main()`` hang
when multiple gateway replicas start concurrently behind a transaction-
pooling PgBouncer: N replicas race for ``pg_try_advisory_lock``, one wins,
another client reuses that server backend mid-upgrade, and the remaining
replicas then spin against an orphaned lock until the retry loop gives up.

This module pins the mechanism as a first-class fact so future refactors
to ``bootstrap_db.py`` can be validated against the same known-bad
substrate.

This test documents the PgBouncer mechanism and should keep passing even
after the fix lands — the fix works *around* this behavior, it does not
eliminate it.

Requirements:
    - Reproduction stack running:

        docker compose -f tests/integration/fixtures/transaction_pool/docker-compose.yml \\
            up -d postgres pgbouncer

    - ``PGBOUNCER_URL`` / ``POSTGRES_URL`` point at that stack (defaults match
      the ports exposed in the fixture compose file).

Usage:
    uv run pytest tests/integration/test_migrations_under_transaction_pool.py -v --with-integration
"""

# Standard
import os

# Third-Party
import pytest

psycopg = pytest.importorskip("psycopg")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PGBOUNCER_URL = os.environ.get(
    "PGBOUNCER_URL",
    "postgresql://postgres:reprosecret@localhost:64320/mcp",
)
POSTGRES_URL = os.environ.get(
    "POSTGRES_URL",
    "postgresql://postgres:reprosecret@localhost:54320/mcp",
)

# Any 64-bit int works; we use the same sentinel as bootstrap_db so an
# operator inspecting pg_locks sees the familiar value.
LOCK_ID = 42_424_242_424_242


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acquire_lock_via_pgbouncer_and_disconnect(lock_id: int) -> None:
    """Open one pgbouncer connection, take an advisory lock, close the connection.

    The connection is closed by ``with`` unwind; the server backend goes back
    into pgbouncer's pool with the lock still held at the Postgres level.
    """
    with psycopg.connect(PGBOUNCER_URL, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (lock_id,))


def _count_advisory_locks_held(lock_id: int) -> int:
    """Return the number of advisory locks matching ``lock_id`` currently held.

    ``pg_locks.classid`` and ``pg_locks.objid`` are 32-bit OIDs; a 64-bit
    advisory lock ID is split across them (high 32 bits → classid, low 32
    bits → objid). We reconstruct the 64-bit ID in SQL to filter precisely.
    """
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT count(*)
            FROM pg_locks
            WHERE locktype = 'advisory'
              AND granted
              AND ((classid::bigint << 32) | objid::bigint) = %s
            """,
            (lock_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _release_any_lingering_lock(lock_id: int) -> None:
    """Kill the Postgres session that still holds the test's advisory lock.

    Run as a fixture teardown so one failed test does not wedge the next
    one behind the same orphan. ``pg_terminate_backend`` releases session-
    scoped advisory locks as a side effect.
    """
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_locks
            WHERE locktype = 'advisory'
              AND ((classid::bigint << 32) | objid::bigint) = %s
            """,
            (lock_id,),
        )


@pytest.fixture(autouse=True)
def _clean_orphaned_lock():  # noqa: PT004 - autouse teardown, no return value
    """Ensure we start and end each test with no lingering advisory lock."""
    _release_any_lingering_lock(LOCK_ID)
    yield
    _release_any_lingering_lock(LOCK_ID)


# Pyright cannot see pytest's autouse wiring; assert at import time that the
# fixture is present so a future refactor can't silently drop the teardown.
assert callable(_clean_orphaned_lock)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_session_advisory_lock_persists_across_pgbouncer_client_disconnect():
    """A client disconnect through PgBouncer does NOT release its advisory lock.

    Mirrors step 1 → step 2 of ``demonstrate_orphan.sh``. The pgbouncer
    client is gone by the time we check, but Postgres still shows the lock
    as held by the (now orphaned) server-side session.
    """
    _acquire_lock_via_pgbouncer_and_disconnect(LOCK_ID)

    held = _count_advisory_locks_held(LOCK_ID)

    assert held == 1, (
        "Expected the advisory lock to still be held on Postgres after the "
        "pgbouncer client disconnected (this is the orphaning that makes "
        "bootstrap_db hang). Found %d held locks for id=%d." % (held, LOCK_ID)
    )


@pytest.mark.integration
def test_orphaned_lock_blocks_a_fresh_postgres_session():
    """A fresh Postgres session cannot acquire the orphaned lock.

    This is the assertion that maps directly to the bug symptom: the N-th
    gateway replica's Alembic bootstrap sees ``pg_try_advisory_lock`` return
    FALSE and spins in its retry loop until it times out.
    """
    _acquire_lock_via_pgbouncer_and_disconnect(LOCK_ID)

    # Fresh direct-to-postgres connection = guaranteed distinct session.
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)
        ).fetchone()
        assert row is not None
        acquired = bool(row[0])

    assert not acquired, (
        "Expected pg_try_advisory_lock to return FALSE from a fresh session "
        "because the lock is held by the orphaned backend. Got TRUE — either "
        "pgbouncer is not configured with pool_mode=transaction, or "
        "server_reset_query is clearing advisory locks between clients. "
        "Check tests/integration/fixtures/transaction_pool/docker-compose.yml."
    )


@pytest.mark.integration
def test_reentrant_acquire_through_same_pgbouncer_is_not_a_counter_example():
    """Same-session reentrance explains the 'sometimes it works' confusion.

    When a subsequent pgbouncer client happens to land on the *same* server
    backend that still holds the lock, ``pg_try_advisory_lock`` returns TRUE
    because Postgres advisory locks are reentrant within a session.

    This is not contradictory evidence: it's why the bug is intermittent
    under load, and why our repro had to pin pool sizing to force a handoff.
    This test exists so a future reader who reruns ``pg_try_advisory_lock``
    via pgbouncer and sees TRUE does not conclude "no bug". With
    ``DEFAULT_POOL_SIZE=2`` (our repro config) and only one client active,
    the second pgbouncer connection will reuse the same backend.
    """
    _acquire_lock_via_pgbouncer_and_disconnect(LOCK_ID)

    with psycopg.connect(PGBOUNCER_URL, autocommit=True) as conn:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)
        ).fetchone()
        assert row is not None
        acquired_via_bouncer = bool(row[0])

        # The pgbouncer client's view (reentrant) differs from a fresh
        # direct session's view (blocked) — that divergence is what makes
        # the bug hard to debug.
        with psycopg.connect(POSTGRES_URL, autocommit=True) as direct:
            row = direct.execute(
                "SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)
            ).fetchone()
            assert row is not None
            acquired_direct = bool(row[0])

    assert acquired_via_bouncer, (
        "Expected same-backend reentrance via pgbouncer to succeed. If this "
        "fails, pgbouncer may not be reusing the same server backend for a "
        "sequential client — check DEFAULT_POOL_SIZE in "
        "tests/integration/fixtures/transaction_pool/docker-compose.yml."
    )
    assert not acquired_direct, (
        "A fresh direct session must still be blocked — otherwise the "
        "orphaning invariant from the previous test no longer holds."
    )
