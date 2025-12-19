# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_bootstrap_db.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for bootstrap_db module.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.bootstrap_db import (
    bootstrap_admin_user,
    bootstrap_default_roles,
    bootstrap_resource_assignments,
    main,
    normalize_team_visibility,
)


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = Mock()
    settings.email_auth_enabled = True
    settings.platform_admin_email = "admin@example.com"
    settings.platform_admin_password = SecretStr("secure_password")
    settings.platform_admin_full_name = "Platform Admin"
    settings.auto_create_personal_teams = True
    settings.database_url = "sqlite:///:memory:"
    return settings


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = Mock()
    session.query = Mock()
    session.commit = Mock()
    session.close = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def mock_conn():
    """Create mock database connection."""
    conn = Mock()
    conn.commit = Mock()
    conn.rollback = Mock()
    conn.close = Mock()
    return conn


@pytest.fixture
def mock_email_auth_service():
    """Create mock EmailAuthService."""
    service = Mock()
    service.get_user_by_email = AsyncMock()
    service.create_user = AsyncMock()
    return service


@pytest.fixture
def mock_role_service():
    """Create mock RoleService."""
    service = Mock()
    service.get_role_by_name = AsyncMock()
    service.create_role = AsyncMock()
    service.get_user_role_assignment = AsyncMock()
    service.assign_role_to_user = AsyncMock()
    return service


@pytest.fixture
def mock_admin_user():
    """Create mock admin user."""
    user = Mock()
    user.email = "admin@example.com"
    user.is_admin = True
    user.email_verified_at = None
    user.get_personal_team = Mock()
    return user


@pytest.fixture
def mock_personal_team():
    """Create mock personal team."""
    team = Mock()
    team.id = "team-123"
    team.name = "Admin Personal Team"
    return team


class TestBootstrapAdminUser:
    """Test bootstrap_admin_user function."""

    @pytest.mark.asyncio
    async def test_bootstrap_admin_user_disabled(self, mock_settings, mock_conn):
        """Test when email auth is disabled."""
        mock_settings.email_auth_enabled = False

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                await bootstrap_admin_user(mock_conn)

                mock_logger.info.assert_called_with("Email authentication disabled - skipping admin user bootstrap")

    @pytest.mark.asyncio
    async def test_bootstrap_admin_user_already_exists(self, mock_settings, mock_db_session, mock_email_auth_service, mock_admin_user, mock_conn):
        """Test when admin user already exists."""
        mock_email_auth_service.get_user_by_email.return_value = mock_admin_user

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                        await bootstrap_admin_user(mock_conn)

                        mock_email_auth_service.get_user_by_email.assert_called_once_with(mock_settings.platform_admin_email)
                        mock_email_auth_service.create_user.assert_not_called()
                        mock_logger.info.assert_called_with(f"Admin user {mock_settings.platform_admin_email} already exists - skipping creation")

    @pytest.mark.asyncio
    async def test_bootstrap_admin_user_success(self, mock_settings, mock_db_session, mock_email_auth_service, mock_admin_user, mock_conn):
        """Test successful admin user creation."""
        mock_email_auth_service.get_user_by_email.return_value = None
        mock_email_auth_service.create_platform_admin.return_value = mock_admin_user

        with (
            patch("mcpgateway.bootstrap_db.settings", mock_settings),
            patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session),
            patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service),
            patch("mcpgateway.db.utc_now") as mock_utc_now,
            patch("mcpgateway.bootstrap_db.logger") as mock_logger,
        ):
            mock_utc_now.return_value = "2024-01-01T00:00:00Z"
            await bootstrap_admin_user(mock_conn)

            mock_email_auth_service.create_platform_admin.assert_called_once_with(
                email=mock_settings.platform_admin_email,
                password=mock_settings.platform_admin_password.get_secret_value(),
                full_name=mock_settings.platform_admin_full_name,
            )
            mock_logger.info.assert_any_call(f"Creating platform admin user: {mock_settings.platform_admin_email}")

    @pytest.mark.asyncio
    async def test_bootstrap_admin_user_with_personal_team(self, mock_settings, mock_db_session, mock_email_auth_service, mock_admin_user, mock_conn):
        """Test admin user creation with personal team auto-creation."""
        mock_settings.auto_create_personal_teams = True
        mock_email_auth_service.get_user_by_email.return_value = None
        mock_email_auth_service.create_platform_admin.return_value = mock_admin_user

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.db.utc_now", return_value="2024-01-01T00:00:00Z"):
                        with patch("mcpgateway.bootstrap_db.logger"):
                            await bootstrap_admin_user(mock_conn)

                            # Verify that the user creation was attempted
                            mock_email_auth_service.create_platform_admin.assert_called_once()

    @pytest.mark.asyncio
    async def test_bootstrap_admin_user_exception(self, mock_settings, mock_db_session, mock_email_auth_service, mock_conn):
        """Test exception handling during admin user creation."""
        mock_email_auth_service.get_user_by_email.side_effect = Exception("Database error")

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                        await bootstrap_admin_user(mock_conn)

                        mock_logger.error.assert_called_with("Failed to bootstrap admin user: Database error")


