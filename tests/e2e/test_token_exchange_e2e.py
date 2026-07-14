# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_token_exchange_e2e.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end test for RFC 8693 token exchange audit logging.

Proves that a transparent token exchange emits a structured audit event
that references the principal and target audience, without leaking the
exchanged token or the inbound user JWT.
"""

# Standard
import logging
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

pytestmark = pytest.mark.e2e

_FAKE_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1QGUifQ.sig"  # pragma: allowlist secret


@pytest.mark.asyncio
async def test_transparent_exchange_emits_audit_without_token(caplog):
    """A successful token exchange logs an audit event without leaking token material."""
    # First-Party
    from mcpgateway.services.tool_service import ToolService

    svc = ToolService()
    svc.oauth_manager = MagicMock()
    svc.oauth_manager.token_exchange = AsyncMock(return_value={"access_token": "EXCHANGED", "expires_in": 1200})
    cfg = {
        "grant_type": "token-exchange",
        "token_url": "https://as/token",
        "client_id": "cf",
        "target_audience": "https://svc",
        "subject_token_source": "inbound_user_jwt",
    }
    await svc._token_exchange_cache.invalidate("gw1", "u@e", "https://svc")

    with caplog.at_level(logging.INFO):
        header = await svc._resolve_token_exchange_header(cfg, "gw1", "gw", "u@e", {"authorization": f"Bearer {_FAKE_JWT}"})

    assert header == {"Authorization": "Bearer EXCHANGED"}
    svc.oauth_manager.token_exchange.assert_awaited_once()
    # audit event present, references the principal + audience, and leaks no token material
    rec = next(r for r in caplog.records if hasattr(r, "token_exchange"))
    assert rec.token_exchange["user_email"] == "u@e"
    assert rec.token_exchange["target_audience"] == "https://svc"
    assert "EXCHANGED" not in " ".join(r.getMessage() for r in caplog.records)
    assert _FAKE_JWT not in " ".join(r.getMessage() for r in caplog.records)
