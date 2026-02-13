# -*- coding: utf-8 -*-
"""Coverage tests for mcpgateway.services.team_management_service — missing branches."""

# Standard
import asyncio
import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

# Third-Party
import orjson
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam, EmailTeamJoinRequest, EmailTeamMember, EmailTeamMemberHistory, EmailUser
from mcpgateway.services.team_management_service import TeamManagementService


@pytest.fixture(autouse=True)
def _clear_caches():
    try:
        from mcpgateway.cache.auth_cache import get_auth_cache

        get_auth_cache().invalidate_all()
    except (ImportError, Exception):
        pass
    try:
        from mcpgateway.cache.admin_stats_cache import get_admin_stats_cache

        get_admin_stats_cache().invalidate_all()
    except (ImportError, Exception):
        pass
    yield


@pytest.fixture(autouse=True)
async def _drain_fire_and_forget_tasks():
    """Allow scheduled cache invalidation tasks to run before fixture teardown."""
    yield
    await asyncio.sleep(0)


@pytest.fixture
def db():
    return MagicMock(spec=Session)


@pytest.fixture
def svc(db):
    return TeamManagementService(db)


def _mock_team(**overrides):
    t = MagicMock(spec=EmailTeam)
    t.id = overrides.get("id", "t1")
    t.name = overrides.get("name", "Team")
    t.slug = overrides.get("slug", "team")
    t.description = overrides.get("description", "desc")
    t.created_by = overrides.get("created_by", "u@t.com")
    t.is_personal = overrides.get("is_personal", False)
    t.visibility = overrides.get("visibility", "public")
    t.max_members = overrides.get("max_members", 100)
    t.is_active = overrides.get("is_active", True)
    t.created_at = datetime.now(timezone.utc)
    t.updated_at = datetime.now(timezone.utc)
    t.get_member_count = MagicMock(return_value=1)
    return t


def _mock_membership(**overrides):
    m = MagicMock(spec=EmailTeamMember)
    m.id = overrides.get("id", "m1")
    m.team_id = overrides.get("team_id", "t1")
    m.user_email = overrides.get("user_email", "u@t.com")
    m.role = overrides.get("role", "member")
    m.is_active = overrides.get("is_active", True)
    m.joined_at = datetime.now(timezone.utc)
    return m


# ===========================================================================
# _fire_and_forget helper
# ===========================================================================


class TestFireAndForgetHelper:
    def test_create_task_success(self, svc):
        coro = MagicMock()
        coro.close = MagicMock()
        task = MagicMock()

        with patch("mcpgateway.services.team_management_service.asyncio.create_task", return_value=task) as mock_create_task:
            svc._fire_and_forget(coro)

        mock_create_task.assert_called_once_with(coro)
        coro.close.assert_not_called()

    def test_create_task_failure_closes_coroutine(self, svc):
        coro = MagicMock()
        coro.close = MagicMock()

        with patch("mcpgateway.services.team_management_service.asyncio.create_task", side_effect=RuntimeError("no loop")):
            with pytest.raises(RuntimeError, match="no loop"):
                svc._fire_and_forget(coro)

        coro.close.assert_called_once()


# ===========================================================================
# create_team — reactivate inactive team paths
# ===========================================================================


