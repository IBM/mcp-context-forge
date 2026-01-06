# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch
from mcpgateway.services.system_stats_service import SystemStatsService


@pytest.fixture
def mock_db():
    """Mock database session for aggregated query pattern (db.execute(select(...)).one())"""
    m = MagicMock()

    # Mock the new aggregated query pattern
    mock_result = MagicMock()
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    mock_execute.all.return_value = []
    m.execute.return_value = mock_execute

    return m


@pytest.fixture
def mock_db_user_stats():
    """Mock for user stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.total = 10
    mock_result.active = 7
    mock_result.admins = 2
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_team_stats():
    """Mock for team stats query (2 queries: one for teams, one scalar for members)"""
    m = MagicMock()
    mock_team_result = MagicMock()
    mock_team_result.total_teams = 5
    mock_team_result.personal_teams = 3

    call_count = [0]

    def mock_execute_side_effect(stmt):
        result = MagicMock()
        if call_count[0] == 0:  # team stats aggregated query
            result.one.return_value = mock_team_result
        else:  # team_members scalar query
            result.scalar.return_value = 15
        call_count[0] += 1
        return result

    m.execute.side_effect = mock_execute_side_effect
    return m


@pytest.fixture
def mock_db_mcp_resource_stats():
    """Mock for MCP resource stats query (UNION ALL pattern)"""
    m = MagicMock()
    mock_results = [
        MagicMock(type="servers", cnt=2),
        MagicMock(type="gateways", cnt=1),
        MagicMock(type="tools", cnt=50),
        MagicMock(type="resources", cnt=100),
        MagicMock(type="prompts", cnt=30),
        MagicMock(type="a2a_agents", cnt=5),
    ]
    mock_execute = MagicMock()
    mock_execute.all.return_value = mock_results
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_token_stats():
    """Mock for token stats query (2 queries: one for tokens, one scalar for revoked)"""
    m = MagicMock()
    mock_token_result = MagicMock()
    mock_token_result.total = 20
    mock_token_result.active = 15

    call_count = [0]

    def mock_execute_side_effect(stmt):
        result = MagicMock()
        if call_count[0] == 0:  # token stats aggregated query
            result.one.return_value = mock_token_result
        else:  # revoked scalar query
            result.scalar.return_value = 5
        call_count[0] += 1
        return result

    m.execute.side_effect = mock_execute_side_effect
    return m


@pytest.fixture
def mock_db_session_stats():
    """Mock for session stats query (UNION ALL pattern)"""
    m = MagicMock()
    mock_results = [
        MagicMock(type="mcp_sessions", cnt=8),
        MagicMock(type="mcp_messages", cnt=100),
        MagicMock(type="subscriptions", cnt=12),
        MagicMock(type="oauth_tokens", cnt=3),
    ]
    mock_execute = MagicMock()
    mock_execute.all.return_value = mock_results
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_metrics_stats():
    """Mock for metrics stats query (UNION ALL pattern)"""
    m = MagicMock()
    mock_results = [
        MagicMock(type="tool_metrics", cnt=500),
        MagicMock(type="resource_metrics", cnt=200),
        MagicMock(type="prompt_metrics", cnt=150),
        MagicMock(type="server_metrics", cnt=50),
        MagicMock(type="a2a_agent_metrics", cnt=25),
        MagicMock(type="token_usage_logs", cnt=75),
    ]
    mock_execute = MagicMock()
    mock_execute.all.return_value = mock_results
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_security_stats():
    """Mock for security stats query (UNION ALL pattern)"""
    m = MagicMock()
    mock_results = [
        MagicMock(type="auth_events", cnt=1000),
        MagicMock(type="audit_logs", cnt=500),
        MagicMock(type="pending_approvals", cnt=10),
        MagicMock(type="sso_providers", cnt=2),
    ]
    mock_execute = MagicMock()
    mock_execute.all.return_value = mock_results
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_workflow_stats():
    """Mock for workflow stats query (UNION ALL pattern)"""
    m = MagicMock()
    mock_results = [
        MagicMock(type="invitations", cnt=5),
        MagicMock(type="join_requests", cnt=3),
    ]
    mock_execute = MagicMock()
    mock_execute.all.return_value = mock_results
    m.execute.return_value = mock_execute
    return m


def test_get_user_stats(mock_db_user_stats):
    """Test user stats aggregation (3 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_user_stats(mock_db_user_stats)
    assert stats["total"] == 10
    assert stats["breakdown"]["active"] == 7
    assert stats["breakdown"]["inactive"] == 3
    assert stats["breakdown"]["admins"] == 2


def test_team_stats(mock_db_team_stats):
    """Test team stats aggregation (3 queries → 2)"""
    service = SystemStatsService()
    stats = service._get_team_stats(mock_db_team_stats)
    assert stats["total"] == 5
    assert stats["breakdown"]["personal"] == 3
    assert stats["breakdown"]["organizational"] == 2
    assert stats["breakdown"]["members"] == 15


def test_mcp_resource_stats(mock_db_mcp_resource_stats):
    """Test MCP resource stats using UNION ALL (6 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_mcp_resource_stats(mock_db_mcp_resource_stats)
    assert stats["total"] == 188  # 2+1+50+100+30+5
    assert stats["breakdown"]["servers"] == 2
    assert stats["breakdown"]["gateways"] == 1
    assert stats["breakdown"]["tools"] == 50
    assert stats["breakdown"]["resources"] == 100
    assert stats["breakdown"]["prompts"] == 30
    assert stats["breakdown"]["a2a_agents"] == 5


def test_token_stats(mock_db_token_stats):
    """Test token stats aggregation (3 queries → 2)"""
    service = SystemStatsService()
    stats = service._get_token_stats(mock_db_token_stats)
    assert stats["total"] == 20
    assert stats["breakdown"]["active"] == 15
    assert stats["breakdown"]["inactive"] == 5
    assert stats["breakdown"]["revoked"] == 5


def test_session_stats(mock_db_session_stats):
    """Test session stats using UNION ALL (4 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_session_stats(mock_db_session_stats)
    assert stats["total"] == 123  # 8+100+12+3
    assert stats["breakdown"]["mcp_sessions"] == 8
    assert stats["breakdown"]["mcp_messages"] == 100
    assert stats["breakdown"]["subscriptions"] == 12
    assert stats["breakdown"]["oauth_tokens"] == 3


def test_metrics_stats(mock_db_metrics_stats):
    """Test metrics stats using UNION ALL (6 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_metrics_stats(mock_db_metrics_stats)
    assert stats["total"] == 1000  # 500+200+150+50+25+75
    assert stats["breakdown"]["tool_metrics"] == 500
    assert stats["breakdown"]["resource_metrics"] == 200
    assert stats["breakdown"]["prompt_metrics"] == 150
    assert stats["breakdown"]["server_metrics"] == 50
    assert stats["breakdown"]["a2a_agent_metrics"] == 25
    assert stats["breakdown"]["token_usage_logs"] == 75


def test_security_stats(mock_db_security_stats):
    """Test security stats using UNION ALL (4 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_security_stats(mock_db_security_stats)
    assert stats["total"] == 1510  # 1000+500+10
    assert stats["breakdown"]["auth_events"] == 1000
    assert stats["breakdown"]["audit_logs"] == 500
    assert stats["breakdown"]["pending_approvals"] == 10
    assert stats["breakdown"]["sso_providers"] == 2


def test_workflow_stats(mock_db_workflow_stats):
    """Test workflow stats using UNION ALL (2 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_workflow_stats(mock_db_workflow_stats)
    assert stats["total"] == 8  # 5+3
    assert stats["breakdown"]["team_invitations"] == 5
    assert stats["breakdown"]["join_requests"] == 3


def test_get_comprehensive_stats_success():
    """Test comprehensive stats collection with all categories"""
    service = SystemStatsService()

    # Create a comprehensive mock database
    mock_db = MagicMock()

    # Mock all the execute calls - now with correct patterns for each method
    call_count = [0]

    def mock_execute_side_effect(stmt):
        result = MagicMock()
        idx = call_count[0]

        if idx == 0:  # user stats - .one()
            mock_user = MagicMock(total=10, active=7, admins=2)
            result.one.return_value = mock_user
        elif idx == 1:  # team stats aggregated - .one()
            mock_team = MagicMock(total_teams=5, personal_teams=3)
            result.one.return_value = mock_team
        elif idx == 2:  # team members - .scalar()
            result.scalar.return_value = 15
        elif idx == 3:  # mcp stats - .all() UNION ALL
            result.all.return_value = [
                MagicMock(type="servers", cnt=2),
                MagicMock(type="gateways", cnt=1),
                MagicMock(type="tools", cnt=50),
                MagicMock(type="resources", cnt=100),
                MagicMock(type="prompts", cnt=30),
                MagicMock(type="a2a_agents", cnt=5),
            ]
        elif idx == 4:  # token stats aggregated - .one()
            mock_token = MagicMock(total=20, active=15)
            result.one.return_value = mock_token
        elif idx == 5:  # revoked tokens - .scalar()
            result.scalar.return_value = 5
        elif idx == 6:  # session stats - .all() UNION ALL
            result.all.return_value = [
                MagicMock(type="mcp_sessions", cnt=8),
                MagicMock(type="mcp_messages", cnt=100),
                MagicMock(type="subscriptions", cnt=12),
                MagicMock(type="oauth_tokens", cnt=3),
            ]
        elif idx == 7:  # metrics stats - .all() UNION ALL
            result.all.return_value = [
                MagicMock(type="tool_metrics", cnt=500),
                MagicMock(type="resource_metrics", cnt=200),
                MagicMock(type="prompt_metrics", cnt=150),
                MagicMock(type="server_metrics", cnt=50),
                MagicMock(type="a2a_agent_metrics", cnt=25),
                MagicMock(type="token_usage_logs", cnt=75),
            ]
        elif idx == 8:  # security stats - .all() UNION ALL
            result.all.return_value = [
                MagicMock(type="auth_events", cnt=1000),
                MagicMock(type="audit_logs", cnt=500),
                MagicMock(type="pending_approvals", cnt=10),
                MagicMock(type="sso_providers", cnt=2),
            ]
        elif idx == 9:  # workflow stats - .all() UNION ALL
            result.all.return_value = [
                MagicMock(type="invitations", cnt=5),
                MagicMock(type="join_requests", cnt=3),
            ]

        call_count[0] += 1
        return result

    mock_db.execute.side_effect = mock_execute_side_effect

    result = service.get_comprehensive_stats(mock_db)
    expected_keys = [
        "users", "teams", "mcp_resources", "tokens",
        "sessions", "metrics", "security", "workflow"
    ]
    for key in expected_keys:
        assert key in result
        assert "total" in result[key]
        assert isinstance(result[key]["breakdown"], dict)


def test_get_comprehensive_stats_error():
    """Test error handling in comprehensive stats collection"""
    service = SystemStatsService()
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Database connection failed")

    with pytest.raises(Exception, match="Database connection failed"):
        service.get_comprehensive_stats(mock_db)
