# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/csrf_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

CSRF Token Service.

Provides CSRF token generation and validation using HMAC-SHA256 with time-based
windows for token expiry. Implements constant-time comparison to prevent timing
attacks.

## Security Features

**Time-Window Based Tokens:**
- Tokens are valid for a configurable time window (default: 3600 seconds)
- Validation accepts current window and previous window (handles boundary cases)
- Timestamp is rounded to window boundaries for consistent token generation

**Constant-Time Comparison:**
- All token comparisons use `hmac.compare_digest()` to prevent timing attacks
- Never use `==` for token comparison

**Cookie Security:**
- HttpOnly=False (CSRF tokens must be readable by JavaScript)
- Secure flag configurable (HTTPS-only in production)
- SameSite configurable (Strict/Lax/None)
- Path set to "/" for site-wide coverage

## Token Format

Tokens are HMAC-SHA256 hex digests (64 characters) computed from:
```
message = f"{user_id}:{session_id}:{timestamp}"
timestamp = int(time.time() / expiry) * expiry  # Rounded to window boundary
token = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
```

## API Usage

**Generate Token:**
```python
token = generate_csrf_token(
    user_id="user@example.com",
    session_id="abc123",
    secret="my-secret-key",
    expiry=3600
)
```

**Validate Token:**
```python
is_valid = validate_csrf_token(
    token=token,
    user_id="user@example.com",
    session_id="abc123",
    secret="my-secret-key",
    expiry=3600
)
```

**Set Cookie:**
```python
from fastapi import Response
set_csrf_cookie(response, token, settings)
```

**Clear Cookie:**
```python
clear_csrf_cookie(response, settings)
```

## Error Handling

