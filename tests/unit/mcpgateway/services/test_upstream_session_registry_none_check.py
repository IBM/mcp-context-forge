# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_upstream_session_registry_none_check.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for UpstreamSessionRegistry None session check.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import anyio

from mcpgateway.services.upstream_session_registry import UpstreamSessionRegistry


@pytest.mark.asyncio
async def test_session_none_check_raises_runtime_error():
    """Test that None session after acquire raises RuntimeError (line 538)."""
    registry = UpstreamSessionRegistry()

    # Mock the session creation to return None
    with patch.object(registry, "_create_session", return_value=None):
        # Attempt to acquire session - should raise RuntimeError
        with pytest.raises(RuntimeError, match="Session unexpectedly None after acquire"):
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                pass  # Should not reach here


@pytest.mark.asyncio
async def test_session_none_check_with_existing_none_session():
    """Test that existing None session in cache raises RuntimeError."""
    registry = UpstreamSessionRegistry()

    # Mock _create_session to return None (simulating a creation failure)
    with patch.object(registry, "_create_session", return_value=None):
        # Manually inject a None session into the cache
        key = ("test-session", "test-gateway")
        registry._sessions[key] = None

        # Attempt to acquire - should raise RuntimeError
        with pytest.raises(RuntimeError, match="Session unexpectedly None after acquire"):
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                pass  # Should not reach here


@pytest.mark.asyncio
async def test_session_valid_after_acquire():
    """Test that valid session passes the None check."""
    registry = UpstreamSessionRegistry()

    # Mock a valid session
    mock_session = MagicMock()
    mock_session.last_used = 0
    mock_session.use_count = 0
    mock_session.is_closed = False

    with patch.object(registry, "_create_session", return_value=mock_session):
        # Should not raise RuntimeError
        async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
            assert session is not None
            assert session == mock_session


@pytest.mark.asyncio
async def test_session_transport_error_eviction():
    """Test that transport errors trigger session eviction."""
    registry = UpstreamSessionRegistry()

    # Mock a valid session
    mock_session = MagicMock()
    mock_session.last_used = 0
    mock_session.use_count = 0
    mock_session.is_closed = False

    with patch.object(registry, "_create_session", return_value=mock_session):
        key = ("test-session", "test-gateway")

        # Acquire session and simulate transport error
        try:
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                # Verify session is in cache
                assert key in registry._sessions
                # Simulate transport error
                raise OSError("Connection broken")
        except OSError:
            pass

        # Session should be evicted from cache after transport error
        assert key not in registry._sessions


@pytest.mark.asyncio
async def test_session_closed_resource_error_eviction():
    """Test that ClosedResourceError triggers session eviction."""
    registry = UpstreamSessionRegistry()

    # Mock a valid session
    mock_session = MagicMock()
    mock_session.last_used = 0
    mock_session.use_count = 0
    mock_session.is_closed = False

    with patch.object(registry, "_create_session", return_value=mock_session):
        key = ("test-session", "test-gateway")

        # Acquire session and simulate closed resource error
        try:
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                assert key in registry._sessions
                raise anyio.ClosedResourceError("Resource closed")
        except anyio.ClosedResourceError:
            pass

        # Session should be evicted
        assert key not in registry._sessions


@pytest.mark.asyncio
async def test_session_broken_resource_error_eviction():
    """Test that BrokenResourceError triggers session eviction."""
    registry = UpstreamSessionRegistry()

    # Mock a valid session
    mock_session = MagicMock()
    mock_session.last_used = 0
    mock_session.use_count = 0
    mock_session.is_closed = False

    with patch.object(registry, "_create_session", return_value=mock_session):
        key = ("test-session", "test-gateway")

        # Acquire session and simulate broken resource error
        try:
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                assert key in registry._sessions
                raise anyio.BrokenResourceError("Resource broken")
        except anyio.BrokenResourceError:
            pass

        # Session should be evicted
        assert key not in registry._sessions


@pytest.mark.asyncio
async def test_session_other_error_no_eviction():
    """Test that non-transport errors don't trigger eviction."""
    registry = UpstreamSessionRegistry()

    # Mock a valid session
    mock_session = MagicMock()
    mock_session.last_used = 0
    mock_session.use_count = 0
    mock_session.is_closed = False

    with patch.object(registry, "_create_session", return_value=mock_session):
        key = ("test-session", "test-gateway")

        # Acquire session and simulate non-transport error
        try:
            async with registry.acquire(downstream_session_id="test-session", gateway_id="test-gateway", url="http://test.example.com", headers=None, transport_type="sse") as session:
                assert key in registry._sessions
                raise ValueError("Some other error")
        except ValueError:
            pass

        # Session should NOT be evicted for non-transport errors
        assert key in registry._sessions
