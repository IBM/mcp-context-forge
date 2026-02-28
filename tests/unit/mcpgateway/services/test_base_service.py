# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_base_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for BaseService ABC: __init_subclass__ validation, _apply_access_control,
and _apply_visibility_filter.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# First-Party
from mcpgateway.services.base_service import BaseService


# ---------------------------------------------------------------------------
# Helpers: lightweight SQLAlchemy model and concrete test subclass
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _FakeItem(_Base):
    """Minimal SQLAlchemy model with the columns BaseService accesses."""

    __tablename__ = "fake_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    visibility: Mapped[str] = mapped_column(sa.String(20))
    team_id: Mapped[str] = mapped_column(sa.String(50), nullable=True)
    owner_email: Mapped[str] = mapped_column(sa.String(100), nullable=True)


class _ConcreteService(BaseService):
    """Valid concrete subclass used by every test that needs an instance."""

    _visibility_model_cls = _FakeItem


# ---------------------------------------------------------------------------
# __init_subclass__ validation
# ---------------------------------------------------------------------------


class TestInitSubclass:
    """Tests for __init_subclass__ enforcement of _visibility_model_cls."""

    def test_missing_visibility_model_cls_raises(self):
        """Subclass that does not set _visibility_model_cls must raise TypeError."""
        with pytest.raises(TypeError, match="must set _visibility_model_cls to a model class"):

            class _Bad(BaseService):
                pass

    def test_non_type_visibility_model_cls_raises(self):
        """Subclass that sets _visibility_model_cls to a non-type value must raise TypeError."""
        with pytest.raises(TypeError, match="must set _visibility_model_cls to a model class"):

            class _Bad(BaseService):
                _visibility_model_cls = "not-a-type"  # type: ignore[assignment]

    def test_valid_model_class_succeeds(self):
        """Subclass with a proper type for _visibility_model_cls should be created without error."""

        class _Good(BaseService):
            _visibility_model_cls = _FakeItem

        assert _Good._visibility_model_cls is _FakeItem


# ---------------------------------------------------------------------------
# _apply_access_control
# ---------------------------------------------------------------------------


class TestApplyAccessControl:
    """Tests for the _apply_access_control orchestration method."""

    @pytest.fixture()
    def service(self):
        return _ConcreteService()

    @pytest.fixture()
    def mock_db(self):
        return MagicMock()

    @pytest.fixture()
    def query(self):
        q = MagicMock()
        q.where.return_value = "filtered"
        return q

    @pytest.mark.asyncio
    async def test_admin_bypass_returns_query_unmodified(self, service, mock_db, query):
        """When user_email=None and token_teams=None (admin bypass), return query as-is."""
        result = await service._apply_access_control(query, mock_db, user_email=None, token_teams=None)
        assert result is query
        query.where.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_only_token_suppresses_owner_email(self, service, mock_db, query):
        """Public-only token (token_teams=[]) should delegate with filter_email=None."""
        with patch.object(service, "_apply_visibility_filter", return_value="filtered") as mock_filter:
            result = await service._apply_access_control(query, mock_db, user_email="user@test.com", token_teams=[])
            mock_filter.assert_called_once_with(query, None, [], None)
            assert result == "filtered"

    @pytest.mark.asyncio
    async def test_team_scoped_token_passes_teams_through(self, service, mock_db, query):
        """Team-scoped token passes the team list and user_email to the filter."""
        with patch.object(service, "_apply_visibility_filter", return_value="filtered") as mock_filter:
            result = await service._apply_access_control(query, mock_db, user_email="dev@test.com", token_teams=["team-1"])
            mock_filter.assert_called_once_with(query, "dev@test.com", ["team-1"], None)
            assert result == "filtered"

    @pytest.mark.asyncio
    async def test_team_scoped_token_with_team_id(self, service, mock_db, query):
        """team_id parameter is forwarded to _apply_visibility_filter."""
        with patch.object(service, "_apply_visibility_filter", return_value="filtered") as mock_filter:
            result = await service._apply_access_control(query, mock_db, user_email="dev@test.com", token_teams=["team-1"], team_id="team-1")
            mock_filter.assert_called_once_with(query, "dev@test.com", ["team-1"], "team-1")
            assert result == "filtered"

    @pytest.mark.asyncio
    async def test_db_lookup_fallback_when_token_teams_is_none(self, service, mock_db, query):
        """When token_teams is None but user_email is set, look up teams from TeamManagementService."""
        fake_teams = [SimpleNamespace(id="team-a"), SimpleNamespace(id="team-b")]

        with (
            patch("mcpgateway.services.base_service.TeamManagementService") as mock_tms_cls,
            patch.object(service, "_apply_visibility_filter", return_value="filtered") as mock_filter,
        ):
            mock_tms_cls.return_value.get_user_teams = AsyncMock(return_value=fake_teams)
            result = await service._apply_access_control(query, mock_db, user_email="user@test.com", token_teams=None)

            mock_tms_cls.assert_called_once_with(mock_db)
            mock_tms_cls.return_value.get_user_teams.assert_awaited_once_with("user@test.com")
            mock_filter.assert_called_once_with(query, "user@test.com", ["team-a", "team-b"], None)
            assert result == "filtered"

    @pytest.mark.asyncio
    async def test_db_lookup_fallback_no_user_email(self, service, mock_db, query):
        """When token_teams is None and user_email is None (admin bypass), return query unchanged."""
        result = await service._apply_access_control(query, mock_db, user_email=None, token_teams=None)
        assert result is query


