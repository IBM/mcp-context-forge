# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_email_auth_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for EmailAuthService - focusing on user creation role assignment.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.email_auth_service import EmailAuthService, UserExistsError


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalars.return_value.all.return_value = []

    # Mock add/commit/refresh to handle user creation
    def mock_refresh(obj):
        """Mock refresh that sets an id if not present."""
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = "test-user-id"

    db.refresh.side_effect = mock_refresh
    return db


@pytest.fixture
def mock_password_service():
    """Mock password service."""
    service = MagicMock()
    service.hash_password_async = AsyncMock(return_value="hashed_password")
    return service


@pytest.fixture
def email_auth_service(mock_db, mock_password_service):
    """Create EmailAuthService with mocked dependencies."""
    with patch("mcpgateway.services.email_auth_service.Argon2PasswordService", return_value=mock_password_service):
        service = EmailAuthService(mock_db)
        service.password_service = mock_password_service
        return service


# ---------- Personal Team Creation Error Handling ----------


@pytest.mark.asyncio
async def test_create_user_personal_team_creation_fails(email_auth_service, mock_db):
    """Test user creation continues when personal team creation fails (lines 392-393)."""
    # Mock get_user_by_email to return None (user doesn't exist)
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        # Mock settings for both password validation and personal teams
        with patch("mcpgateway.config.settings") as mock_config_settings:
            mock_config_settings.password_min_length = 8
            mock_config_settings.password_require_uppercase = False
            mock_config_settings.password_require_lowercase = False
            mock_config_settings.password_require_numbers = False
            mock_config_settings.password_require_special = False
            mock_config_settings.auto_create_personal_teams = True

            with patch("mcpgateway.services.email_auth_service.settings", mock_config_settings):
                # Mock PersonalTeamService to raise exception (patch where it's imported)
                mock_personal_team_service = MagicMock()
                mock_personal_team_service.create_personal_team = AsyncMock(side_effect=Exception("Team creation failed"))

                with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                    # Should not raise exception, just log warning
                    user = await email_auth_service.create_user(
                        email="test@example.com",
                        password="ValidPass123!",
                        is_admin=False,
                    )

                    assert user is not None
                    # db.add is called twice: once for user, once for registration event
                    assert mock_db.add.call_count == 2
                    mock_db.commit.assert_called()


# ---------- Admin Role Assignment Error Handling ----------


@pytest.mark.asyncio
async def test_create_user_admin_platform_admin_role_assignment_fails(email_auth_service, mock_db):
    """Test admin user creation when platform_admin role assignment fails (lines 416-420)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock RoleService to return platform_admin role but fail on assignment
            platform_admin_role = SimpleNamespace(id="role1", name="platform_admin", is_active=True)
            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(return_value=platform_admin_role)
            mock_role_service.assign_role_to_user = AsyncMock(side_effect=ValueError("Role assignment failed"))

            with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                # Should not raise exception, just log warning
                user = await email_auth_service.create_user(
                    email="admin@example.com",
                    password="ValidPass123!",
                    is_admin=True,
                )

                assert user is not None
                # db.add is called twice: once for user, once for registration event
                assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_create_user_admin_team_admin_role_assignment(email_auth_service, mock_db):
    """Test admin user gets team_admin role on personal team (lines 426,428-433,435)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock personal team creation with proper id attribute
            personal_team = SimpleNamespace(id="team1", name="Personal Team")
            mock_personal_team_service = MagicMock()
            mock_personal_team_service.create_personal_team = AsyncMock(return_value=personal_team)

            # Mock RoleService to return roles in sequence
            platform_admin_role = SimpleNamespace(id="role1", name="platform_admin", is_active=True)
            team_admin_role = SimpleNamespace(id="role2", name="team_admin", is_active=True)

            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(
                side_effect=[
                    platform_admin_role,  # First call for platform_admin
                    team_admin_role,  # Second call for team_admin
                ]
            )
            mock_role_service.assign_role_to_user = AsyncMock()

            with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await email_auth_service.create_user(
                        email="admin@example.com",
                        password="ValidPass123!",
                        is_admin=True,
                    )

                    assert user is not None
                    # Should be called twice: once for platform_admin, once for team_admin
                    assert mock_role_service.assign_role_to_user.call_count == 2