class TestBootstrapDefaultRoles:
    """Test bootstrap_default_roles function."""

    @pytest.mark.asyncio
    async def test_bootstrap_roles_disabled(self, mock_settings, mock_conn):
        """Test when email auth is disabled."""
        mock_settings.email_auth_enabled = False

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                await bootstrap_default_roles(mock_conn)

                mock_logger.info.assert_called_with("Email authentication disabled - skipping default roles bootstrap")

    @pytest.mark.asyncio
    async def test_bootstrap_roles_no_admin_user(self, mock_settings, mock_email_auth_service, mock_role_service, mock_conn):
        """Test when admin user doesn't exist."""
        mock_email_auth_service.get_user_by_email.return_value = None

        # Mock Session context manager
        mock_db = Mock()
        mock_session_cm = Mock()
        mock_session_cm.__enter__ = Mock(return_value=mock_db)
        mock_session_cm.__exit__ = Mock(return_value=None)

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_session_cm):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                        with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                            await bootstrap_default_roles(mock_conn)

                            mock_logger.info.assert_called_with("Admin user not found - skipping role assignment")

    @pytest.mark.asyncio
    async def test_bootstrap_roles_create_success(self, mock_settings, mock_email_auth_service, mock_role_service, mock_admin_user, mock_conn):
        """Test successful role creation and assignment."""
        mock_email_auth_service.get_user_by_email.return_value = mock_admin_user
        mock_role_service.get_role_by_name.return_value = None  # No existing roles

        platform_admin_role = Mock()
        platform_admin_role.id = "role-admin"
        platform_admin_role.name = "platform_admin"

        mock_role_service.create_role.return_value = platform_admin_role
        mock_role_service.get_user_role_assignment.return_value = None

        # Mock Session context manager
        mock_db = Mock()
        mock_session_cm = Mock()
        mock_session_cm.__enter__ = Mock(return_value=mock_db)
        mock_session_cm.__exit__ = Mock(return_value=None)

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_session_cm):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                        with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                            await bootstrap_default_roles(mock_conn)

                            # Check that roles were created
                            assert mock_role_service.create_role.call_count >= 4

                            # Check that admin role was assigned
                            mock_role_service.assign_role_to_user.assert_called_once_with(
                                user_email=mock_admin_user.email, role_id=platform_admin_role.id, scope="global", scope_id=None, granted_by=mock_admin_user.email
                            )

                            mock_logger.info.assert_any_call(f"Assigned platform_admin role to {mock_admin_user.email}")

    @pytest.mark.asyncio
    async def test_bootstrap_roles_already_exist(self, mock_settings, mock_email_auth_service, mock_role_service, mock_admin_user, mock_conn):
        """Test when roles already exist."""
        mock_email_auth_service.get_user_by_email.return_value = mock_admin_user

        existing_role = Mock()
        existing_role.id = "role-admin"
        existing_role.name = "platform_admin"
        mock_role_service.get_role_by_name.return_value = existing_role

        existing_assignment = Mock()
        existing_assignment.is_active = True
        mock_role_service.get_user_role_assignment.return_value = existing_assignment

        # Mock Session context manager
        mock_db = Mock()
        mock_session_cm = Mock()
        mock_session_cm.__enter__ = Mock(return_value=mock_db)
        mock_session_cm.__exit__ = Mock(return_value=None)

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_session_cm):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                        with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                            await bootstrap_default_roles(mock_conn)

                            mock_role_service.create_role.assert_not_called()
                            mock_role_service.assign_role_to_user.assert_not_called()
                            mock_logger.info.assert_any_call("Admin user already has platform_admin role")

    @pytest.mark.asyncio
    async def test_bootstrap_roles_exception_handling(self, mock_settings, mock_email_auth_service, mock_role_service, mock_admin_user, mock_conn):
        """Test exception handling during role creation."""
        mock_email_auth_service.get_user_by_email.return_value = mock_admin_user
        mock_role_service.get_role_by_name.return_value = None
        mock_role_service.create_role.side_effect = Exception("Role creation failed")

        # Mock Session context manager
        mock_db = Mock()
        mock_session_cm = Mock()
        mock_session_cm.__enter__ = Mock(return_value=mock_db)
        mock_session_cm.__exit__ = Mock(return_value=None)

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_session_cm):
                with patch("mcpgateway.services.email_auth_service.EmailAuthService", return_value=mock_email_auth_service):
                    with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                        with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                            await bootstrap_default_roles(mock_conn)

                            mock_logger.error.assert_any_call("Failed to create role platform_admin: Role creation failed")


