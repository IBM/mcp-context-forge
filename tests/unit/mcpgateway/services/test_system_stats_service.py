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
    """Mock for team stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.total_teams = 5
    mock_result.personal_teams = 3
    mock_result.team_members = 15
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
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
    """Mock for token stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.total = 20
    mock_result.active = 15
    mock_result.revoked = 5
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_session_stats():
    """Mock for session stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.mcp_sessions = 8
    mock_result.mcp_messages = 100
    mock_result.subscriptions = 12
    mock_result.oauth_tokens = 3
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_metrics_stats():
    """Mock for metrics stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.tool_metrics = 500
    mock_result.resource_metrics = 200
    mock_result.prompt_metrics = 150
    mock_result.server_metrics = 50
    mock_result.a2a_agent_metrics = 25
    mock_result.token_usage_logs = 75
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_security_stats():
    """Mock for security stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.auth_events = 1000
    mock_result.audit_logs = 500
    mock_result.pending_approvals = 10
    mock_result.sso_providers = 2
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
    m.execute.return_value = mock_execute
    return m


@pytest.fixture
def mock_db_workflow_stats():
    """Mock for workflow stats query"""
    m = MagicMock()
    mock_result = MagicMock()
    mock_result.invitations = 5
    mock_result.join_requests = 3
    mock_execute = MagicMock()
    mock_execute.one.return_value = mock_result
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
    """Test team stats aggregation (3 queries → 1)"""
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
    """Test token stats aggregation (3 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_token_stats(mock_db_token_stats)
    assert stats["total"] == 20
    assert stats["breakdown"]["active"] == 15
    assert stats["breakdown"]["inactive"] == 5
    assert stats["breakdown"]["revoked"] == 5


def test_session_stats(mock_db_session_stats):
    """Test session stats aggregation (4 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_session_stats(mock_db_session_stats)
    assert stats["total"] == 123  # 8+100+12+3
    assert stats["breakdown"]["mcp_sessions"] == 8
    assert stats["breakdown"]["mcp_messages"] == 100
    assert stats["breakdown"]["subscriptions"] == 12
    assert stats["breakdown"]["oauth_tokens"] == 3


def test_metrics_stats(mock_db_metrics_stats):
    """Test metrics stats aggregation (6 queries → 1)"""
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
    """Test security stats aggregation (4 queries → 1)"""
    service = SystemStatsService()
    stats = service._get_security_stats(mock_db_security_stats)
    assert stats["total"] == 1510  # 1000+500+10
    assert stats["breakdown"]["auth_events"] == 1000
    assert stats["breakdown"]["audit_logs"] == 500
    assert stats["breakdown"]["pending_approvals"] == 10
    assert stats["breakdown"]["sso_providers"] == 2


def test_workflow_stats(mock_db_workflow_stats):
    """Test workflow stats aggregation (2 queries → 1)"""
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
    
    # Mock all the execute calls
    mock_results = {
        "user": MagicMock(total=10, active=7, admins=2),
        "team": MagicMock(total_teams=5, personal_teams=3, team_members=15),
        "mcp": [
            MagicMock(type="servers", cnt=2),
            MagicMock(type="gateways", cnt=1),
            MagicMock(type="tools", cnt=50),
            MagicMock(type="resources", cnt=100),
            MagicMock(type="prompts", cnt=30),
            MagicMock(type="a2a_agents", cnt=5),
        ],
        "token": MagicMock(total=20, active=15, revoked=5),
        "session": MagicMock(mcp_sessions=8, mcp_messages=100, subscriptions=12, oauth_tokens=3),
        "metrics": MagicMock(
            tool_metrics=500, resource_metrics=200, prompt_metrics=150,
            server_metrics=50, a2a_agent_metrics=25, token_usage_logs=75
        ),
        "security": MagicMock(auth_events=1000, audit_logs=500, pending_approvals=10, sso_providers=2),
        "workflow": MagicMock(invitations=5, join_requests=3),
    }
    
    # Configure mock to return appropriate result for each call
    call_count = [0]
    
    def mock_execute_side_effect(stmt):
        result = MagicMock()
        if call_count[0] == 0:  # user stats
            result.one.return_value = mock_results["user"]
            result.all.return_value = []
        elif call_count[0] == 1:  # team stats
            result.one.return_value = mock_results["team"]
            result.all.return_value = []
        elif call_count[0] == 2:  # mcp stats
            result.one.return_value = None
            result.all.return_value = mock_results["mcp"]
        elif call_count[0] == 3:  # token stats
            result.one.return_value = mock_results["token"]
            result.all.return_value = []
        elif call_count[0] == 4:  # session stats
            result.one.return_value = mock_results["session"]
            result.all.return_value = []
        elif call_count[0] == 5:  # metrics stats
            result.one.return_value = mock_results["metrics"]
            result.all.return_value = []
        elif call_count[0] == 6:  # security stats
            result.one.return_value = mock_results["security"]
            result.all.return_value = []
        elif call_count[0] == 7:  # workflow stats
            result.one.return_value = mock_results["workflow"]
            result.all.return_value = []
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