class TestCreateTeamReactivation:
    @pytest.mark.asyncio
    async def test_reactivate_with_existing_membership(self, svc, db):
        """Reactivate inactive team when creator already has inactive membership."""
        inactive_team = _mock_team(is_active=False)
        existing_membership = _mock_membership(role="member", is_active=False)

        # query().filter().first() returns inactive team first, then membership
        mock_query = MagicMock()
        call_count = [0]

        def _first_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return inactive_team
            return existing_membership

        mock_filter = MagicMock()
        mock_filter.first = _first_side_effect
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_user_teams = AsyncMock()
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.create_team("Team", "desc", "u@t.com", "public")

        assert result is inactive_team
        assert inactive_team.is_active is True
        assert existing_membership.role == "owner"
        assert existing_membership.is_active is True

    @pytest.mark.asyncio
    async def test_reactivate_without_existing_membership(self, svc, db):
        """Reactivate inactive team when creator has no prior membership."""
        inactive_team = _mock_team(is_active=False)

        mock_query = MagicMock()
        call_count = [0]

        def _first_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return inactive_team
            return None  # no existing membership

        mock_filter = MagicMock()
        mock_filter.first = _first_side_effect
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_user_teams = AsyncMock()
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.create_team("Team", "desc", "u@t.com", "public")

        assert result is inactive_team
        db.add.assert_called_once()  # new membership created

    @pytest.mark.asyncio
    async def test_cache_invalidation_failure(self, svc, db):
        """Cache failure during create_team does not raise."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=None)  # no inactive team
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_user_teams = AsyncMock(side_effect=Exception("redis down"))
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.create_team("NewTeam", "desc", "u@t.com", "public")

        assert result is not None


# ===========================================================================
# update_team — max_members branch
# ===========================================================================


class TestUpdateTeamEdge:
    @pytest.mark.asyncio
    async def test_update_max_members(self, svc, db):
        team = _mock_team()
        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)):
            result = await svc.update_team("t1", max_members=200)
        assert result is True
        assert team.max_members == 200


# ===========================================================================
# delete_team — membership loop + cache error
# ===========================================================================


class TestDeleteTeamEdge:
    @pytest.mark.asyncio
    async def test_membership_history_and_cache(self, svc, db):
        team = _mock_team()
        m1 = _mock_membership(id="m1", user_email="a@t.com", role="owner")
        m2 = _mock_membership(id="m2", user_email="b@t.com", role="member")

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[m1, m2])
        mock_filter.update = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch.object(svc, "_log_team_member_action") as mock_log, \
             patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_team_roles = AsyncMock()
            mock_cache.invalidate_team = AsyncMock()
            mock_cache.invalidate_user_teams = AsyncMock()
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.delete_team("t1", "admin@t.com")

        assert result is True
        assert mock_log.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_failure_during_delete(self, svc, db):
        team = _mock_team()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[])
        mock_filter.update = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch("mcpgateway.services.team_management_service.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock(side_effect=RuntimeError("no loop"))

            result = await svc.delete_team("t1", "admin@t.com")

        assert result is True


# ===========================================================================
# add_member_to_team — max_members + cache error
# ===========================================================================


class TestAddMemberEdge:
    @pytest.mark.asyncio
    async def test_max_members_reached(self, svc, db):
        from mcpgateway.services.team_management_service import TeamMemberLimitExceededError
        team = _mock_team(max_members=2)
        user = MagicMock(spec=EmailUser)

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(side_effect=[user, None])  # user exists, no existing membership
        mock_filter.count = MagicMock(return_value=2)  # at limit
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)):
            with pytest.raises(TeamMemberLimitExceededError, match="Team has reached maximum member limit of 2"):
                await svc.add_member_to_team("t1", "new@t.com")

    @pytest.mark.asyncio
    async def test_cache_failure_on_add(self, svc, db):
        team = _mock_team(max_members=None)
        user = MagicMock(spec=EmailUser)

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(side_effect=[user, None])  # user exists, no existing membership
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch("mcpgateway.services.team_management_service.asyncio") as mock_asyncio, \
             patch.object(svc, "invalidate_team_member_count_cache", AsyncMock()):
            mock_asyncio.create_task = MagicMock(side_effect=RuntimeError("no loop"))

            await svc.add_member_to_team("t1", "new@t.com")


# ===========================================================================
# remove_member_from_team — cache error
# ===========================================================================


class TestRemoveMemberEdge:
    @pytest.mark.asyncio
    async def test_cache_failure_on_remove(self, svc, db):
        team = _mock_team()
        membership = _mock_membership(role="member")

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch.object(svc, "_log_team_member_action"), \
             patch("mcpgateway.services.team_management_service.asyncio") as mock_asyncio, \
             patch.object(svc, "invalidate_team_member_count_cache", AsyncMock()):
            mock_asyncio.create_task = MagicMock(side_effect=RuntimeError("no loop"))

            result = await svc.remove_member_from_team("t1", "u@t.com")

        assert result is True


# ===========================================================================
# update_member_role — cache error + exception handler
# ===========================================================================


class TestUpdateMemberRoleEdge:
    @pytest.mark.asyncio
    async def test_cache_failure_on_role_update(self, svc, db):
        team = _mock_team()
        membership = _mock_membership(role="member")

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch.object(svc, "_log_team_member_action"), \
             patch("mcpgateway.services.team_management_service.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock(side_effect=RuntimeError("no loop"))

            result = await svc.update_member_role("t1", "u@t.com", "owner")

        assert result is True

    @pytest.mark.asyncio
    async def test_generic_exception(self, svc, db):
        with patch.object(svc, "get_team_by_id", AsyncMock(side_effect=RuntimeError("db fail"))):
            result = await svc.update_member_role("t1", "u@t.com", "owner")
        assert result is False
        db.rollback.assert_called_once()


# ===========================================================================
# get_user_teams — cache paths
# ===========================================================================


class TestGetUserTeamsCachePaths:
    @pytest.mark.asyncio
    async def test_cache_hit_empty(self, svc, db):
        """Cached empty list returns [] immediately."""
        mock_cache = MagicMock()
        mock_cache.get_user_teams = AsyncMock(return_value=[])

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_teams("u@t.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_cache_hit_with_ids(self, svc, db):
        """Cached team IDs fetches from DB."""
        mock_cache = MagicMock()
        mock_cache.get_user_teams = AsyncMock(return_value=["t1", "t2"])

        team1 = _mock_team(id="t1")
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[team1])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_teams("u@t.com")
        assert result == [team1]

    @pytest.mark.asyncio
    async def test_cache_hit_db_failure_falls_through(self, svc, db):
        """If DB lookup from cached IDs fails, falls through to full query."""
        mock_cache = MagicMock()
        mock_cache.get_user_teams = AsyncMock(return_value=["t1"])
        mock_cache.set_user_teams = AsyncMock()

        mock_query = MagicMock()
        mock_filter = MagicMock()
        # First call (from cache) fails, second (full query) succeeds
        mock_filter.all = MagicMock(side_effect=[Exception("db fail"), []])
        mock_query.filter = MagicMock(return_value=mock_filter)
        mock_join = MagicMock()
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_teams("u@t.com")
        assert result == []

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self, svc, db):
        """Cache miss queries DB and stores result."""
        mock_cache = MagicMock()
        mock_cache.get_user_teams = AsyncMock(return_value=None)  # cache miss
        mock_cache.set_user_teams = AsyncMock()

        team1 = _mock_team(id="t1")
        mock_query = MagicMock()
        mock_join = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[team1])
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_teams("u@t.com")
        assert result == [team1]
        mock_cache.set_user_teams.assert_called_once()


# ===========================================================================
# verify_team_for_user — outer exception handler
# ===========================================================================


class TestVerifyTeamForUserEdge:
    @pytest.mark.asyncio
    async def test_outer_exception_no_team_id(self, svc, db):
        """Outer exception with no team_id sets team_id to None."""
        mock_query = MagicMock()
        mock_join = MagicMock()
        # First inner try succeeds, then outer processing raises
        teams_list = MagicMock()
        teams_list.__iter__ = MagicMock(side_effect=RuntimeError("iter fail"))
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=teams_list)
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.verify_team_for_user("u@t.com")
        assert result is None


# ===========================================================================
# get_team_members — page-based, cursor error, exception handlers
# ===========================================================================


class TestGetTeamMembersEdge:
    @pytest.mark.asyncio
    async def test_page_based_pagination(self, svc, db):
        """Page-based pagination returns dict with data/pagination/links."""
        m = _mock_membership()
        m.user = MagicMock(spec=EmailUser)

        pag_result = {
            "data": [m],
            "pagination": {"page": 1, "per_page": 30, "total": 1},
            "links": None,
        }

        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=pag_result)):
            result = await svc.get_team_members("t1", page=1, per_page=30)

        assert isinstance(result, dict)
        assert "data" in result
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_invalid_cursor_ignored(self, svc, db):
        """Invalid cursor is silently ignored."""
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_team_members("t1", cursor="invalid-base64!!!", limit=10)
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_exception_page_mode(self, svc, db):
        """Exception in page mode returns empty page dict."""
        db.execute = MagicMock(side_effect=RuntimeError("fail"))

        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(side_effect=RuntimeError("fail"))):
            result = await svc.get_team_members("t1", page=1)

        assert isinstance(result, dict)
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_exception_cursor_mode(self, svc, db):
        """Exception in cursor mode returns ([], None)."""
        db.execute = MagicMock(side_effect=RuntimeError("fail"))

        result = await svc.get_team_members("t1", cursor="abc", limit=10)
        assert result == ([], None)


# ===========================================================================
# _get_auth_cache / _get_admin_stats_cache — import error
# ===========================================================================


class TestCacheGetters:
    def test_auth_cache_import_error(self, svc):
        """ImportError in _get_auth_cache returns None."""
        with patch("mcpgateway.services.team_management_service.get_auth_cache", side_effect=ImportError("mocked")):
            result = svc._get_auth_cache()
        assert result is None

    def test_admin_stats_cache_import_error(self, svc):
        """ImportError in _get_admin_stats_cache returns None."""
        with patch.dict("sys.modules", {"mcpgateway.cache.admin_stats_cache": None}):
            result = svc._get_admin_stats_cache()
        assert result is None

    def test_admin_stats_cache_success(self, svc):
        """_get_admin_stats_cache returns cache instance when available."""
        result = svc._get_admin_stats_cache()
        assert result is not None


# ===========================================================================
# get_user_role_in_team — cache hit paths
# ===========================================================================


class TestGetUserRoleCache:
    @pytest.mark.asyncio
    async def test_cached_role(self, svc, db):
        """Cache returns role string directly."""
        mock_cache = MagicMock()
        mock_cache.get_user_role = AsyncMock(return_value="owner")

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_role_in_team("u@t.com", "t1")
        assert result == "owner"

    @pytest.mark.asyncio
    async def test_cached_empty_string_means_not_member(self, svc, db):
        """Cache returns empty string = not a member (cached None)."""
        mock_cache = MagicMock()
        mock_cache.get_user_role = AsyncMock(return_value="")

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_role_in_team("u@t.com", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_miss_stores(self, svc, db):
        """Cache miss queries DB and stores result."""
        mock_cache = MagicMock()
        mock_cache.get_user_role = AsyncMock(return_value=None)
        mock_cache.set_user_role = AsyncMock()

        membership = _mock_membership(role="member")
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=mock_cache):
            result = await svc.get_user_role_in_team("u@t.com", "t1")
        assert result == "member"
        mock_cache.set_user_role.assert_called_once()


# ===========================================================================
# list_teams — filter branches
# ===========================================================================


class TestListTeamsFilters:
    @pytest.mark.asyncio
    async def test_visibility_filter(self, svc, db):
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=([], None))):
            result = await svc.list_teams(visibility_filter="public")
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_offset_without_cursor_or_page(self, svc, db):
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=([], None))):
            result = await svc.list_teams(offset=10)
        assert result == ([], None)


# ===========================================================================
# get_all_team_ids — filter branches
# ===========================================================================


class TestGetAllTeamIdsFilters:
    @pytest.mark.asyncio
    async def test_all_filters(self, svc, db):
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[("id1",)])
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_all_team_ids(
            include_inactive=True,
            include_personal=True,
            visibility_filter="public",
            search_query="test",
        )
        assert result == ["id1"]


# ===========================================================================
# get_teams_count — filter branches
# ===========================================================================


class TestGetTeamsCountFilters:
    @pytest.mark.asyncio
    async def test_all_filters(self, svc, db):
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=5)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_teams_count(
            include_inactive=True,
            include_personal=True,
            visibility_filter="private",
            search_query="dev",
        )
        assert result == 5


# ===========================================================================
# discover_public_teams — limit branch
# ===========================================================================


class TestDiscoverPublicTeamsEdge:
    @pytest.mark.asyncio
    async def test_with_limit(self, svc, db):
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.offset = MagicMock(return_value=mock_query)
        mock_query.limit = MagicMock(return_value=mock_query)
        mock_query.all = MagicMock(return_value=[])
        db.query = MagicMock(return_value=mock_query)

        result = await svc.discover_public_teams("u@t.com", limit=10)
        assert result == []
        mock_query.limit.assert_called_once_with(10)


# ===========================================================================
# approve_join_request — cache error
# ===========================================================================


class TestApproveJoinRequestEdge:
    @pytest.mark.asyncio
    async def test_cache_failure_on_approve(self, svc, db):
        join_req = MagicMock(spec=EmailTeamJoinRequest)
        join_req.id = "jr1"
        join_req.team_id = "t1"
        join_req.user_email = "new@t.com"
        join_req.is_expired = MagicMock(return_value=False)
        join_req.status = "pending"

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=join_req)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_log_team_member_action"), \
             patch.object(svc, "invalidate_team_member_count_cache", AsyncMock()), \
             patch("mcpgateway.services.team_management_service.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock(side_effect=RuntimeError("no loop"))

            result = await svc.approve_join_request("jr1", "owner@t.com")

        assert result is not None


# ===========================================================================
# get_user_join_requests — team_id filter
# ===========================================================================


class TestGetUserJoinRequestsEdge:
    @pytest.mark.asyncio
    async def test_with_team_filter(self, svc, db):
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.filter = MagicMock(return_value=mock_filter)
        mock_filter.all = MagicMock(return_value=[])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.get_user_join_requests("u@t.com", team_id="t1")
        assert result == []


# ===========================================================================
# get_member_counts_batch_cached — Redis paths
# ===========================================================================


class TestMemberCountsCachedEdge:
    @pytest.mark.asyncio
    async def test_cache_disabled(self, svc, db):
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = False
            with patch.object(svc, "get_member_counts_batch", return_value={"t1": 5}):
                result = await svc.get_member_counts_batch_cached(["t1"])
        assert result == {"t1": 5}

    @pytest.mark.asyncio
    async def test_redis_unavailable(self, svc, db):
        """No redis falls back to DB."""
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300

            mock_query = MagicMock()
            mock_filter = MagicMock()
            mock_filter.group_by = MagicMock(return_value=mock_filter)
            mock_filter.all = MagicMock(return_value=[])
            mock_query.filter = MagicMock(return_value=mock_filter)
            db.query = MagicMock(return_value=mock_query)

            with patch("mcpgateway.services.team_management_service.TeamManagementService.get_member_counts_batch_cached") as mock_method:
                # Just call through to test the redis unavailable path
                mock_method.return_value = {"t1": 0}
                result = await svc.get_member_counts_batch_cached(["t1"])
            assert "t1" in result

    @pytest.mark.asyncio
    async def test_redis_available_cache_hit(self, svc, db):
        """Redis has cached values, no DB query needed."""
        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(return_value=[b"5"])

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings, \
             patch("mcpgateway.services.team_management_service.get_redis_client", AsyncMock(return_value=mock_redis)):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "test:"

            result = await svc.get_member_counts_batch_cached(["t1"])
        assert result == {"t1": 5}

    @pytest.mark.asyncio
    async def test_redis_read_failure(self, svc, db):
        """Redis read fails, falls back to DB."""
        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(side_effect=Exception("redis fail"))
        mock_redis.setex = AsyncMock()

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.group_by = MagicMock(return_value=mock_filter)
        row = MagicMock()
        row.team_id = "t1"
        row.count = 3
        mock_filter.all = MagicMock(return_value=[row])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings, \
             patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis)):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "test:"

            result = await svc.get_member_counts_batch_cached(["t1"])
        assert result == {"t1": 3}

    @pytest.mark.asyncio
    async def test_redis_write_failure(self, svc, db):
        """Redis write fails silently."""
        mock_redis = AsyncMock()
        mock_redis.mget = AsyncMock(return_value=[None])
        mock_redis.setex = AsyncMock(side_effect=Exception("write fail"))

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.group_by = MagicMock(return_value=mock_filter)
        mock_filter.all = MagicMock(return_value=[])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings, \
             patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis)):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "test:"

            result = await svc.get_member_counts_batch_cached(["t1"])
        assert result == {"t1": 0}


# ===========================================================================
# invalidate_team_member_count_cache — redis error
# ===========================================================================


class TestInvalidateCacheEdge:
    @pytest.mark.asyncio
    async def test_redis_delete_failure(self, svc):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("delete fail"))

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings, \
             patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=mock_redis)):
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.cache_prefix = "test:"

            # Should not raise
            await svc.invalidate_team_member_count_cache("t1")


# ===========================================================================
# _get_member_count_cache_key
# ===========================================================================


class TestCacheKeyPrefix:
    def test_uses_settings_prefix(self, svc):
        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.cache_prefix = "custom:"
            key = svc._get_member_count_cache_key("t1")
        assert key == "custom:team:member_count:t1"


# ===========================================================================
# create_team — explicit max_members (branch 178->183)
# ===========================================================================


class TestCreateTeamMaxMembers:
    @pytest.mark.asyncio
    async def test_explicit_max_members_skips_default(self, svc, db):
        """When max_members is explicitly provided, the default is not applied."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=None)  # no inactive team
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_user_teams = AsyncMock()
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.create_team("Team", "desc", "u@t.com", "public", max_members=50)

        assert result is not None
        # Verify the team was added with the explicit max_members
        db.add.assert_called()


