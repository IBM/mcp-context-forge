# -*- coding: utf-8 -*-
"""Unit tests for StdIOEndpoint with environment variable support.

Location: ./tests/unit/mcpgateway/test_translate_stdio_endpoint.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Tests for StdIOEndpoint class modifications to support dynamic environment variables.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from unittest.mock import Mock, patch

import pytest

# First-Party
from mcpgateway.translate import _PubSub, StdIOEndpoint


class TestStdIOEndpointEnvironmentVariables:
    """Test StdIOEndpoint with environment variable support."""

    async def _read_output(self, pubsub: _PubSub, timeout: float = 2.0) -> str:
        """Helper method to read output from pubsub subscriber.

        Args:
            pubsub: The pubsub instance to subscribe to
            timeout: Maximum time to wait for output in seconds

        Returns:
            The output string received from the subprocess

        Raises:
            asyncio.TimeoutError: If no output received within timeout
        """
        queue = pubsub.subscribe()
        try:
            output = await asyncio.wait_for(queue.get(), timeout=timeout)
            return output
        finally:
            pubsub.unsubscribe(queue)

    @pytest.fixture
    def test_script(self):
        """Return the path to the test script that echoes environment variables."""
        return os.path.join(os.path.dirname(__file__), "fixtures", "stdio_echo_env.py")

    @pytest.fixture
    def echo_script(self):
        """Create a simple echo script for testing."""
        script_content = """#!/usr/bin/env python3