class TestNormalizeTeamVisibility:
    """Test normalize_team_visibility function."""

    def test_normalize_team_visibility_no_invalid(self, mock_db_session, mock_conn):
        """Test when all teams have valid visibility."""
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db_session.query.return_value = mock_query

        with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
            with patch("mcpgateway.bootstrap_db.logger"):
                result = normalize_team_visibility(mock_conn)

                assert result == 0
                mock_db_session.commit.assert_not_called()

    def test_normalize_team_visibility_with_invalid(self, mock_db_session, mock_conn):
        """Test normalizing teams with invalid visibility."""
        mock_team1 = Mock()
        mock_team1.id = "team-1"
        mock_team1.visibility = "team"  # Invalid

        mock_team2 = Mock()
        mock_team2.id = "team-2"
        mock_team2.visibility = "internal"  # Invalid

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_team1, mock_team2]
        mock_db_session.query.return_value = mock_query

        with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                result = normalize_team_visibility(mock_conn)

                assert result == 2
                assert mock_team1.visibility == "private"
                assert mock_team2.visibility == "private"
                mock_db_session.commit.assert_called_once()
                assert mock_logger.info.call_count == 2

    def test_normalize_team_visibility_exception(self, mock_db_session, mock_conn):
        """Test exception handling during normalization."""
        mock_db_session.query.side_effect = Exception("Database error")

        with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                result = normalize_team_visibility(mock_conn)

                assert result == 0
                mock_logger.error.assert_called_with("Failed to normalize team visibility: Database error")


