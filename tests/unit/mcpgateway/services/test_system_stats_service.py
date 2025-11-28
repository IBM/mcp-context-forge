# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
from mcpgateway.services.system_stats_service import SystemStatsService


@pytest.fixture
def mock_db():
    m = MagicMock()
    q = MagicMock()
    q.scalar.return_value = 1
    q.filter.return_value = q
    m.query.return_value = q
    return m


def test_get_user_stats(mock_db):
    service = SystemStatsService()
    stats = service._get_user_stats(mock_db)
    assert stats["total"] == 1
    assert "active" in stats["breakdown"]
    assert isinstance(stats["breakdown"]["admins"], int)


def test_team_stats(mock_db):
    service = SystemStatsService()
    stats = service._get_team_stats(mock_db)
    assert stats["total"] == 1
    assert "personal" in stats["breakdown"]
    assert "members" in stats["breakdown"]


@pytest.mark.parametrize("method", [
    "_get_mcp_resource_stats",
    "_get_token_stats",
    "_get_session_stats",
    "_get_metrics_stats",
    "_get_security_stats",
    "_get_workflow_stats",
])
def test_each_stats_method(mock_db, method):
    service = SystemStatsService()
    result = getattr(service, method)(mock_db)
    assert "total" in result
    assert "breakdown" in result
    assert isinstance(result["breakdown"], dict)


def test_get_comprehensive_stats_success(mock_db):
    service = SystemStatsService()
    result = service.get_comprehensive_stats(mock_db)
    expected_keys = [
        "users", "teams", "mcp_resources", "tokens",
        "sessions", "metrics", "security", "workflow"
    ]
    for key in expected_keys:
        assert key in result
        assert "total" in result[key]
        assert isinstance(result[key]["breakdown"], dict)


def test_get_comprehensive_stats_error(mock_db):
    service = SystemStatsService()
    with patch.object(service, "_get_user_stats", side_effect=Exception("db fail")):
        with pytest.raises(Exception):
            service.get_comprehensive_stats(mock_db)
