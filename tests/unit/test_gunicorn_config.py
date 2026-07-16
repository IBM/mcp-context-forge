# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_gunicorn_config.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the ``gunicorn.config.py`` ``post_fork`` hook.

Covers two concerns of the hook:

- **Engine / Redis pool reset on fork** (``TestPostForkHook``): each worker
  disposes the inherited SQLAlchemy engine pool and resets the Redis client.

- **Per-worker WORKER_ID rebind (#4557)**: the load-bearing fix behind PR #4981.
  With ``--preload``, ``mcpgateway.services.session_affinity.WORKER_ID`` is
  captured at import time in the master process, so every forked worker would
  otherwise inherit ``{hostname}:1`` (the master's PID). A shared WORKER_ID
  collapses the per-worker pub/sub channels and makes every forwarded request
  execute on all workers in the container (24x broadcast amplification observed
  in #4557). The ``post_fork`` hook recomputes WORKER_ID per worker to restore
  single-executor forwarding, and wraps the rebind in a broad ``except`` that
  logs a ``warning`` referencing #4557 so silent fallback can't drift production
  back into the amplification state.
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


def test_post_fork_rebinds_worker_id_per_worker(fake_worker, monkeypatch):
    """Happy path: with the affinity flag on, ``post_fork`` overrides the master-frozen ``WORKER_ID`` with ``{hostname}:{worker.pid}``.

    Without this, every forked gunicorn worker carries the master's
    ``{hostname}:1``, so a forwarded request published to the owner's
    pub/sub channel reaches every worker in the container.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
    cfg = _load_gunicorn_config()
    original = session_affinity.WORKER_ID
    try:
        cfg.post_fork(_make_fake_server(), fake_worker)
        assert session_affinity.WORKER_ID == f"{socket.gethostname()}:{fake_worker.pid}"
    finally:
        # Restore the module-level constant so other tests aren't affected.
        session_affinity.WORKER_ID = original


def test_post_fork_skips_worker_id_rebind_when_affinity_disabled(fake_worker, monkeypatch):
    """With the affinity flag off, ``post_fork`` must NOT touch ``WORKER_ID``.

    The kill-switch contract: flag off means the affinity machinery is a clean
    no-op, so the per-worker rebind (and the ``session_affinity`` import at fork)
    is skipped and ``WORKER_ID`` keeps whatever value it already had.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", False)
    cfg = _load_gunicorn_config()
    sentinel = "sentinel-host:0"
    original = session_affinity.WORKER_ID
    session_affinity.WORKER_ID = sentinel
    try:
        cfg.post_fork(_make_fake_server(), fake_worker)
        # Unchanged: the rebind block was gated out by the disabled flag.
        assert session_affinity.WORKER_ID == sentinel
    finally:
        session_affinity.WORKER_ID = original


def test_post_fork_logs_warning_when_rebind_fails(fake_worker, monkeypatch):
    """If the rebind raises, the hook must log a ``warning`` referencing #4557 and NOT crash the worker.

    Regression test for the F2 follow-up: the original ``except ImportError: pass``
    silently fell back to the master's frozen ``WORKER_ID``, so #4557's broadcast
    amplification could return into production unnoticed. The fix broadens the
    catch and surfaces the failure via ``server.log.warning(...)``.

    To reproduce a rebind failure deterministically without depending on the
    real module's internals, monkeypatch ``socket.gethostname`` (called inside
    the try block) to raise.
    """
    # First-Party
    from mcpgateway.config import settings
    from mcpgateway.services import session_affinity

    monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

    original_worker_id = session_affinity.WORKER_ID

    def _boom() -> str:
        raise RuntimeError("simulated rebind failure")

    monkeypatch.setattr(socket, "gethostname", _boom)

    cfg = _load_gunicorn_config()
    server = _make_fake_server()
    try:
        # Must not raise — the hook is expected to swallow + log, never propagate.
        cfg.post_fork(server, fake_worker)
    finally:
        session_affinity.WORKER_ID = original_worker_id

    # WORKER_ID was NOT silently rebound (the failure was real, not papered over).
    assert session_affinity.WORKER_ID == original_worker_id

    # A warning was emitted, mentioning the failing operation (rebind) and the consequence.
    assert server.log.warning.called, "expected post_fork to log a warning on rebind failure"
    call_args = server.log.warning.call_args
    # First arg is the format string; subsequent args are the format params.
    fmt = call_args.args[0] if call_args.args else ""
    assert "WORKER_ID" in fmt
    assert "broadcast" in fmt, "warning should describe the consequence (per-container broadcast) so operators can act on it"
