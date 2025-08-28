# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/user_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

User Management Service.
Provides user management functionality including:
- User creation and authentication
- Password management and security
- User session handling
- API token management
- Team membership management
"""

# Standard
from datetime import timedelta
import logging
import re
import secrets
from typing import Dict, List, Optional

# Third-Party
import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import SessionLocal, TeamMember, User, UserSession, utc_now
from mcpgateway.utils.auth_logging import log_auth_event

logger = logging.getLogger(__name__)

# Common password list for validation (subset of most common)
COMMON_PASSWORDS = {
    "password",
    "123456",
    "password123",
    "admin",
    "qwerty",
    "letmein",
    "welcome",
    "monkey",
    "dragon",
    "123456789",
    "football",
    "iloveyou",
    "master",
    "sunshine",
    "password1",
    "123123",
    "princess",
    "admin123",
    "welcome123",
    "login",
    "passw0rd",
    "abc123",
    "111111",
    "trustno1",
    "Password",
    "Password123",
    "changeme",
    "secret",
}


class PasswordPolicy:
    """Password policy validation and enforcement."""

    @staticmethod
    def validate(password: str) -> List[str]:
        """
        Validate password against security policy.

        Args:
            password: The password to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if len(password) < settings.password_min_length:
            errors.append(f"Password must be at least {settings.password_min_length} characters")

        if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
            errors.append("Password must contain uppercase letters")

        if settings.password_require_lowercase and not re.search(r"[a-z]", password):
            errors.append("Password must contain lowercase letters")

        if settings.password_require_numbers and not re.search(r"\d", password):
            errors.append("Password must contain numbers")

        if settings.password_require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append("Password must contain special characters")

        # Check common passwords
        if password.lower() in COMMON_PASSWORDS:
            errors.append("Password is too common")

        return errors

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using bcrypt.

        Args:
            password: The plain text password

        Returns:
            The bcrypt hash of the password
        """
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=settings.password_bcrypt_rounds)).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify password against bcrypt hash.

        Args:
            password: The plain text password
            password_hash: The bcrypt hash

        Returns:
            True if password matches hash
        """
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception as e:
            logger.warning(f"Password verification failed: {e}")
            return False