@pytest.mark.asyncio
async def test_create_user_admin_team_admin_role_not_found(email_auth_service, mock_db):
    """Test admin user creation when team_admin role not found (line 435)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock personal team creation with proper id attribute
            personal_team = SimpleNamespace(id="team1", name="Personal Team")
            mock_personal_team_service = MagicMock()
            mock_personal_team_service.create_personal_team = AsyncMock(return_value=personal_team)

            # Mock RoleService - platform_admin exists, team_admin doesn't
            platform_admin_role = SimpleNamespace(id="role1", name="platform_admin", is_active=True)

            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(
                side_effect=[
                    platform_admin_role,  # First call for platform_admin
                    None,  # Second call for team_admin (not found)
                ]
            )
            mock_role_service.assign_role_to_user = AsyncMock()

            with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await email_auth_service.create_user(
                        email="admin@example.com",
                        password="ValidPass123!",
                        is_admin=True,
                    )

                    assert user is not None
                    # Should only be called once for platform_admin
                    assert mock_role_service.assign_role_to_user.call_count == 1


# ---------- Non-Admin Role Assignment Error Handling ----------


@pytest.mark.asyncio
async def test_create_user_non_admin_platform_viewer_role_assignment_fails(email_auth_service, mock_db):
    """Test non-admin user creation when platform_viewer role assignment fails (lines 444-448)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock RoleService to return platform_viewer role but fail on assignment
            platform_viewer_role = SimpleNamespace(id="role1", name="platform_viewer", is_active=True)
            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(return_value=platform_viewer_role)
            mock_role_service.assign_role_to_user = AsyncMock(side_effect=ValueError("Role assignment failed"))

            with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                # Should not raise exception, just log warning
                user = await email_auth_service.create_user(
                    email="user@example.com",
                    password="ValidPass123!",
                    is_admin=False,
                )

                assert user is not None
                # db.add is called twice: once for user, once for registration event
                assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_create_user_non_admin_team_admin_role_assignment(email_auth_service, mock_db):
    """Test non-admin user gets team_admin role on personal team (lines 454,456-461,463)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock personal team creation with proper id attribute
            personal_team = SimpleNamespace(id="team1", name="Personal Team")
            mock_personal_team_service = MagicMock()
            mock_personal_team_service.create_personal_team = AsyncMock(return_value=personal_team)

            # Mock RoleService to return roles in sequence
            platform_viewer_role = SimpleNamespace(id="role1", name="platform_viewer", is_active=True)
            team_admin_role = SimpleNamespace(id="role2", name="team_admin", is_active=True)

            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(
                side_effect=[
                    platform_viewer_role,  # First call for platform_viewer
                    team_admin_role,  # Second call for team_admin
                ]
            )
            mock_role_service.assign_role_to_user = AsyncMock()

            with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await email_auth_service.create_user(
                        email="user@example.com",
                        password="ValidPass123!",
                        is_admin=False,
                    )

                    assert user is not None
                    # Should be called twice: once for platform_viewer, once for team_admin
                    assert mock_role_service.assign_role_to_user.call_count == 2


@pytest.mark.asyncio
async def test_create_user_non_admin_team_admin_role_not_found(email_auth_service, mock_db):
    """Test non-admin user creation when team_admin role not found (line 463)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock personal team creation with proper id attribute
            personal_team = SimpleNamespace(id="team1", name="Personal Team")
            mock_personal_team_service = MagicMock()
            mock_personal_team_service.create_personal_team = AsyncMock(return_value=personal_team)

            # Mock RoleService - platform_viewer exists, team_admin doesn't
            platform_viewer_role = SimpleNamespace(id="role1", name="platform_viewer", is_active=True)

            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(
                side_effect=[
                    platform_viewer_role,  # First call for platform_viewer
                    None,  # Second call for team_admin (not found)
                ]
            )
            mock_role_service.assign_role_to_user = AsyncMock()

            with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await email_auth_service.create_user(
                        email="user@example.com",
                        password="ValidPass123!",
                        is_admin=False,
                    )

                    assert user is not None
                    # Should only be called once for platform_viewer
                    assert mock_role_service.assign_role_to_user.call_count == 1


