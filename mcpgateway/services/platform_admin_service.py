# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/platform_admin_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Platform Admin Bootstrap Service.
Creates initial admin user from .env configuration.
"""

# Standard
import logging
from typing import Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.models_email_only import EmailUser
from mcpgateway.services.argon2_service import get_argon2_service
from mcpgateway.utils.auth_logging import log_auth_event

logger = logging.getLogger(__name__)


class PlatformAdminService:
    """
    Service to bootstrap platform admin from environment configuration.
    """

    def __init__(self, db: Session):
        """Initialize with database session."""
        self.db = db
        self.argon2_service = get_argon2_service()

    async def ensure_platform_admin_exists(self) -> Optional[EmailUser]:
        """
        Ensure platform admin exists, creating from .env if necessary.

        Returns:
            EmailUser: The platform admin user

        Raises:
            ValueError: If required environment variables are missing
        """
        # Get platform admin configuration from .env
        admin_email = getattr(settings, "platform_admin_email", None)
        admin_password = getattr(settings, "platform_admin_password", None)
        admin_full_name = getattr(settings, "platform_admin_full_name", "Platform Administrator")

        if not admin_email:
            logger.warning("PLATFORM_ADMIN_EMAIL not set in .env - no platform admin will be created")
            return None

        if not admin_password:
            logger.warning("PLATFORM_ADMIN_PASSWORD not set in .env - no platform admin will be created")
            return None

        # Check if admin already exists
        existing_admin = self.db.query(EmailUser).filter(EmailUser.email == admin_email).first()
        if existing_admin:
            logger.info(f"Platform admin already exists: {admin_email}")
            return existing_admin

        # Create platform admin
        try:
            password_hash = self.argon2_service.hash_password(admin_password)

            admin_user = EmailUser(
                email=admin_email,
                password_hash=password_hash,
                full_name=admin_full_name,
                is_admin=True,
                is_active=True,
                email_verified_at=None,  # Platform admin auto-verified
                auth_provider="platform",
            )

            self.db.add(admin_user)
            self.db.commit()
            self.db.refresh(admin_user)

            # Log admin creation
            await log_auth_event(
                db=self.db,
                event_type="platform_admin_created",
                user_email=admin_email,
                success=True,
                ip_address="127.0.0.1",
                user_agent="Platform Bootstrap",
                details={"full_name": admin_full_name, "created_from_env": True},
            )

            logger.info(f"Platform admin created: {admin_email}")
            return admin_user

        except Exception as e:
            logger.error(f"Failed to create platform admin: {e}")
            self.db.rollback()
            raise

    async def get_platform_admin(self) -> Optional[EmailUser]:
        """Get the platform admin user."""
        admin_email = getattr(settings, "platform_admin_email", None)
        if not admin_email:
            return None

        return self.db.query(EmailUser).filter(EmailUser.email == admin_email).first()

    async def update_platform_admin_password(self, new_password: str) -> bool:
        """
        Update platform admin password.

        Args:
            new_password: New password for platform admin

        Returns:
            bool: True if password updated successfully
        """
        admin = await self.get_platform_admin()
        if not admin:
            logger.error("Platform admin not found")
            return False

        try:
            admin.password_hash = self.argon2_service.hash_password(new_password)
            admin.password_hash_type = "argon2id"

            self.db.commit()

            await log_auth_event(db=self.db, event_type="platform_admin_password_changed", user_email=admin.email, success=True, details={"password_hash_type": "argon2id"})

            logger.info(f"Platform admin password updated: {admin.email}")
            return True

        except Exception as e:
            logger.error(f"Failed to update platform admin password: {e}")
            self.db.rollback()
            return False


def get_platform_admin_service(db: Session) -> PlatformAdminService:
    """Get platform admin service with database session."""
    return PlatformAdminService(db)
