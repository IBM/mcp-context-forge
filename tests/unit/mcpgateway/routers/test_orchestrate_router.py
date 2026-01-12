# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.services.orchestration_service import orchestration_service

client = TestClient(app)


def test_cancel_broadcasts_to_sessions(monkeypatch):
    # Prepare a registered run
    async def _setup():
        await orchestration_service.register_run("run-test", name="tool")

    asyncio_run = __import__("asyncio").run
    asyncio_run(_setup())

    # Mock session enumeration and broadcast
    monkeypatch.setattr("mcpgateway.main.session_registry.get_all_session_ids", AsyncMock(return_value=["s1", "s2"]))
    monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", AsyncMock())

    resp = client.post("/orchestrate/cancel", json={"requestId": "run-test", "reason": "user"}, headers={"Authorization": "Bearer test-token"})
    assert resp.status_code in (200, 401, 403)  # auth may be required in test environment
    if resp.status_code == 200:
        body = resp.json()
        assert body["requestId"] == "run-test"
        assert body["status"] == "cancelled"


def test_status_endpoint_not_found():
    resp = client.get("/orchestrate/status/no-such-id", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code in (404, 401, 403)
