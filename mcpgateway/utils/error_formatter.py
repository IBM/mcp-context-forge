# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/error_formatter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway Centralized for Pydantic validation error, SQL exception.
This module provides centralized error formatting for the MCP Gateway,
transforming technical Pydantic validation errors and SQLAlchemy database
exceptions into user-friendly messages suitable for API responses.

The ErrorFormatter class handles:
- Pydantic ValidationError formatting
- SQLAlchemy DatabaseError and IntegrityError formatting
- Mapping technical error messages to user-friendly explanations
- Consistent error response structure

Examples:
    >>> from mcpgateway.utils.error_formatter import ErrorFormatter
    >>> from pydantic import ValidationError
    >>>
    >>> # Format validation errors
    >>> formatter = ErrorFormatter()
    >>> # formatted_error = formatter.format_validation_error(validation_error)
"""

# Standard
from typing import Any, Dict

# Third-Party
from pydantic import ValidationError
from sqlalchemy.exc import DatabaseError, IntegrityError

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ErrorFormatter:
    """Transform technical errors into user-friendly messages.

    Provides static methods to convert Pydantic validation errors and
    SQLAlchemy database exceptions into consistent, user-friendly error
    responses suitable for API consumption.

    Examples:
        >>> formatter = ErrorFormatter()
        >>> isinstance(formatter, ErrorFormatter)
        True
    """

    @staticmethod
    def format_validation_error(error: ValidationError) -> Dict[str, Any]:
        """Convert Pydantic errors to user-friendly format.

        Transforms Pydantic ValidationError objects into a structured
        dictionary containing user-friendly error messages. Maps technical
        validation messages to more understandable explanations.

        Args:
            error (ValidationError): The Pydantic validation error to format

        Returns:
            Dict[str, Any]: A dictionary with formatted error details containing:
                - message: General error description
                - details: List of field-specific errors
                - success: Always False for errors

        Examples:
            >>> from pydantic import BaseModel, ValidationError, field_validator
            >>> # Create a test model with validation
            >>> class TestModel(BaseModel):
            ...     name: str
            ...     @field_validator('name')
            ...     def validate_name(cls, v):
            ...         if not v.startswith('A'):
            ...             raise ValueError('Tool name must start with a letter A')
            ...         return v
            >>> # Test validation error formatting
            >>> try:
            ...     TestModel(name="B123")
            ... except ValidationError as e:
            ...     print(type(e))
            ...     result = ErrorFormatter.format_validation_error(e)
            <class 'pydantic_core._pydantic_core.ValidationError'>
            >>> result['message']
            'Validation failed: Name must start with a letter and contain only letters, numbers, and underscores'
            >>> result['success']
            False
            >>> len(result['details']) > 0
            True
            >>> result['details'][0]['field']
            'name'
            >>> 'must start with a letter' in result['details'][0]['message']
            True

            >>> # Test with multiple errors
            >>> class MultiFieldModel(BaseModel):
            ...     name: str
            ...     url: str
            ...     @field_validator('name')
            ...     def validate_name(cls, v):
            ...         if len(v) > 255:
            ...             raise ValueError('Tool name exceeds maximum length')
            ...         return v
            ...     @field_validator('url')
            ...     def validate_url(cls, v):
            ...         if not v.startswith('http'):
            ...             raise ValueError('Tool URL must start with http')
            ...         return v
            >>>
            >>> try:
            ...     MultiFieldModel(name='A' * 300, url='ftp://invalid')
            ... except ValidationError as e:
            ...     print(type(e))
            ...     result = ErrorFormatter.format_validation_error(e)
            <class 'pydantic_core._pydantic_core.ValidationError'>
            >>> len(result['details'])
            2
            >>> any('too long' in detail['message'] for detail in result['details'])
            True
            >>> any('valid HTTP' in detail['message'] for detail in result['details'])
            True
        """
        errors = []

        for err in error.errors():
            loc = err.get("loc", ["field"])
            field = loc[-1] if loc else "field"
            msg = err.get("msg", "Invalid value")

            # Map technical messages to user-friendly ones
            user_message = ErrorFormatter._get_user_message(field, msg)
            errors.append({"field": field, "message": user_message})

        # Log the full error for debugging
        logger.debug(f"Validation error: {error}")

        return {"message": f"Validation failed: {user_message}", "details": errors, "success": False}

    @staticmethod
    def _get_user_message(field: str, technical_msg: str) -> str:
        """Map technical validation messages to user-friendly ones.

        Converts technical validation error messages into user-friendly
        explanations based on pattern matching. Provides field-specific
        context in the returned message.

        Args:
            field (str): The field name that failed validation
            technical_msg (str): The technical validation message from Pydantic

        Returns:
            str: User-friendly error message with field context

        Examples:
            >>> # Test letter requirement mapping
            >>> msg = ErrorFormatter._get_user_message("name", "Tool name must start with a letter")
            >>> msg
            'Name must start with a letter and contain only letters, numbers, and underscores'

            >>> # Test length validation mapping
            >>> msg = ErrorFormatter._get_user_message("description", "Tool name exceeds maximum length")
            >>> msg
            'Description is too long (maximum 255 characters)'

            >>> # Test URL validation mapping
            >>> msg = ErrorFormatter._get_user_message("endpoint", "Tool URL must start with http")
            >>> msg
            'Endpoint must be a valid HTTP or WebSocket URL'

            >>> # Test directory traversal validation
            >>> msg = ErrorFormatter._get_user_message("path", "cannot contain directory traversal")
            >>> msg
            'Path contains invalid characters'

            >>> # Test HTML injection validation
            >>> msg = ErrorFormatter._get_user_message("content", "contains HTML tags")
            >>> msg
            'Content cannot contain HTML or script tags'

            >>> # Test fallback for unknown messages
            >>> msg = ErrorFormatter._get_user_message("custom_field", "Some unknown error")
            >>> msg
            'Invalid custom_field'
        """
        mappings = {
            "Tool name must start with a letter": f"{field.title()} must start with a letter and contain only letters, numbers, and underscores",
            "Tool name exceeds maximum length": f"{field.title()} is too long (maximum 255 characters)",
            "Tool URL must start with": f"{field.title()} must be a valid HTTP or WebSocket URL",
            "cannot contain directory traversal": f"{field.title()} contains invalid characters",
            "contains HTML tags": f"{field.title()} cannot contain HTML or script tags",
            "Server ID must be a valid UUID format": f"{field.title()} must be a valid UUID",
        }

        for pattern, friendly_msg in mappings.items():
            if pattern in technical_msg:
                return friendly_msg

        # Default fallback
        return f"Invalid {field}"

    @staticmethod
    def format_database_error(error: DatabaseError) -> Dict[str, Any]:
        """Convert database errors to user-friendly format.

        Transforms SQLAlchemy database exceptions into structured error
        responses. Handles common integrity constraint violations and
        provides specific messages for known error patterns.

        Args:
            error (DatabaseError): The SQLAlchemy database error to format

        Returns:
            Dict[str, Any]: A dictionary with formatted error details containing:
                - message: User-friendly error description
                - success: Always False for errors

        Examples:
            >>> from unittest.mock import Mock
            >>>
            >>> # Test UNIQUE constraint on gateway URL
            >>> mock_error = Mock(spec=IntegrityError)
            >>> mock_error.orig = Mock()
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: gateways.url"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A gateway with this URL already exists'
            >>> result['success']
            False

            >>> # Test UNIQUE constraint on gateway slug
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: gateways.slug"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A gateway with this name already exists'

            >>> # Test UNIQUE constraint on tool name
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: tools.name"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A tool with this name already exists'

            >>> # Test UNIQUE constraint on resource URI
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: resources.uri"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A resource with this URI already exists'

            >>> # Test UNIQUE constraint on server name
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: servers.name"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A server with this name already exists'

            >>> # Test UNIQUE constraint on prompt name
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: prompts.name"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A prompt with this name already exists'

            >>> # Test FOREIGN KEY constraint
            >>> mock_error.orig.__str__ = lambda self: "FOREIGN KEY constraint failed"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'Referenced item not found'

            >>> # Test NOT NULL constraint
            >>> mock_error.orig.__str__ = lambda self: "NOT NULL constraint failed"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'Required field is missing'

            >>> # Test CHECK constraint
            >>> mock_error.orig.__str__ = lambda self: "CHECK constraint failed: invalid_data"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'Validation failed. Please check the input data.'

            >>> # Test generic database error
            >>> generic_error = Mock(spec=DatabaseError)
            >>> generic_error.orig = None
            >>> result = ErrorFormatter.format_database_error(generic_error)
            >>> result['message']
            'Unable to complete the operation. Please try again.'
            >>> result['success']
            False
        """
        error_str = str(error.orig) if hasattr(error, "orig") else str(error)

        # Log full error
        logger.error(f"Database error: {error}")

        # Map common database errors
        if isinstance(error, IntegrityError):
            if "UNIQUE constraint failed" in error_str:
                if "gateways.url" in error_str:
                    return {"message": "A gateway with this URL already exists", "success": False}
                elif "gateways.slug" in error_str:
                    return {"message": "A gateway with this name already exists", "success": False}
                elif "tools.name" in error_str:
                    return {"message": "A tool with this name already exists", "success": False}
                elif "resources.uri" in error_str:
                    return {"message": "A resource with this URI already exists", "success": False}
                elif "servers.name" in error_str:
                    return {"message": "A server with this name already exists", "success": False}
                elif "prompts.name" in error_str:
                    return {"message": "A prompt with this name already exists", "success": False}
                elif "servers.id" in error_str:
                    return {"message": "A server with this ID already exists", "success": False}

            elif "FOREIGN KEY constraint failed" in error_str:
                return {"message": "Referenced item not found", "success": False}
            elif "NOT NULL constraint failed" in error_str:
                return {"message": "Required field is missing", "success": False}
            elif "CHECK constraint failed:" in error_str:
                return {"message": "Validation failed. Please check the input data.", "success": False}

        # Generic database error
        return {"message": "Unable to complete the operation. Please try again.", "success": False}
