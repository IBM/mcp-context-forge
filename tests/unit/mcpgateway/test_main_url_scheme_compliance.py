# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_main_url_scheme_compliance.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for _check_url_scheme_compliance startup check.
"""

# Standard
from collections import namedtuple
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.exc import SQLAlchemyError


# First-Party
from mcpgateway.main import _check_url_scheme_compliance

GwRow = namedtuple("GwRow", ["id", "name", "url"])
ToolRow = namedtuple("ToolRow", ["id", "original_name", "url"])
AgentRow = namedtuple("AgentRow", ["id", "name", "endpoint_url"])


def _mock_session(gateways=None, tools=None, agents=None):
    """Build a mock SessionLocal context manager returning canned query results."""
    gateways = gateways or []
    tools = tools or []
    agents = agents or []

    mock_db = MagicMock()

    def fake_query(*cols):
        # Identify which model by checking the first column's parent class name.
        parent = cols[0].class_.__name__
        mock_q = MagicMock()
        if parent == "Gateway":
            mock_q.filter.return_value.all.return_value = gateways
        elif parent == "Tool":
            mock_q.filter.return_value.all.return_value = tools
        elif parent == "A2AAgent":
            mock_q.filter.return_value.all.return_value = agents
        else:
            mock_q.filter.return_value.all.return_value = []
        return mock_q

    mock_db.query.side_effect = fake_query
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_no_violations_is_silent():
    """No warnings or exits when all URLs use allowed schemes."""
    ctx = _mock_session(
        gateways=[GwRow("g1", "gw", "https://ok.example.com")],
        tools=[ToolRow("t1", "tool", "http://ok.example.com")],
        agents=[AgentRow("a1", "agent", "https://ok.example.com")],
    )
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
    ):
        _check_url_scheme_compliance()
    mock_logger.warning.assert_not_called()


def test_gateway_violation_logged():
    """A gateway with a disallowed scheme produces a warning."""
    ctx = _mock_session(gateways=[GwRow("g1", "bad-gw", "ftp://evil.example.com")])
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    assert mock_logger.warning.call_count == 1
    assert "bad-gw" in mock_logger.warning.call_args[0][0]


def test_tool_violation_logged():
    """A tool with a disallowed scheme produces a warning."""
    ctx = _mock_session(tools=[ToolRow("t1", "bad-tool", "ftp://evil.example.com")])
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    assert mock_logger.warning.call_count == 1
    assert "bad-tool" in mock_logger.warning.call_args[0][0]


def test_agent_violation_logged():
    """An A2A agent with a disallowed scheme produces a warning."""
    ctx = _mock_session(agents=[AgentRow("a1", "bad-agent", "ftp://evil.example.com")])
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    assert mock_logger.warning.call_count == 1
    assert "bad-agent" in mock_logger.warning.call_args[0][0]


def test_agent_violation_with_per_table_scan():
    """Agent violations are collected even when scanned per-table."""
    ctx = _mock_session(
        gateways=[GwRow("g1", "ok-gw", "https://ok.example.com")],
        agents=[AgentRow("a1", "bad-agent", "ftp://evil.example.com")],
    )
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    warning_messages = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("bad-agent" in m for m in warning_messages)


def test_strict_enforcement_raises_system_exit():
    """SystemExit raised when strict_scheme_enforcement is True and violations exist."""
    ctx = _mock_session(gateways=[GwRow("g1", "bad-gw", "ftp://evil.example.com")])
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger"),
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = True
        with pytest.raises(SystemExit, match="STRICT_SCHEME_ENFORCEMENT"):
            _check_url_scheme_compliance()


def test_multiple_violations_all_logged():
    """Each violation across entity types produces its own warning."""
    ctx = _mock_session(
        gateways=[GwRow("g1", "gw", "ftp://a")],
        tools=[ToolRow("t1", "tool", "ftp://b")],
        agents=[AgentRow("a1", "agent", "ftp://c")],
    )
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    assert mock_logger.warning.call_count == 3


def test_disabled_records_excluded():
    """Disabled records are not scanned (the query filters on enabled=True)."""
    mock_db = MagicMock()
    # Return no rows for every query — simulates no enabled records
    mock_db.query.return_value.filter.return_value.all.return_value = []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["http://", "https://"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    mock_logger.warning.assert_not_called()
    # Verify filter was called exactly 3 times (Gateway, Tool, A2AAgent) with the enabled clause
    filter_mock = mock_db.query.return_value.filter
    assert filter_mock.call_count == 3, f"Expected 3 filter() calls, got {filter_mock.call_count}"
    for call in filter_mock.call_args_list:
        assert call.args, "filter() must receive at least one argument (the enabled clause)"


def test_none_and_empty_urls_skipped():
    """Records with None or empty URLs are silently skipped (no violation)."""
    ctx = _mock_session(
        gateways=[GwRow("g1", "null-gw", None), GwRow("g2", "empty-gw", "")],
        tools=[ToolRow("t1", "null-tool", None)],
        agents=[AgentRow("a1", "empty-agent", "")],
    )
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
    ):
        _check_url_scheme_compliance()
    mock_logger.warning.assert_not_called()


def test_mixed_case_scheme_accepted():
    """Mixed-case schemes like HTTPS:// match the allowlist (case-insensitive)."""
    ctx = _mock_session(
        gateways=[GwRow("g1", "upper-gw", "HTTPS://example.com")],
        tools=[ToolRow("t1", "mixed-tool", "Http://example.com")],
    )
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.logger") as mock_logger,
    ):
        _check_url_scheme_compliance()
    mock_logger.warning.assert_not_called()


def test_db_error_strict_mode_exits():
    """Strict mode raises SystemExit when the compliance query fails."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(side_effect=SQLAlchemyError("connection refused"))
    ctx.__exit__ = MagicMock(return_value=False)
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.settings") as mock_settings,
    ):
        mock_settings.validation_allowed_url_schemes = ["https"]
        mock_settings.strict_scheme_enforcement = True
        with pytest.raises(SystemExit, match="STRICT_SCHEME_ENFORCEMENT"):
            _check_url_scheme_compliance()


def test_db_error_nonstrict_mode_warns():
    """Non-strict mode logs a warning and returns when the compliance query fails."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(side_effect=SQLAlchemyError("connection refused"))
    ctx.__exit__ = MagicMock(return_value=False)
    with (
        patch("mcpgateway.main.SessionLocal", return_value=ctx),
        patch("mcpgateway.main.settings") as mock_settings,
        patch("mcpgateway.main.logger") as mock_logger,
    ):
        mock_settings.validation_allowed_url_schemes = ["https"]
        mock_settings.strict_scheme_enforcement = False
        _check_url_scheme_compliance()
    mock_logger.warning.assert_called_once_with("URL scheme compliance check skipped: database unavailable")
