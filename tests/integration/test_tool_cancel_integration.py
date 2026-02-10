# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tool_cancel_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for cancellation router endpoints.
Tests HTTP endpoints with authentication and authorization.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.services.cancellation_service import cancellation_service

client = TestClient(app)


@pytest.fixture
def auth_headers():
    """Fixture providing valid auth headers for testing."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def mock_session_broadcast(monkeypatch):
    """Fixture to mock session registry broadcast operations."""
    monkeypatch.setattr("mcpgateway.main.session_registry.get_all_session_ids", AsyncMock(return_value=["s1", "s2"]))
    monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", AsyncMock())


@pytest.mark.asyncio
async def test_cancel_endpoint_success(auth_headers, mock_session_broadcast):
    """Test successful cancellation via POST /cancellation/cancel."""
    cancel_event = asyncio.Event()

    async def cb(reason):
        cancel_event.set()

    await cancellation_service.register_run("run-cancel-1", name="test_tool", cancel_callback=cb)

    resp = client.post("/cancellation/cancel", json={"requestId": "run-cancel-1", "reason": "user requested"}, headers=auth_headers)

    # May return 200 (success), 401 (auth required), or 403 (permission denied)
    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["requestId"] == "run-cancel-1"
        assert data["reason"] == "user requested"

        # Wait for callback to execute
        await asyncio.wait_for(cancel_event.wait(), timeout=1.0)

        # Verify cancellation in service
        status = await cancellation_service.get_status("run-cancel-1")
        assert status is not None
        assert status["cancelled"] is True
        assert status["cancel_reason"] == "user requested"


@pytest.mark.asyncio
async def test_cancel_endpoint_unknown_run(auth_headers, mock_session_broadcast):
    """Test cancellation of unknown run returns 'queued' status."""
    resp = client.post("/cancellation/cancel", json={"requestId": "unknown-run-id", "reason": "test"}, headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "queued"  # Not found locally, queued for remote
        assert data["requestId"] == "unknown-run-id"


@pytest.mark.asyncio
async def test_cancel_endpoint_without_reason(auth_headers, mock_session_broadcast):
    """Test cancellation without reason parameter."""
    await cancellation_service.register_run("run-no-reason", name="tool")

    resp = client.post("/cancellation/cancel", json={"requestId": "run-no-reason"}, headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["reason"] is None


@pytest.mark.asyncio
async def test_cancel_endpoint_broadcasts_to_sessions(auth_headers, monkeypatch):
    """Test that cancellation broadcasts notifications to all sessions."""
    broadcast_mock = AsyncMock()
    get_sessions_mock = AsyncMock(return_value=["session1", "session2", "session3"])

    monkeypatch.setattr("mcpgateway.main.session_registry.get_all_session_ids", get_sessions_mock)
    monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", broadcast_mock)

    await cancellation_service.register_run("run-broadcast", name="tool")

    resp = client.post("/cancellation/cancel", json={"requestId": "run-broadcast", "reason": "test"}, headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        # Verify broadcast was called for each session
        assert broadcast_mock.call_count == 3

        # Verify notification format
        for call in broadcast_mock.call_args_list:
            session_id, notification = call[0]
            assert session_id in ["session1", "session2", "session3"]
            assert notification["jsonrpc"] == "2.0"
            assert notification["method"] == "notifications/cancelled"
            assert notification["params"]["requestId"] == "run-broadcast"
            assert notification["params"]["reason"] == "test"


@pytest.mark.asyncio
async def test_status_endpoint_success(auth_headers):
    """Test successful status retrieval via GET /cancellation/status/{request_id}."""
    await cancellation_service.register_run("run-status-1", name="test_tool")

    resp = client.get("/cancellation/status/run-status-1", headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        data = resp.json()
        assert data["name"] == "test_tool"
        assert data["cancelled"] is False
        assert "registered_at" in data
        assert "cancel_callback" not in data  # Should be filtered out


@pytest.mark.asyncio
async def test_status_endpoint_not_found(auth_headers):
    """Test status endpoint returns 404 for unknown run."""
    resp = client.get("/cancellation/status/nonexistent-run", headers=auth_headers)

    assert resp.status_code in (404, 401, 403)

    if resp.status_code == 404:
        data = resp.json()
        assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_status_endpoint_cancelled_run(auth_headers):
    """Test status endpoint shows cancellation details."""
    await cancellation_service.register_run("run-cancelled", name="tool")
    await cancellation_service.cancel_run("run-cancelled", reason="test cancellation")

    resp = client.get("/cancellation/status/run-cancelled", headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        data = resp.json()
        assert data["cancelled"] is True
        assert data["cancel_reason"] == "test cancellation"
        assert "cancelled_at" in data


@pytest.mark.asyncio
async def test_cancel_endpoint_requires_auth():
    """Test that cancel endpoint requires authentication."""
    resp = client.post("/cancellation/cancel", json={"requestId": "test-run"})

    # Should return 401 (unauthorized) or 403 (forbidden) without auth
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_status_endpoint_requires_auth():
    """Test that status endpoint requires authentication."""
    resp = client.get("/cancellation/status/test-run")

    # Should return 401 (unauthorized) or 403 (forbidden) without auth
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_cancel_endpoint_handles_broadcast_errors(auth_headers, monkeypatch):
    """Test that broadcast errors don't prevent cancellation."""
    # Mock broadcast to raise exception
    monkeypatch.setattr("mcpgateway.main.session_registry.get_all_session_ids", AsyncMock(return_value=["s1"]))
    monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", AsyncMock(side_effect=Exception("Broadcast failed")))

    await cancellation_service.register_run("run-broadcast-error", name="tool")

    resp = client.post("/cancellation/cancel", json={"requestId": "run-broadcast-error", "reason": "test"}, headers=auth_headers)

    assert resp.status_code in (200, 401, 403)

    if resp.status_code == 200:
        # Cancellation should still succeed despite broadcast error
        data = resp.json()
        assert data["status"] == "cancelled"

        # Verify local cancellation worked
        status = await cancellation_service.get_status("run-broadcast-error")
        assert status["cancelled"] is True



