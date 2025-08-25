# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/auth_logging.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Authentication Event Logging Utilities.
Provides shared utilities for logging authentication events across services.
"""

# Standard
import logging
from typing import Dict, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuthEvent

logger = logging.getLogger(__name__)


async def log_auth_event(
    db: Session,
    event_type: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    success: bool = True,
    failure_reason: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[Dict] = None,
):
    """Log authentication event for audit purposes.

    Args:
        db: Database session
        event_type: Type of authentication event
        user_id: User ID if known
        username: Username if known
        success: Whether the event was successful
        failure_reason: Reason for failure if applicable
        ip_address: Client IP address
        user_agent: Client user agent
        details: Additional event details
    """
    if not settings.enable_auth_logging:
        return

    event = AuthEvent(
        user_id=user_id,
        username=username,
        event_type=event_type,
        success=success,
        failure_reason=failure_reason,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )

    db.add(event)
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log auth event: {e}")
        db.rollback()
