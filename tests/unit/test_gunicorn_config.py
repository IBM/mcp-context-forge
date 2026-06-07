# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_gunicorn_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for the ``post_fork(server, worker)`` hook in ``gunicorn.config.py``.

The hook recomputes ``mcpgateway.services.session_affinity.WORKER_ID`` per worker.
Without this, every gunicorn ``--preload`` worker inherits the master's WORKER_ID,
re-introducing the multi-worker broadcast amplification regression (#4557).
"""

# Future
from __future__ import annotations

# Standard
import importlib.util
from pathlib import Path
import socket
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import session_affinity

REPO_ROOT = Path(__file__).resolve().parents[2]
GUNICORN_CONFIG_PATH = REPO_ROOT / "gunicorn.config.py"


def _load_gunicorn_config():
    """Load ``gunicorn.config.py`` as a module (the dotted filename is not importable)."""
    spec = importlib.util.spec_from_file_location("gunicorn_config_under_test", GUNICORN_CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gunicorn_config():
    """Provide the loaded gunicorn config module."""
    return _load_gunicorn_config()


@pytest.fixture(autouse=True)
def _restore_worker_id():
    """Save and restore ``session_affinity.WORKER_ID`` so tests don't pollute each other."""
    saved = session_affinity.WORKER_ID
    try:
        yield
    finally:
        session_affinity.WORKER_ID = saved


def _make_server():
    server = MagicMock()
    server.log = MagicMock()
    server.log.warning = MagicMock()
    return server


def _make_worker(pid: int):
    worker = MagicMock()
    worker.pid = pid
    return worker


def test_post_fork_rebinds_worker_id_happy_path(gunicorn_config):
    """post_fork rebinds WORKER_ID to ``{hostname}:{pid}`` and logs no warning."""
    server = _make_server()
    worker = _make_worker(54321)

    gunicorn_config.post_fork(server, worker)

    assert session_affinity.WORKER_ID == f"{socket.gethostname()}:{worker.pid}"
    server.log.warning.assert_not_called()


def test_post_fork_swallows_rebind_failure_and_warns(gunicorn_config, monkeypatch):
    """On rebind failure, post_fork must not raise and must log a 'broadcast' warning."""

    def _boom():
        raise RuntimeError("hostname lookup failed")

    monkeypatch.setattr(socket, "gethostname", _boom)

    server = _make_server()
    worker = _make_worker(99999)

    # Must not propagate the exception (workers must never crash on rebind failure).
    gunicorn_config.post_fork(server, worker)

    server.log.warning.assert_called_once()
    warning_message = server.log.warning.call_args.args[0]
    assert "broadcast" in warning_message
