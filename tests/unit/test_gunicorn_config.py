# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_gunicorn_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

Tests for the ``gunicorn.config.py`` ``post_fork`` hook (#4557).

The hook is the load-bearing fix behind PR #4981: with ``--preload``,
``mcpgateway.services.session_affinity.WORKER_ID`` is captured at import
time in the master process, so every forked worker would otherwise inherit
``{hostname}:1`` (the master's PID). A shared WORKER_ID collapses the
per-worker pub/sub channels and makes every forwarded request execute on
all workers in the container (24x broadcast amplification observed in
#4557). The ``post_fork`` hook recomputes WORKER_ID per worker to restore
single-executor forwarding.

The hook also wraps the rebind in a broad ``except Exception`` that logs
a ``warning`` referencing #4557 — the F2 follow-up. Silent fallback would
let production drift back into the amplification state without any signal.
"""

# Future
from __future__ import annotations

# Standard
import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest


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


def test_post_fork_rebinds_worker_id_per_worker(fake_worker):
    """Happy path: ``post_fork`` overrides the master-frozen ``WORKER_ID`` with ``{hostname}:{worker.pid}``.

    Without this, every forked gunicorn worker carries the master's
    ``{hostname}:1``, so a forwarded request published to the owner's
    pub/sub channel reaches every worker in the container.
    """
    # First-Party
    from mcpgateway.services import session_affinity

    cfg = _load_gunicorn_config()
    original = session_affinity.WORKER_ID
    try:
        cfg.post_fork(_make_fake_server(), fake_worker)
        assert session_affinity.WORKER_ID == f"{socket.gethostname()}:{fake_worker.pid}"
    finally:
        # Restore the module-level constant so other tests aren't affected.
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
    from mcpgateway.services import session_affinity

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

    # A warning was emitted, mentioning the failing operation (rebind) and #4557.
    assert server.log.warning.called, "expected post_fork to log a warning on rebind failure"
    call_args = server.log.warning.call_args
    # First arg is the format string; subsequent args are the format params.
    fmt = call_args.args[0] if call_args.args else ""
    assert "WORKER_ID" in fmt
    assert "#4557" in fmt, "warning should reference #4557 so operators can find the root cause"
