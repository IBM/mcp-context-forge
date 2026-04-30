# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/time_restrictions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Sebastian Iozu

Time restriction validation utilities for token access control.
This module provides functions to validate time-based access restrictions
on API tokens, ensuring tokens can only be used during specified time windows.
"""

# Standard
from datetime import datetime
import logging
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Third-Party
from fastapi import HTTPException, status

# Initialize logging
logger = logging.getLogger(__name__)

# Valid day names for day restrictions
VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


def validate_time_restrictions(payload: Dict[str, Any]) -> None:
    """Validate time restrictions from JWT token payload.

    Checks if the current time falls within the allowed time windows and days
    specified in the token's time_restrictions. Raises HTTPException if the
    token is being used outside of its allowed time periods.

    Time restrictions format in JWT payload:
    {
        "scopes": {
            "time_restrictions": {
                "start_time": "09:00",
                "end_time": "17:00",
                "timezone": "UTC",
                "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
            }
        }
    }

    Args:
        payload: Decoded JWT payload containing time_restrictions in scopes

    Raises:
        HTTPException: 403 if current time is outside allowed windows

    Examples:
        >>> payload = {
        ...     "sub": "user@example.com",
        ...     "scopes": {
        ...         "time_restrictions": {
        ...             "start_time": "09:00",
        ...             "end_time": "17:00",
        ...             "timezone": "UTC",
        ...             "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        ...         }
        ...     }
        ... }
        >>> # Will raise HTTPException if called outside business hours
        >>> # validate_time_restrictions(payload)
    """
    # Extract time restrictions from token scopes
    scopes = payload.get("scopes", {})
    if not isinstance(scopes, dict):
        return  # No restrictions to validate

    time_restrictions = scopes.get("time_restrictions", {})
    if not time_restrictions or not isinstance(time_restrictions, dict):
        return  # No time restrictions configured

    # Get restriction parameters
    start_time_str = time_restrictions.get("start_time")
    end_time_str = time_restrictions.get("end_time")
    timezone_str = time_restrictions.get("timezone", "UTC")
    allowed_days = time_restrictions.get("days", [])

    # If no restrictions are actually set, allow access
    if not (start_time_str or end_time_str or allowed_days):
        return

    # SECURITY: Type-validate all fields before processing.
    # Malformed types (e.g. start_time=123, days="Monday") would cause
    # TypeError in strptime/set operations; fail closed to prevent bypass.
    if (start_time_str is not None and not isinstance(start_time_str, str)) or (end_time_str is not None and not isinstance(end_time_str, str)):
        logger.warning(
            "Invalid type for start_time or end_time in time_restrictions",
            extra={
                "security_event": "time_restriction_validation_error",
                "error_type": "invalid_field_type",
                "user": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has invalid time restriction format: start_time and end_time must be strings",
        )

    if not isinstance(timezone_str, str):
        logger.warning(
            "Invalid type for timezone in time_restrictions",
            extra={
                "security_event": "time_restriction_validation_error",
                "error_type": "invalid_field_type",
                "user": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has invalid time restriction format: timezone must be a string",
        )

    if not isinstance(allowed_days, list) or not all(isinstance(d, str) for d in allowed_days):
        logger.warning(
            "Invalid type for days in time_restrictions",
            extra={
                "security_event": "time_restriction_validation_error",
                "error_type": "invalid_field_type",
                "user": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has invalid time restriction format: days must be a list of strings",
        )

    # SECURITY: Fail closed on half-configured time windows.
    # Only start_time or only end_time is malformed — deny to prevent bypass.
    if bool(start_time_str) != bool(end_time_str):
        logger.warning(
            f"Incomplete time window in time_restrictions: start_time={start_time_str!r}, end_time={end_time_str!r}",
            extra={
                "security_event": "time_restriction_validation_error",
                "error_type": "incomplete_time_window",
                "start_time": start_time_str,
                "end_time": end_time_str,
                "user": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has incomplete time restriction: both start_time and end_time are required",
        )

    # Validate day names if day restrictions are present
    if allowed_days:
        invalid_days = set(allowed_days) - VALID_DAYS
        if invalid_days:
            logger.warning(
                f"Invalid day names in time_restrictions: {invalid_days}",
                extra={
                    "security_event": "time_restriction_validation_error",
                    "error_type": "invalid_day_names",
                    "invalid_days": list(invalid_days),
                    "user": payload.get("sub"),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token has invalid day names in time restrictions: {', '.join(sorted(invalid_days))}",
            )

    # Get current time in the specified timezone
    try:
        tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            f"Invalid timezone in time_restrictions: {timezone_str}",
            extra={
                "security_event": "time_restriction_validation_error",
                "error_type": "invalid_timezone",
                "timezone": timezone_str,
                "user": payload.get("sub"),
            },
        )
        # SECURITY: Fail closed - deny access on invalid timezone to prevent bypass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token has invalid timezone in time restrictions: {timezone_str}",
        )

    now = datetime.now(tz)
    current_day = now.strftime("%A")  # e.g., "Monday", "Tuesday", etc.
    current_time = now.time()

    # Check day restriction
    if allowed_days and current_day not in allowed_days:
        logger.warning(
            f"Token access denied: current day '{current_day}' not in allowed days {allowed_days}",
            extra={
                "security_event": "time_restriction_violation",
                "violation_type": "day_restriction",
                "current_day": current_day,
                "allowed_days": allowed_days,
                "user": payload.get("sub"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token access is restricted to specific days. Current day: {current_day}. Allowed days: {', '.join(allowed_days)}",
        )

    # Check time range restriction
    if start_time_str and end_time_str:
        try:
            # Parse time strings (format: "HH:MM" or "HH:MM:SS")
            # Try HH:MM:SS first, then HH:MM as fallback
            start_time = None
            for fmt in ["%H:%M:%S", "%H:%M"]:
                try:
                    start_time = datetime.strptime(start_time_str, fmt).time()
                    break
                except ValueError:
                    continue

            if start_time is None:
                raise ValueError(f"Invalid start_time format: {start_time_str}")

            end_time = None
            for fmt in ["%H:%M:%S", "%H:%M"]:
                try:
                    end_time = datetime.strptime(end_time_str, fmt).time()
                    break
                except ValueError:
                    continue

            if end_time is None:
                raise ValueError(f"Invalid end_time format: {end_time_str}")

            # Handle time ranges that cross midnight
            if start_time <= end_time:
                # Normal range (e.g., 09:00 - 17:00)
                time_allowed = start_time <= current_time <= end_time
            else:
                # Range crosses midnight (e.g., 22:00 - 06:00)
                time_allowed = current_time >= start_time or current_time <= end_time

            if not time_allowed:
                logger.warning(
                    f"Token access denied: current time {current_time.strftime('%H:%M')} outside allowed range {start_time_str} - {end_time_str}",
                    extra={
                        "security_event": "time_restriction_violation",
                        "violation_type": "time_range_restriction",
                        "current_time": current_time.isoformat(),
                        "start_time": start_time_str,
                        "end_time": end_time_str,
                        "timezone": timezone_str,
                        "user": payload.get("sub"),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Token access is restricted to {start_time_str} - {end_time_str} {timezone_str}. Current time: {current_time.strftime('%H:%M')} {timezone_str}",
                )
        except ValueError as e:
            logger.error(
                f"Invalid time format in time_restrictions: {e}",
                extra={
                    "security_event": "time_restriction_validation_error",
                    "error_type": "invalid_time_format",
                    "start_time": start_time_str,
                    "end_time": end_time_str,
                    "user": payload.get("sub"),
                },
            )
            # SECURITY: Fail closed - deny access on parsing errors to prevent bypass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token has invalid time format in time restrictions: {e}",
            )
