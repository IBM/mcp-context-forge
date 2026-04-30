# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_trace_context.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for trace context helpers.
"""

# First-Party
from mcpgateway.utils.trace_context import (
    clear_trace_context,
    format_trace_team_scope,
    get_trace_auth_method,
    get_trace_session_id,
    get_trace_team_name,
    get_trace_team_scope,
    get_trace_user_email,
    get_trace_user_is_admin,
    primary_team_name_from_teams,
    primary_team_from_scope,
    set_trace_context_from_teams,
    set_trace_session_id,
)


def setup_function():
    clear_trace_context()


def teardown_function():
    clear_trace_context()


def test_format_trace_team_scope_handles_admin_public_and_truncation():
    assert format_trace_team_scope(None) == "admin"
    assert format_trace_team_scope([]) == "public"
    assert format_trace_team_scope([{"id": "team-1"}, "team-2", "", None]) == "team-1,team-2"
    assert format_trace_team_scope(["t1", "t2", "t3"], max_teams=2) == "t1,t2,..."


def test_primary_team_from_scope_ignores_special_labels():
    assert primary_team_from_scope("team-a,team-b") == "team-a"
    assert primary_team_from_scope("admin") is None
    assert primary_team_from_scope("public") is None
    assert primary_team_from_scope(None) is None


def test_primary_team_name_from_teams_tracks_primary_team_only():
    assert primary_team_name_from_teams([{"id": "team-a", "name": "Team A"}, {"id": "team-b", "name": "Team B"}]) == "Team A"
    assert primary_team_name_from_teams(["team-a", {"id": "team-b", "name": "Team B"}]) is None
    assert primary_team_name_from_teams([]) is None
    assert primary_team_name_from_teams(None) is None


def test_set_trace_context_from_teams_populates_context():
    set_trace_context_from_teams(["team-a", "team-b"], user_email="user@example.com", is_admin=True, auth_method="jwt")
    set_trace_session_id("session-123")

    assert get_trace_user_email() == "user@example.com"
    assert get_trace_user_is_admin() is True
    assert get_trace_team_scope() == "team-a,team-b"
    assert get_trace_team_name() is None
    assert get_trace_auth_method() == "jwt"
    assert get_trace_session_id() == "session-123"

    clear_trace_context()

    assert get_trace_user_email() is None
    assert get_trace_user_is_admin() is False
    assert get_trace_team_scope() is None
    assert get_trace_team_name() is None
    assert get_trace_auth_method() is None
    assert get_trace_session_id() is None


def test_set_trace_context_from_teams_preserves_primary_team_name():
    set_trace_context_from_teams([{"id": "team-a", "name": "Team A"}, {"id": "team-b", "name": "Team B"}], user_email="user@example.com", is_admin=False, auth_method="jwt")

    assert get_trace_team_scope() == "team-a,team-b"
    assert get_trace_team_name() == "Team A"
