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
# entity_exists
# ---------------------------------------------------------------------------


class TestEntityExists:
    """Tests for the BaseService.entity_exists lightweight existence check."""

    @pytest.fixture()
    def service(self):
        return _ConcreteService()

    @pytest.mark.asyncio
    async def test_returns_true_when_entity_exists(self, service):
        db = MagicMock()
        db.execute.return_value.scalar.return_value = True
        assert await service.entity_exists(db, "some-id") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_entity_missing(self, service):
        db = MagicMock()
        db.execute.return_value.scalar.return_value = False
        assert await service.entity_exists(db, "missing-id") is False

    @pytest.mark.asyncio
    async def test_propagates_db_exceptions(self, service):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("connection lost")
        with pytest.raises(RuntimeError, match="connection lost"):
            await service.entity_exists(db, "any-id")


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
    async def test_admin_bypass_filters_private_resources(self, service, mock_db, query):
        """When user_email=None and token_teams=None (admin bypass), filter out private resources."""
        result = await service._apply_access_control(query, mock_db, user_email=None, token_teams=None)
        # Admin bypass now filters out private resources (security fix)
        assert result == "filtered"
        query.where.assert_called_once()

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
        """When token_teams is None and user_email is None (admin bypass), filter out private resources."""
        result = await service._apply_access_control(query, mock_db, user_email=None, token_teams=None)
        # Admin bypass now filters out private resources (security fix)
        assert result == "filtered"
        query.where.assert_called_once()

    def test_apply_visibility_scope_db_admin_includes_own_private_only(self):
        """PR #4341 carve-out coverage for the static ``_apply_visibility_scope`` helper.

        ``_apply_visibility_scope`` is the sibling of ``_apply_access_control`` used by
        completion/tag enumeration. Without this test the (email, None) DB-admin
        branch in base_service.py:215-221 was unexecuted by the suite; the existing
        ``test_apply_visibility_scope_admin_bypass_excludes_private`` coverage in
        test_authorization_access.py only exercises the ``(None, None)`` shape.
        """
        from mcpgateway.services.base_service import BaseService
        from mcpgateway.services.tag_service import TagService

        service = TagService()
        stmt = sa.select(_FakeItem)
        mock_db = MagicMock()

        with patch("mcpgateway.services.base_service.is_user_admin", return_value=True):
            scoped = BaseService._apply_visibility_scope(
                stmt,
                _FakeItem,
                user_email="dba@test.com",
                token_teams=None,
                team_ids=[],
                db=mock_db,
            )

        compiled = _compile_where(scoped)
        assert "visibility != 'private'" in compiled, f"public/team carve-out missing: {compiled}"
        assert "visibility = 'private'" in compiled, f"own-private allowance missing: {compiled}"
        assert "owner_email = 'dba@test.com'" in compiled, f"owner clause must bind caller: {compiled}"
        # Same OR-count guard as test_db_admin_bypass_includes_own_private_only.
        or_count = compiled.upper().count(" OR ")
        assert or_count == 1, f"expected exactly 1 OR in WHERE clause, got {or_count}: {compiled}"
        # Sanity: TagService._apply_visibility_scope is unused here (the static
        # helper on BaseService is what we exercise) but importing it ensures the
        # module-level binding exists so this test fails loudly if a refactor
        # removes the indirection.
        assert callable(getattr(service, "_apply_visibility_scope", None))

    @pytest.mark.asyncio
    async def test_db_admin_bypass_includes_own_private_only(self, service, mock_db):
        """PR #4341 carve-out: DB-admin (email, None) shape compiles a WHERE that allows own private but not others'.

        Asserts the actual compiled predicate so a wrong predicate (e.g. unconditional
        ``True`` allowing all private) cannot slip through. The ``(email, None)`` shape
        was previously a fall-through with no filter applied — the equivalent leak class
        as B5 (resource_service.list_resource_templates).
        """
        base_query = sa.select(_FakeItem)

        with patch("mcpgateway.services.base_service.is_user_admin", return_value=True):
            result = await service._apply_access_control(
                base_query,
                mock_db,
                user_email="dba@test.com",
                token_teams=None,
            )

        compiled = _compile_where(result)

        assert "visibility != 'private'" in compiled, f"public/team carve-out missing: {compiled}"
        assert "visibility = 'private'" in compiled, f"own-private allowance missing: {compiled}"
        assert "owner_email = 'dba@test.com'" in compiled, f"owner clause must bind caller: {compiled}"
        # Exactly one OR — multiple ORs would indicate a too-broad predicate
        # (e.g. an extra unconditional private allowance bolted on).
        or_count = compiled.upper().count(" OR ")
        assert or_count == 1, f"expected exactly 1 OR in WHERE clause, got {or_count}: {compiled}"

    @pytest.mark.asyncio
    async def test_non_admin_with_email_but_null_token_teams_does_not_bypass(self, service, mock_db, query):
        """Non-admin (email, None) shape must NOT take the DB-admin branch — falls through to TeamManagementService lookup."""
        with (
            patch("mcpgateway.services.base_service.is_user_admin", return_value=False),
            patch("mcpgateway.services.base_service.TeamManagementService") as mock_tms_cls,
            patch.object(service, "_apply_visibility_filter", return_value="filtered") as mock_filter,
        ):
            mock_tms_cls.return_value.get_user_teams = AsyncMock(return_value=[])
            result = await service._apply_access_control(
                query,
                mock_db,
                user_email="user@example.com",
                token_teams=None,
            )

            mock_tms_cls.return_value.get_user_teams.assert_awaited_once_with("user@example.com")
            mock_filter.assert_called_once_with(query, "user@example.com", [], None)
            assert result == "filtered"


# ---------------------------------------------------------------------------
# _apply_visibility_filter
# ---------------------------------------------------------------------------


def _compile_where(stmt) -> str:
    """Extract and compile just the WHERE clause to a string for assertion matching."""
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # Extract everything after WHERE to avoid matching column names in SELECT
    if "WHERE" in compiled:
        return compiled[compiled.index("WHERE") :]
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
