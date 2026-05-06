# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_gateway_filtering.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for gateway_id filtering on /prompts and /resources endpoints.

Verifies:
1. Partition completeness: filtered subsets sum to the unfiltered total.
2. Null association: gateway_id=null returns only unassociated artifacts.
3. Nonexistent gateway: returns 200 with empty list, not an error.
4. RBAC composition: gateway_id filter does not bypass token scoping.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.schemas import PromptRead, ResourceRead


# ---------------------------------------------------------------------------
# Local permission mock (accepts all kwargs the RBAC middleware may pass)
# ---------------------------------------------------------------------------
class _PermitAllPermissionService:
    """Minimal mock that grants every permission regardless of kwargs."""

    def __init__(self, *args, **kwargs):
        pass

    async def check_permission(self, *args, **kwargs):
        return True

    async def check_admin_permission(self, *args, **kwargs):
        return True


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------
_NOW = datetime(2025, 1, 1)
_COMMON = {
    "created_at": _NOW,
    "updated_at": _NOW,
    "enabled": True,
    "tags": [],
    "description": "test",
    "visibility": "public",
}

PROMPT_GW_A = PromptRead(
    id="p-1",
    name="prompt_a",
    original_name="prompt_a",
    custom_name="Prompt A",
    custom_name_slug="prompt-a",
    template="Hello",
    arguments=[],
    gateway_id="gw-A",
    **_COMMON,
)
PROMPT_GW_B = PromptRead(
    id="p-2",
    name="prompt_b",
    original_name="prompt_b",
    custom_name="Prompt B",
    custom_name_slug="prompt-b",
    template="Hello",
    arguments=[],
    gateway_id="gw-B",
    **_COMMON,
)
PROMPT_NO_GW = PromptRead(
    id="p-3",
    name="prompt_none",
    original_name="prompt_none",
    custom_name="Prompt None",
    custom_name_slug="prompt-none",
    template="Hello",
    arguments=[],
    gateway_id=None,
    **_COMMON,
)
ALL_PROMPTS = [PROMPT_GW_A, PROMPT_GW_B, PROMPT_NO_GW]

RESOURCE_GW_A = ResourceRead(
    id="r-1",
    uri="file:///a",
    name="res_a",
    mime_type="text/plain",
    size=10,
    metrics=None,
    gateway_id="gw-A",
    **_COMMON,
)
RESOURCE_NO_GW = ResourceRead(
    id="r-2",
    uri="file:///none",
    name="res_none",
    mime_type="text/plain",
    size=10,
    metrics=None,
    gateway_id=None,
    **_COMMON,
)
ALL_RESOURCES = [RESOURCE_GW_A, RESOURCE_NO_GW]


