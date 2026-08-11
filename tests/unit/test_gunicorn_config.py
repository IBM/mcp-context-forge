# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_gunicorn_config.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the ``gunicorn.config.py`` ``post_fork`` hook.

Covers two concerns of the hook:

- **Engine / Redis pool reset on fork** (``TestPostForkHook``): each worker
  disposes the inherited SQLAlchemy engine pool and resets the Redis client.

- **Per-worker worker-id correctness (#4557)**: with ``--preload``, a
  module-level ``WORKER_ID`` constant would be captured at import time in the
  master process, so every forked worker would inherit ``{hostname}:1`` (the
  master's PID). A shared worker id collapses the per-worker pub/sub channels
  and makes every forwarded request execute on all workers in the container
  (24x broadcast amplification observed in #4557).
  ``mcpgateway.services.session_affinity.get_worker_id()`` derives the id from
  the live PID at call time, so each forked worker reports its own id with no
  ``post_fork`` rebind required; these tests pin that contract.
"""

# Future
from __future__ import annotations

# Standard
import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# Load gunicorn.config.py as a module (it has a dot in the name, so we need importlib)
project_root = Path(__file__).parent.parent.parent
gunicorn_config_path = project_root / "gunicorn.config.py"

spec = importlib.util.spec_from_file_location("gunicorn_config", gunicorn_config_path)
gunicorn_config = importlib.util.module_from_spec(spec)
sys.modules["gunicorn_config"] = gunicorn_config
spec.loader.exec_module(gunicorn_config)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUNICORN_CONFIG_PATH = _REPO_ROOT / "gunicorn.config.py"


def _load_gunicorn_config():
    """Import ``gunicorn.config`` from the repo root by file path.

    ``gunicorn.config.py`` sits at the repo root, not on ``sys.path``, so
    a plain ``import gunicorn.config`` doesn't reach it. Loading via spec
    keeps the test hermetic and avoids polluting ``sys.modules`` with a
    name that collides with the real ``gunicorn`` package.
    """
    spec = importlib.util.spec_from_file_location("_gunicorn_config_under_test", _GUNICORN_CONFIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_fake_server() -> SimpleNamespace:
    """Build a minimal gunicorn-server stand-in exposing ``log.info/warning/error``."""
    return SimpleNamespace(log=MagicMock())


@pytest.fixture
def fake_worker() -> SimpleNamespace:
    """A gunicorn-worker stand-in with a stable PID."""
    return SimpleNamespace(pid=4242)


class TestPostForkHook:
    """Test the post_fork() hook in gunicorn.config.py."""

    def test_post_fork_disposes_engine_with_close_false(self):
        """Test that post_fork() calls engine.dispose(close=False) successfully."""
        # Mock server and worker
        mock_server = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 12345

        # Mock the engine
        mock_engine = MagicMock()
        mock_db_module = MagicMock()
        mock_db_module.engine = mock_engine

        mock_redis_module = MagicMock()

        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module, "mcpgateway.utils.redis_client": mock_redis_module}):
            gunicorn_config.post_fork(mock_server, mock_worker)

        # Verify engine.dispose(close=False) was called
        mock_engine.dispose.assert_called_once_with(close=False)

        # Verify logging
        mock_server.log.info.assert_any_call("Worker spawned (pid: %s)", 12345)
        mock_server.log.info.assert_any_call("SQLAlchemy engine pool reset for worker %s", 12345)

    def test_post_fork_logs_warning_on_engine_dispose_failure(self):
        """Test that post_fork() logs warning when engine.dispose() fails."""
        mock_server = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 12345

        # Mock engine that raises exception on dispose
        mock_engine = MagicMock()
        mock_engine.dispose.side_effect = RuntimeError("Connection pool error")
        mock_db_module = MagicMock()
        mock_db_module.engine = mock_engine

        mock_redis_module = MagicMock()

        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module, "mcpgateway.utils.redis_client": mock_redis_module}):
            # Should not raise - exception is caught
            gunicorn_config.post_fork(mock_server, mock_worker)

        # Verify the engine-pool warning was logged. Search among all warning calls
        # rather than asserting it was the only one: post_fork may emit other warnings
        # (e.g. the affinity rebind) depending on configuration, so assert_called_once()
        # would be brittle.
        engine_warnings = [c for c in mock_server.log.warning.call_args_list if c.args and "Failed to reset SQLAlchemy engine pool" in str(c.args[0])]
        assert engine_warnings, "expected a warning about engine pool reset failure"
        warning_call = engine_warnings[0].args
        assert "Connection pool error" in str(warning_call[1])

    def test_post_fork_resets_redis_client(self):
        """Test that post_fork() resets Redis client state."""
        mock_server = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 12345

        mock_engine = MagicMock()
        mock_db_module = MagicMock()
        mock_db_module.engine = mock_engine

        mock_reset_client = MagicMock()
        mock_redis_module = MagicMock()
        mock_redis_module._reset_client = mock_reset_client

        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module, "mcpgateway.utils.redis_client": mock_redis_module}):
            gunicorn_config.post_fork(mock_server, mock_worker)

        # Verify Redis client reset was called
        mock_reset_client.assert_called_once()

    def test_post_fork_handles_redis_import_error(self):
        """Test that post_fork() handles Redis ImportError gracefully."""
        mock_server = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 12345

        mock_engine = MagicMock()
        mock_db_module = MagicMock()
        mock_db_module.engine = mock_engine

        # Simulate redis_client module not available by not including it in sys.modules
        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module, "mcpgateway.utils.redis_client": None}):
            # Should not raise - ImportError is caught
            gunicorn_config.post_fork(mock_server, mock_worker)

        # Should still complete successfully
        mock_server.log.info.assert_any_call("Worker spawned (pid: %s)", 12345)
        mock_server.log.info.assert_any_call("SQLAlchemy engine pool reset for worker %s", 12345)


def test_get_worker_id_reads_live_pid(monkeypatch):
    """``get_worker_id()`` derives the id from the live PID at call time.

    This is what makes per-worker identity correct after ``fork()`` without any
    ``post_fork`` rebind: each forked worker has its own PID, so every worker
    automatically reports ``{hostname}:{worker.pid}`` instead of the master's
    import-time-frozen id (#4557's per-container broadcast amplification).
    """
    # First-Party
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(session_affinity.os, "getpid", lambda: 4242)
    assert session_affinity.get_worker_id() == f"{socket.gethostname()}:4242"


def test_post_fork_does_not_rebind_worker_id_constant_enabled(fake_worker, monkeypatch):
    """With the affinity flag on, ``post_fork`` must not set a module-level ``WORKER_ID``.

    The constant was replaced by ``get_worker_id()``; a stale rebind would be
    dead state and mask regressions of the live-PID contract.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
    cfg = _load_gunicorn_config()
    cfg.post_fork(_make_fake_server(), fake_worker)
    assert not hasattr(session_affinity, "WORKER_ID")


def test_post_fork_does_not_rebind_worker_id_constant_disabled(fake_worker, monkeypatch):
    """With the affinity flag off, ``post_fork`` likewise sets no ``WORKER_ID``.

    The kill-switch contract stays intact: flag off means the affinity
    machinery is a clean no-op.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", False)
    cfg = _load_gunicorn_config()
    cfg.post_fork(_make_fake_server(), fake_worker)
    assert not hasattr(session_affinity, "WORKER_ID")
