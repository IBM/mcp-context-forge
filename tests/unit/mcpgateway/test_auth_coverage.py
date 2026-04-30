# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_auth_coverage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Additional tests for auth.py coverage gaps.

This module contains targeted tests for specific uncovered lines in mcpgateway/auth.py
to achieve 100% coverage.
"""


class TestGetTeamNameByIdSync:
    """Tests for _get_team_name_by_id_sync function."""

    def test_get_team_name_none_team_id_line_206(self):
        """Test _get_team_name_by_id_sync with None team_id (line 206)."""
        # First-Party
        from mcpgateway.auth import _get_team_name_by_id_sync

        # Should return None immediately for None team_id
        result = _get_team_name_by_id_sync(None)
        assert result is None

    def test_get_team_name_empty_team_id_line_206(self):
        """Test _get_team_name_by_id_sync with empty string team_id (line 206)."""
        # First-Party
        from mcpgateway.auth import _get_team_name_by_id_sync

        # Should return None immediately for empty team_id
        result = _get_team_name_by_id_sync("")
        assert result is None


class TestExtractClaimTeamName:
    """Tests for _extract_claim_team_name function."""

    def test_extract_claim_none_team_id_line_221(self):
        """Test _extract_claim_team_name with None team_id (line 221)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        payload = {"teams": [{"id": "team-1", "name": "Team One"}]}

        # Should return None immediately for None team_id
        result = _extract_claim_team_name(payload, None)
        assert result is None

    def test_extract_claim_teams_not_list_line_235(self):
        """Test _extract_claim_team_name when teams is not a list (line 235)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # teams is a string instead of list
        payload = {"teams": "not-a-list"}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_teams_is_dict_line_235(self):
        """Test _extract_claim_team_name when teams is a dict (line 235)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # teams is a dict instead of list
        payload = {"teams": {"id": "team-1"}}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_string_format_line_239(self):
        """Test _extract_claim_team_name with string team format (line 239)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team as string (not dict)
        payload = {"teams": ["team-1", "team-2"]}

        # Should handle string format but return None (no name available)
        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_name_none_line_251(self):
        """Test _extract_claim_team_name when team name is None (line 251)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team dict with id but name is None
        payload = {"teams": [{"id": "team-1", "name": None}]}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None

    def test_extract_claim_team_name_empty_string_line_259(self):
        """Test _extract_claim_team_name when normalized name is empty (line 259)."""
        # First-Party
        from mcpgateway.auth import _extract_claim_team_name

        # Team dict with id and name that becomes empty after strip
        payload = {"teams": [{"id": "team-1", "name": "   "}]}

        result = _extract_claim_team_name(payload, "team-1")
        assert result is None


# Note: Lines 993-994, 1006, and 1011 are inside get_current_user function
# which is complex to test in isolation. These lines are covered by existing
# integration tests in test_auth.py. The helper functions above provide
# sufficient coverage for the simpler utility functions.
