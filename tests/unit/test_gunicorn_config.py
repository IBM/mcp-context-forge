# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_gunicorn_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for gunicorn.config.py hooks.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load gunicorn.config.py as a module (it has a dot in the name, so we need importlib)
project_root = Path(__file__).parent.parent.parent
gunicorn_config_path = project_root / "gunicorn.config.py"

spec = importlib.util.spec_from_file_location("gunicorn_config", gunicorn_config_path)
gunicorn_config = importlib.util.module_from_spec(spec)
sys.modules["gunicorn_config"] = gunicorn_config
spec.loader.exec_module(gunicorn_config)


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

        # Verify warning was logged
        mock_server.log.warning.assert_called_once()
        warning_call = mock_server.log.warning.call_args[0]
        assert "Failed to reset SQLAlchemy engine pool" in warning_call[0]
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
