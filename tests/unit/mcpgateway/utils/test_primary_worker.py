# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_primary_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for the primary-worker election helper.
"""

# Third-Party
from filelock import FileLock
import pytest

# First-Party
import mcpgateway.utils.primary_worker as pw
from mcpgateway.utils.primary_worker import _lock_path, is_primary_worker


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset module-level lock state and env between tests."""
    monkeypatch.delenv(pw._LOCK_PATH_ENV, raising=False)
    pw._lock = None
    pw._is_primary = False
    yield
    if pw._lock is not None:
        try:
            pw._lock.release()
        except Exception:
            pass
    pw._lock = None
    pw._is_primary = False


def test_first_caller_is_primary(tmp_path, monkeypatch):
    """The first process to acquire the lock is the primary."""
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(tmp_path / "p.lock"))
    assert is_primary_worker() is True


def test_repeated_calls_stay_primary(tmp_path, monkeypatch):
    """Once primary, repeated calls keep returning True (memoized)."""
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(tmp_path / "p.lock"))
    assert is_primary_worker() is True
    assert is_primary_worker() is True


def test_contention_returns_false(tmp_path, monkeypatch):
    """A worker loses when another process already holds the lock."""
    lock_file = tmp_path / "p.lock"
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(lock_file))
    holder = FileLock(str(lock_file))
    holder.acquire(timeout=0)
    try:
        assert is_primary_worker() is False
    finally:
        holder.release()


def test_follower_retries_and_takes_over(tmp_path, monkeypatch):
    """A non-primary worker takes over once the primary releases the lock."""
    lock_file = tmp_path / "p.lock"
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(lock_file))
    holder = FileLock(str(lock_file))
    holder.acquire(timeout=0)
    assert is_primary_worker() is False  # primary held elsewhere
    holder.release()  # primary "exits"
    assert is_primary_worker() is True  # next call takes over


def test_env_override_path(tmp_path, monkeypatch):
    """The lock path honours the env override."""
    override = str(tmp_path / "custom.lock")
    monkeypatch.setenv(pw._LOCK_PATH_ENV, override)
    assert _lock_path() == override


def test_default_path_scoped_by_port(monkeypatch):
    """Without an override the default path is tempdir-scoped by port and stable."""
    monkeypatch.delenv(pw._LOCK_PATH_ENV, raising=False)
    monkeypatch.setattr(pw.settings, "port", 4444, raising=False)
    path = _lock_path()
    assert path.endswith("mcpgw_plugin_primary_4444.lock")
    assert _lock_path() == path  # stable across calls


def test_two_scopes_are_independent(tmp_path, monkeypatch):
    """Different scopes (lock files) each elect a primary without contending."""
    # Instance A on its own lock file.
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(tmp_path / "a.lock"))
    assert is_primary_worker() is True
    # Simulate a separate instance: reset state, point at a different lock file.
    pw._lock = None
    pw._is_primary = False
    monkeypatch.setenv(pw._LOCK_PATH_ENV, str(tmp_path / "b.lock"))
    assert is_primary_worker() is True