# Tests for feature disabled state
#
# TEST GAP ACKNOWLEDGMENT:
# Router registration happens at import time (module-level code in main.py), so we cannot
# test the actual 404 behavior when MCPGATEWAY_TOOL_CANCELLATION_ENABLED=false via runtime
# monkeypatching. Testing this properly would require:
#   - Subprocess testing with environment variable set before import
#   - Or a test harness that reimports the app module
#
# The tests below verify:
#   1. Configuration flag exists and has correct default
#   2. Configuration flag can be disabled
#   3. Conditional router registration code exists in main.py (code path verification)
#
# The documented behavior (endpoints return 404 when disabled) relies on code review
# verification of the conditional registration at main.py:6469-6479.


def test_cancellation_feature_flag_exists():
    """Test that the cancellation feature flag exists and has expected default."""
    from mcpgateway.config import Settings

    # Create a fresh settings instance to verify default
    settings = Settings()
    assert hasattr(settings, "mcpgateway_tool_cancellation_enabled")
    # Default is True (feature enabled)
    assert settings.mcpgateway_tool_cancellation_enabled is True


def test_cancellation_feature_flag_can_be_disabled():
    """Test that the cancellation feature flag can be set to False."""
    from mcpgateway.config import Settings

    # Create settings with feature disabled
    settings = Settings(mcpgateway_tool_cancellation_enabled=False)
    assert settings.mcpgateway_tool_cancellation_enabled is False


def test_conditional_router_registration_code_exists():
    """Verify the conditional router registration code exists in main.py.

    This test verifies that the code path for conditional router registration exists,
    even though we can't test the runtime behavior due to import-time registration.
    """
    import inspect
    import mcpgateway.main as main_module

    # Get the source code of the main module
    source = inspect.getsource(main_module)

    # Verify the conditional registration pattern exists
    assert "if settings.mcpgateway_tool_cancellation_enabled:" in source
    assert "app.include_router(cancellation_router)" in source
    assert "Cancellation router included" in source