class TestBootstrapResourceAssignments:
    """Test bootstrap_resource_assignments function."""

    @pytest.mark.asyncio
    async def test_resource_assignments_disabled(self, mock_settings, mock_conn):
        """Test when email auth is disabled."""
        mock_settings.email_auth_enabled = False

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                await bootstrap_resource_assignments(mock_conn)

                mock_logger.info.assert_called_with("Email authentication disabled - skipping resource assignment")

    @pytest.mark.asyncio
    async def test_resource_assignments_no_admin(self, mock_settings, mock_db_session, mock_conn):
        """Test when admin user doesn't exist."""
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db_session.query.return_value = mock_query

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                    await bootstrap_resource_assignments(mock_conn)

                    mock_logger.warning.assert_called_with("Admin user not found - skipping resource assignment")

    @pytest.mark.asyncio
    async def test_resource_assignments_no_personal_team(self, mock_settings, mock_db_session, mock_admin_user, mock_conn):
        """Test when admin has no personal team."""
        mock_admin_user.get_personal_team.return_value = None

        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = mock_admin_user
        mock_db_session.query.return_value = mock_query

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                    await bootstrap_resource_assignments(mock_conn)

                    mock_logger.warning.assert_called_with("Admin personal team not found - skipping resource assignment")

    @pytest.mark.asyncio
    async def test_resource_assignments_success(self, mock_settings, mock_db_session, mock_admin_user, mock_personal_team, mock_conn):
        """Test successful resource assignment."""
        mock_admin_user.get_personal_team.return_value = mock_personal_team

        # Mock unassigned resources
        mock_server = Mock()
        mock_server.team_id = None
        mock_server.owner_email = None
        mock_server.visibility = None
        mock_server.federation_source = None

        mock_tool = Mock()
        mock_tool.team_id = None
        mock_tool.owner_email = None
        mock_tool.visibility = None

        def mock_query_handler(model):
            query = Mock()
            query.filter.return_value = query

            if model.__name__ == "EmailUser":
                query.first.return_value = mock_admin_user
            elif model.__name__ == "Server":
                query.all.return_value = [mock_server]
            elif model.__name__ == "Tool":
                query.all.return_value = [mock_tool]
            else:
                query.all.return_value = []

            return query

        mock_db_session.query.side_effect = mock_query_handler

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.db.EmailUser", Mock(__name__="EmailUser")):
                    with patch("mcpgateway.db.Server", Mock(__name__="Server")):
                        with patch("mcpgateway.db.Tool", Mock(__name__="Tool")):
                            with patch("mcpgateway.db.Resource", Mock(__name__="Resource")):
                                with patch("mcpgateway.db.Prompt", Mock(__name__="Prompt")):
                                    with patch("mcpgateway.db.Gateway", Mock(__name__="Gateway")):
                                        with patch("mcpgateway.db.A2AAgent", Mock(__name__="A2AAgent")):
                                            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                await bootstrap_resource_assignments(mock_conn)

                                                # Check that resources were assigned
                                                assert mock_server.team_id == mock_personal_team.id
                                                assert mock_server.owner_email == mock_admin_user.email
                                                assert mock_server.visibility == "public"
                                                assert mock_server.federation_source == "mcpgateway-0.7.0-migration"

                                                assert mock_tool.team_id == mock_personal_team.id
                                                assert mock_tool.owner_email == mock_admin_user.email
                                                assert mock_tool.visibility == "public"

                                                mock_logger.info.assert_any_call("Successfully assigned 2 orphaned resources to admin team")

    @pytest.mark.asyncio
    async def test_resource_assignments_no_orphans(self, mock_settings, mock_db_session, mock_admin_user, mock_personal_team, mock_conn):
        """Test when no orphaned resources exist."""
        mock_admin_user.get_personal_team.return_value = mock_personal_team

        def mock_query_handler(model):
            query = Mock()
            query.filter.return_value = query

            if model.__name__ == "EmailUser":
                query.first.return_value = mock_admin_user
            else:
                query.all.return_value = []

            return query

        mock_db_session.query.side_effect = mock_query_handler

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.db.EmailUser", Mock(__name__="EmailUser")):
                    with patch("mcpgateway.db.Server", Mock(__name__="Server")):
                        with patch("mcpgateway.db.Tool", Mock(__name__="Tool")):
                            with patch("mcpgateway.db.Resource", Mock(__name__="Resource")):
                                with patch("mcpgateway.db.Prompt", Mock(__name__="Prompt")):
                                    with patch("mcpgateway.db.Gateway", Mock(__name__="Gateway")):
                                        with patch("mcpgateway.db.A2AAgent", Mock(__name__="A2AAgent")):
                                            with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                await bootstrap_resource_assignments(mock_conn)

                                                mock_logger.info.assert_any_call("No orphaned resources found - all resources have team assignments")

    @pytest.mark.asyncio
    async def test_resource_assignments_exception(self, mock_settings, mock_db_session, mock_conn):
        """Test exception handling during resource assignment."""
        mock_db_session.query.side_effect = Exception("Database error")

        with patch("mcpgateway.bootstrap_db.settings", mock_settings):
            with patch("mcpgateway.bootstrap_db.Session", return_value=mock_db_session):
                with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                    await bootstrap_resource_assignments(mock_conn)

                    mock_logger.error.assert_called_with("Failed to bootstrap resource assignments: Database error")