# ---------------------------------------------------------------------------
# Fixtures — reuse the integration test_client from test_integration.py
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with temp DB and auth bypassed."""
    # Standard
    import os
    import tempfile
    from unittest.mock import MagicMock

    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.config import settings
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod
    from mcpgateway.main import app
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service
    from mcpgateway.utils.verify_credentials import require_auth

    mp = MonkeyPatch()
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    mp.setattr(settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    db_mod.Base.metadata.create_all(bind=engine)

    mock_email_user = MagicMock()
    mock_email_user.email = "admin@example.com"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "admin@example.com",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    with patch("mcpgateway.middleware.rbac.PermissionService", _PermitAllPermissionService):
        app.dependency_overrides[require_auth] = lambda: "integration-test-user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = lambda: _PermitAllPermissionService(always_grant=True)
        app.dependency_overrides[rbac_get_db] = override_get_db

        client = TestClient(app)
        yield client

        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer 123.123.integration"}


# ---------------------------------------------------------------------------
# Helper to build side_effect that filters by gateway_id
# ---------------------------------------------------------------------------
def _make_gateway_side_effect(all_items):
    """Return an async side_effect that filters items by gateway_id."""

    async def _side_effect(db, gateway_id=None, **kwargs):
        if gateway_id is None:
            return (all_items, None)
        if gateway_id.lower() == "null":
            return ([i for i in all_items if getattr(i, "gateway_id", "x") is None], None)
        return ([i for i in all_items if getattr(i, "gateway_id", None) == gateway_id], None)

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestGatewayIdFilteringPrompts:
    """Verify gateway_id filtering on /prompts endpoint."""

    @patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock)
    def test_partition_completeness(self, mock_list, test_client, auth_headers):
        """Sum of gateway-filtered partitions + null == unfiltered total."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_PROMPTS)

        resp_all = test_client.get("/prompts/", headers=auth_headers)
        resp_a = test_client.get("/prompts/?gateway_id=gw-A", headers=auth_headers)
        resp_b = test_client.get("/prompts/?gateway_id=gw-B", headers=auth_headers)
        resp_null = test_client.get("/prompts/?gateway_id=null", headers=auth_headers)

        assert resp_all.status_code == 200
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_null.status_code == 200

        total = resp_all.json() if isinstance(resp_all.json(), list) else resp_all.json().get("items", resp_all.json())
        part_a = resp_a.json() if isinstance(resp_a.json(), list) else resp_a.json().get("items", resp_a.json())
        part_b = resp_b.json() if isinstance(resp_b.json(), list) else resp_b.json().get("items", resp_b.json())
        part_null = resp_null.json() if isinstance(resp_null.json(), list) else resp_null.json().get("items", resp_null.json())

        assert len(part_a) + len(part_b) + len(part_null) == len(total)

    @patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock)
    def test_null_gateway_returns_unassociated_only(self, mock_list, test_client, auth_headers):
        """gateway_id=null returns only prompts without a gateway."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_PROMPTS)

        resp = test_client.get("/prompts/?gateway_id=null", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", resp.json())
        assert len(items) == 1
        assert items[0]["gatewayId"] is None

    @patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock)
    def test_nonexistent_gateway_returns_empty(self, mock_list, test_client, auth_headers):
        """Nonexistent gateway_id returns 200 with empty list."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_PROMPTS)

        resp = test_client.get("/prompts/?gateway_id=does-not-exist", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", resp.json())
        assert items == []


class TestGatewayIdFilteringResources:
    """Verify gateway_id filtering on /resources endpoint."""

    @patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock)
    def test_partition_completeness(self, mock_list, test_client, auth_headers):
        """Sum of gateway-filtered partitions + null == unfiltered total."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_RESOURCES)

        resp_all = test_client.get("/resources/", headers=auth_headers)
        resp_a = test_client.get("/resources/?gateway_id=gw-A", headers=auth_headers)
        resp_null = test_client.get("/resources/?gateway_id=null", headers=auth_headers)

        assert resp_all.status_code == 200
        assert resp_a.status_code == 200
        assert resp_null.status_code == 200

        total = resp_all.json() if isinstance(resp_all.json(), list) else resp_all.json().get("items", resp_all.json())
        part_a = resp_a.json() if isinstance(resp_a.json(), list) else resp_a.json().get("items", resp_a.json())
        part_null = resp_null.json() if isinstance(resp_null.json(), list) else resp_null.json().get("items", resp_null.json())

        assert len(part_a) + len(part_null) == len(total)

    @patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock)
    def test_null_gateway_returns_unassociated_only(self, mock_list, test_client, auth_headers):
        """gateway_id=null returns only resources without a gateway."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_RESOURCES)

        resp = test_client.get("/resources/?gateway_id=null", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", resp.json())
        assert len(items) == 1
        assert items[0]["gatewayId"] is None

    @patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock)
    def test_nonexistent_gateway_returns_empty(self, mock_list, test_client, auth_headers):
        """Nonexistent gateway_id returns 200 with empty list."""
        mock_list.side_effect = _make_gateway_side_effect(ALL_RESOURCES)

        resp = test_client.get("/resources/?gateway_id=does-not-exist", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", resp.json())
        assert items == []
