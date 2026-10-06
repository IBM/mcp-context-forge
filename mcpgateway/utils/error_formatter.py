# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/error_formatter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

ContextForge Centralized for Pydantic validation error, SQL exception.
This module provides centralized error formatting for ContextForge,
transforming technical Pydantic validation errors and SQLAlchemy database
exceptions into user-friendly messages suitable for API responses.

The ErrorFormatter class handles:
- Pydantic ValidationError formatting
- FastAPI RequestValidationError formatting (request-body parsing)
- SQLAlchemy DatabaseError and IntegrityError formatting
- Mapping technical error messages to user-friendly explanations
- Consistent error response structure

Policy: HTTP responses never carry raw exception text. Known error kinds
(validation, database constraints) get a specific, user-actionable message
built from a fixed vocabulary; anything else gets a generic fallback. Full
technical detail is logged server-side only. There is no runtime switch that
re-enables raw text in responses.

Examples:
    >>> from mcpgateway.utils.error_formatter import ErrorFormatter
    >>> from pydantic import ValidationError
    >>>
    >>> # Format validation errors
    >>> formatter = ErrorFormatter()
    >>> # formatted_error = formatter.format_validation_error(validation_error)
"""

# Standard
from typing import Any, Dict, List, Union

# Third-Party
from pydantic import ValidationError
from sqlalchemy.exc import DatabaseError, IntegrityError

# First-Party
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.correlation_id import get_correlation_id

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

    # Pydantic error types whose default message embeds Python-level detail
    # (a model/class name, or the text of an arbitrary underlying exception).
    # For these the message is replaced by a neutral "Invalid <field>".
    _UNSAFE_MESSAGE_TYPES = frozenset(
        {
            "model_type",
            "model_attributes_type",
            "dataclass_type",
            "dataclass_exact_type",
            "is_instance_of",
            "is_subclass_of",
            "get_attribute_error",
            "iteration_error",
            "mapping_type",
        }
    )

    # Pydantic prefixes a custom validator's own message with the error kind.
    _CUSTOM_MSG_PREFIXES = ("Value error, ", "Assertion failed, ")

    @staticmethod
    def format_validation_error(error: Any) -> Dict[str, Any]:
        """Convert Pydantic errors to user-friendly format.

        Transforms a Pydantic ``ValidationError`` (or any object exposing a
        Pydantic-style ``errors()`` method, such as FastAPI's
        ``RequestValidationError``) into a structured dictionary of
        user-friendly, field-level messages. The output never contains the
        model class name, the Pydantic version/docs URL, or the submitted
        input value.

        Args:
            error: The validation error to format

        Returns:
            Dict[str, Any]: ``{"message": str, "detail": str, "details": [{"field": str, "message": str}, ...], "success": False}``.
                ``message`` and ``detail`` carry the same one-line summary; ``detail`` is
                kept for clients that read the FastAPI-style key.

        Examples:
            >>> from pydantic import BaseModel
            >>> class M(BaseModel):
            ...     count: int
            >>> try:
            ...     M(count="lots")
            ... except ValidationError as e:
            ...     out = ErrorFormatter.format_validation_error(e)
            >>> out["success"]
            False
            >>> out["details"][0]["field"]
            'count'
            >>> "pydantic" in out["message"].lower() or "input_value" in out["message"]
            False
        """
        # Log only loc/type — never msg, ctx, input, or input_value (Pydantic v2 includes input_value in str())
        logger.warning("Validation error: %s", sanitize_validation_error_for_log(error))

        details: List[Dict[str, str]] = []
        for err in error.errors():
            loc = err.get("loc") or ()
            field = str(loc[-1]) if loc else "field"
            user_message = ErrorFormatter._get_user_message(field, err.get("msg", "Invalid value"), err.get("type", ""))
            details.append({"field": field, "message": user_message})

        summary = "; ".join(d["message"] for d in details) if details else "Validation error"
        message = f"Validation failed: {summary}"
        return {"message": message, "detail": message, "details": details, "success": False}

    @staticmethod
    def format_request_validation_error(error: Any) -> List[Dict[str, Any]]:
        """Build a FastAPI-shaped, sanitized error list for request-parsing failures.

        Keeps the standard ``{"type", "loc", "msg"}`` entries API clients expect
        from a FastAPI 422 response, but drops the fields that leak detail:
        ``input`` (echoes the submitted value), ``url`` (embeds the Pydantic
        version), and any non-primitive ``ctx`` entries (exception objects).
        Messages for error types that embed class names are neutralised.

        Args:
            error: A FastAPI ``RequestValidationError`` or any object with a Pydantic-style ``errors()`` method

        Returns:
            List[Dict[str, Any]]: Sanitized error entries suitable for ``{"detail": [...]}``

        Examples:
            >>> from pydantic import BaseModel
            >>> class M(BaseModel):
            ...     count: int
            >>> try:
            ...     M(count="lots")
            ... except ValidationError as e:
            ...     out = ErrorFormatter.format_request_validation_error(e)
            >>> sorted(out[0].keys())
            ['loc', 'msg', 'type']
            >>> out[0]["loc"]
            ['count']
        """
        entries: List[Dict[str, Any]] = []
        for err in error.errors():
            loc = list(err.get("loc") or ())
            field = str(loc[-1]) if loc else "field"
            err_type = err.get("type", "value_error")
            entry: Dict[str, Any] = {
                "type": err_type,
                "loc": loc,
                "msg": ErrorFormatter._safe_pydantic_message(field, err.get("msg", "Invalid value"), err_type),
            }
            ctx = err.get("ctx")
            if isinstance(ctx, dict):
                safe_ctx = {k: v for k, v in ctx.items() if v is None or isinstance(v, (str, int, float, bool))}
                if safe_ctx:
                    entry["ctx"] = safe_ctx
            entries.append(entry)
        return entries

    @staticmethod
    def _safe_pydantic_message(field: str, technical_msg: str, error_type: str) -> str:
        """Return a Pydantic error message with Python-level detail removed.

        Standard Pydantic messages ("Input should be a valid integer") are
        fixed library strings and are passed through. Messages for the types in
        ``_UNSAFE_MESSAGE_TYPES`` embed a class name or an arbitrary exception
        text and are replaced with a neutral message.

        Args:
            field: Field name, used for the neutral replacement
            technical_msg: The Pydantic ``msg`` value
            error_type: The Pydantic ``type`` value

        Returns:
            str: A message safe to place in an HTTP response

        Examples:
            >>> ErrorFormatter._safe_pydantic_message("count", "Input should be a valid integer", "int_type")
            'Input should be a valid integer'
            >>> ErrorFormatter._safe_pydantic_message("cfg", "Input should be a valid dictionary or instance of GatewayCreate", "model_type")
            'Invalid cfg'
        """
        if error_type in ErrorFormatter._UNSAFE_MESSAGE_TYPES or not technical_msg:
            return f"Invalid {field}"
        return technical_msg

    @staticmethod
    def _get_user_message(field: str, technical_msg: str, error_type: str = "") -> str:
        """Map technical validation messages to user-friendly ones.

        Known project validator messages are mapped to a fixed friendly
        sentence. Other messages are passed through with Pydantic's
        "Value error, " prefix removed, unless the error type is one whose
        message embeds Python-level detail, in which case a neutral
        "Invalid <field>" is returned.

        Args:
            field (str): The field name that failed validation
            technical_msg (str): The technical validation message from Pydantic
            error_type (str): The Pydantic error ``type`` (e.g. ``value_error``, ``model_type``)

        Returns:
            str: User-friendly error message with field context

        Examples:
            >>> # Test letter requirement mapping
            >>> msg = ErrorFormatter._get_user_message("name", "Tool name must start with a letter, number, or underscore")
            >>> msg
            'Name must start with a letter, number, or underscore and contain only letters, numbers, periods, underscores, hyphens, and slashes'

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

            >>> # Unknown custom-validator messages pass through, minus Pydantic's prefix
            >>> ErrorFormatter._get_user_message("custom_field", "Value error, Some unknown error", "value_error")
            'Some unknown error'

            >>> # Error types that embed a class name are neutralised
            >>> ErrorFormatter._get_user_message("config", "Input should be a valid dictionary or instance of GatewayCreate", "model_type")
            'Invalid config'
        """
        mappings = {
            "Tool name must start with a letter, number, or underscore": f"{field.title()} must start with a letter, number, or underscore and contain only letters, numbers, periods, underscores, hyphens, and slashes",
            "Tool name exceeds maximum length": f"{field.title()} is too long (maximum 255 characters)",
            "Tool URL must start with": f"{field.title()} must be a valid HTTP or WebSocket URL",
            "cannot contain directory traversal": f"{field.title()} contains invalid characters",
            "contains HTML tags": f"{field.title()} cannot contain HTML or script tags",
            "Server ID must be a valid UUID format": f"{field.title()} must be a valid UUID",
        }

        for pattern, friendly_msg in mappings.items():
            if pattern in technical_msg:
                return friendly_msg

        if error_type in ErrorFormatter._UNSAFE_MESSAGE_TYPES:
            return f"Invalid {field}"

        msg = technical_msg
        for prefix in ErrorFormatter._CUSTOM_MSG_PREFIXES:
            if msg.startswith(prefix):
                msg = msg[len(prefix) :]
                break
        return msg or f"Invalid {field}"

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

            >>> # Test UNIQUE constraint on resource URI (SQLite)
            >>> mock_error.orig.__str__ = lambda self: "UNIQUE constraint failed: resources.uri"
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.'

            >>> # Test unique constraint on resource URI (PostgreSQL reports the constraint name)
            >>> mock_error.orig.__str__ = lambda self: 'duplicate key value violates unique constraint "uq_team_owner_gateway_uri_resource"'
            >>> result = ErrorFormatter.format_database_error(mock_error)
            >>> result['message']
            'A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.'

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
            # Token name uniqueness: check before generic UNIQUE handler so the specific message
            # takes priority. PostgreSQL reports the constraint name (either the db.py name or the
            # Alembic migration name); SQLite reports the column paths.
            if (
                "uq_email_api_tokens_user_name_team" in error_str
                or "uq_email_api_tokens_user_name" in error_str
                or "uq_email_api_tokens_user_name_global" in error_str
                or "uq_email_api_tokens_user_email_name" in error_str
                or ("email_api_tokens.user_email" in error_str and "email_api_tokens.name" in error_str)
            ):
                return {
                    "message": "A token with this name already exists for this user in the same team scope. Token names must be unique per user per team. Please choose a different name.",
                    "success": False,
                }
            # Resource URI uniqueness: check before the generic UNIQUE handler so the specific message
            # takes priority. PostgreSQL reports the constraint name ("duplicate key value violates
            # unique constraint \"...\""), which matches none of the SQLite-shaped column-path patterns
            # below. Only the URI is unique -- resource names are display labels and may repeat.
            if "uq_team_owner_gateway_uri_resource" in error_str or "uq_team_owner_uri_resource_local" in error_str:
                return {"message": "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.", "success": False}
            if "UNIQUE constraint failed" in error_str:
                if "gateways.url" in error_str:
                    return {"message": "A gateway with this URL already exists", "success": False}
                elif "gateways.slug" in error_str:
                    return {"message": "A gateway with this name already exists", "success": False}
                elif "tools.name" in error_str:
                    return {"message": "A tool with this name already exists", "success": False}
                elif "resources.uri" in error_str:
                    return {"message": "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.", "success": False}
                elif "servers.name" in error_str:
                    return {"message": "A server with this name already exists", "success": False}
                elif "prompts.name" in error_str:
                    return {"message": "A prompt with this name already exists", "success": False}
                elif "servers.id" in error_str:
                    return {"message": "A server with this ID already exists", "success": False}
                elif "a2a_agents.slug" in error_str:
                    return {"message": "An A2A agent with this name already exists", "success": False}

            elif "FOREIGN KEY constraint failed" in error_str:
                return {"message": "Referenced item not found", "success": False}
            elif "NOT NULL constraint failed" in error_str:
                return {"message": "Required field is missing", "success": False}
            elif "CHECK constraint failed:" in error_str:
                return {"message": "Validation failed. Please check the input data.", "success": False}

        # Generic database error
        return {"message": "Unable to complete the operation. Please try again.", "success": False}


def sanitize_validation_error_for_log(error: Union[ValidationError, Any]) -> str:
    """Return a safe log summary of a Pydantic ValidationError.

    Includes only error count, loc, and type — never msg, ctx, input, or input_value,
    which can contain user-submitted data in Pydantic v2 (input_value=...).

    Args:
        error: A Pydantic ValidationError (or any object with an .errors() method).

    Returns:
        str: A safe log string, e.g. "2 error(s): [loc=('name',) type=value_error] [loc=('url',) type=url_error]"
    """
    try:
        raw_errors: List[Dict[str, Any]] = error.errors()
    except Exception:
        return "validation error (could not extract detail)"

    parts = [f"[loc={err.get('loc', ())} type={err.get('type', 'unknown')}]" for err in raw_errors]
    return f"{len(raw_errors)} error(s): {' '.join(parts)}"


UNEXPECTED_ERROR_MESSAGE = "An unexpected error occurred"


def _is_project_exception(exception: BaseException) -> bool:
    """Return True when the exception type is defined inside the mcpgateway package.

    Project exception classes (``ToolNotFoundError``, ``GatewayConnectionError``,
    ``PublicValidationError`` ...) carry messages written in this codebase, so their
    text is safe to show. Built-in and third-party exceptions carry whatever the
    library put there.

    Args:
        exception: The exception to classify

    Returns:
        bool: True for mcpgateway-defined exception types

    Examples:
        >>> _is_project_exception(PublicValidationError("x"))
        True
        >>> _is_project_exception(ValueError("x"))
        False
    """
    return isinstance(exception, PublicValidationError) or type(exception).__module__.startswith("mcpgateway.")


def _with_reference(message: str) -> str:
    """Append the current request's correlation ID so the user can quote it to support.

    Args:
        message: The user-safe message

    Returns:
        str: ``message`` plus `` (reference: <id>)`` when a correlation ID is set

    Examples:
        >>> _with_reference("Something failed")  # no request context in doctests
        'Something failed'
    """
    correlation_id = get_correlation_id()
    return f"{message} (reference: {correlation_id})" if correlation_id else message


def safe_error_detail(exception: Exception, fallback: str = "Invalid request. Please check your input and try again.") -> str:
    """Return a safe message for an HTTP response in place of raw exception text.

    This is the single point of policy for "what do we say about this exception?":

    - A project-defined exception (see ``_is_project_exception``) carries a message
      written in this codebase, so that message is returned as-is.
    - Anything else (built-in or third-party) may carry library versions, class
      names, database schema names or upstream error bodies, so ``fallback`` is
      returned instead, with the request correlation ID appended for traceability.
      The exception type is logged at debug level; callers log the full exception
      themselves.

    Args:
        exception: The exception being reported
        fallback: The generic, user-safe message for non-project exceptions

    Returns:
        str: A message safe to place in an HTTP response

    Examples:
        >>> safe_error_detail(ValueError("UNIQUE constraint failed: tools.name"), "Could not save the tool.")
        'Could not save the tool.'
        >>> safe_error_detail(RuntimeError("boom"))
        'Invalid request. Please check your input and try again.'
        >>> safe_error_detail(PublicValidationError("Token expiration cannot exceed 365 days"))
        'Token expiration cannot exceed 365 days'
    """
    if _is_project_exception(exception) and str(exception):
        return str(exception)
    logger.debug("Suppressed %s detail in HTTP response", type(exception).__name__)
    return _with_reference(fallback)


def unexpected_error_detail(exception: Exception) -> str:
    """Return the message for an exception caught by a catch-all handler.

    Shorthand for ``safe_error_detail(exception, UNEXPECTED_ERROR_MESSAGE)``: project
    exceptions keep their message, everything else becomes
    ``"An unexpected error occurred (reference: <correlation id>)"``.

    Args:
        exception: The exception caught by ``except Exception``

    Returns:
        str: A message safe to place in an HTTP response

    Examples:
        >>> unexpected_error_detail(KeyError("secret_column"))
        'An unexpected error occurred'
    """
    return safe_error_detail(exception, UNEXPECTED_ERROR_MESSAGE)


class PublicValidationError(ValueError):
    """Marker class for ValueError whose str() is intentionally safe to expose.

    Opt-in sub-class of ValueError whose message is user-actionable and safe
    to expose in production. Routers catch it before the generic ValueError
    branch and pass str(e) through unsanitised.

    Examples:
        >>> err = PublicValidationError("Token expiration cannot exceed 365 days")
        >>> str(err)
        'Token expiration cannot exceed 365 days'
        >>> isinstance(err, ValueError)
        True
    """