@pytest.mark.asyncio
async def test_create_user_admin_team_owner_role_assignment_fails(email_auth_service, mock_db):
    """Test admin user creation when team owner role assignment fails (line 440)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = True
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False
            mock_settings.default_admin_role = "platform_admin"
            mock_settings.default_user_role = "platform_viewer"
            mock_settings.default_team_owner_role = "team_admin"

            # Mock personal team creation
            personal_team = SimpleNamespace(id="team1", name="Personal Team")
            mock_personal_team_service = MagicMock()
            mock_personal_team_service.create_personal_team = AsyncMock(return_value=personal_team)

            # Mock RoleService - both roles exist but team_admin assignment fails
            platform_admin_role = SimpleNamespace(id="role1", name="platform_admin", is_active=True)
            team_admin_role = SimpleNamespace(id="role2", name="team_admin", is_active=True)

            mock_role_service = MagicMock()
            mock_role_service.get_role_by_name = AsyncMock(
                side_effect=[
                    platform_admin_role,  # First call for platform_admin
                    team_admin_role,  # Second call for team_admin
                ]
            )
            mock_role_service.assign_role_to_user = AsyncMock(side_effect=ValueError("Team role assignment failed"))

            with patch("mcpgateway.services.personal_team_service.PersonalTeamService", return_value=mock_personal_team_service):
                with patch("mcpgateway.services.role_service.RoleService", return_value=mock_role_service):
                    user = await email_auth_service.create_user(
                        email="admin@example.com",
                        password="ValidPass123!",
                        is_admin=True,
                    )

                    assert user is not None
                    # Should be called twice: once for platform_admin, once for team_admin
                    assert mock_role_service.assign_role_to_user.call_count == 2


# ---------- Role Assignment Exception Handling ----------


@pytest.mark.asyncio
async def test_create_user_role_assignment_exception(email_auth_service, mock_db):
    """Test user creation continues when role assignment raises exception (lines 465-466)."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.auto_create_personal_teams = False
            mock_settings.password_min_length = 8
            mock_settings.password_require_uppercase = False
            mock_settings.password_require_lowercase = False
            mock_settings.password_require_numbers = False
            mock_settings.password_require_special = False

            # Mock RoleService to raise generic exception
            with patch("mcpgateway.services.role_service.RoleService", side_effect=Exception("Unexpected error")):
                # Should not raise exception, just log error
                user = await email_auth_service.create_user(
                    email="user@example.com",
                    password="ValidPass123!",
                    is_admin=False,
                )

                assert user is not None
                # db.add is called twice: once for user, once for registration event
                assert mock_db.add.call_count == 2
                mock_db.commit.assert_called()


# ---------- skip_onboarding Tests ----------


@pytest.mark.asyncio
async def test_create_user_skip_onboarding_no_personal_team(email_auth_service, mock_db):
    """create_user(skip_onboarding=True) must not create a personal team."""
    mock_personal_team_service = MagicMock()
    mock_personal_team_service.create_personal_team = AsyncMock()

    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            mock_settings.auto_create_personal_teams = True

            with patch(
                "mcpgateway.services.personal_team_service.PersonalTeamService",
                return_value=mock_personal_team_service,
            ):
                user = await email_auth_service.create_user(
                    email="synth@wxo.system",
                    password="",
                    skip_password_validation=True,
                    skip_onboarding=True,
                )

                assert user is not None
                mock_personal_team_service.create_personal_team.assert_not_called()


@pytest.mark.asyncio
async def test_create_user_skip_onboarding_no_role_assignment(email_auth_service, mock_db):
    """create_user(skip_onboarding=True) must not assign roles."""
    mock_role_service = MagicMock()
    mock_role_service.assign_role_to_user = AsyncMock()
    mock_role_service.get_role_by_name = AsyncMock()

    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8

            # Inject mock role service to detect if it gets called
            email_auth_service._role_service = mock_role_service

            user = await email_auth_service.create_user(
                email="synth@wxo.system",
                password="",
                skip_password_validation=True,
                skip_onboarding=True,
            )

            assert user is not None
            mock_role_service.get_role_by_name.assert_not_called()
            mock_role_service.assign_role_to_user.assert_not_called()


@pytest.mark.asyncio
async def test_create_user_skip_onboarding_no_registration_event(email_auth_service, mock_db):
    """create_user(skip_onboarding=True) must not log a registration event."""
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8

            user = await email_auth_service.create_user(
                email="synth@wxo.system",
                password="",
                skip_password_validation=True,
                skip_onboarding=True,
            )

            assert user is not None
            # Only 1 commit for the user row, not 2 (user + event)
            assert mock_db.commit.call_count == 1


