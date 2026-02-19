# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_catalog_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for token catalog service implementation.
"""

# Standard
from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import (
    EmailApiToken,
    EmailTeam,
    EmailTeamMember,
    EmailUser,
    TokenRevocation,
    TokenUsageLog,
    utc_now,
)
from mcpgateway.services.token_catalog_service import TokenCatalogService, TokenScope


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock(spec=Session)
    db.execute = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def token_service(mock_db):
    """Create a TokenCatalogService instance with mock database."""
    return TokenCatalogService(mock_db)


@pytest.fixture
def mock_user():
    """Create a mock EmailUser."""
    user = MagicMock(spec=EmailUser)
    user.email = "test@example.com"
    user.is_admin = False
    user.id = "user-123"
    return user


@pytest.fixture
def mock_team():
    """Create a mock EmailTeam."""
    team = MagicMock(spec=EmailTeam)
    team.id = "team-123"
    team.name = "Test Team"
    return team


@pytest.fixture
def mock_team_member():
    """Create a mock EmailTeamMember."""
    member = MagicMock(spec=EmailTeamMember)
    member.team_id = "team-123"
    member.user_email = "test@example.com"
    member.role = "owner"
    member.is_active = True
    return member


@pytest.fixture
def mock_api_token():
    """Create a mock EmailApiToken."""
    token = MagicMock(spec=EmailApiToken)
    token.id = "token-123"
    token.user_email = "test@example.com"
    token.name = "Test Token"
    token.token_hash = "hash123"
    token.description = "Test description"
    token.expires_at = None
    token.tags = ["test"]
    token.team_id = None
    token.server_id = None
    token.resource_scopes = []
    token.ip_restrictions = []
    token.time_restrictions = {}
    token.usage_limits = {}
    token.is_active = True
    token.jti = "jti-123"
    token.created_at = utc_now()
    token.last_used = None
    return token


@pytest.fixture
def token_scope():
    """Create a TokenScope instance."""
    return TokenScope(
        server_id="server-123",
        permissions=["tools.read", "resources.read"],
        ip_restrictions=["192.168.1.0/24"],
        time_restrictions={"business_hours_only": True},
        usage_limits={"max_requests_per_hour": 100},
    )


# --------------------------------------------------------------------------- #
# TokenScope Tests                                                            #
# --------------------------------------------------------------------------- #
class TestTokenScope:
    """Tests for TokenScope class."""

    def test_init_with_defaults(self):
        """Test TokenScope initialization with default values."""
        scope = TokenScope()
        assert scope.server_id is None
        assert scope.permissions == []
        assert scope.ip_restrictions == []
        assert scope.time_restrictions == {}
        assert scope.usage_limits == {}

    def test_init_with_values(self, token_scope):
        """Test TokenScope initialization with provided values."""
        assert token_scope.server_id == "server-123"
        assert token_scope.permissions == ["tools.read", "resources.read"]
        assert token_scope.ip_restrictions == ["192.168.1.0/24"]
        assert token_scope.time_restrictions == {"business_hours_only": True}
        assert token_scope.usage_limits == {"max_requests_per_hour": 100}

    def test_is_server_scoped(self, token_scope):
        """Test is_server_scoped method."""
        assert token_scope.is_server_scoped() is True

        scope_no_server = TokenScope()
        assert scope_no_server.is_server_scoped() is False

    def test_has_permission(self, token_scope):
        """Test has_permission method."""
        assert token_scope.has_permission("tools.read") is True
        assert token_scope.has_permission("resources.read") is True
        assert token_scope.has_permission("tools.write") is False
        assert token_scope.has_permission("admin") is False

    def test_to_dict(self, token_scope):
        """Test conversion to dictionary."""
        result = token_scope.to_dict()
        assert isinstance(result, dict)
        assert result["server_id"] == "server-123"
        assert result["permissions"] == ["tools.read", "resources.read"]
        assert result["ip_restrictions"] == ["192.168.1.0/24"]
        assert result["time_restrictions"] == {"business_hours_only": True}
        assert result["usage_limits"] == {"max_requests_per_hour": 100}

    def test_from_dict(self):
        """Test creating TokenScope from dictionary."""
        data = {
            "server_id": "server-456",
            "permissions": ["tools.execute", "prompts.read"],
            "ip_restrictions": ["10.0.0.0/8"],
            "time_restrictions": {"weekdays_only": True},
            "usage_limits": {"max_requests_per_day": 1000},
        }
        scope = TokenScope.from_dict(data)
        assert scope.server_id == "server-456"
        assert scope.permissions == ["tools.execute", "prompts.read"]
        assert scope.ip_restrictions == ["10.0.0.0/8"]
        assert scope.time_restrictions == {"weekdays_only": True}
        assert scope.usage_limits == {"max_requests_per_day": 1000}

    def test_from_dict_empty(self):
        """Test creating TokenScope from empty dictionary."""
        scope = TokenScope.from_dict({})
        assert scope.server_id is None
        assert scope.permissions == []
        assert scope.ip_restrictions == []
        assert scope.time_restrictions == {}
        assert scope.usage_limits == {}

    def test_from_dict_partial(self):
        """Test creating TokenScope from partial dictionary."""
        data = {"server_id": "server-789", "permissions": ["read"]}
        scope = TokenScope.from_dict(data)
        assert scope.server_id == "server-789"
        assert scope.permissions == ["read"]
        assert scope.ip_restrictions == []
        assert scope.time_restrictions == {}
        assert scope.usage_limits == {}


# --------------------------------------------------------------------------- #
# TokenCatalogService Tests                                                   #
# --------------------------------------------------------------------------- #
class TestTokenCatalogService:
    """Tests for TokenCatalogService class."""

    def test_init(self, mock_db):
        """Test TokenCatalogService initialization."""
        service = TokenCatalogService(mock_db)
        assert service.db == mock_db

    def test_hash_token(self, token_service):
        """Test _hash_token method."""
        token = "test_token_123"
        result = token_service._hash_token(token)
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert result == expected
        assert len(result) == 64  # SHA-256 produces 64 hex characters

    def test_hash_token_consistency(self, token_service):
        """Test that _hash_token produces consistent results."""
        token = "consistent_token"
        hash1 = token_service._hash_token(token)
        hash2 = token_service._hash_token(token)
        assert hash1 == hash2

    def test_hash_token_different_inputs(self, token_service):
        """Test that different tokens produce different hashes."""
        hash1 = token_service._hash_token("token1")
        hash2 = token_service._hash_token("token2")
        assert hash1 != hash2

    def test_validate_scope_containment_allows_empty_scope(self, token_service):
        """Custom scopes are allowed only when requested scope is empty (inherit-at-runtime)."""
        token_service._validate_scope_containment(requested_permissions=None, caller_permissions=None)
        token_service._validate_scope_containment(requested_permissions=[], caller_permissions=[])

    def test_validate_scope_containment_denies_custom_scope_without_permissions(self, token_service):
        with pytest.raises(ValueError, match="Cannot specify custom token permissions"):
            token_service._validate_scope_containment(requested_permissions=["tools.read"], caller_permissions=None)

    def test_validate_scope_containment_allows_wildcard_caller(self, token_service):
        token_service._validate_scope_containment(requested_permissions=["anything"], caller_permissions=["*"])

    def test_validate_scope_containment_denies_wildcard_request_without_wildcard_caller(self, token_service):
        with pytest.raises(ValueError, match="Cannot create token with wildcard permissions"):
            token_service._validate_scope_containment(requested_permissions=["*"], caller_permissions=["tools.read"])

    def test_validate_scope_containment_allows_category_wildcard(self, token_service):
        token_service._validate_scope_containment(requested_permissions=["tools.read"], caller_permissions=["tools.*"])

    def test_validate_scope_containment_denies_permission_not_in_effective_permissions(self, token_service):
        with pytest.raises(ValueError, match="Cannot grant permission"):
            token_service._validate_scope_containment(requested_permissions=["tools.execute"], caller_permissions=["tools.read"])

    @pytest.mark.asyncio
    async def test_generate_token_basic(self, token_service):
        """Test _generate_token method with basic parameters."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_123"
            jti = str(uuid.uuid4())
            token = await token_service._generate_token("user@example.com", jti)

            assert token == "jwt_token_123"
            mock_create_jwt.assert_called_once()
            # Access keyword arguments from the call
            call_kwargs = mock_create_jwt.call_args.kwargs
            assert call_kwargs["data"]["sub"] == "user@example.com"
            assert call_kwargs["data"]["jti"] == jti
            assert call_kwargs["user_data"]["email"] == "user@example.com"
            assert call_kwargs["user_data"]["is_admin"] is False

    @pytest.mark.asyncio
    async def test_generate_token_with_team(self, token_service):
        """Test _generate_token method with team_id."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_team"
            jti = str(uuid.uuid4())
            token = await token_service._generate_token("user@example.com", jti=jti, team_id="team-123")

            assert token == "jwt_token_team"
            call_kwargs = mock_create_jwt.call_args.kwargs
            assert call_kwargs["teams"] == ["team-123"]
            # namespaces removed; API tokens have token_use="api" in data dict
            assert "namespaces" not in call_kwargs
            assert mock_create_jwt.call_args.kwargs.get("data", {}).get("token_use") == "api" or "token_use" in mock_create_jwt.call_args[0][0]

    @pytest.mark.asyncio
    async def test_generate_token_with_expiry(self, token_service):
        """Test _generate_token method with expiration."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_exp"
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("user@example.com", jti=jti, expires_at=expires_at)

            assert token == "jwt_token_exp"
            call_kwargs = mock_create_jwt.call_args.kwargs
            # expires_in_minutes should be calculated from expires_at using ceiling
            # 7 days = 10080 minutes
            assert call_kwargs["expires_in_minutes"] >= 10079  # Allow for timing variance

    @pytest.mark.asyncio
    async def test_generate_token_rejects_past_expiry(self, token_service):
        """Test _generate_token rejects expiration in the past."""
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        jti = str(uuid.uuid4())

        with pytest.raises(ValueError, match="Token expiration time is in the past"):
            await token_service._generate_token("user@example.com", jti=jti, expires_at=expires_at)

    @pytest.mark.asyncio
    async def test_generate_token_short_expiry_uses_ceiling(self, token_service):
        """Test _generate_token uses ceiling for sub-minute expiration to ensure exp is always set."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_short"
            # 30 seconds in the future should round up to 1 minute
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("user@example.com", jti=jti, expires_at=expires_at)

            assert token == "jwt_token_short"
            call_kwargs = mock_create_jwt.call_args.kwargs
            # Should be at least 1 minute due to ceiling and max(1, ...)
            assert call_kwargs["expires_in_minutes"] >= 1

    @pytest.mark.asyncio
    async def test_generate_token_with_scope(self, token_service, token_scope):
        """Test _generate_token method with TokenScope."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_scoped"
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("user@example.com", jti=jti, scope=token_scope)

            assert token == "jwt_token_scoped"
            call_kwargs = mock_create_jwt.call_args.kwargs
            assert call_kwargs["scopes"]["server_id"] == "server-123"
            assert call_kwargs["scopes"]["permissions"] == ["tools.read", "resources.read"]
            assert call_kwargs["scopes"]["ip_restrictions"] == ["192.168.1.0/24"]

    @pytest.mark.asyncio
    async def test_generate_token_with_admin_user(self, token_service, mock_user):
        """Test _generate_token method with admin user."""
        mock_user.is_admin = True
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_admin"
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("admin@example.com", jti=jti, user=mock_user)

            assert token == "jwt_token_admin"
            call_kwargs = mock_create_jwt.call_args.kwargs
            assert call_kwargs["user_data"]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_create_token_success(self, token_service, mock_db, mock_user):
        """Test create_token method - successful creation."""
        # Setup mocks
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # No existing token with same name
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen_token:
            mock_gen_token.return_value = "jwt_token_new"

            token, raw_token = await token_service.create_token(user_email="test@example.com", name="New Token", description="Test token", expires_in_days=30, tags=["api", "test"])

            assert raw_token == "jwt_token_new"
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called()
            mock_db.refresh.assert_called_once()

            # Check the token object added to DB
            added_token = mock_db.add.call_args[0][0]
            assert isinstance(added_token, EmailApiToken)
            assert added_token.user_email == "test@example.com"
            assert added_token.name == "New Token"
            assert added_token.description == "Test token"
            assert added_token.tags == ["api", "test"]

    @pytest.mark.asyncio
    async def test_create_token_user_not_found(self, token_service, mock_db):
        """Test create_token method - user not found."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(ValueError, match="User not found"):
            await token_service.create_token(user_email="nonexistent@example.com", name="Token")

    @pytest.mark.asyncio
    async def test_create_token_duplicate_name(self, token_service, mock_db, mock_user, mock_api_token):
        """Test create_token method - duplicate token name."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            mock_api_token,  # Token with same name exists
        ]

        with pytest.raises(ValueError, match="Token with name 'Duplicate' already exists for user test@example.com in team None. Please choose a different name."):
            await token_service.create_token(user_email="test@example.com", name="Duplicate")

    @pytest.mark.asyncio
    async def test_create_token_with_team_success(self, token_service, mock_db, mock_user, mock_team, mock_team_member):
        """Test create_token method with team - successful."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            mock_team,  # Team exists
            mock_team_member,  # User is team owner
            None,  # No existing token with same name
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen_token:
            mock_gen_token.return_value = "jwt_token_team"

            token, raw_token = await token_service.create_token(user_email="test@example.com", name="Team Token", team_id="team-123", expires_in_days=30)

            assert raw_token == "jwt_token_team"
            added_token = mock_db.add.call_args[0][0]
            assert added_token.team_id == "team-123"

    @pytest.mark.asyncio
    async def test_create_token_with_is_active_false(self, token_service, mock_db, mock_user):
        """Test create_token with is_active=False persists the inactive state."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # No existing token with same name
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen_token:
            mock_gen_token.return_value = "jwt_token_inactive"

            token, raw_token = await token_service.create_token(
                user_email="test@example.com",
                name="Inactive Token",
                is_active=False,
                expires_in_days=30,
            )

            assert raw_token == "jwt_token_inactive"
            # Verify the token added to DB has is_active=False
            added_token = mock_db.add.call_args[0][0]
            assert added_token.is_active is False

    @pytest.mark.asyncio
    async def test_create_token_default_is_active_true(self, token_service, mock_db, mock_user):
        """Test create_token defaults to is_active=True when not specified."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # No existing token with same name
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen_token:
            mock_gen_token.return_value = "jwt_token_active"

            token, raw_token = await token_service.create_token(
                user_email="test@example.com",
                name="Default Active Token",
                expires_in_days=30,
            )

            # Verify the token added to DB has is_active=True by default
            added_token = mock_db.add.call_args[0][0]
            assert added_token.is_active is True

    @pytest.mark.asyncio
    async def test_create_token_team_not_found(self, token_service, mock_db, mock_user):
        """Test create_token method - team not found."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # Team doesn't exist
        ]

        with pytest.raises(ValueError, match="Team not found"):
            await token_service.create_token(user_email="test@example.com", name="Token", team_id="nonexistent-team")

    @pytest.mark.asyncio
    async def test_create_token_not_team_owner(self, token_service, mock_db, mock_user, mock_team):
        """Test create_token method - user not team owner."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            mock_team,  # Team exists
            None,  # User is not team owner
        ]

        with pytest.raises(ValueError, match="User test@example.com is not an active member of team team-123. Only team members can create tokens for the team."):
            await token_service.create_token(user_email="test@example.com", name="Token", team_id="team-123")

    @pytest.mark.asyncio
    async def test_create_token_with_scope(self, token_service, mock_db, mock_user, token_scope):
        """Test create_token method with TokenScope."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # No existing token
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen_token:
            mock_gen_token.return_value = "jwt_token_scoped"

            # Must provide caller_permissions that include the requested scope permissions
            token, raw_token = await token_service.create_token(
                user_email="test@example.com",
                name="Scoped Token",
                scope=token_scope,
                caller_permissions=["tools.read", "resources.read"],  # Caller has these permissions
                expires_in_days=30,
            )

            assert raw_token == "jwt_token_scoped"
            added_token = mock_db.add.call_args[0][0]
            assert added_token.server_id == "server-123"
            assert added_token.resource_scopes == ["tools.read", "resources.read"]
            assert added_token.ip_restrictions == ["192.168.1.0/24"]

    @pytest.mark.asyncio
    async def test_list_user_tokens_basic(self, token_service, mock_db, mock_api_token):
        """Test list_user_tokens method - basic case."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_api_token]
        mock_db.execute.return_value = mock_result

        tokens = await token_service.list_user_tokens("test@example.com")

        assert len(tokens) == 1
        assert tokens[0] == mock_api_token
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_user_tokens_with_inactive(self, token_service, mock_db):
        """Test list_user_tokens method - including inactive tokens."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        tokens = await token_service.list_user_tokens("test@example.com", include_inactive=True)

        assert tokens == []
        # Verify query was executed (should not filter out inactive tokens)
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_list_user_tokens_with_pagination(self, token_service, mock_db):
        """Test list_user_tokens method with pagination."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await token_service.list_user_tokens("test@example.com", limit=10, offset=20)

        # Verify query was executed (should have limit and offset applied)
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_list_user_tokens_invalid_limit(self, token_service, mock_db):
        """Test list_user_tokens method with invalid limit."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        # Test with limit too high
        await token_service.list_user_tokens("test@example.com", limit=2000)
        # Should use default limit of 50

        # Test with negative limit
        await token_service.list_user_tokens("test@example.com", limit=-5)
        # Should use default limit of 50

    @pytest.mark.asyncio
    async def test_list_team_tokens_success(self, token_service, mock_db, mock_api_token):
        """Test list_team_tokens method - user is active team member."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_api_token]
        mock_db.execute.return_value = mock_result

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=["team-123"]):
            tokens = await token_service.list_team_tokens("team-123", "test@example.com")

        assert len(tokens) == 1
        assert tokens[0] == mock_api_token

    @pytest.mark.asyncio
    async def test_list_team_tokens_invalid_limit_uses_default(self, token_service, mock_db):
        """Invalid list_team_tokens limit should fall back to the default limit (50)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=["team-123"]):
            await token_service.list_team_tokens("team-123", "test@example.com", limit=0)

        query = mock_db.execute.call_args_list[-1][0][0]
        assert query._limit_clause.value == 50  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_list_team_tokens_not_member(self, token_service, mock_db):
        """Test list_team_tokens method - user is not a team member."""
        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(ValueError, match="is not an active member of team"):
                await token_service.list_team_tokens("team-123", "notmember@example.com")

    @pytest.mark.asyncio
    async def test_list_user_and_team_tokens_basic(self, token_service, mock_db, mock_api_token):
        """Test list_user_and_team_tokens method - basic case with personal tokens."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_api_token]

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=[]):
            tokens = await token_service.list_user_and_team_tokens("test@example.com")

        assert len(tokens) == 1
        assert tokens[0] == mock_api_token

    @pytest.mark.asyncio
    async def test_list_user_and_team_tokens_with_team_member(self, token_service, mock_db):
        """Test list_user_and_team_tokens includes team tokens for team members."""
        personal_token = MagicMock(spec=EmailApiToken)
        personal_token.id = "personal-token"
        personal_token.user_email = "test@example.com"
        personal_token.team_id = None

        team_token = MagicMock(spec=EmailApiToken)
        team_token.id = "team-token"
        team_token.user_email = "other@example.com"  # Created by someone else
        team_token.team_id = "team-123"

        mock_db.execute.return_value.scalars.return_value.all.return_value = [personal_token, team_token]

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=["team-123"]):
            tokens = await token_service.list_user_and_team_tokens("test@example.com")

        assert len(tokens) == 2
        token_ids = [t.id for t in tokens]
        assert "personal-token" in token_ids
        assert "team-token" in token_ids

    @pytest.mark.asyncio
    async def test_list_user_and_team_tokens_with_inactive(self, token_service, mock_db):
        """Test list_user_and_team_tokens method - including inactive tokens."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=[]):
            await token_service.list_user_and_team_tokens("test@example.com", include_inactive=True)

        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_list_user_and_team_tokens_with_pagination(self, token_service, mock_db):
        """Test list_user_and_team_tokens method with pagination."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=[]):
            await token_service.list_user_and_team_tokens("test@example.com", limit=10, offset=20)

        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_list_user_and_team_tokens_invalid_limit(self, token_service, mock_db):
        """Test list_user_and_team_tokens method with invalid limit."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=[]):
            await token_service.list_user_and_team_tokens("test@example.com", limit=2000)
            await token_service.list_user_and_team_tokens("test@example.com", limit=-5)

        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_get_token_found(self, token_service, mock_db, mock_api_token):
        """Test get_token method - token found."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_api_token

        token = await token_service.get_token("token-123")

        assert token == mock_api_token
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_token_with_user_filter(self, token_service, mock_db, mock_api_token):
        """Test get_token method with user email filter."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_api_token

        token = await token_service.get_token("token-123", user_email="test@example.com")

        assert token == mock_api_token

    @pytest.mark.asyncio
    async def test_get_token_not_found(self, token_service, mock_db):
        """Test get_token method - token not found."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        token = await token_service.get_token("nonexistent-token")

        assert token is None

    @pytest.mark.asyncio
    async def test_update_token_success(self, token_service, mock_db, mock_api_token):
        """Test update_token method - successful update."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No duplicate name

            updated = await token_service.update_token(token_id="token-123", user_email="test@example.com", name="Updated Name", description="Updated description", tags=["new", "tags"])

            assert updated == mock_api_token
            assert mock_api_token.name == "Updated Name"
            assert mock_api_token.description == "Updated description"
            assert mock_api_token.tags == ["new", "tags"]
            mock_db.commit.assert_called()
            mock_db.refresh.assert_called_once_with(mock_api_token)

    @pytest.mark.asyncio
    async def test_update_token_not_found(self, token_service):
        """Test update_token method - token not found."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            with pytest.raises(ValueError, match="Token not found or not authorized"):
                await token_service.update_token(token_id="nonexistent", user_email="test@example.com", name="New Name")

    @pytest.mark.asyncio
    async def test_update_token_duplicate_name(self, token_service, mock_db, mock_api_token):
        """Test update_token method - duplicate name."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            mock_db.execute.return_value.scalar_one_or_none.return_value = MagicMock()  # Duplicate exists

            with pytest.raises(ValueError, match="Token name 'Duplicate' already exists"):
                await token_service.update_token(token_id="token-123", user_email="test@example.com", name="Duplicate")

    @pytest.mark.asyncio
    async def test_update_token_with_scope(self, token_service, mock_db, mock_api_token, token_scope):
        """Test update_token method with TokenScope."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            # Must provide caller_permissions that include the requested scope permissions
            updated = await token_service.update_token(
                token_id="token-123",
                user_email="test@example.com",
                scope=token_scope,
                caller_permissions=["tools.read", "resources.read"],  # Caller has these permissions
            )

            assert mock_api_token.server_id == "server-123"
            assert mock_api_token.resource_scopes == ["tools.read", "resources.read"]
            assert mock_api_token.ip_restrictions == ["192.168.1.0/24"]
            assert mock_api_token.time_restrictions == {"business_hours_only": True}
            assert mock_api_token.usage_limits == {"max_requests_per_hour": 100}

    @pytest.mark.asyncio
    async def test_update_token_deactivate(self, token_service, mock_db, mock_api_token):
        """Test update_token to deactivate a token by setting is_active=False."""
        mock_api_token.is_active = True  # Start as active

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            await token_service.update_token(
                token_id="token-123",
                user_email="test@example.com",
                is_active=False,
            )

            # Verify token was deactivated
            assert mock_api_token.is_active is False
            mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_token_reactivate(self, token_service, mock_db, mock_api_token):
        """Test update_token to reactivate a token by setting is_active=True."""
        mock_api_token.is_active = False  # Start as inactive

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            await token_service.update_token(
                token_id="token-123",
                user_email="test@example.com",
                is_active=True,
            )

            # Verify token was reactivated
            assert mock_api_token.is_active is True
            mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_update_token_is_active_none_no_change(self, token_service, mock_db, mock_api_token):
        """Test update_token with is_active=None does not change the active status."""
        mock_api_token.is_active = True  # Start as active

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            await token_service.update_token(
                token_id="token-123",
                user_email="test@example.com",
                description="Updated description",  # Only update description, not name
                is_active=None,  # Explicitly None - should not change
            )

            # Verify is_active was not changed
            assert mock_api_token.is_active is True

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, token_service, mock_db, mock_api_token):
        """Test revoke_token method - successful revocation."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            # Must provide user_email for ownership verification
            result = await token_service.revoke_token(
                token_id="token-123",
                user_email="test@example.com",  # Token owner
                revoked_by="test@example.com",
                reason="Security concern",
            )

            assert result is True
            assert mock_api_token.is_active is False
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called()

            # Check revocation record
            revocation = mock_db.add.call_args[0][0]
            assert isinstance(revocation, TokenRevocation)
            assert revocation.jti == "jti-123"
            assert revocation.revoked_by == "test@example.com"
            assert revocation.reason == "Security concern"

    @pytest.mark.asyncio
    async def test_revoke_token_cache_invalidation_failure_is_swallowed(self, token_service, mock_api_token):
        """If auth cache invalidation fails, revocation should still succeed."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            # Patch invalidate_revocation to avoid any Redis dependency and to return a coroutine we can safely close.
            with patch("mcpgateway.cache.auth_cache.auth_cache.invalidate_revocation", new_callable=AsyncMock):
                # Patch create_task to raise, but close the coroutine to avoid warnings.
                import asyncio  # pylint: disable=import-outside-toplevel

                def _boom_create_task(coro):
                    coro.close()
                    raise RuntimeError("boom")

                with patch.object(asyncio, "create_task", side_effect=_boom_create_task):
                    result = await token_service.revoke_token(
                        token_id="token-123",
                        user_email="test@example.com",
                        revoked_by="test@example.com",
                        reason="test",
                    )

        assert result is True

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, token_service):
        """Test revoke_token method - token not found."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            # Must provide user_email for ownership verification
            result = await token_service.revoke_token(
                token_id="nonexistent",
                user_email="test@example.com",
                revoked_by="test@example.com",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_revoke_token_team_owner_can_revoke_team_token(self, token_service, mock_db):
        """Test that a team owner can revoke a token scoped to their team even if they don't own it."""
        team_token = MagicMock(spec=EmailApiToken)
        team_token.id = "team-token-456"
        team_token.user_email = "other@example.com"  # Owned by someone else
        team_token.team_id = "team-123"
        team_token.is_active = True
        team_token.jti = "jti-team-456"
        team_token.name = "Other's Team Token"

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            # First call (with user_email) returns None (not owned by caller)
            # Second call (without user_email) returns the team token
            mock_get.side_effect = [None, team_token]

            with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_team_cls:
                mock_team_svc = MagicMock()
                mock_team_svc.get_user_role_in_team = AsyncMock(return_value="owner")
                mock_team_cls.return_value = mock_team_svc

                result = await token_service.revoke_token(
                    token_id="team-token-456",
                    user_email="owner@example.com",
                    revoked_by="owner@example.com",
                    reason="No longer needed",
                )

        assert result is True
        assert team_token.is_active is False
        revocation = mock_db.add.call_args[0][0]
        assert isinstance(revocation, TokenRevocation)
        assert revocation.jti == "jti-team-456"
        assert revocation.revoked_by == "owner@example.com"

    @pytest.mark.asyncio
    async def test_revoke_token_regular_member_cannot_revoke_team_token(self, token_service):
        """Test that a regular team member cannot revoke another member's team token."""
        team_token = MagicMock(spec=EmailApiToken)
        team_token.id = "team-token-789"
        team_token.team_id = "team-123"

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [None, team_token]

            with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_team_cls:
                mock_team_svc = MagicMock()
                mock_team_svc.get_user_role_in_team = AsyncMock(return_value="member")
                mock_team_cls.return_value = mock_team_svc

                result = await token_service.revoke_token(
                    token_id="team-token-789",
                    user_email="member@example.com",
                    revoked_by="member@example.com",
                )

        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_token_non_member_cannot_revoke_team_token(self, token_service):
        """Test that a non-member cannot revoke a team-scoped token."""
        team_token = MagicMock(spec=EmailApiToken)
        team_token.id = "team-token-789"
        team_token.team_id = "team-123"

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [None, team_token]

            with patch("mcpgateway.services.team_management_service.TeamManagementService") as mock_team_cls:
                mock_team_svc = MagicMock()
                mock_team_svc.get_user_role_in_team = AsyncMock(return_value=None)
                mock_team_cls.return_value = mock_team_svc

                result = await token_service.revoke_token(
                    token_id="team-token-789",
                    user_email="outsider@example.com",
                    revoked_by="outsider@example.com",
                )

        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_token_non_team_token_not_owned(self, token_service):
        """Test that a non-team token that isn't owned by the caller cannot be revoked."""
        personal_token = MagicMock(spec=EmailApiToken)
        personal_token.id = "personal-token-999"
        personal_token.team_id = None  # Not a team token

        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [None, personal_token]

            result = await token_service.revoke_token(
                token_id="personal-token-999",
                user_email="other@example.com",
                revoked_by="other@example.com",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_admin_revoke_token_not_found(self, token_service):
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            result = await token_service.admin_revoke_token("missing", revoked_by="admin@example.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_admin_revoke_token_cache_invalidation_failure_is_swallowed(self, token_service, mock_db, mock_api_token):
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            with patch("mcpgateway.cache.auth_cache.auth_cache.invalidate_revocation", new_callable=AsyncMock):
                # Standard
                import asyncio  # pylint: disable=import-outside-toplevel

                def _boom_create_task(coro):
                    coro.close()
                    raise RuntimeError("boom")

                with patch.object(asyncio, "create_task", side_effect=_boom_create_task):
                    result = await token_service.admin_revoke_token("token-123", revoked_by="admin@example.com", reason="test")

        assert result is True
        assert mock_api_token.is_active is False
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_is_token_revoked_true(self, token_service, mock_db):
        """Test is_token_revoked method - token is revoked."""
        mock_revocation = MagicMock(spec=TokenRevocation)
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_revocation

        result = await token_service.is_token_revoked("jti-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_token_revoked_false(self, token_service, mock_db):
        """Test is_token_revoked method - token not revoked."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = await token_service.is_token_revoked("jti-456")

        assert result is False

    @pytest.mark.asyncio
    async def test_log_token_usage_basic(self, token_service, mock_db, mock_api_token):
        """Test log_token_usage method - basic logging."""
        await token_service.log_token_usage(
            jti="jti-123",
            user_email="test@example.com",
            endpoint="/api/tools",
            method="GET",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            status_code=200,
            response_time_ms=45,
        )

        # Check usage log was added
        assert mock_db.add.call_count == 1
        usage_log = mock_db.add.call_args[0][0]
        assert isinstance(usage_log, TokenUsageLog)
        assert usage_log.token_jti == "jti-123"
        assert usage_log.user_email == "test@example.com"
        assert usage_log.endpoint == "/api/tools"
        assert usage_log.method == "GET"
        assert usage_log.status_code == 200
        assert usage_log.response_time_ms == 45
        assert usage_log.blocked is False

        # Note: last_used is updated during authentication (auth.py), not here
        # This method only logs usage statistics

    @pytest.mark.asyncio
    async def test_log_token_usage_blocked(self, token_service, mock_db):
        """Test log_token_usage method - blocked request."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # No token found

        await token_service.log_token_usage(
            jti="jti-blocked",
            user_email="test@example.com",
            endpoint="/api/admin",
            method="DELETE",
            ip_address="10.0.0.1",
            blocked=True,
            block_reason="IP not in whitelist",
        )

        usage_log = mock_db.add.call_args[0][0]
        assert usage_log.blocked is True
        assert usage_log.block_reason == "IP not in whitelist"

    @pytest.mark.asyncio
    async def test_get_token_usage_stats_basic(self, token_service, mock_db):
        """Test get_token_usage_stats method - basic statistics."""
        # Create mock usage logs
        mock_logs = []
        for i in range(10):
            log = MagicMock(spec=TokenUsageLog)
            log.status_code = 200 if i < 8 else 401
            log.blocked = i == 9
            log.response_time_ms = 50 + i * 10
            log.endpoint = "/api/tools" if i < 5 else "/api/resources"
            mock_logs.append(log)

        mock_db.execute.return_value.scalars.return_value.all.return_value = mock_logs

        stats = await token_service.get_token_usage_stats("test@example.com", days=7)

        assert stats["period_days"] == 7
        assert stats["total_requests"] == 10
        assert stats["successful_requests"] == 8
        assert stats["blocked_requests"] == 1
        assert stats["success_rate"] == 0.8
        assert stats["average_response_time_ms"] > 0
        assert len(stats["top_endpoints"]) == 2
        assert stats["top_endpoints"][0][0] == "/api/tools"
        assert stats["top_endpoints"][0][1] == 5

    @pytest.mark.asyncio
    async def test_get_token_usage_stats_with_token_id(self, token_service, mock_db, mock_api_token):
        """Test get_token_usage_stats method with specific token ID."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            mock_db.execute.return_value.scalars.return_value.all.return_value = []

            stats = await token_service.get_token_usage_stats("test@example.com", token_id="token-123", days=30)

            assert stats["total_requests"] == 0
            assert stats["success_rate"] == 0
            assert stats["average_response_time_ms"] == 0
            assert stats["top_endpoints"] == []

    @pytest.mark.asyncio
    async def test_get_token_usage_stats_no_data(self, token_service, mock_db):
        """Test get_token_usage_stats method with no usage data."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        stats = await token_service.get_token_usage_stats("test@example.com")

        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["blocked_requests"] == 0
        assert stats["success_rate"] == 0
        assert stats["average_response_time_ms"] == 0
        assert stats["top_endpoints"] == []

    @pytest.mark.asyncio
    async def test_get_token_revocation_found(self, token_service, mock_db):
        """Test get_token_revocation method - revocation found."""
        mock_revocation = MagicMock(spec=TokenRevocation)
        mock_revocation.jti = "jti-123"
        mock_revocation.revoked_by = "admin@example.com"
        mock_revocation.reason = "Compromised"
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_revocation

        revocation = await token_service.get_token_revocation("jti-123")

        assert revocation == mock_revocation
        assert revocation.reason == "Compromised"

    @pytest.mark.asyncio
    async def test_get_token_revocation_not_found(self, token_service, mock_db):
        """Test get_token_revocation method - not found."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        revocation = await token_service.get_token_revocation("jti-456")

        assert revocation is None

    @pytest.mark.asyncio
    async def test_get_user_team_ids(self, token_service, mock_db):
        """Test get_user_team_ids delegates to TeamManagementService."""
        mock_team1 = MagicMock()
        mock_team1.id = "team-a"
        mock_team2 = MagicMock()
        mock_team2.id = "team-b"

        with patch("mcpgateway.services.team_management_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[mock_team1, mock_team2])
            MockTMS.return_value = mock_tms

            result = await token_service.get_user_team_ids("user@example.com")

        assert result == ["team-a", "team-b"]
        mock_tms.get_user_teams.assert_awaited_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_get_user_team_ids_no_teams(self, token_service, mock_db):
        """Test get_user_team_ids returns empty list when user has no teams."""
        with patch("mcpgateway.services.team_management_service.TeamManagementService") as MockTMS:
            mock_tms = MagicMock()
            mock_tms.get_user_teams = AsyncMock(return_value=[])
            MockTMS.return_value = mock_tms

            result = await token_service.get_user_team_ids("lonely@example.com")

        assert result == []

    @pytest.mark.asyncio
    async def test_count_user_and_team_tokens(self, token_service, mock_db):
        """Test count_user_and_team_tokens with teams."""
        with patch.object(token_service, "get_user_team_ids", AsyncMock(return_value=["team-1"])):
            mock_db.execute.return_value.scalar.return_value = 5

            count = await token_service.count_user_and_team_tokens("user@example.com")

        assert count == 5

    @pytest.mark.asyncio
    async def test_count_user_and_team_tokens_no_teams(self, token_service, mock_db):
        """Test count_user_and_team_tokens without teams."""
        with patch.object(token_service, "get_user_team_ids", AsyncMock(return_value=[])):
            mock_db.execute.return_value.scalar.return_value = 2

            count = await token_service.count_user_and_team_tokens("user@example.com")

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_user_and_team_tokens_include_inactive(self, token_service, mock_db):
        """Test count_user_and_team_tokens with include_inactive=True."""
        with patch.object(token_service, "get_user_team_ids", AsyncMock(return_value=[])):
            mock_db.execute.return_value.scalar.return_value = 10

            count = await token_service.count_user_and_team_tokens("user@example.com", include_inactive=True)

        assert count == 10

    @pytest.mark.asyncio
    async def test_count_user_and_team_tokens_none_result(self, token_service, mock_db):
        """Test count_user_and_team_tokens returns 0 when scalar returns None."""
        with patch.object(token_service, "get_user_team_ids", AsyncMock(return_value=[])):
            mock_db.execute.return_value.scalar.return_value = None

            count = await token_service.count_user_and_team_tokens("user@example.com")

        assert count == 0

    @pytest.mark.asyncio
    async def test_get_token_revocations_batch_multiple(self, token_service, mock_db):
        """Test batch revocation lookup returns dict keyed by JTI."""
        rev1 = MagicMock(spec=TokenRevocation)
        rev1.jti = "jti-1"
        rev2 = MagicMock(spec=TokenRevocation)
        rev2.jti = "jti-3"
        mock_db.execute.return_value.scalars.return_value.all.return_value = [rev1, rev2]

        result = await token_service.get_token_revocations_batch(["jti-1", "jti-2", "jti-3"])

        assert result == {"jti-1": rev1, "jti-3": rev2}
        assert "jti-2" not in result

    @pytest.mark.asyncio
    async def test_get_token_revocations_batch_empty_input(self, token_service, mock_db):
        """Test batch revocation lookup with empty list returns empty dict without querying."""
        result = await token_service.get_token_revocations_batch([])

        assert result == {}
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_token_revocations_batch_none_revoked(self, token_service, mock_db):
        """Test batch revocation lookup when no tokens are revoked."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        result = await token_service.get_token_revocations_batch(["jti-1", "jti-2"])

        assert result == {}

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_multiple(self, token_service, mock_db):
        """Test cleanup_expired_tokens method with multiple expired tokens."""
        # Mock bulk UPDATE returning count of 5 updated rows
        mock_db.query.return_value.filter.return_value.update.return_value = 5

        count = await token_service.cleanup_expired_tokens()

        assert count == 5
        mock_db.query.assert_called_once_with(EmailApiToken)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_none(self, token_service, mock_db):
        """Test cleanup_expired_tokens method with no expired tokens."""
        # Mock bulk UPDATE returning 0 updated rows
        mock_db.query.return_value.filter.return_value.update.return_value = 0

        count = await token_service.cleanup_expired_tokens()

        assert count == 0
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_partial(self, token_service, mock_db):
        """Test cleanup_expired_tokens method with some expired tokens."""
        # Mock bulk UPDATE returning count of 2 updated rows
        mock_db.query.return_value.filter.return_value.update.return_value = 2

        count = await token_service.cleanup_expired_tokens()

        assert count == 2
        mock_db.query.assert_called_once_with(EmailApiToken)

    @pytest.mark.asyncio
    async def test_cleanup_expired_tokens_db_error(self, token_service, mock_db):
        """Test cleanup_expired_tokens handles database errors gracefully."""
        # Mock database error
        mock_db.query.return_value.filter.return_value.update.side_effect = Exception("Database error")

        count = await token_service.cleanup_expired_tokens()

        assert count == 0
        mock_db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# Edge Cases and Error Handling Tests                                        #
# --------------------------------------------------------------------------- #
class TestTokenCatalogServiceEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_create_token_empty_name(self, token_service, mock_db, mock_user):
        """Test create_token with empty name."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt"
            token, _ = await token_service.create_token(user_email="test@example.com", name="", expires_in_days=30)  # Empty name should still work
            assert mock_db.add.called

    @pytest.mark.asyncio
    async def test_create_token_very_long_description(self, token_service, mock_db, mock_user):
        """Test create_token with very long description."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        long_desc = "A" * 10000  # Very long description
        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt"
            token, _ = await token_service.create_token(user_email="test@example.com", name="Token", description=long_desc, expires_in_days=30)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.description == long_desc

    @pytest.mark.asyncio
    async def test_create_token_negative_expiry(self, token_service, mock_db, mock_user):
        """Test create_token with negative expiry days."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt"
            # Negative expiry should still create a token (expired immediately)
            token, _ = await token_service.create_token(user_email="test@example.com", name="Token", expires_in_days=-1)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.expires_at is not None

    @pytest.mark.asyncio
    async def test_list_user_tokens_empty_email(self, token_service, mock_db):
        """Test list_user_tokens with empty email."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        tokens = await token_service.list_user_tokens("")  # Empty email
        assert tokens == []

    @pytest.mark.asyncio
    async def test_update_token_none_values(self, token_service, mock_db, mock_api_token):
        """Test update_token with None values (should not update)."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            original_desc = mock_api_token.description

            await token_service.update_token(token_id="token-123", user_email="test@example.com", description=None)

            # Description should remain unchanged
            assert mock_api_token.description == original_desc
            mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_log_token_usage_missing_token(self, token_service, mock_db):
        """Test log_token_usage when token doesn't exist in DB."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None  # Token not found

        # Should still log usage even if token not found
        await token_service.log_token_usage(jti="nonexistent-jti", user_email="test@example.com")

        assert mock_db.add.called
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_get_token_usage_stats_invalid_days(self, token_service, mock_db):
        """Test get_token_usage_stats with invalid days parameter."""
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        # Negative days
        stats = await token_service.get_token_usage_stats("test@example.com", days=-10)
        assert stats["period_days"] == -10  # Should still process

        # Zero days
        stats = await token_service.get_token_usage_stats("test@example.com", days=0)
        assert stats["period_days"] == 0

    @pytest.mark.asyncio
    async def test_hash_token_unicode(self, token_service):
        """Test _hash_token with unicode characters."""
        unicode_token = "token_🔑_秘密_κλειδί"
        hash_result = token_service._hash_token(unicode_token)
        assert len(hash_result) == 64
        assert hash_result != token_service._hash_token("regular_token")

    @pytest.mark.asyncio
    async def test_create_token_with_empty_scope(self, token_service, mock_db, mock_user):
        """Test create_token with empty TokenScope."""
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        empty_scope = TokenScope()  # All defaults
        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt"
            token, _ = await token_service.create_token(user_email="test@example.com", name="Token", scope=empty_scope, expires_in_days=30)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.server_id is None
            assert added_token.resource_scopes == []

    @pytest.mark.asyncio
    async def test_create_token_no_expiry_when_required(self, token_service, mock_db, mock_user, monkeypatch):
        """Test create_token rejects None expiry when REQUIRE_TOKEN_EXPIRATION=true."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "require_token_expiration", True)

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with pytest.raises(ValueError, match="Token expiration is required by server policy"):
            await token_service.create_token(user_email="test@example.com", name="No Expiry Token", expires_in_days=None)

    @pytest.mark.asyncio
    async def test_create_token_no_expiry_when_allowed(self, token_service, mock_db, mock_user, monkeypatch):
        """Test create_token allows None expiry when REQUIRE_TOKEN_EXPIRATION=false."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "require_token_expiration", False)

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt_token_without_exp"
            token, raw_token = await token_service.create_token(user_email="test@example.com", name="No Expiry Token", expires_in_days=None)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.expires_at is None
            assert raw_token == "jwt_token_without_exp"

    @pytest.mark.asyncio
    async def test_create_token_with_expiry_when_required(self, token_service, mock_db, mock_user, monkeypatch):
        """Test create_token accepts expiry when REQUIRE_TOKEN_EXPIRATION=true."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "require_token_expiration", True)

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt_token_with_exp"
            token, raw_token = await token_service.create_token(user_email="test@example.com", name="Token With Expiry", expires_in_days=30)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.expires_at is not None
            assert raw_token == "jwt_token_with_exp"

    @pytest.mark.asyncio
    async def test_create_token_with_team_and_expiry_required(self, token_service, mock_db, mock_user, mock_team, mock_team_member, monkeypatch):
        """Test create_token with team requires expiry when REQUIRE_TOKEN_EXPIRATION=true."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "require_token_expiration", True)

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            mock_team,
            mock_team_member,
            None,
        ]

        with pytest.raises(ValueError, match="Token expiration is required by server policy"):
            await token_service.create_token(user_email="test@example.com", name="Team Token", team_id="team-123", expires_in_days=None)

    @pytest.mark.asyncio
    async def test_create_token_zero_expiry_days_when_required(self, token_service, mock_db, mock_user, monkeypatch):
        """Test create_token with expires_in_days=0 is treated as no expiry and rejected when REQUIRE_TOKEN_EXPIRATION=true."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "require_token_expiration", True)

        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            None,
        ]

        with pytest.raises(ValueError, match="Token expiration is required by server policy"):
            await token_service.create_token(user_email="test@example.com", name="Zero Expiry Token", expires_in_days=0)

    @pytest.mark.asyncio
    async def test_generate_token_settings_values(self, token_service):
        """Test _generate_token delegates to create_jwt_token correctly."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = "jwt"
            jti = str(uuid.uuid4())

            await token_service._generate_token("user@example.com", jti=jti)

            # Verify the function was called with correct keyword arguments
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["data"]["sub"] == "user@example.com"
            assert call_kwargs["data"]["jti"] == jti
            assert "user_data" in call_kwargs
            assert "teams" in call_kwargs
            assert "namespaces" not in call_kwargs
            assert "scopes" in call_kwargs


# --------------------------------------------------------------------------- #
# Integration-like Tests                                                      #
# --------------------------------------------------------------------------- #
class TestTokenCatalogServiceIntegration:
    """Integration-like tests for complex scenarios."""

    @pytest.mark.asyncio
    async def test_full_token_lifecycle(self, token_service, mock_db, mock_user, mock_api_token):
        """Test complete token lifecycle: create, update, use, revoke."""
        # Create token
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,  # User exists
            None,  # No duplicate
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt_new"
            token, raw = await token_service.create_token(user_email="test@example.com", name="Lifecycle Token", expires_in_days=30)

        # Update token
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            # Reset side_effect and use return_value for update
            mock_db.execute.return_value.scalar_one_or_none.side_effect = None
            mock_db.execute.return_value.scalar_one_or_none.return_value = None
            await token_service.update_token(token_id="token-123", user_email="test@example.com", name="Updated Lifecycle")

        # Log usage
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_api_token
        await token_service.log_token_usage(jti="jti-123", user_email="test@example.com", endpoint="/api/test")

        # Get stats
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        await token_service.get_token_usage_stats("test@example.com")

        # Revoke token
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            result = await token_service.revoke_token(
                token_id="token-123",
                user_email="test@example.com",
                revoked_by="test@example.com",
            )
            assert result is True

        # Check if revoked
        mock_db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
        is_revoked = await token_service.is_token_revoked("jti-123")
        assert is_revoked is True

    @pytest.mark.asyncio
    async def test_team_token_management_flow(self, token_service, mock_db, mock_user, mock_team, mock_team_member):
        """Test team token management workflow."""
        # Create team token
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_user,
            mock_team,
            mock_team_member,
            None,
        ]

        with patch.object(token_service, "_generate_token", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "jwt_team"
            token, _ = await token_service.create_token(user_email="test@example.com", name="Team Token", team_id="team-123", expires_in_days=30)

        # List team tokens
        mock_db.execute.side_effect = None
        mock_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))

        with patch.object(token_service, "get_user_team_ids", new_callable=AsyncMock, return_value=["team-123"]):
            tokens = await token_service.list_team_tokens("team-123", "test@example.com")
        assert isinstance(tokens, list)

    @pytest.mark.asyncio
    async def test_concurrent_token_operations(self, token_service, mock_db, mock_api_token):
        """Test handling of concurrent token operations."""
        # Simulate concurrent updates
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            # First update
            mock_db.execute.return_value.scalar_one_or_none.return_value = None
            await token_service.update_token(token_id="token-123", user_email="test@example.com", name="First Update")

            # Second update (simulating concurrent access)
            await token_service.update_token(token_id="token-123", user_email="test@example.com", description="Concurrent Update")

            # Both updates should succeed
            assert mock_db.commit.call_count >= 2


# --------------------------------------------------------------------------- #
# SQL Optimization Tests (PostgreSQL vs Python fallback)                       #
# --------------------------------------------------------------------------- #
class TestTokenCatalogServiceSqlOptimization:
    """Tests for SQL-optimized usage stats computation."""

    @pytest.mark.asyncio
    async def test_get_usage_stats_postgresql_path(self, mock_db):
        """Test that PostgreSQL path is used when available."""
        # Mock the session's bind dialect instead of global engine
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.get_bind.return_value = mock_bind
        service = TokenCatalogService(mock_db)

        # Mock the PostgreSQL queries - attribute names match SQL query labels
        mock_stats_row = MagicMock()
        mock_stats_row.total = 100
        mock_stats_row.successful = 90
        mock_stats_row.blocked = 5
        mock_stats_row.avg_response = 45.5

        mock_endpoint_row = MagicMock()
        mock_endpoint_row.endpoint = "/api/tools"
        mock_endpoint_row.count = 50

        # Configure execute to return different results for different queries
        mock_db.execute.return_value.fetchone.return_value = mock_stats_row
        mock_db.execute.return_value.fetchall.return_value = [mock_endpoint_row]

        stats = await service.get_token_usage_stats("test@example.com", days=7)

        assert stats["total_requests"] == 100
        assert stats["successful_requests"] == 90
        assert stats["blocked_requests"] == 5
        assert stats["average_response_time_ms"] == 45.5

    @pytest.mark.asyncio
    async def test_get_usage_stats_postgresql_path_with_token_filter(self, mock_db):
        """PostgreSQL usage stats should include the token_jti filter when a token_id is provided."""
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.get_bind.return_value = mock_bind
        service = TokenCatalogService(mock_db)

        mock_token = MagicMock()
        mock_token.jti = "jti-123"

        mock_token_result = MagicMock()
        mock_token_result.scalar_one_or_none.return_value = mock_token

        mock_stats_row = MagicMock()
        mock_stats_row.total = 1
        mock_stats_row.successful = 1
        mock_stats_row.blocked = 0
        mock_stats_row.avg_response = 1.0

        mock_stats_result = MagicMock()
        mock_stats_result.fetchone.return_value = mock_stats_row

        mock_endpoint_row = MagicMock()
        mock_endpoint_row.endpoint = "/api/tools"
        mock_endpoint_row.count = 1

        mock_endpoints_result = MagicMock()
        mock_endpoints_result.fetchall.return_value = [mock_endpoint_row]

        mock_db.execute.side_effect = [mock_token_result, mock_stats_result, mock_endpoints_result]

        stats = await service.get_token_usage_stats("test@example.com", token_id="token-123", days=7)

        assert stats["total_requests"] == 1
        assert stats["successful_requests"] == 1

    @pytest.mark.asyncio
    async def test_get_usage_stats_sqlite_fallback(self, mock_db):
        """Test that Python fallback is used for SQLite."""
        # Mock the session's bind dialect instead of global engine
        mock_bind = MagicMock()
        mock_bind.dialect.name = "sqlite"
        mock_db.get_bind.return_value = mock_bind
        service = TokenCatalogService(mock_db)

        # Mock the Python path query
        mock_logs = []
        for i in range(10):
            log = MagicMock()
            log.status_code = 200
            log.blocked = False
            log.response_time_ms = 50.0
            log.endpoint = "/api/test"
            mock_logs.append(log)

        mock_db.execute.return_value.scalars.return_value.all.return_value = mock_logs

        stats = await service.get_token_usage_stats("test@example.com", days=7)

        assert stats["total_requests"] == 10
        assert stats["successful_requests"] == 10
        assert stats["blocked_requests"] == 0

    @pytest.mark.asyncio
    async def test_get_usage_stats_postgresql_no_data(self, mock_db):
        """Test PostgreSQL path with no usage data."""
        # Mock the session's bind dialect instead of global engine
        mock_bind = MagicMock()
        mock_bind.dialect.name = "postgresql"
        mock_db.get_bind.return_value = mock_bind
        service = TokenCatalogService(mock_db)

        # Mock empty result - attribute names match SQL query labels
        mock_stats_row = MagicMock()
        mock_stats_row.total = None
        mock_stats_row.successful = None
        mock_stats_row.blocked = None
        mock_stats_row.avg_response = None

        mock_db.execute.return_value.fetchone.return_value = mock_stats_row
        mock_db.execute.return_value.fetchall.return_value = []

        stats = await service.get_token_usage_stats("test@example.com", days=7)

        assert stats["total_requests"] == 0
        assert stats["successful_requests"] == 0
        assert stats["success_rate"] == 0


# --------------------------------------------------------------------------- #
# Token Count Tests                                                           #
# --------------------------------------------------------------------------- #
class TestTokenCountFunctions:
    """Tests for token counting functions."""

    @pytest.mark.asyncio
    async def test_count_user_tokens_include_inactive(self, mock_db):
        """Test counting user tokens including inactive ones."""
        service = TokenCatalogService(mock_db)

        # Mock the query result
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db.execute.return_value = mock_result

        count = await service.count_user_tokens("test@example.com", include_inactive=True)

        assert count == 5
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_user_tokens_active_only(self, mock_db):
        """Test counting only active user tokens."""
        service = TokenCatalogService(mock_db)

        # Mock the query result
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_result

        count = await service.count_user_tokens("test@example.com", include_inactive=False)

        assert count == 3
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_user_tokens_returns_zero(self, mock_db):
        """Test counting user tokens when none exist."""
        service = TokenCatalogService(mock_db)

        # Mock the query result returning None
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        count = await service.count_user_tokens("test@example.com")

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_team_tokens_include_inactive(self, mock_db):
        """Test counting team tokens including inactive ones."""
        service = TokenCatalogService(mock_db)

        # Mock the query result
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_db.execute.return_value = mock_result

        count = await service.count_team_tokens("team-123", include_inactive=True)

        assert count == 10
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_team_tokens_active_only(self, mock_db):
        """Test counting only active team tokens."""
        service = TokenCatalogService(mock_db)

        # Mock the query result
        mock_result = MagicMock()
        mock_result.scalar.return_value = 7
        mock_db.execute.return_value = mock_result

        count = await service.count_team_tokens("team-123", include_inactive=False)

        assert count == 7
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_team_tokens_returns_zero(self, mock_db):
        """Test counting team tokens when none exist."""
        service = TokenCatalogService(mock_db)

        # Mock the query result returning None
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        count = await service.count_team_tokens("team-123")

        assert count == 0

    @pytest.mark.asyncio
    async def test_list_all_tokens_basic(self, token_service, mock_db, mock_api_token):
        """Test list_all_tokens method - basic case."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_api_token]
        mock_db.execute.return_value = mock_result

        tokens = await token_service.list_all_tokens()

        assert len(tokens) == 1
        assert tokens[0] == mock_api_token
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_all_tokens_include_inactive(self, token_service, mock_db):
        """Test list_all_tokens with include_inactive=True."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await token_service.list_all_tokens(include_inactive=True)

        call_args = mock_db.execute.call_args[0][0]
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_list_all_tokens_pagination(self, token_service, mock_db):
        """Test list_all_tokens with pagination."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await token_service.list_all_tokens(limit=50, offset=10)

        call_args = mock_db.execute.call_args[0][0]
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_list_all_tokens_invalid_limit(self, token_service, mock_db):
        """Test list_all_tokens with invalid limit falls back to default."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await token_service.list_all_tokens(limit=0)
        await token_service.list_all_tokens(limit=2000)

        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_count_all_tokens_basic(self, token_service, mock_db):
        """Test count_all_tokens method - basic case."""
        mock_db.execute.return_value.scalar.return_value = 5

        count = await token_service.count_all_tokens()

        assert count == 5
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_all_tokens_include_inactive(self, token_service, mock_db):
        """Test count_all_tokens with include_inactive=True."""
        mock_db.execute.return_value.scalar.return_value = 10

        count = await token_service.count_all_tokens(include_inactive=True)

        assert count == 10
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_all_tokens_no_tokens(self, token_service, mock_db):
        """Test count_all_tokens returns 0 when no tokens exist."""
        mock_db.execute.return_value.scalar.return_value = None

        count = await token_service.count_all_tokens()

        assert count == 0
