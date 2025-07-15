# -*- coding: utf-8 -*-
"""MCP Gateway Centralized for Pydantic validation error, SQL exception.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti


"""

# Standard
import logging
from typing import Any, Dict

# Third-Party
from pydantic import ValidationError
from sqlalchemy.exc import DatabaseError, IntegrityError

logger = logging.getLogger(__name__)


class ErrorFormatter:
    """
    Transform technical errors into user-friendly messages.
    """

    @staticmethod
    def format_validation_error(error: ValidationError) -> Dict[str, Any]:
        """
        Convert Pydantic errors to user-friendly format.

        Args:
            error (ValidationError): The Pydantic validation error.

        Returns:
            Dict[str, Any]: A dictionary with formatted error details.
        """
        errors = []

        for err in error.errors():
            field = err.get("loc", ["field"])[-1]
            msg = err.get("msg", "Invalid value")

            # Map technical messages to user-friendly ones
            user_message = ErrorFormatter._get_user_message(field, msg)
            errors.append({"field": field, "message": user_message})

        # Log the full error for debugging
        logger.debug(f"Validation error: {error}")
        print(type(error))

        return {"message": "Validation failed", "details": errors, "success": False}

    @staticmethod
    def _get_user_message(field: str, technical_msg: str) -> str:
        """
        Map technical validation messages to user-friendly ones.

        Args:
            field (str): The field name.
            technical_msg (str): The technical validation message.

        Returns:
            str: User-friendly error message.
        """
        mappings = {
            "Tool name must start with a letter": f"{field.title()} must start with a letter and contain only letters, numbers, and underscores",
            "Tool name exceeds maximum length": f"{field.title()} is too long (maximum 255 characters)",
            "Tool URL must start with": f"{field.title()} must be a valid HTTP or WebSocket URL",
            "cannot contain directory traversal": f"{field.title()} contains invalid characters",
            "contains HTML tags": f"{field.title()} cannot contain HTML or script tags",
        }

        for pattern, friendly_msg in mappings.items():
            if pattern in technical_msg:
                return friendly_msg

        # Default fallback
        return f"Invalid {field}"

    @staticmethod
    def format_database_error(error: DatabaseError) -> Dict[str, Any]:
        """
        Convert database errors to user-friendly format.

        Args:
            error (DatabaseError): The database error.

        Returns:
            Dict[str, Any]: A dictionary with formatted error details.
        """
        error_str = str(error.orig) if hasattr(error, "orig") else str(error)

        # Log full error
        logger.error(f"Database error: {error}")

        # Map common database errors
        if isinstance(error, IntegrityError):
            if "UNIQUE constraint failed" in error_str:
                if "gateways.url" in error_str:
                    return {"message": "A gateway with this URL already exists", "success": False}
                elif "gateways.name" in error_str:
                    return {"message": "A gateway with this name already exists", "success": False}
                elif "tools.name" in error_str:
                    return {"message": "A tool with this name already exists", "success": False}
                elif "resources.uri" in error_str:
                    return {"message": "A resource with this URI already exists", "success": False}
            elif "FOREIGN KEY constraint failed" in error_str:
                return {"message": "Referenced item not found", "success": False}
            elif "NOT NULL constraint failed" in error_str:
                return {"message": "Required field is missing", "success": False}
            elif "CHECK constraint failed:" in error_str:
                return {"message": "Gateway validation failed. Please check the input data.", "success": False}

        # Generic database error
        return {"message": "Unable to complete the operation. Please try again.", "success": False}
