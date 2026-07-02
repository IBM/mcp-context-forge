# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_primary_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for the primary-worker election helper.
"""

# Standard
import threading

# Third-Party
from filelock import FileLock, Timeout
import pytest

# First-Party
import mcpgateway.utils.primary_worker as pw
from mcpgateway.utils.primary_worker import _lock_path, is_primary_worker


def _set_override(monkeypatch, path):
    """Point the lock path at ``path`` via the settings override."""
    monkeypatch.setattr(pw.settings, "primary_worker_lock_path", str(path), raising=False)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset module-level lock state and the path override between tests."""
    monkeypatch.setattr(pw.settings, "primary_worker_lock_path", None, raising=False)
    pw._lock = None
    pw._is_primary = False
    yield
    if pw._lock is not None:
        try:
            pw._lock.release()
        except (Timeout, OSError):
            pass
    pw._lock = None
    pw._is_primary = False


def test_first_caller_is_primary(tmp_path, monkeypatch):
    """The first process to acquire the lock is the primary."""
    _set_override(monkeypatch, tmp_path / "p.lock")
    assert is_primary_worker() is True


def test_repeated_calls_stay_primary(tmp_path, monkeypatch):
    """Once primary, repeated calls keep returning True (memoized)."""
    _set_override(monkeypatch, tmp_path / "p.lock")
    assert is_primary_worker() is True
    assert is_primary_worker() is True


def test_contention_returns_false(tmp_path, monkeypatch):
    """A worker loses when another process already holds the lock."""
    lock_file = tmp_path / "p.lock"
    _set_override(monkeypatch, lock_file)
    holder = FileLock(str(lock_file))
    holder.acquire(timeout=0)
    try:
        assert is_primary_worker() is False
    finally:
        holder.release()


def test_follower_retries_and_takes_over(tmp_path, monkeypatch):
    """A non-primary worker takes over once the primary releases the lock."""
    lock_file = tmp_path / "p.lock"
    _set_override(monkeypatch, lock_file)
    holder = FileLock(str(lock_file))
    holder.acquire(timeout=0)
    assert is_primary_worker() is False  # primary held elsewhere
    holder.release()  # primary "exits"
    assert is_primary_worker() is True  # next call takes over


def test_settings_override_path(tmp_path, monkeypatch):
    """The lock path honours the settings override."""
    override = str(tmp_path / "custom.lock")
    _set_override(monkeypatch, override)
    assert _lock_path() == override


def test_default_path_scoped_by_port(monkeypatch):
    """Without an override the default path is tempdir-scoped by port and stable."""
    monkeypatch.setattr(pw.settings, "primary_worker_lock_path", None, raising=False)
    monkeypatch.setattr(pw.settings, "port", 4444, raising=False)
    path = _lock_path()
    assert path.endswith("mcpgw_plugin_primary_4444.lock")
    assert _lock_path() == path  # stable across calls


def test_two_scopes_are_independent(tmp_path, monkeypatch):
    """Different scopes (lock files) each elect a primary without contending."""
    _set_override(monkeypatch, tmp_path / "a.lock")
    assert is_primary_worker() is True
    # Simulate a separate instance: reset state, point at a different lock file.
    pw._lock = None
    pw._is_primary = False
    _set_override(monkeypatch, tmp_path / "b.lock")
    assert is_primary_worker() is True


def test_oserror_returns_false_without_raising(tmp_path, monkeypatch):
    """An OSError from FileLock.acquire fails closed (non-primary), not crash."""
    _set_override(monkeypatch, tmp_path / "p.lock")

    class BoomLock:
        def __init__(self, *args, **kwargs):
            pass

        def acquire(self, *args, **kwargs):
            raise PermissionError("read-only temp dir")

        def release(self, *args, **kwargs):
            pass

    monkeypatch.setattr(pw, "FileLock", BoomLock)
    assert is_primary_worker() is False


def test_thread_safe_single_lock_creation(tmp_path, monkeypatch):
    """Concurrent first-callers create one FileLock; all see primary (one process)."""
    _set_override(monkeypatch, tmp_path / "p.lock")

    created = []
    real_filelock = pw.FileLock

    def counting_filelock(*args, **kwargs):
        inst = real_filelock(*args, **kwargs)
        created.append(inst)
        return inst

    monkeypatch.setattr(pw, "FileLock", counting_filelock)

    results = []
    n = 8
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()  # maximise contention on the lazy init
        results.append(is_primary_worker())

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(created) == 1  # guard prevented duplicate FileLock creation
    assert results == [True] * n  # one process -> every thread is primary


def test_lock_path_is_directory_fails_closed(tmp_path, monkeypatch):
    """A lock path pointing at a directory raises OSError -> non-primary, not crash."""
    _set_override(monkeypatch, tmp_path)  # tmp_path is an existing directory
    assert is_primary_worker() is False


def test_empty_string_override_falls_back_to_default(monkeypatch):
    """An empty override is falsy, so the default port-scoped path is used."""
    monkeypatch.setattr(pw.settings, "primary_worker_lock_path", "", raising=False)
    monkeypatch.setattr(pw.settings, "port", 4444, raising=False)
    assert _lock_path().endswith("mcpgw_plugin_primary_4444.lock")