- `validate_csrf_token()` never raises exceptions
- Returns `False` on any error or validation failure
- Logs errors for debugging but maintains security through safe defaults
"""

# Standard
import hashlib
import hmac
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def generate_csrf_token(user_id: str, session_id: str, secret: str, expiry: int) -> str:
    """Generate a CSRF token using HMAC-SHA256.

    The token is computed from user_id, session_id, and a timestamp rounded to
    the expiry window boundary. This ensures the token remains valid for the
    entire window without storing the issue time.

    Args:
        user_id: User identifier (e.g., email address)
        session_id: Session identifier
        secret: Secret key for HMAC computation
        expiry: Token validity window in seconds

    Returns:
        str: HMAC-SHA256 hex digest (64 characters)

    Examples:
        >>> token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        >>> len(token)
        64
        >>> all(c in '0123456789abcdef' for c in token)
        True

        >>> # Tokens are deterministic within the same time window
        >>> t1 = generate_csrf_token("user1", "sess1", "key1", 3600)
        >>> t2 = generate_csrf_token("user1", "sess1", "key1", 3600)
        >>> t1 == t2
        True

        >>> # Different inputs produce different tokens
        >>> t1 = generate_csrf_token("user1", "sess1", "key1", 3600)
        >>> t2 = generate_csrf_token("user2", "sess1", "key1", 3600)
        >>> t1 != t2
        True
    """
    # Round timestamp to expiry window boundary
    timestamp = int(time.time() / expiry) * expiry

    # Construct message
    message = f"{user_id}:{session_id}:{timestamp}"

    # Compute HMAC-SHA256
    token = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    return token


def validate_csrf_token(token: str, user_id: str, session_id: str, secret: str, expiry: int) -> bool:
    """Validate a CSRF token using constant-time comparison.

    Validates the token against both the current time window and the previous
    time window. This handles tokens generated just before a window boundary.

    SECURITY: Uses `hmac.compare_digest()` for all comparisons to prevent
    timing attacks. Never raises exceptions - returns False on any error.

    Args:
        token: CSRF token to validate (64-character hex string)
        user_id: User identifier (must match token generation)
        session_id: Session identifier (must match token generation)
        secret: Secret key (must match token generation)
        expiry: Token validity window in seconds (must match token generation)

    Returns:
        bool: True if token is valid for current or previous window, False otherwise

    Examples:
        >>> # Generate and validate a token
        >>> token = generate_csrf_token("user@example.com", "session123", "secret", 3600)
        >>> validate_csrf_token(token, "user@example.com", "session123", "secret", 3600)
        True

        >>> # Wrong user_id fails validation
        >>> validate_csrf_token(token, "wrong@example.com", "session123", "secret", 3600)
        False

        >>> # Wrong session_id fails validation
        >>> validate_csrf_token(token, "user@example.com", "wrong_session", "secret", 3600)
        False

        >>> # Wrong secret fails validation
        >>> validate_csrf_token(token, "user@example.com", "session123", "wrong_secret", 3600)
        False

        >>> # Invalid token format fails validation
        >>> validate_csrf_token("invalid", "user@example.com", "session123", "secret", 3600)
        False

        >>> # Empty token fails validation
        >>> validate_csrf_token("", "user@example.com", "session123", "secret", 3600)
        False
    """
    try:
        # Validate token format (must be 64-character hex string)
        if not token or len(token) != 64:
            return False

        if not all(c in "0123456789abcdef" for c in token):
            return False

        # Compute expected token for current window
        current_timestamp = int(time.time() / expiry) * expiry
        current_message = f"{user_id}:{session_id}:{current_timestamp}"
        current_expected = hmac.new(secret.encode(), current_message.encode(), hashlib.sha256).hexdigest()

        # Check current window using constant-time comparison
        if hmac.compare_digest(token, current_expected):
            return True

        # Compute expected token for previous window
        previous_timestamp = current_timestamp - expiry
        previous_message = f"{user_id}:{session_id}:{previous_timestamp}"
        previous_expected = hmac.new(secret.encode(), previous_message.encode(), hashlib.sha256).hexdigest()

        # Check previous window using constant-time comparison
        if hmac.compare_digest(token, previous_expected):
            return True

        # Token doesn't match either window
        return False

    except Exception as e:
        # Log error but return False (never raise)
        logger.error("CSRF token validation error: %s", e)
        return False


def set_csrf_cookie(response: Any, token: str, settings: Any) -> None:
    """Set CSRF token cookie on response.

    Configures cookie with security settings from application settings:
    - httponly=False (CSRF tokens must be readable by JavaScript)
    - secure=settings.csrf_cookie_secure (HTTPS-only in production)
    - samesite=settings.csrf_cookie_samesite (Strict/Lax/None)
    - max_age=settings.csrf_token_expiry (cookie lifetime)
    - path="/" (site-wide coverage)

    Args:
        response: FastAPI Response object
        token: CSRF token to set in cookie
        settings: Application settings object with CSRF configuration

    Examples:
        >>> from unittest.mock import Mock
        >>> response = Mock()
        >>> settings = Mock(csrf_cookie_secure=True, csrf_cookie_samesite="Strict", csrf_token_expiry=3600)
        >>> set_csrf_cookie(response, "a" * 64, settings)
        >>> response.set_cookie.called
        True
        >>> call_kwargs = response.set_cookie.call_args[1]
        >>> call_kwargs['httponly']
        False
        >>> call_kwargs['secure']
        True
        >>> call_kwargs['samesite']
        'Strict'
        >>> call_kwargs['max_age']
        3600
        >>> call_kwargs['path']
        '/'
    """
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,  # Must be readable by JavaScript
        secure=settings.csrf_cookie_secure,
        samesite=settings.csrf_cookie_samesite,
        max_age=settings.csrf_token_expiry,
        path="/",
    )


def clear_csrf_cookie(response: Any, settings: Any) -> None:
    """Clear CSRF token cookie from response.

    Sets cookie with max_age=0 to expire it immediately.

    Args:
        response: FastAPI Response object
        settings: Application settings object with CSRF configuration

    Examples:
        >>> from unittest.mock import Mock
        >>> response = Mock()
        >>> settings = Mock(csrf_cookie_secure=True, csrf_cookie_samesite="Strict")
        >>> clear_csrf_cookie(response, settings)
        >>> response.set_cookie.called
        True
        >>> call_kwargs = response.set_cookie.call_args[1]
        >>> call_kwargs['max_age']
        0
        >>> call_kwargs['httponly']
        False
        >>> call_kwargs['secure']
        True
    """
    response.set_cookie(
        key="csrf_token",
        value="",
        httponly=False,
        secure=settings.csrf_cookie_secure,
        samesite=settings.csrf_cookie_samesite,
        max_age=0,
        path="/",
    )


class CSRFService:
    """CSRF service wrapper for dependency injection.
    
    Provides methods for CSRF token generation and validation.
    """

    def __init__(self, secret: str, expiry: int):
        """Initialize CSRF service.
        
        Args:
            secret: Secret key for HMAC computation
            expiry: Token validity window in seconds
        """
        self.secret = secret
        self.expiry = expiry

    def generate_csrf_token(self, user_id: str, session_id: str) -> str:
        """Generate a CSRF token.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            CSRF token string
        """
        return generate_csrf_token(user_id, session_id, self.secret, self.expiry)

    def validate_csrf_token(self, token: str, user_id: str, session_id: str) -> bool:
        """Validate a CSRF token.
        
        Args:
            token: CSRF token to validate
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            True if valid, False otherwise
        """
        return validate_csrf_token(token, user_id, session_id, self.secret, self.expiry)


# Global service instance
_csrf_service: CSRFService = None


def get_csrf_service() -> CSRFService:
    """Get the global CSRF service instance.
    
    Returns:
        CSRFService instance
    """
    global _csrf_service
    if _csrf_service is None:
        # First-Party
        from mcpgateway.config import settings
        
        _csrf_service = CSRFService(
            secret=settings.csrf_secret_key,
            expiry=settings.csrf_token_expiry
        )
    return _csrf_service