import sys
print(sys.stdin.readline().strip())
sys.stdout.flush()
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            try:
                yield f.name
            finally:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass

    def test_stdio_endpoint_init_with_env_vars(self):
        """Test StdIOEndpoint initialization with environment variables."""
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token", "TENANT_ID": "acme"}

        endpoint = StdIOEndpoint("echo hello", pubsub, env_vars)

        assert endpoint._cmd == "echo hello"
        assert endpoint._pubsub is pubsub
        assert endpoint._env_vars == env_vars
        assert endpoint._proc is None
        assert endpoint._stdin is None
        assert endpoint._pump_task is None

    def test_stdio_endpoint_init_without_env_vars(self):
        """Test StdIOEndpoint initialization without environment variables."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint("echo hello", pubsub)

        assert endpoint._cmd == "echo hello"
        assert endpoint._pubsub is pubsub
        assert endpoint._env_vars == {}
        assert endpoint._proc is None
        assert endpoint._stdin is None
        assert endpoint._pump_task is None

    @pytest.mark.asyncio
    async def test_start_with_initial_env_vars(self, test_script, caplog):
        """Test starting StdIOEndpoint with initial environment variables."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token-123", "TENANT_ID": "acme-corp"}

        # Pass env var names as command line arguments, not via stdin
        endpoint = StdIOEndpoint("jq -cMn env", pubsub, env_vars)
        await endpoint.start()

        try:
            # Read output from pubsub to verify environment variables were set
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify environment variables were properly set
            assert result["GITHUB_TOKEN"] == "test-token-123"
            assert result["TENANT_ID"] == "acme-corp"

            # Check that process was started
            assert endpoint._proc is not None
            assert endpoint._stdin is not None
            assert endpoint._pump_task is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_start_with_additional_env_vars(self, test_script, caplog):
        """Test starting StdIOEndpoint with additional environment variables."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")
        pubsub = _PubSub()
        initial_env_vars = {"BASE_VAR": "base-value"}
        additional_env_vars = {"GITHUB_TOKEN": "additional-token", "TENANT_ID": "additional-tenant"}

        # Pass env var names as command line arguments
        endpoint = StdIOEndpoint("jq -cMn env", pubsub, initial_env_vars)
        await endpoint.start(additional_env_vars=additional_env_vars)

        try:
            # Read output from pubsub to verify environment variables
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify all environment variables were properly set
            assert result["BASE_VAR"] == "base-value"
            assert result["GITHUB_TOKEN"] == "additional-token"
            assert result["TENANT_ID"] == "additional-tenant"

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_environment_variable_override(self, test_script, caplog):
        """Test that additional environment variables override initial ones."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")
        pubsub = _PubSub()
        initial_env_vars = {"GITHUB_TOKEN": "initial-token", "BASE_VAR": "base-value"}
        additional_env_vars = {"GITHUB_TOKEN": "override-token"}  # Override initial

        # Pass env var names as command line arguments
        endpoint = StdIOEndpoint("jq -cMn env", pubsub, initial_env_vars)
        await endpoint.start(additional_env_vars=additional_env_vars)

        try:
            # Read output from pubsub to verify environment variables
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify that additional env var overrode the initial one
            assert result["GITHUB_TOKEN"] == "override-token"
            assert result["BASE_VAR"] == "base-value"

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_start_without_env_vars(self, echo_script):
        """Test starting StdIOEndpoint without environment variables."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub)
        await endpoint.start()

        try:
            # Test basic functionality
            await endpoint.send("hello world\n")

            # Wait for response
            await asyncio.sleep(0.1)

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("error::RuntimeWarning")
    async def test_start_twice_handled_gracefully(self, echo_script):
        """Test that starting an already started endpoint is handled gracefully."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub)
        await endpoint.start()

        try:
            # Starting again should be handled gracefully (restart the process)
            await endpoint.start()
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_send_before_start_raises_error(self):
        """Test that sending before starting raises an error."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint("echo hello", pubsub)

        with pytest.raises(RuntimeError, match="stdio endpoint not started"):
            await endpoint.send("test message\n")

    @pytest.mark.asyncio
    async def test_stop_before_start(self):
        """Test that stopping before starting is handled gracefully."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint("echo hello", pubsub)

        # Should not raise an error
        await endpoint.stop()
        assert endpoint._proc is None

    @pytest.mark.asyncio
    async def test_stop_after_start(self, echo_script):
        """Test stopping after starting."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub)
        await endpoint.start()

        assert endpoint._proc is not None

        await endpoint.stop()

        # Process should be terminated and cleaned up
        assert endpoint._proc is None  # Process object should be cleaned up
        # Pump task might still exist but should be finished/cancelled
        if endpoint._pump_task is not None:  # type: ignore[unreachable]
            # Wait a bit for the task to complete if it's still running
            for _ in range(10):  # Try up to 10 times (1 second total)
                if endpoint._pump_task.done():
                    break
                await asyncio.sleep(0.1)
            assert endpoint._pump_task.done()  # Task should be finished

    @pytest.mark.asyncio
    async def test_multiple_env_vars(self, test_script, caplog):
        """Test with multiple environment variables."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")

        pubsub = _PubSub()

        env_vars = {
            "GITHUB_TOKEN": "github-token-123",
            "TENANT_ID": "acme-corp",
            "API_KEY": "api-key-456",
            "ENVIRONMENT": "production",
            "DEBUG": "false",
        }

        endpoint = StdIOEndpoint( "jq -cMn env", pubsub, env_vars)

        await endpoint.start()

        try:
            # Read output from pubsub to verify environment variables
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify all environment variables were properly set
            assert result["GITHUB_TOKEN"] == "github-token-123"
            assert result["TENANT_ID"] == "acme-corp"
            assert result["API_KEY"] == "api-key-456"
            assert result["ENVIRONMENT"] == "production"
            assert result["DEBUG"] == "false"

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_empty_env_vars(self, echo_script):
        """Test with empty environment variables dictionary."""
        pubsub = _PubSub()
        env_vars: dict[str, str] = {}

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub, env_vars)
        await endpoint.start()

        try:
            # Test basic functionality
            await endpoint.send("hello world\n")

            # Wait for response
            await asyncio.sleep(0.5)

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_none_env_vars(self, echo_script):
        """Test with None environment variables."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub, None)
        await endpoint.start()

        try:
            # Test basic functionality
            await endpoint.send("hello world\n")

            # Wait for response
            await asyncio.sleep(0.1)

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_env_vars_with_special_characters(self, test_script, caplog):
        """Test environment variables with special characters."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")
        pubsub = _PubSub()
        env_vars = {
            "API_TOKEN": "Bearer token-123!@#$%^&*()",
            "URL": "https://api.example.com/v1",
            "JSON_CONFIG": '{"key": "value", "number": 123}',
        }

        # Pass env var names as command line arguments
        endpoint = StdIOEndpoint("jq -cMn env", pubsub, env_vars)
        await endpoint.start()

        try:
            # Read output from pubsub to verify environment variables
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify environment variables with special characters were properly set
            assert result["API_TOKEN"] == "Bearer token-123!@#$%^&*()"
            assert result["URL"] == "https://api.example.com/v1"
            assert result["JSON_CONFIG"] == '{"key": "value", "number": 123}'

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_large_env_vars(self, test_script, caplog):
        """Test with large environment variable values."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.translate")

        pubsub = _PubSub()
        large_value = "x" * 1000  # 1KB value
        env_vars = {
            "LARGE_TOKEN": large_value,
            "NORMAL_VAR": "normal",
        }

        # Pass env var names as command line arguments
        endpoint = StdIOEndpoint("jq -cMn env", pubsub, env_vars)
        await endpoint.start()

        try:
            # Read output from pubsub to verify environment variables
            output = await self._read_output(pubsub)
            result = json.loads(output.strip())

            # Verify large environment variable was properly set
            assert result["LARGE_TOKEN"] == large_value
            assert result["NORMAL_VAR"] == "normal"

            # Check that process was started
            assert endpoint._proc is not None

        finally:
            await endpoint.stop()

    @pytest.mark.asyncio
    async def test_mock_subprocess_creation(self):
        """Test subprocess creation with mocked asyncio.create_subprocess_exec."""
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token"}

        # Mock subprocess with proper async behavior
        mock_process = Mock()
        mock_process.stdin = Mock()
        mock_process.stdout = Mock()
        mock_process.pid = 12345

        # Mock the wait method to be awaitable
        async def mock_wait():
            return 0

        mock_process.wait = mock_wait

        with patch("asyncio.create_subprocess_exec") as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_process

            endpoint = StdIOEndpoint("echo hello", pubsub, env_vars)
            await endpoint.start()

            # Verify subprocess was created with correct environment
            mock_create_subprocess.assert_called_once()
            call_args = mock_create_subprocess.call_args

            # Check that env parameter was passed
            assert "env" in call_args.kwargs
            env = call_args.kwargs["env"]

            # Check that our environment variables are included
            assert env["GITHUB_TOKEN"] == "test-token"

            # Check that base environment is preserved
            assert "PATH" in env  # PATH should be preserved from os.environ

            # Don't call stop() as it will try to wait for the mock process
            # Just verify the start() worked correctly

    @pytest.mark.asyncio
    async def test_subprocess_creation_failure(self):
        """Test handling of subprocess creation failure."""
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token"}

        with patch("asyncio.create_subprocess_exec") as mock_create_subprocess:
            # Mock subprocess creation failure
            mock_create_subprocess.side_effect = OSError("Command not found")

            endpoint = StdIOEndpoint("nonexistent-command", pubsub, env_vars)

            with pytest.raises(OSError, match="Command not found"):
                await endpoint.start()

    @pytest.mark.asyncio
    async def test_subprocess_without_stdin_stdout(self):
        """Test handling of subprocess without stdin/stdout pipes."""
        pubsub = _PubSub()
        env_vars = {"GITHUB_TOKEN": "test-token"}

        # Mock subprocess without pipes
        mock_process = Mock()
        mock_process.stdin = None
        mock_process.stdout = None
        mock_process.pid = 12345

        with patch("asyncio.create_subprocess_exec") as mock_create_subprocess:
            mock_create_subprocess.return_value = mock_process

            endpoint = StdIOEndpoint("echo hello", pubsub, env_vars)

            with pytest.raises(RuntimeError, match="Failed to create subprocess with stdin/stdout pipes"):
                await endpoint.start()


class TestStdIOEndpointBackwardCompatibility:
    """Test backward compatibility of StdIOEndpoint changes."""

    @pytest.fixture
    def echo_script(self):
        """Create a simple echo script for testing."""
        script_content = """#!/usr/bin/env python3
