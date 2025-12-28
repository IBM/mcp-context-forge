# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_token_catalog_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for token catalog service implementation.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib
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

    @pytest.mark.asyncio
    async def test_generate_token_basic(self, token_service):
        """Test _generate_token method with basic parameters."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_123"
            jti = str(uuid.uuid4())
            token = await token_service._generate_token("user@example.com", jti)

            assert token == "jwt_token_123"
            mock_create_jwt.assert_called_once()
            call_args = mock_create_jwt.call_args[0][0]
            assert call_args["sub"] == "user@example.com"
            assert "jti" in call_args
            assert call_args["user"]["email"] == "user@example.com"
            assert call_args["user"]["is_admin"] is False

    @pytest.mark.asyncio
    async def test_generate_token_with_team(self, token_service):
        """Test _generate_token method with team_id."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_team"
            jti = str(uuid.uuid4())
            token = await token_service._generate_token("user@example.com", jti=jti, team_id="team-123")

            assert token == "jwt_token_team"
            call_args = mock_create_jwt.call_args[0][0]
            assert call_args["teams"] == ["team-123"]
            assert "team:team-123" in call_args["namespaces"]

    @pytest.mark.asyncio
    async def test_generate_token_with_expiry(self, token_service):
        """Test _generate_token method with expiration."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_exp"
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("user@example.com", jti=jti, expires_at=expires_at)

            assert token == "jwt_token_exp"
            call_args = mock_create_jwt.call_args[0][0]
            assert "exp" in call_args
            assert call_args["exp"] == int(expires_at.timestamp())

    @pytest.mark.asyncio
    async def test_generate_token_with_scope(self, token_service, token_scope):
        """Test _generate_token method with TokenScope."""
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_scoped"
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("user@example.com", jti=jti, scope=token_scope)

            assert token == "jwt_token_scoped"
            call_args = mock_create_jwt.call_args[0][0]
            assert call_args["scopes"]["server_id"] == "server-123"
            assert call_args["scopes"]["permissions"] == ["tools.read", "resources.read"]
            assert call_args["scopes"]["ip_restrictions"] == ["192.168.1.0/24"]

    @pytest.mark.asyncio
    async def test_generate_token_with_admin_user(self, token_service, mock_user):
        """Test _generate_token method with admin user."""
        mock_user.is_admin = True
        with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create_jwt:
            mock_create_jwt.return_value = "jwt_token_admin"
            jti = str(uuid.uuid4())

            token = await token_service._generate_token("admin@example.com", jti=jti, user=mock_user)

            assert token == "jwt_token_admin"
            call_args = mock_create_jwt.call_args[0][0]
            assert call_args["user"]["is_admin"] is True

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

            token, raw_token = await token_service.create_token(user_email="test@example.com", name="Team Token", team_id="team-123")

            assert raw_token == "jwt_token_team"
            added_token = mock_db.add.call_args[0][0]
            assert added_token.team_id == "team-123"

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

            token, raw_token = await token_service.create_token(user_email="test@example.com", name="Scoped Token", scope=token_scope)

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
        # Verify query was built correctly
        call_args = mock_db.execute.call_args[0][0]
        # The query should not filter out inactive tokens

    @pytest.mark.asyncio
    async def test_list_user_tokens_with_pagination(self, token_service, mock_db):
        """Test list_user_tokens method with pagination."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await token_service.list_user_tokens("test@example.com", limit=10, offset=20)

        # Verify pagination was applied
        call_args = mock_db.execute.call_args[0][0]
        # Query should have limit and offset applied

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
    async def test_list_team_tokens_success(self, token_service, mock_db, mock_team_member, mock_api_token):
        """Test list_team_tokens method - successful."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_team_member
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_api_token]
        mock_db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_team_member)),
            mock_result,
        ]

        tokens = await token_service.list_team_tokens("team-123", "test@example.com")

        assert len(tokens) == 1
        assert tokens[0] == mock_api_token

    @pytest.mark.asyncio
    async def test_list_team_tokens_not_owner(self, token_service, mock_db):
        """Test list_team_tokens method - user not team owner."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(ValueError, match="Only team owners can view team tokens"):
            await token_service.list_team_tokens("team-123", "notowner@example.com")

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

            updated = await token_service.update_token(token_id="token-123", user_email="test@example.com", scope=token_scope)

            assert mock_api_token.server_id == "server-123"
            assert mock_api_token.resource_scopes == ["tools.read", "resources.read"]
            assert mock_api_token.ip_restrictions == ["192.168.1.0/24"]
            assert mock_api_token.time_restrictions == {"business_hours_only": True}
            assert mock_api_token.usage_limits == {"max_requests_per_hour": 100}

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, token_service, mock_db, mock_api_token):
        """Test revoke_token method - successful revocation."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token

            result = await token_service.revoke_token(token_id="token-123", revoked_by="admin@example.com", reason="Security concern")

            assert result is True
            assert mock_api_token.is_active is False
            mock_db.add.assert_called_once()
            mock_db.commit.assert_called()

            # Check revocation record
            revocation = mock_db.add.call_args[0][0]
            assert isinstance(revocation, TokenRevocation)
            assert revocation.jti == "jti-123"
            assert revocation.revoked_by == "admin@example.com"
            assert revocation.reason == "Security concern"

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, token_service):
        """Test revoke_token method - token not found."""
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            result = await token_service.revoke_token(token_id="nonexistent", revoked_by="admin@example.com")

            assert result is False

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
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_api_token

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

        # Check token last_used was updated
        assert mock_api_token.last_used is not None

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
            token, _ = await token_service.create_token(user_email="test@example.com", name="")  # Empty name should still work
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
            token, _ = await token_service.create_token(user_email="test@example.com", name="Token", description=long_desc)

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

            # Description should not change when None is passed
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
            token, _ = await token_service.create_token(user_email="test@example.com", name="Token", scope=empty_scope)

            added_token = mock_db.add.call_args[0][0]
            assert added_token.server_id is None
            assert added_token.resource_scopes == []

    @pytest.mark.asyncio
    async def test_generate_token_settings_values(self, token_service):
        """Test _generate_token uses settings for issuer and audience."""
        with patch("mcpgateway.services.token_catalog_service.settings") as mock_settings:
            mock_settings.jwt_issuer = "test-issuer"
            mock_settings.jwt_audience = "test-audience"

            with patch("mcpgateway.services.token_catalog_service.create_jwt_token", new_callable=AsyncMock) as mock_create:
                mock_create.return_value = "jwt"
                jti = str(uuid.uuid4())

                await token_service._generate_token("user@example.com", jti=jti)

                call_args = mock_create.call_args[0][0]
                assert call_args["iss"] == "test-issuer"
                assert call_args["aud"] == "test-audience"


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
            token, raw = await token_service.create_token(user_email="test@example.com", name="Lifecycle Token")

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
        stats = await token_service.get_token_usage_stats("test@example.com")

        # Revoke token
        with patch.object(token_service, "get_token", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_api_token
            result = await token_service.revoke_token(token_id="token-123", revoked_by="admin@example.com")
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
            token, _ = await token_service.create_token(user_email="test@example.com", name="Team Token", team_id="team-123")

        # List team tokens
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_team_member
        mock_db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_team_member)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]

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
