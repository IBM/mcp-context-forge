# -*- coding: utf-8 -*-
"""Integration tests for Alembic bootstrap under transaction-pool PgBouncer.

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

    - **For the end-to-end compose test only**: a built local gateway image
      (``mcpgateway/mcpgateway:latest`` — produced by ``make docker``) AND
      ``MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E=1`` to opt into the destructive
      path. Without the env var the e2e test skips with a clear message.

Usage:
    uv run pytest tests/integration/test_migrations_under_transaction_pool.py -v --with-integration

    # Including the destructive end-to-end test:
    MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E=1 uv run pytest \\
        tests/integration/test_migrations_under_transaction_pool.py -v --with-integration
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
    "postgresql://postgres:reprosecret@localhost:64320/mcp",  # pragma: allowlist secret
)
POSTGRES_URL = os.environ.get(
    "POSTGRES_URL",
    "postgresql://postgres:reprosecret@localhost:54320/mcp",  # pragma: allowlist secret
)

# Any 64-bit int works; we use the same sentinel as bootstrap_db so an
# operator inspecting pg_locks sees the familiar value.
LOCK_ID = 42_424_242_424_242


def _as_sqlalchemy_url(url: str) -> str:
    """Add SQLAlchemy's ``+psycopg`` driver hint.

    The ``PGBOUNCER_URL`` / ``POSTGRES_URL`` env vars are written in plain
    ``postgresql://`` form so that ``psycopg.connect()`` accepts them
    directly. SQLAlchemy's default Postgres dialect tries to import
    ``psycopg2`` — not installed in this project — so we tell it to use
    psycopg3 explicitly when feeding a URL into ``create_engine()``.
    """
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


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

    The pgbouncer client is gone by the time we check, but Postgres still
    shows the lock as held by the (now orphaned) server-side session.
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
        row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()
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
        row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()
        assert row is not None
        acquired_via_bouncer = bool(row[0])

        # The pgbouncer client's view (reentrant) differs from a fresh
        # direct session's view (blocked) — that divergence is what makes
        # the bug hard to debug.
        with psycopg.connect(POSTGRES_URL, autocommit=True) as direct:
            row = direct.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()
            assert row is not None
            acquired_direct = bool(row[0])

    assert acquired_via_bouncer, (
        "Expected same-backend reentrance via pgbouncer to succeed. If this "
        "fails, pgbouncer may not be reusing the same server backend for a "
        "sequential client — check DEFAULT_POOL_SIZE in "
        "tests/integration/fixtures/transaction_pool/docker-compose.yml."
    )
    assert not acquired_direct, "A fresh direct session must still be blocked — otherwise the " "orphaning invariant from the previous test no longer holds."


# ---------------------------------------------------------------------------
# Invariant test — the regression gate for the multi-replica advisory-lock
# hang. Red without the fast-path probe (bootstrap_db always takes the
# advisory-lock path, blocks on the orphan, exhausts retries). Green once
# the "schema already at head" fast-path skip is in place.
# ---------------------------------------------------------------------------


def _drop_public_schema() -> None:
    """Reset the test database to an empty state."""
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def _hold_advisory_lock_in_separate_session(lock_id: int):
    """Open a direct (non-pgbouncer) Postgres session, take ``lock_id``, and
    return the connection so the caller can close it when done.

    Using a direct connection — rather than taking the lock through pgbouncer
    and disconnecting — guarantees the holder's Postgres session is distinct
    from whatever backend pgbouncer hands to a subsequent client. Without
    that guarantee, pgbouncer may assign the same backend twice and
    pg_try_advisory_lock succeeds via PostgreSQL's reentrant-within-session
    semantics (see test_reentrant_acquire_through_same_pgbouncer_is_not_a_
    counter_example), masking the hang this test is trying to catch.
    """
    holder = psycopg.connect(POSTGRES_URL, autocommit=True)
    holder.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
    return holder


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_bootstrap_db_skips_lock_when_schema_already_at_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bootstrap_db.main()`` must complete quickly when the schema is at
    head, even if the migration advisory lock is held by another session.

    In production the "other session" is an orphaned server backend whose
    pgbouncer client disconnected without DISCARD ALL clearing the lock.
    We synthesize the same condition more reliably by
    holding the lock in a distinct, still-alive Postgres session — that
    way pg_try_advisory_lock from bootstrap's pgbouncer-facing session
    must return FALSE regardless of which server backend pgbouncer hands
    us.

    Pre-fix: bootstrap_db always enters the advisory-lock retry loop; it
    sees the lock as held, spins for ~10 minutes, then raises TimeoutError.
    (pytest.mark.timeout cuts us off at 240s.)

    Post-fix: the fast-path short-circuits on ``alembic_version == head``
    before any lock is attempted; the second bootstrap completes in under
    a second.
    """
    # Standard
    import asyncio
    import time

    # First-Party (deferred so import-time failures inside mcpgateway don't
    # break collection for this module).
    from mcpgateway import config as mcp_config  # pylint: disable=import-outside-toplevel
    from mcpgateway.bootstrap_db import main as bootstrap_db  # pylint: disable=import-outside-toplevel

    # --- Preconditions ----------------------------------------------------
    _drop_public_schema()

    # Point the gateway's ORM at pgbouncer (transaction pool). tests/conftest.py
    # normally forces DATABASE_URL to in-memory SQLite; overriding the live
    # settings object is enough — bootstrap_db reads settings.database_url at
    # call time. SQLAlchemy needs the +psycopg driver hint so it doesn't try
    # to import psycopg2 (not installed in this project).
    monkeypatch.setattr(
        mcp_config.settings,
        "database_url",
        _as_sqlalchemy_url(PGBOUNCER_URL),
    )
    monkeypatch.setattr(mcp_config.settings, "email_auth_enabled", False)

    # First bootstrap seeds the schema and stamps alembic_version to head.
    # This is the "replica 1 wins the race" moment in production.
    asyncio.run(bootstrap_db())

    # --- Synthesize the held-lock precondition ---------------------------
    # Reuse the module-level LOCK_ID — same sentinel ``advisory_lock()`` in
    # bootstrap_db uses, so the orphan we synthesise here is the one
    # production would actually contend on.
    holder = _hold_advisory_lock_in_separate_session(LOCK_ID)
    try:
        assert _count_advisory_locks_held(LOCK_ID) == 1, "Test setup failed: expected the advisory lock to be held by the " "holder session before running the second bootstrap."

        # --- The invariant -----------------------------------------------
        # Post-fix: fast-path skips the lock entirely; completes in ms.
        # Pre-fix: advisory_lock retry loop sees FALSE, spins for minutes.
        start = time.monotonic()
        asyncio.run(bootstrap_db())
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, (
            f"bootstrap_db.main() took {elapsed:.1f}s with the schema at head "
            f"and the migration advisory lock held by another session. "
            f"Expected < 10s via the fast-path skip. This is the regression "
            f"gate for the advisory-lock hang on multi-replica startup behind "
            f"transaction-pool PgBouncer."
        )
    finally:
        holder.close()


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_bootstrap_db_is_idempotent_once_schema_is_at_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second ``bootstrap_db.main()`` call must not touch ``advisory_lock``.

    The first invocation populates the schema and stamps ``alembic_version``.
    The second should recognise the DB is at head and take the fast-path
    exclusively — never entering the ``advisory_lock`` context manager at
    all. Pins the fast-path wiring against regressions that would re-route
    bootstrap through the lock even when no schema work is needed.
    """
    # Standard
    import asyncio
    import time
    from contextlib import contextmanager

    # First-Party
    from mcpgateway import bootstrap_db as bootstrap_module  # pylint: disable=import-outside-toplevel
    from mcpgateway import config as mcp_config  # pylint: disable=import-outside-toplevel

    _drop_public_schema()

    monkeypatch.setattr(
        mcp_config.settings,
        "database_url",
        _as_sqlalchemy_url(PGBOUNCER_URL),
    )
    monkeypatch.setattr(mcp_config.settings, "email_auth_enabled", False)

    # First call: real advisory_lock (slow path on empty DB is expected).
    asyncio.run(bootstrap_module.main())

    # Install a spy that wraps the real advisory_lock so we can assert
    # whether the second call entered it. We keep the wrapped behavior
    # (rather than replacing with a no-op) so that if the spy IS hit, the
    # test can still tear down cleanly.
    advisory_lock_entries: list[object] = []
    original_advisory_lock = bootstrap_module.advisory_lock

    @contextmanager
    def spy_advisory_lock(conn: object):
        advisory_lock_entries.append(conn)
        with original_advisory_lock(conn):  # type: ignore[arg-type]
            yield

    monkeypatch.setattr(bootstrap_module, "advisory_lock", spy_advisory_lock)

    # Second call: schema is at head, fast-path should fire exclusively.
    start = time.monotonic()
    asyncio.run(bootstrap_module.main())
    elapsed = time.monotonic() - start

    assert advisory_lock_entries == [], (
        f"bootstrap_db.main() entered advisory_lock {len(advisory_lock_entries)} "
        f"time(s) on the second invocation, when the schema was already at head. "
        f"Expected zero entries via the fast-path. A regression here would "
        f"reintroduce the multi-replica hang behind transaction-pool poolers."
    )

    assert elapsed < 3.0, (
        f"Second bootstrap_db.main() took {elapsed:.1f}s; expected < 3s via the "
        f"fast-path. Either the probe connection or the post-migration bootstrap "
        f"has acquired hidden cost — investigate before relaxing this threshold."
    )

    assert _count_advisory_locks_held(LOCK_ID) == 0, "Fast-path must not leave any advisory locks held after bootstrap_db " "completes."


# ---------------------------------------------------------------------------
# End-to-end compose smoke — the closest re-runnable proxy for an OpenShift
# cluster smoke (3 gateway replicas through CrunchyData PGO + transaction-
# pool PgBouncer). Drives the fixture compose stack at the container level
# rather than calling bootstrap_db.main() in-process.
#
# Destructive: drops the fixture's `public` schema. Gated behind an explicit
# env-var opt-in (MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E=1) so a contributor
# who happens to have an unrelated Postgres on localhost cannot trip it
# accidentally.
# ---------------------------------------------------------------------------


_FIXTURE_COMPOSE = "tests/integration/fixtures/transaction_pool/docker-compose.yml"
_GATEWAY_IMAGE = "mcpgateway/mcpgateway:latest"


def _docker_compose_args() -> list[str]:
    """Absolute-path compose invocation that works regardless of cwd."""
    # Standard
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    repo_root = Path(__file__).resolve().parents[2]
    return ["docker", "compose", "-f", str(repo_root / _FIXTURE_COMPOSE)]


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_compose_three_replicas_complete_bootstrap_e2e():
    """End-to-end: scale fixture's gateway service to 3 replicas; assert all
    reach bootstrap completion within 60s.

    This drives the FULL pod-startup path (gunicorn + lifespan +
    bootstrap_db.main() inside real containers) against the same
    transaction-pool PgBouncer the rest of this module uses. It is the
    closest re-runnable analog of an OpenShift cluster smoke (3 gateway
    replicas through CrunchyData PGO + transaction-pool PgBouncer).

    Pre-fix (no fast-path probe): replica gunicorn workers race for the
    advisory lock, get orphaned by PgBouncer's backend handoffs, and
    spin in their retry loop. ``pytest.mark.timeout(240)`` fires before
    the 60s polling deadline can complete.

    Post-fix: one worker wins the seed race (slow path), the rest see
    ``alembic_version`` at head and fast-path past the lock. All 3
    replicas emit a bootstrap-completion log line within ~15-30s.

    Destructive — drops the fixture's ``public`` schema. Skipped unless
    ``MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E=1`` is set.
    """
    # Standard
    import re  # pylint: disable=import-outside-toplevel
    import shutil  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel
    import time  # pylint: disable=import-outside-toplevel

    # --- Skip-checks -----------------------------------------------------

    if os.environ.get("MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E") != "1":
        pytest.skip(
            "[regression-gate] End-to-end multi-replica bootstrap test for "
            "issue #4051 — exercises the full pod-startup path (gunicorn "
            "lifespan + bootstrap_db.main() inside real containers) against "
            "transaction-pool PgBouncer. NOT run in CI (cost: image build + "
            "3-replica compose + ~60s polling). Run locally before signing "
            "off on changes to bootstrap_db or chart probe wiring:\n"
            "  1. make docker          # builds mcpgateway/mcpgateway:latest\n"
            "  2. MCPGATEWAY_TEST_ALLOW_DESTRUCTIVE_E2E=1 uv run pytest "
            "tests/integration/test_migrations_under_transaction_pool.py "
            "--with-integration\n"
            "Destructive: drops the fixture stack's `public` schema."
        )

    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH; cannot run compose-driven e2e test")

    image_check = subprocess.run(
        ["docker", "image", "inspect", _GATEWAY_IMAGE],
        capture_output=True,
        check=False,
    )
    if image_check.returncode != 0:
        pytest.skip(f"Local gateway image {_GATEWAY_IMAGE!r} not present — run " "`make docker` first to enable this test.")

    compose = _docker_compose_args()

    # Probe the fixture's postgres+pgbouncer health. If the user hasn't
    # brought the stack up yet, fail soft with the exact command to fix it.
    pgcheck = subprocess.run(
        compose + ["ps", "--services", "--filter", "status=running"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    running_services = set(pgcheck.stdout.split())
    if not {"postgres", "pgbouncer"}.issubset(running_services):
        pytest.skip("Fixture stack not running. Bring it up first with:\n" "  docker compose -f tests/integration/fixtures/transaction_pool/" "docker-compose.yml up -d postgres pgbouncer")

    # --- Paranoia check: confirm we're talking to the FIXTURE's postgres,
    # not someone's prod DB that happens to be on the same port. ----------
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        row = conn.execute("SELECT current_database()").fetchone()
        assert row is not None and row[0] == "mcp", (
            f"Refusing to run destructive e2e test: connected database is " f"{row[0]!r}, expected 'mcp' (the fixture's database name). " f"POSTGRES_URL appears to be pointing at the wrong server."
        )

    # --- Reset state -----------------------------------------------------

    _drop_public_schema()

    # Scale the gateway service to 0 first so we get clean container names
    # and timing. --no-recreate keeps postgres/pgbouncer running for any
    # subsequent tests.
    subprocess.run(
        compose + ["up", "-d", "--scale", "gateway=0", "--no-recreate", "gateway"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    try:
        # --- Trigger the race ------------------------------------------------

        subprocess.run(
            compose + ["up", "-d", "--scale", "gateway=3", "--no-recreate", "gateway"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # --- Poll for completion --------------------------------------------
        # Match either log line that signals a worker finished bootstrap:
        #   · "Database ready"                       (slow-path winner)
        #   · "Schema already at Alembic head"       (L1 fast-path skip)
        # Either way, count UNIQUE container hostnames so we measure
        # pod-level coverage, not per-worker noise.
        completion_pattern = re.compile(r'"name":\s*"mcpgateway\.bootstrap_db".*' r'"message":\s*"(?:Database ready|Schema already at Alembic head)')
        hostname_pattern = re.compile(r'"hostname":\s*"([^"]+)"')

        deadline = time.monotonic() + 60.0
        successful_hostnames: set[str] = set()
        while time.monotonic() < deadline:
            logs = subprocess.run(
                compose + ["logs", "--no-log-prefix", "gateway"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            for line in logs.stdout.splitlines():
                if completion_pattern.search(line):
                    match = hostname_pattern.search(line)
                    if match:
                        successful_hostnames.add(match.group(1))
            if len(successful_hostnames) >= 3:
                break
            time.sleep(2.0)

        if len(successful_hostnames) < 3:
            tail = subprocess.run(
                compose + ["logs", "--tail=80", "gateway"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            ).stdout
            pytest.fail(
                f"Only {len(successful_hostnames)}/3 gateway replicas reached "
                f"bootstrap completion within 60s. Distinct hostnames seen: "
                f"{sorted(successful_hostnames)!r}.\n\nRecent logs:\n{tail}"
            )
    finally:
        # --- Always: scale gateway back to 0 (leave pg+pgbouncer up) ----
        subprocess.run(
            compose + ["up", "-d", "--scale", "gateway=0", "--no-recreate", "gateway"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
