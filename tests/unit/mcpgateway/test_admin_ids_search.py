# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_ids_search.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the admin IDs endpoints with search query parameter.
This module tests that the /admin/tools/ids, /admin/resources/ids, and
/admin/prompts/ids endpoints correctly filter results when a search query
is provided via the 'q' parameter.
"""

# Standard
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.admin import (
    admin_get_all_tool_ids,
    admin_get_all_resource_ids,
    admin_get_all_prompt_ids,
)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    return db


def setup_team_service(monkeypatch, team_ids):
    """Helper to mock team service for tests."""

    async def mock_get_user_team_ids(user, db):
        return team_ids

    from mcpgateway import admin

    monkeypatch.setattr(admin, "_get_user_team_ids", mock_get_user_team_ids)


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_with_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_tool_ids filters by search query when q parameter is provided."""
    setup_team_service(monkeypatch, [])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("tool-git-1",), ("tool-git-2",)]

    result = await admin_get_all_tool_ids(
        q="git",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert result["tool_ids"] == ["tool-git-1", "tool-git-2"]


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_empty_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_tool_ids returns all tools when q parameter is empty."""
    setup_team_service(monkeypatch, [])

    # Mock database to return all results
    mock_db.execute.return_value.all.return_value = [("tool-1",), ("tool-2",), ("tool-3",)]

    result = await admin_get_all_tool_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 3
    assert result["tool_ids"] == ["tool-1", "tool-2", "tool-3"]


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_search_with_gateway_filter(monkeypatch, mock_db):
    """Test that search query works together with gateway filter."""
    setup_team_service(monkeypatch, [])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("tool-git-gw1",)]

    result = await admin_get_all_tool_ids(
        q="git",
        include_inactive=False,
        gateway_id="gw-1",
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 1
    assert result["tool_ids"] == ["tool-git-gw1"]


@pytest.mark.asyncio
async def test_admin_get_all_resource_ids_with_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_resource_ids filters by search query when q parameter is provided."""
    setup_team_service(monkeypatch, [])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("resource-file-1",), ("resource-file-2",)]

    result = await admin_get_all_resource_ids(
        q="file",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert result["resource_ids"] == ["resource-file-1", "resource-file-2"]


@pytest.mark.asyncio
async def test_admin_get_all_resource_ids_empty_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_resource_ids returns all resources when q parameter is empty."""
    setup_team_service(monkeypatch, [])

    # Mock database to return all results
    mock_db.execute.return_value.all.return_value = [("res-1",), ("res-2",), ("res-3",)]

    result = await admin_get_all_resource_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 3
    assert result["resource_ids"] == ["res-1", "res-2", "res-3"]


@pytest.mark.asyncio
async def test_admin_get_all_resource_ids_search_with_team_filter(monkeypatch, mock_db):
    """Test that search query works together with team filter."""
    setup_team_service(monkeypatch, ["team-1"])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("resource-file-team1",)]

    result = await admin_get_all_resource_ids(
        q="file",
        include_inactive=False,
        gateway_id=None,
        team_id="team-1",
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 1
    assert result["resource_ids"] == ["resource-file-team1"]


@pytest.mark.asyncio
async def test_admin_get_all_prompt_ids_with_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_prompt_ids filters by search query when q parameter is provided."""
    setup_team_service(monkeypatch, [])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("prompt-code-1",), ("prompt-code-2",)]

    result = await admin_get_all_prompt_ids(
        q="code",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert result["prompt_ids"] == ["prompt-code-1", "prompt-code-2"]


@pytest.mark.asyncio
async def test_admin_get_all_prompt_ids_empty_search_query(monkeypatch, mock_db):
    """Test that admin_get_all_prompt_ids returns all prompts when q parameter is empty."""
    setup_team_service(monkeypatch, [])

    # Mock database to return all results
    mock_db.execute.return_value.all.return_value = [("prompt-1",), ("prompt-2",), ("prompt-3",)]

    result = await admin_get_all_prompt_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 3
    assert result["prompt_ids"] == ["prompt-1", "prompt-2", "prompt-3"]


@pytest.mark.asyncio
async def test_admin_get_all_prompt_ids_search_no_results(monkeypatch, mock_db):
    """Test that search query returns empty list when no matches found."""
    setup_team_service(monkeypatch, [])

    # Mock database to return no results
    mock_db.execute.return_value.all.return_value = []

    result = await admin_get_all_prompt_ids(
        q="nonexistent",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 0
    assert result["prompt_ids"] == []


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_search_case_insensitive(monkeypatch, mock_db):
    """Test that search query is case-insensitive."""
    setup_team_service(monkeypatch, [])

    # Mock database to return results regardless of case
    mock_db.execute.return_value.all.return_value = [("tool-GIT-1",), ("tool-Git-2",)]

    result = await admin_get_all_tool_ids(
        q="GIT",
        include_inactive=False,
        gateway_id=None,
        team_id=None,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert "tool-GIT-1" in result["tool_ids"]
    assert "tool-Git-2" in result["tool_ids"]


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_search_with_all_filters(monkeypatch, mock_db):
    """Test that search query works with gateway, team, and inactive filters combined."""
    setup_team_service(monkeypatch, ["team-1"])

    # Mock database to return filtered results
    mock_db.execute.return_value.all.return_value = [("tool-git-gw1-team1",)]

    result = await admin_get_all_tool_ids(
        q="git",
        include_inactive=True,
        gateway_id="gw-1",
        team_id="team-1",
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 1
    assert result["tool_ids"] == ["tool-git-gw1-team1"]


@pytest.mark.asyncio
async def test_admin_get_all_tool_ids_include_public_with_team(monkeypatch, mock_db):
    """Test that include_public adds platform-public tools when filtering by team."""
    setup_team_service(monkeypatch, ["team-1"])

    mock_db.execute.return_value.all.return_value = [("tool-team-1",), ("tool-public-1",)]

    result = await admin_get_all_tool_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id="team-1",
        include_public=True,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert "tool-team-1" in result["tool_ids"]
    assert "tool-public-1" in result["tool_ids"]


@pytest.mark.asyncio
async def test_admin_get_all_resource_ids_include_public_with_team(monkeypatch, mock_db):
    """Test that include_public adds platform-public resources when filtering by team."""
    setup_team_service(monkeypatch, ["team-1"])

    mock_db.execute.return_value.all.return_value = [("res-team-1",), ("res-public-1",)]

    result = await admin_get_all_resource_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id="team-1",
        include_public=True,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert "res-team-1" in result["resource_ids"]
    assert "res-public-1" in result["resource_ids"]


@pytest.mark.asyncio
async def test_admin_get_all_prompt_ids_include_public_with_team(monkeypatch, mock_db):
    """Test that include_public adds platform-public prompts when filtering by team."""
    setup_team_service(monkeypatch, ["team-1"])

    mock_db.execute.return_value.all.return_value = [("prompt-team-1",), ("prompt-public-1",)]

    result = await admin_get_all_prompt_ids(
        q="",
        include_inactive=False,
        gateway_id=None,
        team_id="team-1",
        include_public=True,
        db=mock_db,
        user={"email": "user@example.com", "db": mock_db},
    )

    assert result["count"] == 2
    assert "prompt-team-1" in result["prompt_ids"]
    assert "prompt-public-1" in result["prompt_ids"]
