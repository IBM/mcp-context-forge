# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/password_notification_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Password Expiration Notification Service.

This service handles sending notifications to users when their passwords
are approaching expiration. It can be run as a scheduled task or called
directly from admin interfaces.

Examples:
    >>> from mcpgateway.services.password_notification_service import PasswordNotificationService
    >>> from mcpgateway.db import SessionLocal
    >>> 
    >>> with SessionLocal() as db:
    ...     service = PasswordNotificationService(db)
    ...     # In async context:
    ...     # notifications_sent = await service.send_expiry_notifications()
"""

# Standard
import logging
from typing import Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.email_auth_service import EmailAuthService
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class PasswordNotificationService:
    """Service for managing password expiration notifications.
    
    This service provides functionality to check for users with expiring
    passwords and send notifications. In a production system, this would
    integrate with email services or other notification systems.
    
    Attributes:
        db (Session): Database session
        auth_service (EmailAuthService): Authentication service instance
    """

    def __init__(self, db: Session):
        """Initialize the notification service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.auth_service = EmailAuthService(db)

    async def send_expiry_notifications(self, notification_days: int = 14) -> int:
        """Send password expiry notifications to all eligible users.
        
        Args:
            notification_days: Number of days before expiry to send notification
            
        Returns:
            int: Number of notifications sent
            
        Examples:
            >>> service = PasswordNotificationService(db)
            >>> # notifications_sent = await service.send_expiry_notifications()
            >>> # notifications_sent >= 0  # Returns: True
        """
        try:
            notifications_sent = await self.auth_service.check_and_send_password_expiry_notifications(notification_days)
            logger.info(f"Password expiry notification check completed. Sent {notifications_sent} notifications.")
            return notifications_sent
            
        except Exception as e:
            logger.error(f"Error sending password expiry notifications: {e}")
            raise

    async def get_expiry_summary(self, notification_days: int = 14) -> dict:
        """Get a summary of password expiration status across all users.
        
        Args:
            notification_days: Number of days to consider "expiring soon"
            
        Returns:
            dict: Summary containing counts of expired, expiring, and total users
            
        Examples:
            >>> service = PasswordNotificationService(db)
            >>> # summary = await service.get_expiry_summary()
            >>> # isinstance(summary, dict)  # Returns: True
            >>> # "expired" in summary  # Returns: True
        """
        try:
            # Get users with expired passwords
            expired_users = await self.auth_service.get_users_with_expired_passwords()
            
            # Get users with expiring passwords
            expiring_users = await self.auth_service.get_users_with_expiring_passwords(notification_days)
            
            # Get total user count
            total_users = await self.auth_service.count_users()
            
            # Get active user count
            active_users = len(await self.auth_service.list_users(limit=10000))  # Simple way to get active count
            
            summary = {
                "total_users": total_users,
                "active_users": active_users,
                "expired_passwords": len(expired_users),
                "expiring_passwords": len(expiring_users),
                "notification_days": notification_days,
                "expired_user_emails": [user.email for user in expired_users[:10]],  # Limit to 10 for security
                "expiring_user_emails": [user.email for user in expiring_users[:10]]  # Limit to 10 for security
            }
            
            logger.debug(f"Password expiry summary: {summary}")
            return summary
            
        except Exception as e:
            logger.error(f"Error generating password expiry summary: {e}")
            raise

    async def send_notification_to_user(self, email: str) -> bool:
        """Send password expiry notification to a specific user.
        
        Args:
            email: User email address
            
        Returns:
            bool: True if notification was sent, False otherwise
            
        Examples:
            >>> service = PasswordNotificationService(db)
            >>> # success = await service.send_notification_to_user("user@example.com")
            >>> # isinstance(success, bool)  # Returns: True
        """
        try:
            user = await self.auth_service.get_user_by_email(email)
            if not user:
                logger.warning(f"User {email} not found for notification")
                return False
                
            if not user.is_active:
                logger.info(f"User {email} is inactive, skipping notification")
                return False
                
            if user.is_password_expired():
                logger.info(f"User {email} password already expired")
                return False
                
            if not user.is_password_expiring_soon():
                logger.info(f"User {email} password not expiring soon")
                return False
                
            if user.expiry_notification_sent:
                logger.info(f"User {email} already received notification")
                return False
                
            # Mark notification as sent
            user.expiry_notification_sent = True
            self.db.commit()
            
            days_remaining = user.days_until_password_expires()
            logger.info(f"Password expiry notification sent to {email}, expires in {days_remaining} days")
            
            # In a production system, this would send an actual email/notification
            # For now, we just log it and mark the flag
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending notification to {email}: {e}")
            return False

    async def reset_notification_flag(self, email: str) -> bool:
        """Reset the notification flag for a user (e.g., for testing or re-sending).
        
        Args:
            email: User email address
            
        Returns:
            bool: True if flag was reset, False otherwise
        """
        try:
            return await self.auth_service.reset_password_expiry_notification(email)
        except Exception as e:
            logger.error(f"Error resetting notification flag for {email}: {e}")
            return False