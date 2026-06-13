# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_token_exchange_mock_upstream.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Mock-upstream integration tests for RFC 8693 token exchange.

These tests prove two end-to-end invariants the unit tests only assert on
dicts:

- The inbound user JWT never reaches the upstream service; only the
  exchanged token is forwarded.
- A 401 from the upstream triggers exactly one re-exchange and retry.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

pytestmark = pytest.mark.integration

_FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1QGUifQ.sig"  # pragma: allowlist secret


@pytest.mark.asyncio
async def test_upstream_receives_exchanged_token_not_user_jwt():
    """The upstream call must carry the exchanged token, never the user's inbound JWT."""
    # First-Party
    from mcpgateway.services.tool_service import ToolService

    svc = ToolService()
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "EXCHANGED", "expires_in": 3600})

    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as/token",
        "client_id": "cf",
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    captured = {}

    async def _send(headers):
        captured.update(headers)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    await svc._send_with_token_exchange_retry(_send, header, cfg, "gw1", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})
    auth = captured.get("Authorization")
    assert auth == "Bearer EXCHANGED"
    assert _FAKE_JWT not in (auth or "")


@pytest.mark.asyncio
async def test_upstream_401_then_success_reexchanges_once():
    """A 401 from the upstream invalidates the cached token and triggers exactly one re-exchange."""
    # First-Party
    from mcpgateway.services.tool_service import ToolService

    svc = ToolService()
    svc.oauth_manager = MagicMock()
    # first exchange -> T1, after invalidation second exchange -> T2
    svc.oauth_manager.token_exchange = AsyncMock(
        side_effect=[
            {"access_token": "T1", "expires_in": 3600},
            {"access_token": "T2", "expires_in": 3600},
        ]
    )
    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as/token",
        "client_id": "cf",
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    req = {"authorization": f"Bearer {_FAKE_JWT}"}
    header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", req)

    seen = []

    async def _send(headers):
        seen.append(headers.get("Authorization"))
        resp = MagicMock()
        resp.status_code = 401 if len(seen) == 1 else 200
        return resp

    resp = await svc._send_with_token_exchange_retry(_send, header, cfg, "gw1", "gw", "u@e", req)
    assert resp.status_code == 200
    assert seen == ["Bearer T1", "Bearer T2"]  # invalidated, re-exchanged once
