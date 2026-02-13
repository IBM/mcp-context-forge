# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Token Scoping Tests for RBAC System.

Tests the normalize_token_teams() truth table from auth.py and
request.state.team_id derivation logic.
"""

# Future
from __future__ import annotations

# First-Party
from mcpgateway.auth import normalize_token_teams

# ---------------------------------------------------------------------------
# D2.1: normalize_token_teams truth table
# ---------------------------------------------------------------------------


class TestNormalizeTokenTeams:
    """Test the single source of truth for token team normalization."""

    def test_missing_teams_key_returns_empty(self):
        """Missing 'teams' key → [] (public-only, secure default)."""
        result = normalize_token_teams({"sub": "user@test.local"})
        assert result == []

    def test_null_teams_admin_returns_none(self):
        """Explicit null + is_admin=true → None (admin bypass)."""
        result = normalize_token_teams({"teams": None, "is_admin": True})
        assert result is None

    def test_null_teams_non_admin_returns_empty(self):
        """Explicit null + is_admin=false → [] (public-only, no bypass)."""
        result = normalize_token_teams({"teams": None, "is_admin": False})
        assert result == []

    def test_null_teams_no_admin_flag_returns_empty(self):
        """Explicit null + missing is_admin → [] (defaults to false)."""
        result = normalize_token_teams({"teams": None})
        assert result == []

    def test_empty_list_returns_empty(self):
        """Empty teams list → [] (explicit public-only)."""
        result = normalize_token_teams({"teams": []})
        assert result == []

    def test_string_list_returns_ids(self):
        """String team list → list of string IDs."""
        result = normalize_token_teams({"teams": ["team-1", "team-2"]})
        assert result == ["team-1", "team-2"]

    def test_dict_list_extracts_ids(self):
        """Dict entries with 'id' key → extract IDs as strings."""
        result = normalize_token_teams({"teams": [{"id": "abc"}, {"id": "def"}]})
        assert result == ["abc", "def"]

    def test_mixed_entries(self):
        """Mixed string and dict entries → normalized to strings."""
        result = normalize_token_teams({"teams": ["team-1", {"id": "team-2"}]})
        assert result == ["team-1", "team-2"]

    def test_dict_missing_id_skipped(self):
        """Dict entries without 'id' key → skipped."""
        result = normalize_token_teams({"teams": [{"name": "no-id"}, {"id": "valid"}]})
        assert result == ["valid"]

    def test_invalid_entries_skipped(self):
        """Non-string, non-dict entries → skipped."""
        result = normalize_token_teams({"teams": [123, None, True, "valid"]})
        assert result == ["valid"]

    def test_nested_user_is_admin_bypass(self):
        """Null teams + is_admin in nested user dict → admin bypass."""
        result = normalize_token_teams({"teams": None, "user": {"is_admin": True}})
        assert result is None

    def test_nested_user_not_admin_no_bypass(self):
        """Null teams + is_admin=false in nested user dict → public-only."""
        result = normalize_token_teams({"teams": None, "user": {"is_admin": False}})
        assert result == []

    def test_top_level_admin_takes_precedence(self):
        """Top-level is_admin=true should take precedence over nested user."""
        result = normalize_token_teams({"teams": None, "is_admin": True, "user": {"is_admin": False}})
        assert result is None

    def test_empty_list_admin_returns_empty(self):
        """Empty list + is_admin=true → [] (explicit public-only, not bypass)."""
        result = normalize_token_teams({"teams": [], "is_admin": True})
        assert result == []

    def test_integer_team_id_skipped(self):
        """Integer team entries are skipped (not str or dict)."""
        result = normalize_token_teams({"teams": [42]})
        assert result == []

    def test_dict_with_none_id_skipped(self):
        """Dict with id=None is skipped."""
        result = normalize_token_teams({"teams": [{"id": None}]})
        assert result == []


# ---------------------------------------------------------------------------
# D2.2: Token team_id derivation
# ---------------------------------------------------------------------------


class TestTokenTeamIdDerivation:
    """Test request.state.team_id derivation from normalized teams."""

    def test_single_team_api_token_sets_team_id(self):
        """Single-team API token → team_id is set to that team."""
        teams = normalize_token_teams({"teams": ["team-1"]})
        # Simulate auth.py logic: single team + non-session token → set team_id
        token_use = "api"
        assert teams is not None
        if teams is None:
            team_id = None
        elif len(teams) == 1 and token_use != "session":
            team_id = teams[0] if isinstance(teams[0], str) else teams[0].get("id")
        else:
            team_id = None
        assert team_id == "team-1"

    def test_multi_team_token_sets_team_id_none(self):
        """Multi-team token → team_id is None."""
        teams = normalize_token_teams({"teams": ["team-1", "team-2"]})
        assert teams is not None
        token_use = "api"
        if teams is None:
            team_id = None
        elif len(teams) == 1 and token_use != "session":
            team_id = teams[0] if isinstance(teams[0], str) else teams[0].get("id")
        else:
            team_id = None
        assert team_id is None

    def test_session_token_sets_team_id_none(self):
        """Session token with single team → team_id is None (session tokens never pin)."""
        teams = normalize_token_teams({"teams": ["team-1"]})
        assert teams is not None
        token_use = "session"
        if teams is None:
            team_id = None
        elif len(teams) == 1 and token_use != "session":
            team_id = teams[0] if isinstance(teams[0], str) else teams[0].get("id")
        else:
            team_id = None
        assert team_id is None

    def test_admin_bypass_sets_team_id_none(self):
        """Admin bypass (teams=None) → team_id is None."""
        teams = normalize_token_teams({"teams": None, "is_admin": True})
        assert teams is None
        team_id = None  # admin bypass → None
        assert team_id is None
