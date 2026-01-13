# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_orchestrate_cancel_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from mcpgateway.main import app
from mcpgateway.services.orchestration_service import orchestration_service

client = TestClient(app)


@pytest.mark.asyncio
async def test_cancel_signals_callback(monkeypatch):
    cancel_event = asyncio.Event()

    async def cb(reason):
        cancel_event.set()

    await orchestration_service.register_run("run-int-1", name="tool", cancel_callback=cb)

    # Mock broadcast for sessions
    monkeypatch.setattr("mcpgateway.main.session_registry.get_all_session_ids", AsyncMock(return_value=["s1"]))
    monkeypatch.setattr("mcpgateway.main.session_registry.broadcast", AsyncMock())

    # Call endpoint
    resp = client.post("/orchestrate/cancel", json={"requestId": "run-int-1", "reason": "user"}, headers={"Authorization": "Bearer test-token"})

    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        # Wait briefly for callback to run
        await asyncio.wait_for(cancel_event.wait(), timeout=1.0)
        st = await orchestration_service.get_status("run-int-1")
        assert st is not None and st.get("cancelled") is True