class TestMain:
    """Test main function."""

    @pytest.mark.asyncio
    async def test_main_empty_database(self, mock_settings):
        """Test main function with empty database."""
        mock_engine = Mock()
        mock_conn = Mock()
        mock_conn.commit = Mock()
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = []  # Empty database

        mock_config = MagicMock()
        mock_config.attributes = {}

        # Mock engine.connect() as context manager
        mock_connect_cm = Mock()
        mock_connect_cm.__enter__ = Mock(return_value=mock_conn)
        mock_connect_cm.__exit__ = Mock(return_value=None)
        mock_engine.connect = Mock(return_value=mock_connect_cm)

        with patch("mcpgateway.bootstrap_db.create_engine", return_value=mock_engine):
            with patch("mcpgateway.bootstrap_db.inspect", return_value=mock_inspector):
                with patch("importlib.resources.files") as mock_files:
                    mock_files.return_value.joinpath.return_value = "alembic.ini"

                    with patch("mcpgateway.bootstrap_db.Config", return_value=mock_config):
                        with patch("mcpgateway.bootstrap_db.Base") as mock_base:
                            with patch("mcpgateway.bootstrap_db.command") as mock_command:
                                with patch("mcpgateway.bootstrap_db.normalize_team_visibility", return_value=0):
                                    with patch("mcpgateway.bootstrap_db.bootstrap_admin_user", new=AsyncMock()):
                                        with patch("mcpgateway.bootstrap_db.bootstrap_default_roles", new=AsyncMock()):
                                            with patch("mcpgateway.bootstrap_db.bootstrap_resource_assignments", new=AsyncMock()):
                                                with patch("mcpgateway.bootstrap_db.settings", mock_settings):
                                                    with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                        await main()

                                                        mock_base.metadata.create_all.assert_called_once_with(bind=mock_conn)
                                                        mock_command.stamp.assert_called_once_with(mock_config, "head")
                                                        mock_command.upgrade.assert_not_called()
                                                        mock_logger.info.assert_any_call("Empty DB detected - creating baseline schema")

    @pytest.mark.asyncio
    async def test_main_existing_database(self, mock_settings):
        """Test main function with existing database."""
        mock_engine = Mock()
        mock_conn = Mock()
        mock_conn.commit = Mock()
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = ["gateways", "tools"]  # Existing tables

        mock_config = MagicMock()
        mock_config.attributes = {}

        # Mock engine.connect() as context manager
        mock_connect_cm = Mock()
        mock_connect_cm.__enter__ = Mock(return_value=mock_conn)
        mock_connect_cm.__exit__ = Mock(return_value=None)
        mock_engine.connect = Mock(return_value=mock_connect_cm)

        with patch("mcpgateway.bootstrap_db.create_engine", return_value=mock_engine):
            with patch("mcpgateway.bootstrap_db.inspect", return_value=mock_inspector):
                with patch("importlib.resources.files") as mock_files:
                    mock_files.return_value.joinpath.return_value = "alembic.ini"

                    with patch("mcpgateway.bootstrap_db.Config", return_value=mock_config):
                        with patch("mcpgateway.bootstrap_db.Base") as mock_base:
                            with patch("mcpgateway.bootstrap_db.command") as mock_command:
                                with patch("mcpgateway.bootstrap_db.normalize_team_visibility", return_value=0):
                                    with patch("mcpgateway.bootstrap_db.bootstrap_admin_user", new=AsyncMock()):
                                        with patch("mcpgateway.bootstrap_db.bootstrap_default_roles", new=AsyncMock()):
                                            with patch("mcpgateway.bootstrap_db.bootstrap_resource_assignments", new=AsyncMock()):
                                                with patch("mcpgateway.bootstrap_db.settings", mock_settings):
                                                    with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                        await main()

                                                        mock_base.metadata.create_all.assert_not_called()
                                                        mock_command.stamp.assert_not_called()
                                                        mock_command.upgrade.assert_called_once_with(mock_config, "head")
                                                        mock_logger.info.assert_any_call("Running Alembic migrations to ensure schema is up to date")

    @pytest.mark.asyncio
    async def test_main_with_normalization(self, mock_settings):
        """Test main function with team normalization."""
        mock_engine = Mock()
        mock_conn = Mock()
        mock_conn.commit = Mock()
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = ["gateways"]

        mock_config = MagicMock()
        mock_config.attributes = {}

        # Mock engine.connect() as context manager
        mock_connect_cm = Mock()
        mock_connect_cm.__enter__ = Mock(return_value=mock_conn)
        mock_connect_cm.__exit__ = Mock(return_value=None)
        mock_engine.connect = Mock(return_value=mock_connect_cm)

        with patch("mcpgateway.bootstrap_db.create_engine", return_value=mock_engine):
            with patch("mcpgateway.bootstrap_db.inspect", return_value=mock_inspector):
                with patch("importlib.resources.files") as mock_files:
                    mock_files.return_value.joinpath.return_value = "alembic.ini"

                    with patch("mcpgateway.bootstrap_db.Config", return_value=mock_config):
                        with patch("mcpgateway.bootstrap_db.command"):
                            with patch("mcpgateway.bootstrap_db.normalize_team_visibility", return_value=5):
                                with patch("mcpgateway.bootstrap_db.bootstrap_admin_user", new=AsyncMock()):
                                    with patch("mcpgateway.bootstrap_db.bootstrap_default_roles", new=AsyncMock()):
                                        with patch("mcpgateway.bootstrap_db.bootstrap_resource_assignments", new=AsyncMock()):
                                            with patch("mcpgateway.bootstrap_db.settings", mock_settings):
                                                with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                    await main()

                                                    mock_logger.info.assert_any_call("Normalized 5 team record(s) to supported visibility values")

    @pytest.mark.asyncio
    async def test_main_complete_flow(self, mock_settings):
        """Test complete main flow with all bootstrap steps."""
        mock_engine = Mock()
        mock_conn = Mock()
        mock_conn.commit = Mock()
        mock_inspector = Mock()
        mock_inspector.get_table_names.return_value = []

        mock_config = MagicMock()
        mock_config.attributes = {}

        # Mock engine.connect() as context manager
        mock_connect_cm = Mock()
        mock_connect_cm.__enter__ = Mock(return_value=mock_conn)
        mock_connect_cm.__exit__ = Mock(return_value=None)
        mock_engine.connect = Mock(return_value=mock_connect_cm)

        with patch("mcpgateway.bootstrap_db.create_engine", return_value=mock_engine):
            with patch("mcpgateway.bootstrap_db.inspect", return_value=mock_inspector):
                with patch("importlib.resources.files") as mock_files:
                    mock_files.return_value.joinpath.return_value = "alembic.ini"

                    with patch("mcpgateway.bootstrap_db.Config", return_value=mock_config):
                        with patch("mcpgateway.bootstrap_db.Base"):
                            with patch("mcpgateway.bootstrap_db.command"):
                                with patch("mcpgateway.bootstrap_db.normalize_team_visibility", return_value=0):
                                    with patch("mcpgateway.bootstrap_db.bootstrap_admin_user", new=AsyncMock()) as mock_admin:
                                        with patch("mcpgateway.bootstrap_db.bootstrap_default_roles", new=AsyncMock()) as mock_roles:
                                            with patch("mcpgateway.bootstrap_db.bootstrap_resource_assignments", new=AsyncMock()) as mock_resources:
                                                with patch("mcpgateway.bootstrap_db.settings", mock_settings):
                                                    with patch("mcpgateway.bootstrap_db.logger") as mock_logger:
                                                        await main()

                                                        # Verify all bootstrap functions were called
                                                        mock_admin.assert_called_once()
                                                        mock_roles.assert_called_once()
                                                        mock_resources.assert_called_once()
                                                        mock_logger.info.assert_any_call("Database ready")


class TestModuleLevel:
    """Test module-level code and imports."""

    def test_module_imports(self):
        """Test that module imports work correctly."""
        from mcpgateway.bootstrap_db import Base, logger, logging_service

        assert logging_service is not None
        assert logger is not None
        assert hasattr(Base, "metadata")
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")

    def test_main_entrypoint(self):
        """Test that main can be called as a module."""
        # Just verify the module structure is correct
        from mcpgateway.bootstrap_db import main

        assert asyncio.iscoroutinefunction(main)