@pytest.mark.asyncio
async def test_create_user_skip_onboarding_still_logs_failed_registration_event(email_auth_service, mock_db):
    """create_user(skip_onboarding=True) MUST still log a failed registration event on unexpected errors.

    Service-account creation failures are system issues that should always be audited,
    even when success-path onboarding events are skipped.
    """
    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch("mcpgateway.services.email_auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8

            # First commit (user row) raises; second commit (failed event) succeeds
            mock_db.commit.side_effect = [RuntimeError("db down"), None]

            with pytest.raises(RuntimeError):
                await email_auth_service.create_user(
                    email="synth@wxo.system",
                    password="",
                    skip_password_validation=True,
                    skip_onboarding=True,
                )

            # Should have added 2 objects: user row + failed registration event
            assert mock_db.add.call_count == 2


# ---------- ensure_user_exists Tests ----------


@pytest.mark.asyncio
async def test_ensure_user_exists_creates_new_user(email_auth_service):
    """ensure_user_exists creates user when not found."""
    mock_user = MagicMock()
    mock_user.email = "new@example.com"

    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch.object(email_auth_service, "create_user", return_value=mock_user) as mock_create:
            user, created = await email_auth_service.ensure_user_exists(
                email="new@example.com",
                full_name="New User",
            )
            assert created is True
            assert user == mock_user
            mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_user_exists_returns_existing(email_auth_service):
    """ensure_user_exists returns existing user without creating."""
    mock_user = MagicMock()
    mock_user.email = "existing@example.com"

    with patch.object(email_auth_service, "get_user_by_email", return_value=mock_user):
        with patch.object(email_auth_service, "create_user") as mock_create:
            user, created = await email_auth_service.ensure_user_exists(
                email="existing@example.com",
            )
            assert created is False
            assert user == mock_user
            mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_user_exists_handles_race_condition(email_auth_service):
    """ensure_user_exists handles UserExistsError from concurrent creation."""
    mock_user = MagicMock()
    mock_user.email = "race@example.com"

    with patch.object(email_auth_service, "get_user_by_email", side_effect=[None, mock_user]):
        with patch.object(
            email_auth_service,
            "create_user",
            side_effect=UserExistsError("already exists"),
        ):
            user, created = await email_auth_service.ensure_user_exists(
                email="race@example.com",
            )
            assert created is False
            assert user == mock_user


@pytest.mark.asyncio
async def test_ensure_user_exists_passes_skip_onboarding(email_auth_service):
    """ensure_user_exists forwards skip_onboarding to create_user."""
    mock_user = MagicMock()

    with patch.object(email_auth_service, "get_user_by_email", return_value=None):
        with patch.object(email_auth_service, "create_user", return_value=mock_user) as mock_create:
            await email_auth_service.ensure_user_exists(
                email="synth@wxo.system",
                skip_onboarding=True,
                is_admin=True,
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["skip_onboarding"] is True
            assert call_kwargs["skip_password_validation"] is True
            assert call_kwargs["password"] == ""


@pytest.mark.asyncio
async def test_ensure_user_exists_reraises_when_race_fetch_returns_none(email_auth_service):
    """ensure_user_exists re-raises UserExistsError when post-race re-fetch returns None."""
    with patch.object(email_auth_service, "get_user_by_email", side_effect=[None, None]):
        with patch.object(
            email_auth_service,
            "create_user",
            side_effect=UserExistsError("already exists"),
        ):
            with pytest.raises(UserExistsError):
                await email_auth_service.ensure_user_exists(email="ghost@example.com")


@pytest.mark.asyncio
async def test_ensure_user_exists_normalizes_email(email_auth_service):
    """ensure_user_exists normalizes email before lookup so whitespace/case doesn't cause false misses."""
    mock_user = MagicMock()
    mock_user.email = "user@example.com"

    with patch.object(email_auth_service, "get_user_by_email", return_value=mock_user) as mock_get:
        user, created = await email_auth_service.ensure_user_exists(
            email="  User@Example.COM  ",
        )
        assert created is False
        assert user == mock_user
        # Should be called with the normalized email
        mock_get.assert_called_once_with("user@example.com")