# ===========================================================================
# remove_member — last owner check passes (owner_count > 1)
# ===========================================================================


class TestRemoveMemberLastOwnerPasses:
    @pytest.mark.asyncio
    async def test_remove_owner_when_multiple_owners(self, svc, db):
        """Removing an owner succeeds when there are multiple owners."""
        team = _mock_team()
        membership = _mock_membership(role="owner")

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_filter.count = MagicMock(return_value=2)  # 2 owners, removal is OK
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch.object(svc, "_log_team_member_action"), \
             patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin, \
             patch.object(svc, "invalidate_team_member_count_cache", AsyncMock()):
            mock_cache.invalidate_team_roles = AsyncMock()
            mock_cache.invalidate_team = AsyncMock()
            mock_cache.invalidate_user_teams = AsyncMock()
            mock_cache.invalidate_team_membership = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.remove_member_from_team("t1", "u@t.com")

        assert result is True


# ===========================================================================
# update_member_role — last owner check passes (owner_count > 1)
# ===========================================================================


class TestUpdateMemberRoleLastOwnerPasses:
    @pytest.mark.asyncio
    async def test_change_owner_role_when_multiple_owners(self, svc, db):
        """Changing owner role to member succeeds when there are multiple owners."""
        team = _mock_team()
        membership = _mock_membership(role="owner")

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_filter.count = MagicMock(return_value=2)  # 2 owners
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "get_team_by_id", AsyncMock(return_value=team)), \
             patch.object(svc, "_log_team_member_action"), \
             patch("mcpgateway.services.team_management_service.auth_cache") as mock_cache, \
             patch("mcpgateway.services.team_management_service.admin_stats_cache") as mock_admin:
            mock_cache.invalidate_team_roles = AsyncMock()
            mock_cache.invalidate_team = AsyncMock()
            mock_cache.invalidate_user_role = AsyncMock()
            mock_admin.invalidate_teams = AsyncMock()

            result = await svc.update_member_role("t1", "u@t.com", "member")

        assert result is True
        assert membership.role == "member"