# ---------------------------------------------------------------------------
# _apply_visibility_filter
# ---------------------------------------------------------------------------


def _compile_where(stmt) -> str:
    """Extract and compile just the WHERE clause to a string for assertion matching."""
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # Extract everything after WHERE to avoid matching column names in SELECT
    if "WHERE" in compiled:
        return compiled[compiled.index("WHERE"):]
    return compiled


class TestApplyVisibilityFilter:
    """Tests for the _apply_visibility_filter SQL WHERE construction.

    Uses a real SQLAlchemy model so that and_()/or_() produce valid
    clause elements, then compiles the resulting query to SQL text for
    assertion matching.
    """

    @pytest.fixture()
    def service(self):
        return _ConcreteService()

    @pytest.fixture()
    def base_query(self):
        return sa.select(_FakeItem)

    def test_global_listing_public_always_included(self, service, base_query):
        """Global listing (no team_id): public visibility condition is always present."""
        result = service._apply_visibility_filter(base_query, user_email=None, token_teams=[])
        sql = _compile_where(result)
        assert "visibility = 'public'" in sql

    def test_global_listing_with_user_email_adds_private_owner(self, service, base_query):
        """Global listing with user_email: adds private-owner condition."""
        result = service._apply_visibility_filter(base_query, user_email="user@test.com", token_teams=[])
        sql = _compile_where(result)
        assert "visibility = 'public'" in sql
        assert "owner_email = 'user@test.com'" in sql
        assert "visibility = 'private'" in sql

    def test_global_listing_with_token_teams_adds_team_condition(self, service, base_query):
        """Global listing with token_teams: adds team/public visibility for those teams."""
        result = service._apply_visibility_filter(base_query, user_email=None, token_teams=["team-1", "team-2"])
        sql = _compile_where(result)
        assert "team_id IN ('team-1', 'team-2')" in sql
        assert "visibility IN ('team', 'public')" in sql

    def test_global_listing_empty_teams_no_email_only_public(self, service, base_query):
        """Global listing with empty token_teams and no user_email: only public condition."""
        result = service._apply_visibility_filter(base_query, user_email=None, token_teams=[])
        sql = _compile_where(result)
        assert "visibility = 'public'" in sql
        assert "owner_email" not in sql
        assert "team_id" not in sql

    def test_team_scoped_in_token_teams(self, service, base_query):
        """Team-scoped (team_id in token_teams): returns team+public and private-owner conditions."""
        result = service._apply_visibility_filter(base_query, user_email="owner@test.com", token_teams=["team-1"], team_id="team-1")
        sql = _compile_where(result)
        assert "team_id = 'team-1'" in sql
        assert "visibility IN ('team', 'public')" in sql
        assert "owner_email = 'owner@test.com'" in sql
        assert "visibility = 'private'" in sql

    def test_team_scoped_in_token_teams_no_email(self, service, base_query):
        """Team-scoped (team_id in token_teams, no user_email): team+public but no private-owner."""
        result = service._apply_visibility_filter(base_query, user_email=None, token_teams=["team-1"], team_id="team-1")
        sql = _compile_where(result)
        assert "team_id = 'team-1'" in sql
        assert "visibility IN ('team', 'public')" in sql
        assert "owner_email" not in sql

    def test_team_scoped_not_in_token_teams(self, service, base_query):
        """Team-scoped (team_id NOT in token_teams): returns where(false) for access denial."""
        result = service._apply_visibility_filter(base_query, user_email="user@test.com", token_teams=["team-1"], team_id="team-2")
        sql = _compile_where(result)
        # SQLAlchemy compiles where(False) as "WHERE false" or "WHERE 1!=1"
        lower_sql = sql.lower()
        assert "false" in lower_sql or "1 != 1" in lower_sql or "1!=1" in lower_sql
