#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify advisory lock behaviour in aggregate_all_components (issue #2692).

Four scenarios are exercised:

  1. SQLite (dev) path      — lock helpers are no-ops; all workers proceed
  2. PostgreSQL simulation  — threading.Lock simulates pg_try_advisory_lock;
                              exactly one worker runs, the rest are skipped
  3. Lock helpers unit      — _try/_release execute no SQL on SQLite
  4. Caller-provided db=    — lock is never attempted (backfill / log_search)

Design notes:
  - All patches applied at test level (outside threads) to avoid concurrent
    patch teardown races.
  - Test 2 uses an Event to hold the lock until every worker has attempted to
    acquire it, preventing the lock holder from releasing early when mocked
    aggregation completes instantly.

Run from the repo root:
    uv run python scripts/test_advisory_lock.py
"""

# Standard
import logging
import sys
import threading
from unittest.mock import MagicMock, patch

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(threadName)-10s] %(levelname)-5s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# First-Party
from mcpgateway.services.log_aggregator import (  # noqa: E402
    LogAggregator,
    _release_aggregate_pg_lock,
    _try_aggregate_pg_lock,
)

# ── helpers ────────────────────────────────────────────────────────────────────

PASS = "\033[32m✓ PASS\033[0m"
FAIL = "\033[31m✗ FAIL\033[0m"


def _make_mock_db(pairs=None):
    db = MagicMock()
    db.execute.return_value.all.return_value = pairs or []
    return db


# ── test 1: SQLite path ────────────────────────────────────────────────────────

def test_sqlite_all_workers_run() -> bool:
    """On SQLite _is_postgresql() is False — lock bypassed, all workers proceed."""
    print("\n" + "─" * 60)
    print("TEST 1: SQLite path — all workers should run (lock bypassed)")
    print("─" * 60)

    num_workers = 5
    _lock = threading.Lock()
    thread_dbs: dict = {}  # tid -> mock_db
    thread_to_worker: dict = {}  # tid -> worker index

    def make_session():
        db = _make_mock_db()
        with _lock:
            thread_dbs[threading.get_ident()] = db
        return db

    barrier = threading.Barrier(num_workers)

    def worker(i):
        with _lock:
            thread_to_worker[threading.get_ident()] = i
        barrier.wait()
        LogAggregator().aggregate_all_components(db=None)

    with patch("mcpgateway.services.log_aggregator.SessionLocal", side_effect=make_session):
        threads = [threading.Thread(target=worker, args=(i,), name=f"Worker-{i}") for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    outcomes = {
        thread_to_worker[tid]: ("ran" if db.execute.called else "skipped")
        for tid, db in thread_dbs.items()
    }

    ran = sum(1 for v in outcomes.values() if v == "ran")
    skipped = sum(1 for v in outcomes.values() if v == "skipped")

    print(f"  Outcomes : {outcomes}")
    print(f"  Ran      : {ran}/{num_workers}")
    print(f"  Skipped  : {skipped}/{num_workers}")

    ok = ran == num_workers and skipped == 0
    print(f"  {PASS if ok else FAIL}: {'all workers ran on SQLite' if ok else f'expected {num_workers} ran, got {ran}'}")
    return ok


# ── test 2: PostgreSQL simulation ──────────────────────────────────────────────

def test_postgresql_only_one_worker_runs() -> bool:
    """Simulate pg_try_advisory_lock with a threading.Lock.

    The lock holder waits (via all_attempted Event) until every worker has
    called fake_try_lock before releasing. This prevents the holder from
    releasing early when mocked aggregation completes instantly — which would
    let a second worker acquire the lock and cause a spurious failure.
    """
    print("\n" + "─" * 60)
    print("TEST 2: PostgreSQL simulation — exactly one worker should run")
    print("─" * 60)

    num_workers = 5
    _pg_lock = threading.Lock()

    # Signals that all num_workers threads have called fake_try_lock.
    all_attempted = threading.Event()
    attempt_count = [0]
    attempt_count_lock = threading.Lock()

    # tid -> bool: did this thread acquire the lock?
    lock_results: dict = {}

    def fake_try_lock(db):
        tid = threading.get_ident()
        acquired = _pg_lock.acquire(blocking=False)
        lock_results[tid] = acquired
        logger.debug("pg_try_advisory_lock → %s", acquired)
        with attempt_count_lock:
            attempt_count[0] += 1
            if attempt_count[0] == num_workers:
                all_attempted.set()
        return acquired

    def fake_release_lock(db):
        # Hold until every worker has tried to acquire — prevents early release
        # in fast mock environments where aggregation completes in microseconds.
        all_attempted.wait(timeout=10.0)
        try:
            _pg_lock.release()
            logger.debug("pg_advisory_unlock → released")
        except RuntimeError:
            pass

    barrier = threading.Barrier(num_workers)
    thread_to_worker: dict = {}
    thread_to_worker_lock = threading.Lock()

    def worker(i):
        with thread_to_worker_lock:
            thread_to_worker[threading.get_ident()] = i
        barrier.wait()
        LogAggregator().aggregate_all_components(db=None)

    with patch("mcpgateway.services.log_aggregator.SessionLocal", side_effect=_make_mock_db), \
         patch("mcpgateway.services.log_aggregator._try_aggregate_pg_lock", side_effect=fake_try_lock), \
         patch("mcpgateway.services.log_aggregator._release_aggregate_pg_lock", side_effect=fake_release_lock):
        threads = [threading.Thread(target=worker, args=(i,), name=f"Worker-{i}") for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    outcomes = {
        thread_to_worker[tid]: ("ran" if acquired else "skipped")
        for tid, acquired in lock_results.items()
    }

    ran = sum(1 for v in outcomes.values() if v == "ran")
    skipped = sum(1 for v in outcomes.values() if v == "skipped")

    print(f"  Outcomes : {outcomes}")
    print(f"  Ran      : {ran}/{num_workers}")
    print(f"  Skipped  : {skipped}/{num_workers}")

    ok = ran == 1 and skipped == num_workers - 1
    print(f"  {PASS if ok else FAIL}: {'one ran, rest skipped' if ok else f'expected 1 ran / {num_workers - 1} skipped, got {ran} / {skipped}'}")
    return ok


# ── test 3: lock helper unit checks ───────────────────────────────────────────

def test_lock_helpers_sqlite_noop() -> bool:
    """_try_aggregate_pg_lock and _release_aggregate_pg_lock must not call db.execute on SQLite."""
    print("\n" + "─" * 60)
    print("TEST 3: Lock helpers — SQLite no-op (no SQL executed)")
    print("─" * 60)

    mock_db = MagicMock()
    with patch("mcpgateway.services.log_aggregator._is_postgresql", return_value=False):
        acquired = _try_aggregate_pg_lock(mock_db)
        _release_aggregate_pg_lock(mock_db)

    ok = acquired is True and not mock_db.execute.called
    print(f"  acquired={acquired}, db.execute called={mock_db.execute.called}")
    print(f"  {PASS if ok else FAIL}: {'lock helpers are no-ops on SQLite' if ok else 'unexpected SQL executed'}")
    return ok


# ── test 4: caller-provided db= bypasses lock ──────────────────────────────────

def test_caller_provided_db_bypasses_lock() -> bool:
    """When db= is passed by the caller, _try_aggregate_pg_lock must never be called."""
    print("\n" + "─" * 60)
    print("TEST 4: Caller-provided db= — lock never attempted")
    print("─" * 60)

    mock_db = _make_mock_db()
    with patch("mcpgateway.services.log_aggregator._try_aggregate_pg_lock") as mock_try:
        LogAggregator().aggregate_all_components(db=mock_db)

    ok = not mock_try.called
    print(f"  _try_aggregate_pg_lock called: {mock_try.called}")
    print(f"  {PASS if ok else FAIL}: {'lock bypassed for caller-provided sessions' if ok else 'lock was incorrectly attempted'}")
    return ok


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_sqlite_all_workers_run,
        test_postgresql_only_one_worker_runs,
        test_lock_helpers_sqlite_noop,
        test_caller_provided_db_bypasses_lock,
    ]

    passed = failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as exc:
            print(f"  {FAIL}: unhandled exception — {exc}")
            failed += 1

    print("\n" + "=" * 60)
    status = "\033[32mALL PASSED\033[0m" if failed == 0 else f"\033[31m{failed} FAILED\033[0m"
    print(f"  {passed} passed, {failed} failed — {status}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