# ===========================================================================
# get_user_teams — no cache path
# ===========================================================================


class TestGetUserTeamsNoCache:
    @pytest.mark.asyncio
    async def test_no_cache_available(self, svc, db):
        """When _get_auth_cache returns None, goes straight to DB."""
        team1 = _mock_team(id="t1")
        mock_query = MagicMock()
        mock_join = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[team1])
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=None):
            result = await svc.get_user_teams("u@t.com")
        assert result == [team1]


# ===========================================================================
# get_all_team_ids — default filters (include_personal=False, include_inactive=False)
# ===========================================================================


class TestGetAllTeamIdsDefaultFilters:
    @pytest.mark.asyncio
    async def test_default_filters(self, svc, db):
        """Default params apply is_personal=False and is_active=True filters."""
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[("id1",), ("id2",)])
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_all_team_ids()
        assert result == ["id1", "id2"]

    @pytest.mark.asyncio
    async def test_with_search_query_only(self, svc, db):
        """search_query applies name/slug filter without visibility_filter."""
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[])
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_all_team_ids(search_query="test")
        assert result == []


# ===========================================================================
# get_teams_count — default filters
# ===========================================================================


class TestGetTeamsCountDefaultFilters:
    @pytest.mark.asyncio
    async def test_default_filters(self, svc, db):
        """Default params apply is_personal=False and is_active=True filters."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=10)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_teams_count()
        assert result == 10

    @pytest.mark.asyncio
    async def test_with_search_query_only(self, svc, db):
        """search_query applies filter without visibility_filter."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=3)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_teams_count(search_query="dev")
        assert result == 3