class UserService:
    """Service class for user management operations."""

    def __init__(self, db: Session):
        """Initialize UserService with database session.

        Args:
            db: Database session for user operations
        """
        self.db = db

    async def create_user(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        is_admin: bool = False,
        created_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> User:
        """
        Create a new user with password validation.

        Args:
            username: Unique username
            password: Plain text password
            email: Optional email address
            full_name: Optional full name
            is_admin: Whether user should have admin privileges
            created_by: ID of user creating this account
            ip_address: IP address of creation request
            user_agent: User agent of creation request

        Returns:
            The created user

        Raises:
            HTTPException: If validation fails or user already exists
        """
        # Validate password
        password_errors = PasswordPolicy.validate(password)
        if password_errors:
            await log_auth_event(
                db=self.db,
                event_type="user_creation_failed",
                username=username,
                success=False,
                failure_reason=f"Password validation: {', '.join(password_errors)}",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Password validation failed: {'; '.join(password_errors)}")

        # Check if username already exists
        existing_user = self.db.query(User).filter(User.username == username).first()
        if existing_user:
            await log_auth_event(
                db=self.db,
                event_type="user_creation_failed",
                username=username,
                success=False,
                failure_reason="Username already exists",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

        # Check if email already exists (if provided)
        if email and self.db.query(User).filter(User.email == email).first():
            await log_auth_event(
                db=self.db,
                event_type="user_creation_failed",
                username=username,
                success=False,
                failure_reason="Email already exists",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        # Hash password
        password_hash = PasswordPolicy.hash_password(password)

        # Create user
        user = User(
            username=username,
            password_hash=password_hash,
            email=email,
            full_name=full_name,
            is_admin=is_admin,
            is_active=True,
            email_verified=False,
            failed_login_attempts=0,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # Log successful creation
        await log_auth_event(
            db=self.db,
            event_type="user_created",
            user_id=user.id,
            username=username,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"created_by": created_by, "is_admin": is_admin},
        )

        logger.info(f"User created: {username} (ID: {user.id})")
        return user

    async def authenticate_user(self, username: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[User]:
        """
        Authenticate user with username and password.

        Args:
            username: Username or email
            password: Plain text password
            ip_address: IP address of login request
            user_agent: User agent of login request

        Returns:
            User if authentication successful, None otherwise
        """
        # Find user by username or email
        user = self.db.query(User).filter(or_(User.username == username, User.email == username)).first()

        if not user:
            await log_auth_event(
                db=self.db,
                event_type="login_failed",
                username=username,
                success=False,
                failure_reason="User not found",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return None

        # Check if account is locked
        if user.locked_until and user.locked_until > utc_now():
            await log_auth_event(
                db=self.db,
                event_type="login_failed",
                user_id=user.id,
                username=username,
                success=False,
                failure_reason="Account locked",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return None

        # Check if account is active
        if not user.is_active:
            await log_auth_event(
                db=self.db,
                event_type="login_failed",
                user_id=user.id,
                username=username,
                success=False,
                failure_reason="Account inactive",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return None

        # Verify password
        if not PasswordPolicy.verify_password(password, user.password_hash):
            # Increment failed attempts
            user.failed_login_attempts += 1

            # Lock account if too many failed attempts
            if user.failed_login_attempts >= 5:
                user.locked_until = utc_now() + timedelta(minutes=30)
                logger.warning(f"Account locked for user {username} due to too many failed attempts")

            self.db.commit()

            await log_auth_event(
                db=self.db,
                event_type="login_failed",
                user_id=user.id,
                username=username,
                success=False,
                failure_reason="Invalid password",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return None

        # Reset failed attempts on successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = utc_now()

        self.db.commit()

        await log_auth_event(db=self.db, event_type="login_success", user_id=user.id, username=username, success=True, ip_address=ip_address, user_agent=user_agent)

        return user

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID.

        Args:
            user_id: User ID to search for

        Returns:
            Optional[User]: User object if found, None otherwise
        """
        return self.db.query(User).filter(User.id == user_id).first()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username.

        Args:
            username: Username to search for

        Returns:
            Optional[User]: User object if found, None otherwise
        """
        return self.db.query(User).filter(User.username == username).first()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email.

        Args:
            email: Email address to search for

        Returns:
            Optional[User]: User object if found, None otherwise
        """
        return self.db.query(User).filter(User.email == email).first()

    async def list_users(self, skip: int = 0, limit: int = 100, search: Optional[str] = None, is_active: Optional[bool] = None) -> List[User]:
        """
        List users with optional filtering.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            search: Search term for username, email, or full name
            is_active: Filter by active status

        Returns:
            List of users
        """
        query = self.db.query(User)

        if search:
            search_term = f"%{search}%"
            query = query.filter(or_(User.username.ilike(search_term), User.email.ilike(search_term), User.full_name.ilike(search_term)))

        if is_active is not None:
            query = query.filter(User.is_active == is_active)

        return query.offset(skip).limit(limit).all()

    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_admin: Optional[bool] = None,
        updated_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[User]:
        """Update user information.

        Args:
            user_id: ID of user to update
            email: New email address
            full_name: New full name
            is_active: Active status
            is_admin: Admin status
            updated_by: ID of user making the update
            ip_address: IP address of request
            user_agent: User agent of request

        Returns:
            Optional[User]: Updated user object or None if not found

        Raises:
            HTTPException: If email already exists
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        changes = {}
        if email is not None and email != user.email:
            # Check if email already exists
            if self.db.query(User).filter(and_(User.email == email, User.id != user_id)).first():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
            user.email = email
            changes["email"] = email

        if full_name is not None:
            user.full_name = full_name
            changes["full_name"] = full_name

        if is_active is not None:
            user.is_active = is_active
            changes["is_active"] = is_active

        if is_admin is not None:
            user.is_admin = is_admin
            changes["is_admin"] = is_admin

        user.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(user)

        # Log the update
        await log_auth_event(
            db=self.db,
            event_type="user_updated",
            user_id=user.id,
            username=user.username,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"updated_by": updated_by, "changes": changes},
        )

        return user

    async def change_password(self, user_id: str, current_password: str, new_password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
        """
        Change user password.

        Args:
            user_id: ID of user changing password
            current_password: Current password for verification
            new_password: New password
            ip_address: IP address of request
            user_agent: User agent of request

        Returns:
            True if password changed successfully

        Raises:
            HTTPException: If validation fails
        """
        user = await self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Verify current password
        if not PasswordPolicy.verify_password(current_password, user.password_hash):
            await log_auth_event(
                db=self.db,
                event_type="password_change_failed",
                user_id=user.id,
                username=user.username,
                success=False,
                failure_reason="Invalid current password",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

        # Validate new password
        password_errors = PasswordPolicy.validate(new_password)
        if password_errors:
            await log_auth_event(
                db=self.db,
                event_type="password_change_failed",
                user_id=user.id,
                username=user.username,
                success=False,
                failure_reason=f"New password validation: {', '.join(password_errors)}",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"New password validation failed: {'; '.join(password_errors)}")

        # Update password
        user.password_hash = PasswordPolicy.hash_password(new_password)
        user.updated_at = utc_now()
        user.failed_login_attempts = 0  # Reset failed attempts
        user.locked_until = None  # Unlock account if locked

        self.db.commit()

        await log_auth_event(
            db=self.db,
            event_type="password_changed",
            user_id=user.id,
            username=user.username,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        logger.info(f"Password changed for user {user.username}")
        return True

    async def create_session(self, user: User, ip_address: Optional[str] = None, user_agent: Optional[str] = None, expires_in_hours: int = 24) -> UserSession:
        """
        Create a new user session.

        Args:
            user: User to create session for
            ip_address: IP address of the request
            user_agent: User agent of the request
            expires_in_hours: Session expiration in hours

        Returns:
            The created session
        """
        session_token = secrets.token_urlsafe(32)
        expires_at = utc_now() + timedelta(hours=expires_in_hours)

        session = UserSession(user_id=user.id, session_token=session_token, expires_at=expires_at, ip_address=ip_address, user_agent=user_agent, is_active=True)

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session

    async def get_user_teams(self, user_id: str) -> List[Dict]:
        """
        Get teams that a user belongs to.

        Args:
            user_id: ID of the user

        Returns:
            List of team information with roles
        """
        memberships = self.db.query(TeamMember).filter(TeamMember.user_id == user_id).all()

        teams = []
        for membership in memberships:
            team = membership.team
            teams.append({"id": team.id, "name": team.name, "slug": team.slug, "role": membership.role, "joined_at": membership.joined_at})

        return teams

    async def ensure_admin_user_exists(
        self,
        username: str,
        password: str,
        full_name: str = "Default Admin User",
    ) -> User:
        """
        Ensure admin user exists, creating only if necessary.

        This method is idempotent and safe for concurrent calls.

        Args:
            username: Admin username
            password: Admin password
            full_name: Full name for the admin user

        Returns:
            User: The admin user (existing or newly created)

        Raises:
            Exception: If user creation fails or database error occurs
        """
        try:
            # First check if user already exists
            existing_user = self.db.query(User).filter(User.username == username).first()
            if existing_user:
                return existing_user

            # User doesn't exist, try to create it
            password_hash = PasswordPolicy.hash_password(password)

            user = User(
                username=username,
                password_hash=password_hash,
                email=None,
                full_name=full_name,
                is_admin=True,
                is_active=True,
                email_verified=False,
                failed_login_attempts=0,
            )

            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

            # Log successful creation
            await log_auth_event(
                db=self.db,
                event_type="admin_user_created",
                user_id=user.id,
                username=username,
                success=True,
                ip_address="127.0.0.1",
                user_agent="System Initialization",
                details={"created_at_startup": True},
            )

            return user

        except Exception as e:
            # If it's a unique constraint error, the user already exists
            if "UNIQUE constraint failed" in str(e):
                # Rollback and fetch the existing user
                self.db.rollback()
                existing_user = self.db.query(User).filter(User.username == username).first()
                if existing_user:
                    return existing_user

            # Re-raise other errors
            raise e


# Dependency to get user service
def get_user_service():
    """Dependency to get UserService with database session.

    Yields:
        UserService: User service instance with database session
    """
    db = SessionLocal()
    try:
        yield UserService(db)
    finally:
        db.close()
