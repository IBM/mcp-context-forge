# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/email_auth_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Email-Only Authentication Service.
Clean email-based authentication without username complexity.
"""

# Standard
from datetime import timedelta
import logging
import re
from typing import Dict, List, Optional

# Third-Party
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import utc_now
from mcpgateway.models_email_only import EmailUser, TrustedDomain
from mcpgateway.services.argon2_service import get_argon2_service
from mcpgateway.utils.auth_logging import log_auth_event

logger = logging.getLogger(__name__)


class EmailPasswordPolicy:
    """
    Configurable password policy for email-only authentication.
    Implements issue #426: Configurable Password and Secret Policy Engine.
    """

    @staticmethod
    def validate(password: str) -> List[str]:
        """
        Validate password against configurable policy.

        Args:
            password: Password to validate

        Returns:
            List[str]: List of validation errors (empty if valid)
        """
        errors = []

        # Length requirement
        min_length = getattr(settings, "password_min_length", 8)
        if len(password) < min_length:
            errors.append(f"Password must be at least {min_length} characters")

        # Character requirements (configurable)
        if getattr(settings, "password_require_uppercase", False):
            if not re.search(r"[A-Z]", password):
                errors.append("Password must contain uppercase letters")

        if getattr(settings, "password_require_lowercase", False):
            if not re.search(r"[a-z]", password):
                errors.append("Password must contain lowercase letters")

        if getattr(settings, "password_require_numbers", False):
            if not re.search(r"\d", password):
                errors.append("Password must contain numbers")

        if getattr(settings, "password_require_special", False):
            if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
                errors.append("Password must contain special characters")

        return errors


class EmailAuthService:
    """
    Email-only authentication service.
    """

    def __init__(self, db: Session):
        """Initialize with database session."""
        self.db = db
        self.argon2_service = get_argon2_service()

    async def create_user(
        self, email: str, password: str, full_name: Optional[str] = None, is_admin: bool = False, auth_provider: str = "local", email_verified: bool = False, created_by: Optional[str] = None
    ) -> EmailUser:
        """
        Create new user with email-only identity.

        Args:
            email: Email address (primary identifier)
            password: Plain text password
            full_name: Full name for display
            is_admin: Admin privileges flag
            auth_provider: Authentication provider ('local', 'github', 'google', etc.)
            email_verified: Whether email is already verified
            created_by: Email of user who created this account

        Returns:
            EmailUser: Created user

        Raises:
            HTTPException: If validation fails or email already exists
        """
        # Validate email format
        if not self.validate_email(email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address format")

        # Check if email already exists
        existing_user = self.db.query(EmailUser).filter(EmailUser.email == email).first()
        if existing_user:
            await log_auth_event(db=self.db, event_type="user_creation_failed", user_email=email, success=False, failure_reason="Email already exists")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email address already registered")

        # Validate password
        password_errors = EmailPasswordPolicy.validate(password)
        if password_errors:
            await log_auth_event(db=self.db, event_type="user_creation_failed", user_email=email, success=False, failure_reason=f"Password validation: {', '.join(password_errors)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Password validation failed: {'; '.join(password_errors)}")

        # Hash password
        password_hash = self.argon2_service.hash_password(password)

        # Create user
        user = EmailUser(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            is_admin=is_admin,
            is_active=True,
            auth_provider=auth_provider,
            email_verified_at=utc_now() if email_verified else None,
            failed_login_attempts=0,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # Log successful creation
        await log_auth_event(
            db=self.db, event_type="user_created", user_email=email, success=True, details={"full_name": full_name, "is_admin": is_admin, "auth_provider": auth_provider, "created_by": created_by}
        )

        logger.info(f"Email user created: {email} (Full name: {full_name})")
        return user

    async def authenticate_user(self, email: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Optional[EmailUser]:
        """
        Authenticate user by email and password.

        Args:
            email: Email address
            password: Plain text password
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            EmailUser: Authenticated user or None if authentication failed
        """
        # Find user by email
        user = self.db.query(EmailUser).filter(EmailUser.email == email).first()

        if not user:
            await log_auth_event(db=self.db, event_type="login_failed", user_email=email, success=False, failure_reason="User not found", ip_address=ip_address, user_agent=user_agent)
            return None

        # Check if account is active
        if not user.is_active:
            await log_auth_event(db=self.db, event_type="login_failed", user_email=email, success=False, failure_reason="Account inactive", ip_address=ip_address, user_agent=user_agent)
            return None

        # Check if account is locked
        if user.locked_until and user.locked_until > utc_now():
            await log_auth_event(db=self.db, event_type="login_failed", user_email=email, success=False, failure_reason="Account locked", ip_address=ip_address, user_agent=user_agent)
            return None

        # Verify password
        if not self.argon2_service.verify_password(password, user.password_hash):
            # Increment failed attempts
            user.failed_login_attempts += 1

            # Lock account if too many failed attempts
            max_attempts = getattr(settings, "max_failed_login_attempts", 5)
            if user.failed_login_attempts >= max_attempts:
                lockout_duration = getattr(settings, "account_lockout_duration_minutes", 30)
                user.locked_until = utc_now() + timedelta(minutes=lockout_duration)
                logger.warning(f"Account locked for {email} due to {max_attempts} failed attempts")

            self.db.commit()

            await log_auth_event(db=self.db, event_type="login_failed", user_email=email, success=False, failure_reason="Invalid password", ip_address=ip_address, user_agent=user_agent)
            return None

        # Successful authentication
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = utc_now()

        # Check if password needs rehashing (bcrypt -> Argon2id)
        if self.argon2_service.needs_rehash(user.password_hash):
            user.password_hash = self.argon2_service.hash_password(password)
            user.password_hash_type = "argon2id"
            logger.info(f"Password rehashed to Argon2id for user: {email}")

        self.db.commit()

        await log_auth_event(db=self.db, event_type="login_success", user_email=email, success=True, ip_address=ip_address, user_agent=user_agent)

        return user

    async def get_user_by_email(self, email: str) -> Optional[EmailUser]:
        """Get user by email address."""
        return self.db.query(EmailUser).filter(EmailUser.email == email).first()

    async def list_users(self, skip: int = 0, limit: int = 100, search: Optional[str] = None, is_active: Optional[bool] = None, auth_provider: Optional[str] = None) -> List[EmailUser]:
        """
        List users with email-only identity.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            search: Search term for email or full_name
            is_active: Filter by active status
            auth_provider: Filter by authentication provider

        Returns:
            List[EmailUser]: List of users
        """
        query = self.db.query(EmailUser)

        if search:
            search_term = f"%{search}%"
            query = query.filter(or_(EmailUser.email.ilike(search_term), EmailUser.full_name.ilike(search_term)))

        if is_active is not None:
            query = query.filter(EmailUser.is_active.is_(is_active))

        if auth_provider:
            query = query.filter(EmailUser.auth_provider == auth_provider)

        return query.offset(skip).limit(limit).all()

    async def update_user(
        self, email: str, full_name: Optional[str] = None, is_active: Optional[bool] = None, is_admin: Optional[bool] = None, updated_by: Optional[str] = None
    ) -> Optional[EmailUser]:
        """Update user information."""
        user = await self.get_user_by_email(email)
        if not user:
            return None

        changes = {}
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
        await log_auth_event(db=self.db, event_type="user_updated", user_email=email, success=True, details={"updated_by": updated_by, "changes": changes})

        return user

    async def change_password(self, email: str, current_password: str, new_password: str, ip_address: Optional[str] = None) -> bool:
        """
        Change user password.

        Args:
            email: User email
            current_password: Current password for verification
            new_password: New password
            ip_address: Client IP address

        Returns:
            bool: True if password changed successfully
        """
        user = await self.get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Verify current password
        if not self.argon2_service.verify_password(current_password, user.password_hash):
            await log_auth_event(db=self.db, event_type="password_change_failed", user_email=email, success=False, failure_reason="Invalid current password", ip_address=ip_address)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

        # Validate new password
        password_errors = EmailPasswordPolicy.validate(new_password)
        if password_errors:
            await log_auth_event(
                db=self.db, event_type="password_change_failed", user_email=email, success=False, failure_reason=f"New password validation: {', '.join(password_errors)}", ip_address=ip_address
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"New password validation failed: {'; '.join(password_errors)}")

        # Update password
        user.password_hash = self.argon2_service.hash_password(new_password)
        user.password_hash_type = "argon2id"
        user.updated_at = utc_now()
        user.failed_login_attempts = 0
        user.locked_until = None

        self.db.commit()

        await log_auth_event(db=self.db, event_type="password_changed", user_email=email, success=True, ip_address=ip_address, details={"password_hash_type": "argon2id"})

        logger.info(f"Password changed for user: {email}")
        return True

    def validate_email(self, email: str) -> bool:
        """
        Validate email address format.

        Args:
            email: Email address to validate

        Returns:
            bool: True if email is valid
        """
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(email_pattern, email))

    async def check_domain_approval(self, email: str) -> Dict[str, any]:
        """
        Check if email domain should be auto-approved.

        Args:
            email: Email address to check

        Returns:
            Dict: Approval status and details
        """
        domain = "@" + email.split("@")[1].lower()

        # Check trusted domains
        trusted_domain = self.db.query(TrustedDomain).filter(TrustedDomain.domain == domain, TrustedDomain.is_active.is_(True)).first()

        if trusted_domain and trusted_domain.auto_approve:
            return {"auto_approve": True, "domain": domain, "sso_provider": trusted_domain.sso_provider, "reason": "Trusted domain"}

        # Check configuration-based auto-approval
        auto_approve_domains = getattr(settings, "auto_approve_domains", [])
        if domain in auto_approve_domains:
            return {"auto_approve": True, "domain": domain, "reason": "Configuration auto-approval"}

        return {"auto_approve": False, "domain": domain, "requires_approval": True, "reason": "Domain not in trusted list"}


def get_email_auth_service(db: Session) -> EmailAuthService:
    """Get email authentication service with database session."""
    return EmailAuthService(db)