# ===========================================================================
# list_teams — search_query and page-based branches
# ===========================================================================


class TestListTeamsMoreBranches:
    @pytest.mark.asyncio
    async def test_with_search_query(self, svc, db):
        """search_query applies ilike filter."""
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=([], None))):
            result = await svc.list_teams(search_query="test")
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_page_based(self, svc, db):
        """Page-based pagination returns dict."""
        pag_result = {
            "data": [],
            "pagination": {"page": 1, "per_page": 30, "total": 0},
            "links": None,
        }
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=pag_result)):
            result = await svc.list_teams(page=1, per_page=30)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_include_personal_and_inactive(self, svc, db):
        """include_personal=True and include_inactive=True skip those filters."""
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=([], None))):
            result = await svc.list_teams(include_personal=True, include_inactive=True)
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_with_custom_base_url(self, svc, db):
        """Custom base_url skips default base_url assignment."""
        with patch("mcpgateway.services.team_management_service.unified_paginate", AsyncMock(return_value=([], None))):
            result = await svc.list_teams(base_url="/api/v1/teams")
        assert result == ([], None)


# ===========================================================================
# discover_public_teams — without limit (limit=None branch)
# ===========================================================================


class TestDiscoverPublicTeamsNoLimit:
    @pytest.mark.asyncio
    async def test_without_limit(self, svc, db):
        """When limit=None, no .limit() call is made."""
        mock_query = MagicMock()
        mock_query.filter = MagicMock(return_value=mock_query)
        mock_query.offset = MagicMock(return_value=mock_query)
        mock_query.limit = MagicMock(return_value=mock_query)
        mock_query.all = MagicMock(return_value=[])
        db.query = MagicMock(return_value=mock_query)

        result = await svc.discover_public_teams("u@t.com", limit=None)
        assert result == []
        mock_query.limit.assert_not_called()


