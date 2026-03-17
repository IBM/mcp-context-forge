# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_pagination_bounds.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for pagination parameter bounds.
Verifies that endpoints use settings.pagination_max_page_size instead of
hardcoded le=100 for pagination Query parameters.

Related: GitHub issue #3469 (UI pagination 422 response).
"""

# Standard
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi.params import Query as QueryInfo
import pytest

# First-Party
from mcpgateway.config import settings


def _get_query_le(func, param_name: str):
    """Extract the 'le' constraint from a FastAPI Query parameter default.

    Inspects the wrapped function if @require_permission was applied.

    Args:
        func: The endpoint function (possibly decorated).
        param_name: Name of the Query parameter to inspect.

    Returns:
        The ``le`` value from the Query metadata, or ``None`` if not found.
    """
    target = getattr(func, "__wrapped__", func)
    sig = inspect.signature(target)
    param = sig.parameters[param_name]
    default = param.default
    if isinstance(default, QueryInfo):
        for m in default.metadata:
            if hasattr(m, "le"):
                return m.le
    return None


class TestPaginationBoundsMetadata:
    """Verify Query parameter le= constraints reference settings.pagination_max_page_size."""

    def test_admin_search_teams_limit_bound(self):
        # First-Party
        from mcpgateway.admin import admin_search_teams

        le = _get_query_le(admin_search_teams, "limit")
        assert le == settings.pagination_max_page_size

    def test_admin_teams_partial_html_per_page_bound(self):
        # First-Party
        from mcpgateway.admin import admin_teams_partial_html

        le = _get_query_le(admin_teams_partial_html, "per_page")
        assert le == settings.pagination_max_page_size

    def test_admin_list_teams_per_page_bound(self):
        # First-Party
        from mcpgateway.admin import admin_list_teams

        le = _get_query_le(admin_list_teams, "per_page")
        assert le == settings.pagination_max_page_size

    def test_admin_search_tokens_limit_bound(self):
        # First-Party
        from mcpgateway.admin import admin_search_tokens

        le = _get_query_le(admin_search_tokens, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_top_slow_endpoints_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_top_slow_endpoints

        le = _get_query_le(get_top_slow_endpoints, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_top_volume_endpoints_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_top_volume_endpoints

        le = _get_query_le(get_top_volume_endpoints, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_top_error_endpoints_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_top_error_endpoints

        le = _get_query_le(get_top_error_endpoints, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_latency_heatmap_time_buckets_not_pagination(self):
        """time_buckets is a visualization param — should keep le=100, not pagination_max_page_size."""
        # First-Party
        from mcpgateway.admin import get_latency_heatmap

        le = _get_query_le(get_latency_heatmap, "time_buckets")
        assert le == 100

    def test_get_tool_usage_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_tool_usage

        le = _get_query_le(get_tool_usage, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_tool_performance_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_tool_performance

        le = _get_query_le(get_tool_performance, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_tool_errors_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_tool_errors

        le = _get_query_le(get_tool_errors, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_tool_chains_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_tool_chains

        le = _get_query_le(get_tool_chains, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_prompt_usage_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_prompt_usage

        le = _get_query_le(get_prompt_usage, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_prompt_performance_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_prompt_performance

        le = _get_query_le(get_prompt_performance, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_resource_usage_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_resource_usage

        le = _get_query_le(get_resource_usage, "limit")
        assert le == settings.pagination_max_page_size

    def test_get_resource_performance_limit_bound(self):
        # First-Party
        from mcpgateway.admin import get_resource_performance

        le = _get_query_le(get_resource_performance, "limit")
        assert le == settings.pagination_max_page_size

    def test_teams_router_list_teams_limit_bound(self):
        # First-Party
        from mcpgateway.routers.teams import list_teams

        le = _get_query_le(list_teams, "limit")
        assert le == settings.pagination_max_page_size

    def test_teams_router_discover_public_teams_limit_bound(self):
        # First-Party
        from mcpgateway.routers.teams import discover_public_teams

        le = _get_query_le(discover_public_teams, "limit")
        assert le == settings.pagination_max_page_size

    def test_llm_admin_router_providers_per_page_bound(self):
        # First-Party
        from mcpgateway.routers.llm_admin_router import get_providers_partial

        le = _get_query_le(get_providers_partial, "per_page")
        assert le == settings.pagination_max_page_size

    def test_llm_admin_router_models_per_page_bound(self):
        # First-Party
        from mcpgateway.routers.llm_admin_router import get_models_partial

        le = _get_query_le(get_models_partial, "per_page")
        assert le == settings.pagination_max_page_size

    def test_llm_config_router_list_providers_page_size_bound(self):
        # First-Party
        from mcpgateway.routers.llm_config_router import list_providers

        le = _get_query_le(list_providers, "page_size")
        assert le == settings.pagination_max_page_size

    def test_llm_config_router_list_models_page_size_bound(self):
        # First-Party
        from mcpgateway.routers.llm_config_router import list_models

        le = _get_query_le(list_models, "page_size")
        assert le == settings.pagination_max_page_size


class TestPaginationBoundsFunction:
    """Verify endpoint functions accept limit/per_page values above 100 (previously rejected)."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.query.return_value = MagicMock()
        db.query.return_value.filter.return_value = db.query.return_value
        db.query.return_value.order_by.return_value = db.query.return_value
        db.query.return_value.limit.return_value = db.query.return_value
        db.query.return_value.all.return_value = []
        db.commit = MagicMock()
        db.close = MagicMock()
        return db

    @pytest.fixture
    def allow_permission(self, monkeypatch):
        monkeypatch.setattr("mcpgateway.admin.PermissionService", lambda db: MagicMock(check_permission=AsyncMock(return_value=True)))

    @pytest.mark.asyncio
    async def test_admin_search_teams_limit_200(self, monkeypatch, allow_permission, mock_db):
        # First-Party
        from mcpgateway.admin import admin_search_teams

        mock_auth = MagicMock()
        admin_user = SimpleNamespace(is_admin=True)
        mock_auth.get_user_by_email = AsyncMock(return_value=admin_user)
        monkeypatch.setattr("mcpgateway.admin.EmailAuthService", lambda db: mock_auth)

        ts = MagicMock()
        ts.list_teams = AsyncMock(return_value={"data": []})
        monkeypatch.setattr("mcpgateway.admin.TeamManagementService", lambda db: ts)

        result = await admin_search_teams(q="test", include_inactive=False, limit=200, visibility=None, db=mock_db, user={"email": "admin@test.com"})
        assert result == []

    @pytest.mark.asyncio
    async def test_get_top_slow_endpoints_limit_200(self, monkeypatch, mock_db):
        # First-Party
        from mcpgateway.admin import get_top_slow_endpoints

        row = SimpleNamespace(http_url="/slow", http_method="GET", count=1, avg_duration=10.0, max_duration=20.0)
        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = [row]
        mock_db.query.return_value = query_mock
        monkeypatch.setattr("mcpgateway.admin.get_db", lambda: iter([mock_db]))

        result = await get_top_slow_endpoints(request=MagicMock(), hours=24, limit=200, _user={"email": "admin@test.com", "db": mock_db})
        assert "endpoints" in result
        assert len(result["endpoints"]) == 1

    @pytest.mark.asyncio
    async def test_get_tool_usage_limit_200(self, monkeypatch, allow_permission):
        # First-Party
        from mcpgateway.admin import get_tool_usage

        request = MagicMock()
        session = MagicMock()
        session.query.return_value.filter.return_value.group_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        session.commit = MagicMock()
        session.close = MagicMock()
        monkeypatch.setattr("mcpgateway.admin.get_db", lambda: iter([session]))

        result = await get_tool_usage(request, hours=24, limit=200, _user={"email": "admin@test.com"}, db=session)
        assert "tools" in result