import sys
print(sys.stdin.readline().strip())
sys.stdout.flush()
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            f.flush()
            os.chmod(f.name, 0o755)
            try:
                yield f.name
            finally:
                try:
                    os.unlink(f.name)
                except OSError:
                    pass

    def test_old_initialization_still_works(self):
        """Test that old initialization method still works."""
        pubsub = _PubSub()

        # This should work without environment variables (backward compatibility)
        endpoint = StdIOEndpoint("echo hello", pubsub)

        assert endpoint._cmd == "echo hello"
        assert endpoint._pubsub is pubsub
        assert endpoint._env_vars == {}

    @pytest.mark.asyncio
    async def test_old_start_method_still_works(self, echo_script):
        """Test that old start method still works."""
        pubsub = _PubSub()

        endpoint = StdIOEndpoint(f"{sys.executable} {echo_script}", pubsub)
        await endpoint.start()  # No additional_env_vars parameter

        try:
            await endpoint.send("hello world\n")
            await asyncio.sleep(0.1)
            assert endpoint._proc is not None
        finally:
            await endpoint.stop()

    def test_type_hints(self):
        """Test that type hints are correct."""
        pubsub = _PubSub()

        # Test with environment variables
        env_vars = {"GITHUB_TOKEN": "test"}
        endpoint = StdIOEndpoint("echo hello", pubsub, env_vars)

        assert isinstance(endpoint._env_vars, dict)
        assert isinstance(endpoint._env_vars.get("GITHUB_TOKEN"), str)