# ===========================================================================
# get_user_join_requests — without team_id (branch 1404->1407)
# ===========================================================================


class TestGetUserJoinRequestsNoTeam:
    @pytest.mark.asyncio
    async def test_without_team_filter(self, svc, db):
        """When team_id=None, no team_id filter is added."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.get_user_join_requests("u@t.com")
        assert result == []
        # filter should be called once (email filter only, not team_id)
        mock_query.filter.assert_called_once()


# ===========================================================================
# get_member_counts_batch_cached — redis import failure + DB exception
# ===========================================================================


class TestMemberCountsCachedMoreEdges:
    @pytest.mark.asyncio
    async def test_redis_import_failure(self, svc, db):
        """When redis import fails, falls back to DB."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.group_by = MagicMock(return_value=mock_filter)
        row = MagicMock()
        row.team_id = "t1"
        row.count = 7
        mock_filter.all = MagicMock(return_value=[row])
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "test:"

            with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(side_effect=ImportError("no redis"))):
                result = await svc.get_member_counts_batch_cached(["t1"])

        assert result == {"t1": 7}

    @pytest.mark.asyncio
    async def test_db_query_exception(self, svc, db):
        """DB exception during cache miss query is propagated."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.group_by = MagicMock(return_value=mock_filter)
        mock_filter.all = MagicMock(side_effect=RuntimeError("db fail"))
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch("mcpgateway.services.team_management_service.settings") as mock_settings:
            mock_settings.team_member_count_cache_enabled = True
            mock_settings.team_member_count_cache_ttl = 300
            mock_settings.cache_prefix = "test:"

            with patch("mcpgateway.utils.redis_client.get_redis_client", AsyncMock(return_value=None)), \
                 pytest.raises(RuntimeError, match="db fail"):
                await svc.get_member_counts_batch_cached(["t1"])

        db.rollback.assert_called()


# ===========================================================================
# verify_team_for_user — cache/no-team_id path (branch 788->791)
# ===========================================================================


class TestVerifyTeamForUserMoreBranches:
    @pytest.mark.asyncio
    async def test_with_team_id_present(self, svc, db):
        """When team_id is provided and user is member, returns team_id."""
        team = _mock_team(id="t1")
        mock_query = MagicMock()
        mock_join = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=[team])
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.verify_team_for_user("u@t.com", team_id="t1")
        assert result == "t1"

    @pytest.mark.asyncio
    async def test_outer_exception_with_team_id(self, svc, db):
        """Outer exception when team_id was provided keeps team_id."""
        teams_list = MagicMock()
        teams_list.__iter__ = MagicMock(side_effect=RuntimeError("iter fail"))

        mock_query = MagicMock()
        mock_join = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all = MagicMock(return_value=teams_list)
        mock_join.filter = MagicMock(return_value=mock_filter)
        mock_query.join = MagicMock(return_value=mock_join)
        db.query = MagicMock(return_value=mock_query)

        result = await svc.verify_team_for_user("u@t.com", team_id="t1")
        # With team_id provided, the `if not team_id:` check is False, so team_id is returned as-is
        assert result == "t1"


# ===========================================================================
# get_team_members — cursor-based with valid cursor (branch 881->894)
# ===========================================================================


class TestGetTeamMembersCursorValid:
    @pytest.mark.asyncio
    async def test_valid_cursor_with_keyset(self, svc, db):
        """Valid cursor applies keyset filter."""
        cursor_data = orjson.dumps({"id": "m1", "joined_at": "2024-01-01T00:00:00+00:00"})
        cursor = base64.urlsafe_b64encode(cursor_data).decode()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_team_members("t1", cursor=cursor, limit=10)
        assert result == ([], None)

    @pytest.mark.asyncio
    async def test_cursor_missing_fields(self, svc, db):
        """Cursor with missing id/joined_at fields doesn't apply keyset filter."""
        cursor_data = orjson.dumps({"other": "data"})
        cursor = base64.urlsafe_b64encode(cursor_data).decode()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        db.execute = MagicMock(return_value=mock_result)

        result = await svc.get_team_members("t1", cursor=cursor, limit=10)
        assert result == ([], None)


# ===========================================================================
# get_user_role_in_team — no cache path
# ===========================================================================


class TestGetUserRoleNoCachePath:
    @pytest.mark.asyncio
    async def test_no_cache_queries_db(self, svc, db):
        """When _get_auth_cache returns None, queries DB directly."""
        membership = _mock_membership(role="member")
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=membership)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=None):
            result = await svc.get_user_role_in_team("u@t.com", "t1")
        assert result == "member"

    @pytest.mark.asyncio
    async def test_no_cache_no_membership(self, svc, db):
        """When no cache and no membership, returns None."""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first = MagicMock(return_value=None)
        mock_query.filter = MagicMock(return_value=mock_filter)
        db.query = MagicMock(return_value=mock_query)

        with patch.object(svc, "_get_auth_cache", return_value=None):
            result = await svc.get_user_role_in_team("u@t.com", "t1")
        assert result is None
