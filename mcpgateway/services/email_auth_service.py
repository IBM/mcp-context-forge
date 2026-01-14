# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/email_auth_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Email Authentication Service.
This module provides email-based user authentication services including
user creation, authentication, password management, and security features.

Examples:
    Basic usage (requires async context):
        from mcpgateway.services.email_auth_service import EmailAuthService
        from mcpgateway.db import SessionLocal

        with SessionLocal() as db:
            service = EmailAuthService(db)
            # Use in async context:
            # user = await service.create_user("test@example.com", "password123")
            # authenticated = await service.authenticate_user("test@example.com", "password123")
"""

# Standard
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Optional
import warnings

# Third-Party
import orjson
from sqlalchemy import and_, delete, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailAuthEvent, EmailTeam, EmailTeamMember, EmailUser, utc_now
from mcpgateway.schemas import PaginationLinks, PaginationMeta
from mcpgateway.services.argon2_service import Argon2PasswordService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.pagination import unified_paginate

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

_GET_ALL_USERS_LIMIT = 10000


@dataclass(frozen=True)
class UsersListResult:
    """Result for list_users queries."""

    data: list[EmailUser]
    next_cursor: Optional[str] = None
    pagination: Optional[PaginationMeta] = None
    links: Optional[PaginationLinks] = None


class EmailValidationError(Exception):
    """Raised when email format is invalid.

    Examples:
        >>> try:
        ...     raise EmailValidationError("Invalid email format")
        ... except EmailValidationError as e:
        ...     str(e)
        'Invalid email format'
    """


class PasswordValidationError(Exception):
    """Raised when password doesn't meet policy requirements.

    Examples:
        >>> try:
        ...     raise PasswordValidationError("Password too short")
        ... except PasswordValidationError as e:
        ...     str(e)
        'Password too short'
    """


class UserExistsError(Exception):
    """Raised when attempting to create a user that already exists.

    Examples:
        >>> try:
        ...     raise UserExistsError("User already exists")
        ... except UserExistsError as e:
        ...     str(e)
        'User already exists'
    """


class AuthenticationError(Exception):
    """Raised when authentication fails.

    Examples:
        >>> try:
        ...     raise AuthenticationError("Invalid credentials")
        ... except AuthenticationError as e:
        ...     str(e)
        'Invalid credentials'
    """


class EmailAuthService:
    """Service for email-based user authentication.

    This service handles user registration, authentication, password management,
    and security features like account lockout and failed attempt tracking.

    Attributes:
        db (Session): Database session
        password_service (Argon2PasswordService): Password hashing service

    Examples:
        >>> from mcpgateway.db import SessionLocal
        >>> with SessionLocal() as db:
        ...     service = EmailAuthService(db)
        ...     # Service is ready to use
    """

    get_all_users_deprecated_warned = False

    def __init__(self, db: Session):
        """Initialize the email authentication service.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.password_service = Argon2PasswordService()
        logger.debug("EmailAuthService initialized")

    def validate_email(self, email: str) -> bool:
        """Validate email address format.

        Args:
            email: Email address to validate

        Returns:
            bool: True if email is valid

        Raises:
            EmailValidationError: If email format is invalid

        Examples:
            >>> service = EmailAuthService(None)
            >>> service.validate_email("user@example.com")
            True
            >>> service.validate_email("test.user+tag@domain.co.uk")
            True
            >>> service.validate_email("user123@test-domain.com")
            True
            >>> try:
            ...     service.validate_email("invalid-email")
            ... except EmailValidationError as e:
            ...     "Invalid email format" in str(e)
            True
            >>> try:
            ...     service.validate_email("")
            ... except EmailValidationError as e:
            ...     "Email is required" in str(e)
            True
            >>> try:
            ...     service.validate_email("user@")
            ... except EmailValidationError as e:
            ...     "Invalid email format" in str(e)
            True
            >>> try:
            ...     service.validate_email("@domain.com")
            ... except EmailValidationError as e:
            ...     "Invalid email format" in str(e)
            True
            >>> try:
            ...     service.validate_email("user@domain")
            ... except EmailValidationError as e:
            ...     "Invalid email format" in str(e)
            True
            >>> try:
            ...     service.validate_email("a" * 250 + "@domain.com")
            ... except EmailValidationError as e:
            ...     "Email address too long" in str(e)
            True
            >>> try:
            ...     service.validate_email(None)
            ... except EmailValidationError as e:
            ...     "Email is required" in str(e)
            True
        """
        if not email or not isinstance(email, str):
            raise EmailValidationError("Email is required and must be a string")

        # Basic email regex pattern
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        if not re.match(email_pattern, email):
            raise EmailValidationError("Invalid email format")

        if len(email) > 255:
            raise EmailValidationError("Email address too long (max 255 characters)")

        return True

    def validate_password(self, password: str) -> bool:
        """Validate password against policy requirements.

        Args:
            password: Password to validate

        Returns:
            bool: True if password meets policy

        Raises:
            PasswordValidationError: If password doesn't meet requirements

        Examples:
            >>> service = EmailAuthService(None)
            >>> service.validate_password("Password123!")  # Meets all requirements
            True
            >>> service.validate_password("ValidPassword123!")
            True
            >>> service.validate_password("Shortpass!")  # 8+ chars with requirements
            True
            >>> service.validate_password("VeryLongPasswordThatMeetsMinimumRequirements!")
            True
            >>> try:
            ...     service.validate_password("")
            ... except PasswordValidationError as e:
            ...     "Password is required" in str(e)
            True
            >>> try:
            ...     service.validate_password(None)
            ... except PasswordValidationError as e:
            ...     "Password is required" in str(e)
            True
            >>> try:
            ...     service.validate_password("short")  # Only 5 chars, should fail with default min_length=8
            ... except PasswordValidationError as e:
            ...     "characters long" in str(e)
            True
        """
        if not password:
            raise PasswordValidationError("Password is required")

        # Respect global toggle for password policy
        if not getattr(settings, "password_policy_enabled", True):
            return True

        # Get password policy settings
        min_length = getattr(settings, "password_min_length", 8)
        require_uppercase = getattr(settings, "password_require_uppercase", False)
        require_lowercase = getattr(settings, "password_require_lowercase", False)
        require_numbers = getattr(settings, "password_require_numbers", False)
        require_special = getattr(settings, "password_require_special", False)

        if len(password) < min_length:
            raise PasswordValidationError(f"Password must be at least {min_length} characters long")

        if require_uppercase and not re.search(r"[A-Z]", password):
            raise PasswordValidationError("Password must contain at least one uppercase letter")

        if require_lowercase and not re.search(r"[a-z]", password):
            raise PasswordValidationError("Password must contain at least one lowercase letter")

        if require_numbers and not re.search(r"[0-9]", password):
            raise PasswordValidationError("Password must contain at least one number")

        if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise PasswordValidationError("Password must contain at least one special character")

        return True

    async def get_user_by_email(self, email: str) -> Optional[EmailUser]:
        """Get user by email address.

        Args:
            email: Email address to look up

        Returns:
            EmailUser or None if not found

        Examples:
            # Assuming database has user "test@example.com"
            # user = await service.get_user_by_email("test@example.com")
            # user.email if user else None  # Returns: 'test@example.com'
        """
        try:
            stmt = select(EmailUser).where(EmailUser.email == email.lower())
            result = self.db.execute(stmt)
            user = result.scalar_one_or_none()
            return user
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None

    async def create_user(self, email: str, password: str, full_name: Optional[str] = None, is_admin: bool = False, auth_provider: str = "local", skip_password_validation: bool = False) -> EmailUser:
        """Create a new user with email authentication.

        Args:
            email: User's email address (primary key)
            password: Plain text password (will be hashed)
            full_name: Optional full name for display
            is_admin: Whether user has admin privileges
            auth_provider: Authentication provider ('local', 'github', etc.)
            skip_password_validation: Skip password policy validation (for bootstrap)

        Returns:
            EmailUser: The created user object

        Raises:
            EmailValidationError: If email format is invalid
            PasswordValidationError: If password doesn't meet policy
            UserExistsError: If user already exists

        Examples:
            # user = await service.create_user(
            #     email="new@example.com",
            #     password="secure123",
            #     full_name="New User"
            # )
            # user.email          # Returns: 'new@example.com'
            # user.full_name      # Returns: 'New User'
        """
        # Normalize email to lowercase
        email = email.lower().strip()

        # Validate inputs
        self.validate_email(email)
        if not skip_password_validation:
            self.validate_password(password)

        # Check if user already exists
        existing_user = await self.get_user_by_email(email)
        if existing_user:
            raise UserExistsError(f"User with email {email} already exists")

        # Hash the password
        password_hash = self.password_service.hash_password(password)

        # Create new user (record password change timestamp)
        user = EmailUser(email=email, password_hash=password_hash, full_name=full_name, is_admin=is_admin, auth_provider=auth_provider, password_changed_at=utc_now())

        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

            logger.info(f"Created new user: {email}")

            # Create personal team if enabled
            if getattr(settings, "auto_create_personal_teams", True):
                try:
                    # Import here to avoid circular imports
                    # First-Party
                    from mcpgateway.services.personal_team_service import PersonalTeamService  # pylint: disable=import-outside-toplevel

                    personal_team_service = PersonalTeamService(self.db)
                    personal_team = await personal_team_service.create_personal_team(user)
                    logger.info(f"Created personal team '{personal_team.name}' for user {email}")
                except Exception as e:
                    logger.warning(f"Failed to create personal team for {email}: {e}")
                    # Don't fail user creation if personal team creation fails

            # Log registration event
            registration_event = EmailAuthEvent.create_registration_event(user_email=email, success=True)
            self.db.add(registration_event)
            self.db.commit()

            return user

        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"Database error creating user {email}: {e}")
            raise UserExistsError(f"User with email {email} already exists") from e
        except Exception as e:
            self.db.rollback()
            logger.error(f"Unexpected error creating user {email}: {e}")

            # Log failed registration
            registration_event = EmailAuthEvent.create_registration_event(user_email=email, success=False, failure_reason=str(e))
            self.db.add(registration_event)
            self.db.commit()

            raise

    async def authenticate_user(self, email: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[EmailUser]:
        """Authenticate a user with email and password.

        Args:
            email: User's email address
            password: Plain text password
            ip_address: Client IP address for logging
            user_agent: Client user agent for logging

        Returns:
            EmailUser if authentication successful, None otherwise

        Examples:
            # user = await service.authenticate_user("user@example.com", "correct_password")
            # user.email if user else None  # Returns: 'user@example.com'
            # await service.authenticate_user("user@example.com", "wrong_password")  # Returns: None
        """
        email = email.lower().strip()

        # Get user from database
        user = await self.get_user_by_email(email)

        # Track authentication attempt
        auth_success = False
        failure_reason = None

        try:
            if not user:
                failure_reason = "User not found"
                logger.info(f"Authentication failed for {email}: user not found")
                return None

            if not user.is_active:
                failure_reason = "Account is disabled"
                logger.info(f"Authentication failed for {email}: account disabled")
                return None

            if user.is_account_locked():
                failure_reason = "Account is locked"
                logger.info(f"Authentication failed for {email}: account locked")
                return None

            # Verify password
            if not self.password_service.verify_password(password, user.password_hash):
                failure_reason = "Invalid password"

                # Increment failed attempts
                max_attempts = getattr(settings, "max_failed_login_attempts", 5)
                lockout_duration = getattr(settings, "account_lockout_duration_minutes", 30)

                is_locked = user.increment_failed_attempts(max_attempts, lockout_duration)

                if is_locked:
                    logger.warning(f"Account locked for {email} after {max_attempts} failed attempts")
                    failure_reason = "Account locked due to too many failed attempts"

                self.db.commit()
                logger.info(f"Authentication failed for {email}: invalid password")
                return None

            # Authentication successful
            user.reset_failed_attempts()
            self.db.commit()

            auth_success = True
            logger.info(f"Authentication successful for {email}")

            return user

        finally:
            # Log authentication event
            auth_event = EmailAuthEvent.create_login_attempt(user_email=email, success=auth_success, ip_address=ip_address, user_agent=user_agent, failure_reason=failure_reason)
            self.db.add(auth_event)
            self.db.commit()

    async def change_password(self, email: str, old_password: Optional[str], new_password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
        """Change a user's password.

        Args:
            email: User's email address
            old_password: Current password for verification
            new_password: New password to set
            ip_address: Client IP address for logging
            user_agent: Client user agent for logging

        Returns:
            bool: True if password changed successfully

        Raises:
            AuthenticationError: If old password is incorrect
            PasswordValidationError: If new password doesn't meet policy
            Exception: If database operation fails

        Examples:
            # success = await service.change_password(
            #     "user@example.com",
            #     "old_password",
            #     "new_secure_password"
            # )
            # success              # Returns: True
        """
        # Validate old password is provided
        if old_password is None:
            raise AuthenticationError("Current password is required")

        # First authenticate with old password
        user = await self.authenticate_user(email, old_password, ip_address, user_agent)
        if not user:
            raise AuthenticationError("Current password is incorrect")

        # Validate new password
        self.validate_password(new_password)

        # Check if new password is same as old (optional policy)
        if getattr(settings, "password_prevent_reuse", True) and self.password_service.verify_password(new_password, user.password_hash):
            raise PasswordValidationError("New password must be different from current password")

        success = False
        try:
            # Hash new password and update
            new_password_hash = self.password_service.hash_password(new_password)
            user.password_hash = new_password_hash
            # Clear the flag that requires the user to change password
            user.password_change_required = False
            # Record the password change timestamp
            try:
                user.password_changed_at = utc_now()
            except Exception as exc:
                logger.debug("Failed to set password_changed_at for %s: %s", email, exc)

            self.db.commit()
            success = True

            # Invalidate auth cache for user
            try:
                # Standard
                import asyncio  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

                # Ensure cache invalidation runs before returning to avoid stale
                # auth context being used by subsequent requests. Use a timeout
                # to prevent blocking if Redis is slow or unresponsive.
                # Shield the task to prevent cancellation on timeout - allows Redis
                # operations to complete in background even if we stop waiting.
                await asyncio.wait_for(asyncio.shield(auth_cache.invalidate_user(email)), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Auth cache invalidation timed out for {email} - continuing in background")
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate auth cache on password change: {cache_error}")

            logger.info(f"Password changed successfully for {email}")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error changing password for {email}: {e}")
            raise
        finally:
            # Log password change event
            password_event = EmailAuthEvent.create_password_change_event(user_email=email, success=success, ip_address=ip_address, user_agent=user_agent)
            self.db.add(password_event)
            self.db.commit()

        return success

    async def create_platform_admin(self, email: str, password: str, full_name: Optional[str] = None) -> EmailUser:
        """Create or update the platform administrator user.

        This method is used during system bootstrap to create the initial
        admin user from environment variables.

        Args:
            email: Admin email address
            password: Admin password
            full_name: Admin full name

        Returns:
            EmailUser: The admin user

        Examples:
            # admin = await service.create_platform_admin(
            #     "admin@example.com",
            #     "admin_password",
            #     "Platform Administrator"
            # )
            # admin.is_admin       # Returns: True
        """
        # Check if admin user already exists
        existing_admin = await self.get_user_by_email(email)

        if existing_admin:
            # Update existing admin if password or name changed
            if full_name and existing_admin.full_name != full_name:
                existing_admin.full_name = full_name

            # Check if password needs update (verify current password first)
            if not self.password_service.verify_password(password, existing_admin.password_hash):
                existing_admin.password_hash = self.password_service.hash_password(password)
                try:
                    existing_admin.password_changed_at = utc_now()
                except Exception as exc:
                    logger.debug("Failed to set password_changed_at for existing admin %s: %s", email, exc)

            # Ensure admin status
            existing_admin.is_admin = True
            existing_admin.is_active = True

            self.db.commit()
            logger.info(f"Updated platform admin user: {email}")
            return existing_admin

        # Create new admin user - skip password validation during bootstrap
        admin_user = await self.create_user(email=email, password=password, full_name=full_name, is_admin=True, auth_provider="local", skip_password_validation=True)

        logger.info(f"Created platform admin user: {email}")
        return admin_user

    async def update_last_login(self, email: str) -> None:
        """Update the last login timestamp for a user.

        Args:
            email: User's email address
        """
        user = await self.get_user_by_email(email)
        if user:
            user.reset_failed_attempts()  # This also updates last_login
            self.db.commit()

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape LIKE wildcards for prefix search.

        Args:
            value: Raw value to escape for LIKE matching.

        Returns:
            Escaped string safe for LIKE patterns.
        """
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def list_users(
        self,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        search: Optional[str] = None,
    ) -> UsersListResult:
        """List all users with cursor or page-based pagination support and optional search.

        This method supports both cursor-based (for API endpoints with large datasets)
        and page-based (for admin UI with page numbers) pagination, with optional
        search filtering by email or full name.

        Note: This method returns ORM objects and cannot be cached since callers
        depend on ORM attributes and methods (e.g., EmailUserResponse.from_email_user).

        Args:
            limit: Maximum number of users to return (for cursor-based pagination)
            cursor: Opaque cursor token for cursor-based pagination
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination
            search: Optional search term to filter by email or full name (case-insensitive)

        Returns:
            UsersListResult with data and optional pagination metadata.

        Examples:
            # Cursor-based pagination (for APIs)
            # result = await service.list_users(cursor=None, limit=50)
            # len(result.data) <= 50     # Returns: True

            # Page-based pagination (for admin UI)
            # result = await service.list_users(page=1, per_page=10)
            # result.data       # Returns: list of users
            # result.pagination # Returns: pagination metadata

            # Search users
            # users = await service.list_users(search="john", page=1, per_page=10)
            # All users with "john" in email or name
        """
        try:
            # Build base query with ordering by created_at, email for consistent pagination
            # Note: EmailUser uses email as primary key, not id
            query = select(EmailUser).order_by(desc(EmailUser.created_at), desc(EmailUser.email))

            # Apply search filter if provided (prefix search for better index usage)
            if search and search.strip():
                search_term = f"{self._escape_like(search.strip())}%"
                # NOTE: For large Postgres datasets, consider citext or functional indexes for case-insensitive search.
                query = query.where(
                    or_(
                        EmailUser.email.ilike(search_term, escape="\\"),
                        EmailUser.full_name.ilike(search_term, escape="\\"),
                    )
                )

            # Page-based pagination: use unified_paginate
            if page is not None:
                pag_result = await unified_paginate(
                    db=self.db,
                    query=query,
                    page=page,
                    per_page=per_page,
                    cursor=None,
                    limit=None,
                    base_url="/admin/users",
                    query_params={},
                )
                return UsersListResult(data=pag_result["data"], pagination=pag_result["pagination"], links=pag_result["links"])

            # Cursor-based pagination: custom implementation for EmailUser
            # EmailUser uses email as PK (not id), so we need custom cursor using (created_at, email)
            page_size = limit if limit and limit > 0 else settings.pagination_default_page_size
            if limit == 0:
                page_size = None  # No limit

            # Decode cursor and apply keyset filter if provided
            if cursor:
                try:
                    cursor_json = base64.urlsafe_b64decode(cursor.encode()).decode()
                    cursor_data = orjson.loads(cursor_json)
                    last_email = cursor_data.get("email")
                    created_str = cursor_data.get("created_at")
                    if last_email and created_str:
                        last_created = datetime.fromisoformat(created_str)
                        # Apply keyset filter (assumes DESC order on created_at, email)
                        query = query.where(
                            or_(
                                EmailUser.created_at < last_created,
                                and_(EmailUser.created_at == last_created, EmailUser.email < last_email),
                            )
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid cursor for user pagination, ignoring: {e}")

            # Fetch page_size + 1 to determine if there are more results
            if page_size is not None:
                query = query.limit(page_size + 1)
            result = self.db.execute(query)
            users = list(result.scalars().all())

            if page_size is None:
                return UsersListResult(data=users, next_cursor=None)

            # Check if there are more results
            has_more = len(users) > page_size
            if has_more:
                users = users[:page_size]

            # Generate next cursor using (created_at, email) for EmailUser
            next_cursor = None
            if has_more and users:
                last_user = users[-1]
                cursor_data = {
                    "created_at": last_user.created_at.isoformat() if last_user.created_at else None,
                    "email": last_user.email,
                }
                next_cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

            return UsersListResult(data=users, next_cursor=next_cursor)

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            # Return appropriate empty response based on pagination mode
            if page is not None:
                fallback_per_page = per_page or 50
                return UsersListResult(
                    data=[],
                    pagination=PaginationMeta(page=page, per_page=fallback_per_page, total_items=0, total_pages=0, has_next=False, has_prev=False),
                    links=PaginationLinks(  # pylint: disable=kwarg-superseded-by-positional-arg
                        self=f"/admin/users?page=1&per_page={fallback_per_page}",
                        first=f"/admin/users?page=1&per_page={fallback_per_page}",
                        last=f"/admin/users?page=1&per_page={fallback_per_page}",
                    ),
                )

            if cursor is not None:
                return UsersListResult(data=[], next_cursor=None)

            return UsersListResult(data=[])

    async def list_users_not_in_team(
        self,
        team_id: str,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        search: Optional[str] = None,
    ) -> UsersListResult:
        """List users who are NOT members of the specified team with cursor or page-based pagination.

        Uses a NOT IN subquery to efficiently exclude team members.

        Args:
            team_id: ID of the team to exclude members from
            cursor: Opaque cursor token for cursor-based pagination
            limit: Maximum number of users to return (for cursor-based, default: 50)
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination (default: 30)
            search: Optional search term to filter by email or full name

        Returns:
            UsersListResult with data and either cursor or pagination metadata

        Examples:
            # Page-based (admin UI)
            # result = await service.list_users_not_in_team("team-123", page=1, per_page=30)
            # result.pagination # Returns: pagination metadata

            # Cursor-based (API)
            # result = await service.list_users_not_in_team("team-123", cursor=None, limit=50)
            # result.next_cursor # Returns: next cursor token
        """
        try:
            # Build base query
            query = select(EmailUser)

            # Apply search filter if provided
            if search and search.strip():
                search_term = f"{self._escape_like(search.strip())}%"
                query = query.where(
                    or_(
                        EmailUser.email.ilike(search_term, escape="\\"),
                        EmailUser.full_name.ilike(search_term, escape="\\"),
                    )
                )

            # Exclude team members using NOT IN subquery
            member_emails_subquery = select(EmailTeamMember.user_email).where(EmailTeamMember.team_id == team_id, EmailTeamMember.is_active.is_(True))
            query = query.where(EmailUser.is_active.is_(True), ~EmailUser.email.in_(member_emails_subquery))

            # PAGE-BASED PAGINATION (Admin UI) - use unified_paginate
            if page is not None:
                query = query.order_by(EmailUser.full_name, EmailUser.email)
                pag_result = await unified_paginate(
                    db=self.db,
                    query=query,
                    page=page,
                    per_page=per_page or 30,
                    cursor=None,
                    limit=None,
                    base_url=f"/admin/teams/{team_id}/non-members",
                    query_params={},
                )
                return UsersListResult(data=pag_result["data"], pagination=pag_result["pagination"], links=pag_result["links"])

            # CURSOR-BASED PAGINATION - custom implementation using (created_at, email)
            # unified_paginate uses (created_at, id) but EmailUser uses email as PK
            query = query.order_by(desc(EmailUser.created_at), desc(EmailUser.email))

            # Decode cursor and apply keyset filter
            if cursor:
                try:
                    cursor_json = base64.urlsafe_b64decode(cursor.encode()).decode()
                    cursor_data = orjson.loads(cursor_json)
                    last_email = cursor_data.get("email")
                    created_str = cursor_data.get("created_at")
                    if last_email and created_str:
                        last_created = datetime.fromisoformat(created_str)
                        # Keyset filter: (created_at < last) OR (created_at = last AND email < last_email)
                        query = query.where(
                            or_(
                                EmailUser.created_at < last_created,
                                and_(EmailUser.created_at == last_created, EmailUser.email < last_email),
                            )
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid cursor for non-members list, ignoring: {e}")

            # Fetch limit + 1 to check for more results
            page_size = limit or 50
            query = query.limit(page_size + 1)
            users = list(self.db.execute(query).scalars().all())

            # Check if there are more results
            has_more = len(users) > page_size
            if has_more:
                users = users[:page_size]

            # Generate next cursor using (created_at, email)
            next_cursor = None
            if has_more and users:
                last_user = users[-1]
                cursor_data = {
                    "created_at": last_user.created_at.isoformat() if last_user.created_at else None,
                    "email": last_user.email,
                }
                next_cursor = base64.urlsafe_b64encode(orjson.dumps(cursor_data)).decode()

            self.db.commit()
            return UsersListResult(data=users, next_cursor=next_cursor)

        except Exception as e:
            logger.error(f"Error listing non-members for team {team_id}: {e}")

            # Return appropriate empty response based on mode
            if page is not None:
                return UsersListResult(
                    data=[],
                    pagination=PaginationMeta(page=page, per_page=per_page or 30, total_items=0, total_pages=0, has_next=False, has_prev=False),
                    links=PaginationLinks(  # pylint: disable=kwarg-superseded-by-positional-arg
                        self=f"/admin/teams/{team_id}/non-members?page=1&per_page={per_page or 30}",
                        first=f"/admin/teams/{team_id}/non-members?page=1&per_page={per_page or 30}",
                        last=f"/admin/teams/{team_id}/non-members?page=1&per_page={per_page or 30}",
                    ),
                )

            return UsersListResult(data=[], next_cursor=None)

    async def get_all_users(self) -> list[EmailUser]:
        """Get all users without pagination.

        .. deprecated:: 1.0
            Use :meth:`list_users` with proper pagination instead.
            This method has a hardcoded limit of 10,000 users and will not return
            more than that. For production systems with many users, use paginated
            access with search/filtering.

        Returns:
            List of up to 10,000 EmailUser objects

        Raises:
            ValueError: If total users exceed 10,000

        Examples:
            # users = await service.get_all_users()
            # isinstance(users, list)  # Returns: True

        Warning:
            This method is deprecated and will be removed in a future version.
            Use list_users() with pagination instead:

            # For small datasets
            users = await service.list_users(page=1, per_page=1000).data

            # For searching
            users = await service.list_users(search="john", page=1, per_page=10).data
        """
        if not self.__class__.get_all_users_deprecated_warned:
            warnings.warn(
                "get_all_users() is deprecated and limited to 10,000 users. " + "Use list_users() with pagination instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self.__class__.get_all_users_deprecated_warned = True

        total_users = await self.count_users()
        if total_users > _GET_ALL_USERS_LIMIT:
            raise ValueError("get_all_users() supports up to 10,000 users. Use list_users() pagination instead.")

        result = await self.list_users(limit=_GET_ALL_USERS_LIMIT)
        return result.data  # Large limit to get all users

    async def count_users(self) -> int:
        """Count total number of users.

        Returns:
            int: Total user count
        """
        try:
            stmt = select(func.count(EmailUser.email))  # pylint: disable=not-callable
            count = self.db.execute(stmt).scalar() or 0
            return count
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0

    async def get_auth_events(self, email: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[EmailAuthEvent]:
        """Get authentication events for auditing.

        Args:
            email: Filter by specific user email (optional)
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List of EmailAuthEvent objects
        """
        try:
            stmt = select(EmailAuthEvent)
            if email:
                stmt = stmt.where(EmailAuthEvent.user_email == email)
            stmt = stmt.order_by(EmailAuthEvent.timestamp.desc()).offset(offset).limit(limit)

            result = self.db.execute(stmt)
            events = list(result.scalars().all())
            return events
        except Exception as e:
            logger.error(f"Error getting auth events: {e}")
            return []

    async def update_user(self, email: str, full_name: Optional[str] = None, is_admin: Optional[bool] = None, password: Optional[str] = None) -> EmailUser:
        """Update user information.

        Args:
            email: User's email address (primary key)
            full_name: New full name (optional)
            is_admin: New admin status (optional)
            password: New password (optional, will be hashed)

        Returns:
            EmailUser: Updated user object

        Raises:
            ValueError: If user doesn't exist
            PasswordValidationError: If password doesn't meet policy
        """
        try:
            # Get existing user
            stmt = select(EmailUser).where(EmailUser.email == email)
            result = self.db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise ValueError(f"User {email} not found")

            # Update fields if provided
            if full_name is not None:
                user.full_name = full_name

            if is_admin is not None:
                user.is_admin = is_admin

            if password is not None:
                if not self.validate_password(password):
                    raise ValueError("Password does not meet security requirements")
                user.password_hash = self.password_service.hash_password(password)
                user.password_change_required = False  # Clear password change requirement
                user.password_changed_at = utc_now()  # Update password change timestamp

            user.updated_at = datetime.now(timezone.utc)

            self.db.commit()

            return user

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating user {email}: {e}")
            raise

    async def activate_user(self, email: str) -> EmailUser:
        """Activate a user account.

        Args:
            email: User's email address

        Returns:
            EmailUser: Updated user object

        Raises:
            ValueError: If user doesn't exist
        """
        try:
            stmt = select(EmailUser).where(EmailUser.email == email)
            result = self.db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise ValueError(f"User {email} not found")

            user.is_active = True
            user.updated_at = datetime.now(timezone.utc)

            self.db.commit()

            logger.info(f"User {email} activated")
            return user

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error activating user {email}: {e}")
            raise

    async def deactivate_user(self, email: str) -> EmailUser:
        """Deactivate a user account.

        Args:
            email: User's email address

        Returns:
            EmailUser: Updated user object

        Raises:
            ValueError: If user doesn't exist
        """
        try:
            stmt = select(EmailUser).where(EmailUser.email == email)
            result = self.db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise ValueError(f"User {email} not found")

            user.is_active = False
            user.updated_at = datetime.now(timezone.utc)

            self.db.commit()

            logger.info(f"User {email} deactivated")
            return user

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deactivating user {email}: {e}")
            raise

    async def delete_user(self, email: str) -> bool:
        """Delete a user account permanently.

        Args:
            email: User's email address

        Returns:
            bool: True if user was deleted

        Raises:
            ValueError: If user doesn't exist
            ValueError: If user owns teams that cannot be transferred
        """
        try:
            stmt = select(EmailUser).where(EmailUser.email == email)
            result = self.db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                raise ValueError(f"User {email} not found")

            # Check if user owns any teams
            teams_owned_stmt = select(EmailTeam).where(EmailTeam.created_by == email)
            teams_owned = self.db.execute(teams_owned_stmt).scalars().all()

            if teams_owned:
                # For each team, try to transfer ownership to another owner
                for team in teams_owned:
                    # Find other team owners who can take ownership
                    potential_owners_stmt = (
                        select(EmailTeamMember).where(EmailTeamMember.team_id == team.id, EmailTeamMember.user_email != email, EmailTeamMember.role == "owner").order_by(EmailTeamMember.role.desc())
                    )

                    potential_owners = self.db.execute(potential_owners_stmt).scalars().all()

                    if potential_owners:
                        # Transfer ownership to the first available owner
                        new_owner = potential_owners[0]
                        team.created_by = new_owner.user_email
                        logger.info(f"Transferred team '{team.name}' ownership from {email} to {new_owner.user_email}")
                    else:
                        # No other owners available - check if it's a single-user team
                        all_members_stmt = select(EmailTeamMember).where(EmailTeamMember.team_id == team.id)
                        all_members = self.db.execute(all_members_stmt).scalars().all()

                        if len(all_members) == 1 and all_members[0].user_email == email:
                            # This is a single-user personal team - cascade delete it
                            logger.info(f"Deleting personal team '{team.name}' (single member: {email})")
                            # Delete team members first (should be just the owner)
                            delete_team_members_stmt = delete(EmailTeamMember).where(EmailTeamMember.team_id == team.id)
                            self.db.execute(delete_team_members_stmt)
                            # Delete the team
                            self.db.delete(team)
                        else:
                            # Multi-member team with no other owners - cannot delete user
                            raise ValueError(f"Cannot delete user {email}: owns team '{team.name}' with {len(all_members)} members but no other owners to transfer ownership to")

            # Delete related auth events first
            auth_events_stmt = delete(EmailAuthEvent).where(EmailAuthEvent.user_email == email)
            self.db.execute(auth_events_stmt)

            # Remove user from all team memberships
            team_members_stmt = delete(EmailTeamMember).where(EmailTeamMember.user_email == email)
            self.db.execute(team_members_stmt)

            # Delete the user
            self.db.delete(user)
            self.db.commit()

            # Invalidate all auth caches for deleted user
            try:
                # Standard
                import asyncio  # pylint: disable=import-outside-toplevel

                # First-Party
                from mcpgateway.cache.auth_cache import auth_cache  # pylint: disable=import-outside-toplevel

                asyncio.create_task(auth_cache.invalidate_user(email))
                asyncio.create_task(auth_cache.invalidate_user_teams(email))
                asyncio.create_task(auth_cache.invalidate_team_membership(email))
            except Exception as cache_error:
                logger.debug(f"Failed to invalidate cache on user delete: {cache_error}")

            logger.info(f"User {email} deleted permanently")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting user {email}: {e}")
            raise

    async def count_active_admin_users(self) -> int:
        """Count the number of active admin users.

        Returns:
            int: Number of active admin users
        """
        stmt = select(func.count(EmailUser.email)).where(EmailUser.is_admin.is_(True), EmailUser.is_active.is_(True))  # pylint: disable=not-callable
        result = self.db.execute(stmt)
        return result.scalar() or 0

    async def is_last_active_admin(self, email: str) -> bool:
        """Check if the given user is the last active admin.

        Args:
            email: User's email address

        Returns:
            bool: True if this user is the last active admin
        """
        # First check if the user is an active admin
        stmt = select(EmailUser).where(EmailUser.email == email)
        result = self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.is_admin or not user.is_active:
            return False

        # Count total active admins
        admin_count = await self.count_active_admin_users()
        return admin_count == 1
