# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/external/unix/test_runtime.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for Unix socket plugin server runtime.
Tests for run() and main() entry points.
"""

# Standard
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

try:
    from mcpgateway.plugins.framework.external.unix.server.runtime import main, run

    HAS_GRPC = True
except ImportError:
    HAS_GRPC = False

pytestmark = pytest.mark.skipif(not HAS_GRPC, reason="grpc not installed")


class TestUnixRuntimeRun:
    """Tests for the run() async entry point."""

    @pytest.mark.asyncio
    async def test_run_uses_default_config(self):
        """Test run() reads config from environment with defaults."""
        mock_run_server = AsyncMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "mcpgateway.plugins.framework.external.unix.server.runtime.run_server",
                mock_run_server,
            ):
                await run()

        mock_run_server.assert_called_once()
        # run_server is called with keyword args: config_path and socket_path
        call_args = mock_run_server.call_args
        # Check that config_path contains "config.yaml"
        config_path = call_args.kwargs.get("config_path") or call_args[1].get("config_path")
        assert config_path is not None
        assert "config.yaml" in config_path

    @pytest.mark.asyncio
    async def test_run_uses_env_vars(self):
        """Test run() reads config from environment variables."""
        mock_run_server = AsyncMock()

        env_vars = {
            "PLUGINS_CONFIG_PATH": "/custom/config.yaml",
            "UNIX_SOCKET_PATH": "/custom/plugin.sock",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with patch(
                "mcpgateway.plugins.framework.external.unix.server.runtime.run_server",
                mock_run_server,
            ):
                await run()

        mock_run_server.assert_called_once_with(
            config_path="/custom/config.yaml",
            socket_path="/custom/plugin.sock",
        )


class TestUnixRuntimeMain:
    """Tests for the main() CLI entry point."""

    def test_main_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt gracefully."""
        def _raise_keyboard_interrupt(awaitable):
            awaitable.close()
            raise KeyboardInterrupt()

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.runtime.asyncio.run",
            side_effect=_raise_keyboard_interrupt,
        ):
            # Should not raise
            main()

    def test_main_exception_exits(self):
        """Test main exits with code 1 on exception."""
        def _raise_runtime_error(awaitable):
            awaitable.close()
            raise RuntimeError("Server error")

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.runtime.asyncio.run",
            side_effect=_raise_runtime_error,
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_main_calls_run(self):
        """Test main calls asyncio.run with run()."""
        captured = {}

        def _close_and_return(awaitable):
            captured["awaitable"] = awaitable
            awaitable.close()
            return None

        with patch(
            "mcpgateway.plugins.framework.external.unix.server.runtime.asyncio.run",
        ) as mock_asyncio_run:
            mock_asyncio_run.side_effect = _close_and_return
            main()
            mock_asyncio_run.assert_called_once()
            assert asyncio.iscoroutine(captured["awaitable"])
