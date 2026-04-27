#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify advisory lock behaviour in aggregate_all_components (issue #2692).

Three scenarios are exercised:

  1. SQLite (dev) path      — lock helpers are no-ops; all workers proceed
  2. PostgreSQL simulation  — threading.Lock simulates pg_try_advisory_lock;
                              exactly one worker runs, the rest are skipped
  3. Caller-provided db=    — lock is never attempted (backfill / log_search path)

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
    """Return a MagicMock that behaves like an empty SQLAlchemy session."""
    mock_db = MagicMock()
    mock_db.execute.return_value.all.return_value = pairs or []
    return mock_db


def _run_worker(worker_id: int, outcomes: dict, aggregator: LogAggregator, mock_db: MagicMock):
    """Thread target: call aggregate_all_components and record outcome."""
    try:
        with patch("mcpgateway.services.log_aggregator.SessionLocal", return_value=mock_db):
            aggregator.aggregate_all_components(db=None)
        # distinguish ran vs skipped by whether the DB was queried
        outcomes[worker_id] = "ran" if mock_db.execute.called else "skipped"
    except Exception as exc:
        outcomes[worker_id] = f"error: {exc}"


# ── test 1: SQLite ─────────────────────────────────────────────────────────────

def test_sqlite_all_workers_run() -> bool:
    """On SQLite _is_postgresql() == False, so the lock is bypassed and every worker runs."""
    print("\n" + "─" * 60)
    print("TEST 1: SQLite path — all workers should run (lock bypassed)")
    print("─" * 60)

    num_workers = 5
    mock_dbs = [_make_mock_db() for _ in range(num_workers)]
    outcomes: dict = {}
    barrier = threading.Barrier(num_workers)

    def worker(i):
        barrier.wait()  # start all threads simultaneously
        _run_worker(i, outcomes, LogAggregator(), mock_dbs[i])

    threads = [threading.Thread(target=worker, args=(i,), name=f"Worker-{i}") for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

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
    """Simulate pg_try_advisory_lock with a threading.Lock — only the first worker
    to acquire it should run; all others must be skipped immediately."""
    print("\n" + "─" * 60)
    print("TEST 2: PostgreSQL simulation — exactly one worker should run")
    print("─" * 60)

    num_workers = 5
    mock_dbs = [_make_mock_db() for _ in range(num_workers)]
    outcomes: dict = {}
    barrier = threading.Barrier(num_workers)
    _pg_lock = threading.Lock()

    def fake_try_lock(db):
        acquired = _pg_lock.acquire(blocking=False)
        logger.debug("pg_try_advisory_lock → %s", acquired)
        return acquired

    def fake_release_lock(db):
        try:
            _pg_lock.release()
            logger.debug("pg_advisory_unlock → released")
        except RuntimeError:
            pass  # already released

    db_index = iter(range(num_workers))
    db_lock = threading.Lock()

    def make_db():
        with db_lock:
            return mock_dbs[next(db_index)]

    def worker(i):
        barrier.wait()  # all workers contend for the lock at the same instant
        with patch("mcpgateway.services.log_aggregator.SessionLocal", side_effect=make_db), \
             patch("mcpgateway.services.log_aggregator._try_aggregate_pg_lock", side_effect=fake_try_lock), \
             patch("mcpgateway.services.log_aggregator._release_aggregate_pg_lock", side_effect=fake_release_lock):
            try:
                result = LogAggregator().aggregate_all_components(db=None)
                outcomes[i] = "skipped" if result == [] and not mock_dbs[i].execute.called else "ran"
            except Exception as exc:
                outcomes[i] = f"error: {exc}"

    threads = [threading.Thread(target=worker, args=(i,), name=f"Worker-{i}") for i in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ran = sum(1 for v in outcomes.values() if v == "ran")
    skipped = sum(1 for v in outcomes.values() if v == "skipped")

    print(f"  Outcomes : {outcomes}")
    print(f"  Ran      : {ran}/{num_workers}")
    print(f"  Skipped  : {skipped}/{num_workers}")

    ok = ran == 1 and skipped == num_workers - 1
    print(f"  {PASS if ok else FAIL}: {'one ran, rest skipped' if ok else f'expected 1 ran / {num_workers-1} skipped, got {ran} / {skipped}'}")
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


def test_caller_provided_db_bypasses_lock() -> bool:
    """When db= is passed by the caller (backfill / log_search), _try_aggregate_pg_lock
    must never be called."""
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
