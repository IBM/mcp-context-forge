# -*- coding: utf-8 -*-
# tests/integration/test_gateway_filtering.py

# Future
from __future__ import annotations

# Standard
import os
import tempfile
from datetime import datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from _pytest.monkeypatch import MonkeyPatch

# First-Party
from mcpgateway.main import app
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.schemas import PromptRead, ResourceRead
import mcpgateway.db as db_mod
from mcpgateway.auth import get_current_user
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db, get_permission_service
from mcpgateway.config import settings

# -----------------------------------------------------------------------------
# Mock Permission Service & RBAC Bypass
# -----------------------------------------------------------------------------
class MockPermissionService:
    def __init__(self, *args, **kwargs): pass
    async def check_permission(self, *args, **kwargs): return True
    def has_permission(self, *args, **kwargs): return True
    def filter_query_by_gateway(self, query, *args, **kwargs): return query

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------
@pytest.fixture
def test_client() -> TestClient:
    mp = MonkeyPatch()
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    mp.setattr(settings, "database_url", url, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_mod.Base.metadata.create_all(bind=engine)

    async def mock_user_ctx():
        yield {
            "email": "admin@example.com",
            "is_admin": True,
            "permissions": ["prompts.read", "resources.read"],
            "assigned_gateways": ["gw-100", "A", "B", "gw-allowed"],
            "db": TestSessionLocal()
        }

    app.dependency_overrides[require_auth] = lambda: "admin-user"
    app.dependency_overrides[get_current_user] = lambda: MagicMock(email="admin@example.com", is_admin=True)
    app.dependency_overrides[get_current_user_with_permissions] = mock_user_ctx
    app.dependency_overrides[get_permission_service] = lambda: MockPermissionService()
    app.dependency_overrides[rbac_get_db] = lambda: TestSessionLocal()

    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        client = TestClient(app)
        yield client

    app.dependency_overrides.clear()
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)

@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token-2026"}

# -----------------------------------------------------------------------------
# Mock Data
# -----------------------------------------------------------------------------
COMMON_META = {
    "created_at": datetime.now(),
    "updated_at": datetime.now(),
    "enabled": True,
    "tags": [],
    "description": "Test description",
    "visibility": "public"
}

MOCK_PROMPT = PromptRead(
    id="p-1",
    name="test_prompt",
    original_name="test_prompt",
    custom_name="Test Prompt",
    custom_name_slug="test-prompt",
    template="Hello",
    arguments=[],
    gateway_id="gw-100",
    **COMMON_META
)

MOCK_RESOURCE = ResourceRead(
    id="r-1",
    uri="file:///test",
    name="test_res",
    mime_type="text/plain",
    size=10,
    metrics=None,
    gateway_id="gw-100",
    **COMMON_META
)

# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
class TestComplexLogicScenarios:

    @patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock)
    def test_prompts_partition_completeness(self, mock_list, test_client, auth_headers):
        p1 = MOCK_PROMPT.model_copy(update={"id": "1", "gateway_id": "A"})
        p2 = MOCK_PROMPT.model_copy(update={"id": "2", "gateway_id": "B"})
        
        async def side_effect(db, gateway_id=None, **kwargs):
            if gateway_id == "A": return ([p1], None)
            if gateway_id == "B": return ([p2], None)
            return ([p1, p2], None)
        
        mock_list.side_effect = side_effect

        resp_total = test_client.get("/prompts/", headers=auth_headers)
        resp_a = test_client.get("/prompts/?gateway_id=A", headers=auth_headers)
        resp_b = test_client.get("/prompts/?gateway_id=B", headers=auth_headers)

        assert resp_total.status_code == 200

        total_data = resp_total.json()
        items = total_data.get("items", total_data) if isinstance(total_data, dict) else total_data
        
        assert len(items) == 2

    @patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock)
    def test_prompts_rbac_regular_user_filter(self, mock_list, test_client):
        async def mock_regular_user():
            yield {
                "email": "user@test.com", "is_admin": False, 
                "assigned_gateways": ["gw-allowed"], "permissions": ["prompts.read"]
            }

        test_client.app.dependency_overrides[get_current_user_with_permissions] = mock_regular_user

        mock_list.return_value = ([MOCK_PROMPT.model_copy(update={"gateway_id": "gw-allowed"})], None)
        
        resp = test_client.get("/prompts/?gateway_id=gw-allowed", headers={"Authorization": "Bearer token"})
        assert resp.status_code == 200

    @patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock)
    def test_unassociated_resources_null_gateway(self, mock_list, test_client, auth_headers):
        r_unassociated = MOCK_RESOURCE.model_copy(update={"id": "none", "gateway_id": None})
        
        async def side_effect(db, gateway_id=None, **kwargs):
            if gateway_id is None or gateway_id == "null":
                return ([r_unassociated], None)
            return ([], None)

        mock_list.side_effect = side_effect

        resp = test_client.get("/resources/?gateway_id=null", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        
        items = data.get("items", data) if isinstance(data, dict) else data
        assert len(items) == 1
        assert items[0]["gatewayId"] is None