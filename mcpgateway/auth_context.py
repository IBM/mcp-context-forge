# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/auth_context.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Per-request scope resolution and Rust-runtime trust-layer helpers.

Purpose (for future implementers)
---------------------------------
``mcpgateway`` keeps token primitives, request scope resolution, and the
trusted Rust-runtime hop in three logical groups, even though only two
modules currently exist:

- ``mcpgateway.auth`` (the larger sibling) - the **token / session / team
  model layer** and the FastAPI auth dependency. Most helpers there are pure
  primitives over stored artifacts (JWT claims, API tokens, revocation
  records, team membership rows) and do not need a ``Request``. The
  request-coupled exceptions are ``get_current_user`` (the FastAPI
  dependency that bridges the two layers) plus a small set of helpers it
  calls into - ``_inject_userinfo_instate`` and ``_propagate_tenant_id`` -
  which stash payload metadata on ``request.state`` for downstream helpers
  here. New code added to ``auth.py`` should follow the pure-primitive
  pattern unless it is part of the dependency chain.

- ``mcpgateway.auth_context`` (this module) - the **per-request scope
  resolution layer** plus the **Rust-runtime trust-header helpers**. The
  scope-resolution helpers take a FastAPI ``Request`` plus the ``user``
  produced by the auth dependency and compute what the caller is allowed
  to see on this specific request - this is Layer 1 in the two-layer model
  documented in ``AGENTS.md`` ("what you can SEE"), distinct from the
  Layer 2 RBAC checks in ``mcpgateway.middleware.rbac`` ("what you can
  DO"). The trust-header helpers (``decode_internal_mcp_auth_context``,
  ``has_valid_internal_mcp_runtime_auth_header``, the
  ``_expected_internal_mcp_runtime_auth_header*`` family) implement the
  HMAC contract between the Rust MCP runtime and the Python gateway. They
  live here, not in ``auth.py``, because the trusted forwarded context
  produces a synthetic ``user`` that the per-request helpers consume; the
  two responsibilities are coupled at the request boundary. A future
  refactor may extract them into a third ``mcpgateway.auth_runtime``
  module if the coupling weakens.

Why this module exists as a separate file
-----------------------------------------
Both ``mcpgateway.main`` and ``mcpgateway.admin`` need the scoped-access
helper to pass ``(user_email, token_teams)`` into the service layer. Before
this split, the helper lived in ``main.py`` and ``admin.py`` reached back
through a lazy import, creating a static cyclic import
(``admin -> main -> admin``) that ``pylint R0401`` flagged. Hoisting the
helper (and its dependency chain) into a sibling module whose only
non-stdlib first-party dependencies are ``mcpgateway.auth`` and
``mcpgateway.config`` breaks the cycle at the architectural level rather
than papering over it with ``# pylint: disable``.

Public surface
--------------
The names below are the **module's public API**. Callers in ``main.py``,
``admin.py``, routers, and transports should use these names.

    Constants (HTTP header names used by the Rust -> Python MCP bridge)
        INTERNAL_MCP_SESSION_VALIDATED_HEADER

    Identity resolution
        get_user_email(user) -> str

    Trust-layer headers forwarded from the Rust MCP runtime
        decode_internal_mcp_auth_context(header_value) -> dict
        get_internal_mcp_auth_context(request) -> dict | None
        has_valid_internal_mcp_runtime_auth_header(request) -> bool

    Per-request JWT / scope resolution (the Layer-1 surface)
        get_token_teams_from_request(request) -> list[str] | None
        get_rpc_filter_context(request, user) -> (email, teams, is_admin)
        get_request_identity(request, user) -> (email, is_admin)
        get_scoped_resource_access_context(request, user) -> (email, teams)

Private surface
---------------
Leading-underscore names below are **implementation helpers private to this
module**. They are not imported from outside and should not be. If you find
yourself needing one from another module, consider whether the calling code
should really go through one of the public wrappers above, or whether the
helper belongs in ``mcpgateway.auth`` instead.

    _INTERNAL_MCP_RUNTIME_AUTH_CONTEXT   (constant string used to derive headers)
    _INTERNAL_MCP_RUNTIME_AUTH_HEADER    (header name consumed by the trust gate)
    _auth_encryption_secret_value        (config-dependent secret accessor)
    _expected_internal_mcp_runtime_auth_header
    _expected_internal_mcp_runtime_auth_header_for_secret
    _has_verified_jwt_payload            (probe used by the resolution helpers)

Security invariants
-------------------
See ``AGENTS.md`` section "Authentication & RBAC Overview" for the full
policy. The key invariants that this module enforces:

1. ``get_token_teams_from_request`` respects the secure-first semantics of
   ``auth.normalize_token_teams``: missing ``teams`` claim means public-only,
   not admin bypass.
2. ``get_rpc_filter_context`` derives ``is_admin`` from the verified JWT
   payload or the trusted internal MCP auth context - NOT from the DB user -
   so a scoped token (``teams=[]``) cannot inherit admin bypass.
3. ``get_scoped_resource_access_context`` returns ``(None, None)`` *only* for
   genuine admin bypass (verified JWT ``is_admin=true`` + ``teams=null``, or
   non-JWT dev-mode admin). Public-only tokens get ``(email, [])``.
   Downstream services MUST treat ``(None, None)`` as "admin bypass; still
   deny private resources" per PR #4341.
4. Non-JWT admin callers (basic-auth / dev mode) keep unrestricted visibility
   via the fallback-admin branch; this carve-out is intentional and documented
   in ``AGENTS.md``.
"""

# Standard
import asyncio
import base64
from functools import lru_cache
import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from fastapi import Request
import orjson
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import normalize_token_teams
from mcpgateway.config import settings

# Module-level logger
logger = logging.getLogger(__name__)

# Trust-layer header names. ``INTERNAL_MCP_SESSION_VALIDATED_HEADER`` is part
# of the module's public constant API (main.py's middleware compares against
# it). The other two are implementation details of the header-derivation chain
# and are not exported.
INTERNAL_MCP_SESSION_VALIDATED_HEADER = "x-contextforge-session-validated"
_INTERNAL_MCP_RUNTIME_AUTH_HEADER = "x-contextforge-mcp-runtime-auth"
_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT = "contextforge-internal-mcp-runtime-v1"


def get_user_email(user: Any) -> str:
    """Extract email from user object, handling both string and dict formats.

    Args:
        user: User object, can be either a dict (new RBAC format) or string (legacy format)

    Returns:
        str: Email address extracted from user object

    Examples:
        >>> user_dict = {'email': 'admin@example.com'}
        >>> get_user_email(user_dict)
        'admin@example.com'
        >>> user_dict_sub = {'sub': 'user@example.com'}
        >>> get_user_email(user_dict_sub)
        'user@example.com'
        >>> user_dict_both = {'email': 'admin@example.com', 'sub': 'ignored@example.com'}
        >>> get_user_email(user_dict_both)
        'admin@example.com'
        >>> user_dict_no_email = {'other': 'value'}
        >>> get_user_email(user_dict_no_email)
        'unknown'
        >>> user_dict_bad_email = {'email': {'nested': 'value'}}
        >>> get_user_email(user_dict_bad_email)
        'unknown'
        >>> user_dict_list_email = {'email': ['x'], 'sub': 'user@example.com'}
        >>> get_user_email(user_dict_list_email)
        'user@example.com'
        >>> user_string = 'legacy_user'
        >>> get_user_email(user_string)
        'legacy_user'
        >>> get_user_email(None)
        'unknown'
        >>> get_user_email({})
        'unknown'
        >>> get_user_email(123)
        '123'
        >>> user_complex = {'email': 'user@domain.com', 'name': 'Test User', 'roles': ['admin']}
        >>> get_user_email(user_complex)
        'user@domain.com'
        >>> get_user_email('')
        'unknown'
        >>> get_user_email(True)
        'True'
        >>> get_user_email(False)
        'unknown'
    """
    if user is None:
        return "unknown"
    # Handle objects with email attribute (e.g., ORM models, dataclasses)
    if hasattr(user, "email"):
        email = getattr(user, "email", None)
        if isinstance(email, str):
            return email or "unknown"
        # Non-string email attribute falls through to str(user) below
    # Handle dict-like objects
    if isinstance(user, dict):
        email = user.get("email")
        if isinstance(email, str) and email:
            return email
        sub = user.get("sub")
        if isinstance(sub, str) and sub:
            return sub
        return "unknown"
    # Fallback to string conversion for other types
    return str(user) if user else "unknown"


def get_internal_mcp_auth_context(request: Request) -> Optional[Dict[str, Any]]:
    """Return trusted auth context forwarded from the StreamableHTTP MCP auth layer.

    Args:
        request: Incoming request that may carry trusted MCP auth context on state.

    Returns:
        The forwarded auth context dictionary when present, otherwise ``None``.
    """
    internal_auth_context = getattr(request.state, "_mcp_internal_auth_context", None)
    if isinstance(internal_auth_context, dict):
        return internal_auth_context
    return None


def decode_internal_mcp_auth_context(header_value: str) -> Dict[str, Any]:
    """Decode the trusted internal MCP auth header payload.

    Args:
        header_value: Base64url-encoded trusted auth context header value.

    Returns:
        Decoded auth context dictionary.

    Raises:
        ValueError: If the decoded payload is not a JSON object.
    """
    padding = "=" * (-len(header_value) % 4)
    decoded = base64.urlsafe_b64decode(f"{header_value}{padding}".encode("ascii"))
    payload = orjson.loads(decoded)
    if not isinstance(payload, dict):
        raise ValueError("Decoded internal MCP auth context must be an object")
    return payload


def _auth_encryption_secret_value() -> str:
    """Return the configured auth-encryption secret as a plain string.

    Returns:
        The auth-encryption secret, normalized to a regular string.
    """
    secret = settings.auth_encryption_secret
    if hasattr(secret, "get_secret_value"):
        return secret.get_secret_value()
    return str(secret)


@lru_cache(maxsize=8)
def _expected_internal_mcp_runtime_auth_header_for_secret(secret: str) -> str:
    """Return the shared secret-derived trust header for Rust->Python MCP hops.

    Args:
        secret: Auth-encryption secret to derive the trust header from.

    Returns:
        Hex-encoded SHA-256 digest derived from the provided auth secret.
    """
    material = f"{secret}:{_INTERNAL_MCP_RUNTIME_AUTH_CONTEXT}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _expected_internal_mcp_runtime_auth_header() -> str:
    """Return the current shared secret-derived trust header for Rust->Python MCP hops.

    Returns:
        Hex-encoded SHA-256 digest derived from the current auth secret.
    """
    return _expected_internal_mcp_runtime_auth_header_for_secret(_auth_encryption_secret_value())


def has_valid_internal_mcp_runtime_auth_header(request: Request) -> bool:
    """Validate the shared secret-derived trust header for internal MCP requests.

    Args:
        request: Incoming internal MCP request.

    Returns:
        ``True`` when the derived trust header matches the expected value.
    """
    provided = request.headers.get(_INTERNAL_MCP_RUNTIME_AUTH_HEADER)
    if not provided:
        return False
    return hmac.compare_digest(provided, _expected_internal_mcp_runtime_auth_header())


def get_token_teams_from_request(request: Request) -> Optional[List[str]]:
    """Extract and normalize teams from verified JWT token.

    SECURITY: Uses ``normalize_token_teams`` for consistent secure-first semantics:

    - ``teams`` key missing -> ``[]`` (public-only, secure default)
    - ``teams`` key null + ``is_admin=true`` -> ``None`` (admin bypass)
    - ``teams`` key null + ``is_admin=false`` -> ``[]`` (public-only)
    - ``teams`` key ``[]`` -> ``[]`` (explicit public-only)
    - ``teams`` key ``[...]`` -> normalized list of string IDs

    First checks ``request.state.token_teams`` (set by ``auth.py``), then falls
    back to calling ``normalize_token_teams`` on the JWT payload.

    Args:
        request: FastAPI request object.

    Returns:
        ``None`` for admin bypass, ``[]`` for public-only, or list of normalized team ID strings.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from mcpgateway import auth_context
        >>> req = MagicMock()
        >>> req.state = MagicMock()
        >>> req.state.token_teams = ["team_a"]
        >>> auth_context.get_token_teams_from_request(req)
        ['team_a']
        >>> req.state.token_teams = []
        >>> auth_context.get_token_teams_from_request(req)
        []
    """
    internal_auth_context = get_internal_mcp_auth_context(request)
    if isinstance(internal_auth_context, dict) and "teams" in internal_auth_context:
        internal_teams = internal_auth_context.get("teams")
        if internal_teams is None or isinstance(internal_teams, list):
            return internal_teams

    # SECURITY: prefer request.state.token_teams (already normalized by auth.py).
    _not_set = object()
    token_teams = getattr(request.state, "token_teams", _not_set)
    if token_teams is not _not_set and (token_teams is None or isinstance(token_teams, list)):
        return token_teams

    cached = getattr(request.state, "_jwt_verified_payload", None)
    if cached and isinstance(cached, tuple) and len(cached) == 2:
        _, payload = cached
        if payload:
            return normalize_token_teams(payload)

    # No JWT payload - return [] for public-only (secure default).
    return []


def get_rpc_filter_context(request: Request, user) -> tuple[Optional[str], Optional[List[str]], bool]:
    """Extract ``(user_email, token_teams, is_admin)`` for RPC filtering.

    Args:
        request: FastAPI request object.
        user: User object from auth dependency.

    Returns:
        Tuple of ``(user_email, token_teams, is_admin)`` where ``is_admin`` is
        sourced from the verified token, not the DB user, so that scoped tokens
        (empty ``teams``) cannot inherit admin bypass.

        **Type validation**: ``user_email`` is validated to be a string or None.
        Non-string values (dict, list, int, etc.) are logged and converted to None
        for fail-safe public-only access, preventing SQL binding errors.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from mcpgateway import auth_context
        >>> req = MagicMock()
        >>> req.state = MagicMock()
        >>> req.state._jwt_verified_payload = ("token", {"teams": ["t1"], "is_admin": True})
        >>> user = {"email": "test@x.com", "is_admin": True}
        >>> email, teams, is_admin = auth_context.get_rpc_filter_context(req, user)
        >>> email
        'test@x.com'
        >>> teams
        ['t1']
        >>> is_admin
        True
    """
    # Use existing get_user_email() helper for consistent email extraction
    user_email = get_user_email(user)
    # get_user_email() guarantees a string return, but may return "unknown"
    # Convert "unknown" to None for downstream SQL queries
    if user_email == "unknown":
        user_email = None

    token_teams = get_token_teams_from_request(request)

    # SECURITY: admin bit MUST come from the token, not the DB user, so a
    # public-only admin token (teams=[]) does not inherit admin bypass.
    is_admin = False
    internal_auth_context = get_internal_mcp_auth_context(request)
    if isinstance(internal_auth_context, dict):
        if user_email is None:
            internal_email = internal_auth_context.get("email")
            # SECURITY: Type-check internal auth context email
            if internal_email is not None and not isinstance(internal_email, str):
                logger.warning(
                    "get_rpc_filter_context: internal_auth_context email non-string type=%s path=%s; forcing None to prevent SQL binding errors",
                    type(internal_email).__name__,
                    getattr(getattr(request, "url", None), "path", "unknown"),
                )
                internal_email = None
            user_email = internal_email
        is_admin = bool(internal_auth_context.get("is_admin", False))
        if token_teams is not None and len(token_teams) == 0:
            is_admin = False
        return user_email, token_teams, is_admin

    cached = getattr(request.state, "_jwt_verified_payload", None)
    if cached and isinstance(cached, tuple) and len(cached) == 2:
        _, payload = cached
        if payload:
            is_admin = payload.get("is_admin", False) or payload.get("user", {}).get("is_admin", False)

    if token_teams is not None and len(token_teams) == 0:
        is_admin = False

    return user_email, token_teams, is_admin


def _has_verified_jwt_payload(request: Request) -> bool:
    """Return whether request has a verified JWT payload cached in request state.

    Args:
        request: Incoming request context.

    Returns:
        ``True`` when a verified payload tuple is present, otherwise ``False``.
    """
    internal_auth_context = get_internal_mcp_auth_context(request)
    if isinstance(internal_auth_context, dict):
        return True
    cached = getattr(request.state, "_jwt_verified_payload", None)
    return bool(cached and isinstance(cached, tuple) and len(cached) == 2 and cached[1])


def get_request_identity(request: Request, user) -> tuple[str, bool]:
    """Return requester email and admin state honoring scoped-token semantics.

    Args:
        request: Incoming request context.
        user: Authenticated user context from dependency resolution.

    Returns:
        Tuple of ``(requester_email, requester_is_admin)``.
    """
    user_email, _token_teams, token_is_admin = get_rpc_filter_context(request, user)
    resolved_email = user_email or get_user_email(user)

    # When a JWT payload is present, respect token-derived admin semantics
    # (including public-only admin tokens where bypass is intentionally disabled).
    if _has_verified_jwt_payload(request):
        return resolved_email, token_is_admin

    fallback_is_admin = False
    if hasattr(user, "is_admin"):
        fallback_is_admin = bool(getattr(user, "is_admin", False))
    elif isinstance(user, dict):
        fallback_is_admin = bool(user.get("is_admin", False) or user.get("user", {}).get("is_admin", False))

    return resolved_email, token_is_admin or fallback_is_admin


def get_scoped_resource_access_context(request: Request, user) -> tuple[Optional[str], Optional[List[str]]]:
    """Resolve scoped resource access context for the current requester.

    This is the Layer-1 entry point that every route handler should use when
    calling a service's fetch / list / read method. The returned tuple is
    the canonical ``(user_email, token_teams)`` input shape for service-layer
    visibility checks:

    - ``(None, None)``: admin bypass. The service still applies the post-PR
      #4341 rule "admin bypass may see public + team, never another user's
      private".
    - ``(email, [])``: public-only token. Service returns public rows only.
    - ``(email, ["team-a", ...])``: team-scoped token. Service returns
      public rows + team-scoped rows for the listed teams + the caller's own
      private rows.

    Args:
        request: Incoming request context.
        user: Authenticated user context from dependency resolution.

    Returns:
        Tuple of ``(user_email, token_teams)`` as described above.
    """
    user_email, token_teams, is_admin = get_rpc_filter_context(request, user)

    # Non-JWT admin contexts (basic-auth / dev-mode) keep unrestricted access semantics.
    if not _has_verified_jwt_payload(request):
        _requester_email, fallback_admin = get_request_identity(request, user)
        if fallback_admin:
            return _requester_email, None  # Keep email for owner matching (PR #4341 / issue #4694)

    if is_admin and token_teams is None:
        return user_email, None  # Keep user_email for owner matching (PR #4341 / issue #4694)
    if token_teams is None:
        return user_email, []
    return user_email, token_teams


def get_scoped_visibility_from_user_context(user_context: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[List[str]]]:
    """Resolve scoped visibility from a user_context dict (StreamableHTTP transport).

    This is the Layer-1 entry point for MCP handlers in the StreamableHTTP
    transport that operate on a ``user_context`` dict rather than a FastAPI
    ``Request`` object. It applies the same admin-bypass + public-only-secure-default
    semantics as :func:`get_scoped_resource_access_context`.

    SECURITY: Empty or ``None`` contexts return ``(None, [])`` (public-only secure
    default), NOT ``(None, None)`` (admin bypass). This prevents unauthenticated
    StreamableHTTP requests from widening visibility beyond public rows.

    Args:
        user_context: User context dict from StreamableHTTP auth layer, or ``None``
            for unauthenticated requests.

    Returns:
        Tuple of ``(user_email, token_teams)`` where:

        - ``(email, None)``: admin bypass (authenticated admin with unrestricted token)
        - ``(None, [])``: unauthenticated or empty context (public-only secure default)
        - ``(email, [])``: authenticated public-only token
        - ``(email, ["team-a", ...])``: authenticated team-scoped token

    Examples:
        >>> # Admin with unrestricted token
        >>> get_scoped_visibility_from_user_context({"email": "admin@x.com", "teams": None, "is_admin": True})
        ('admin@x.com', None)
        >>> # Admin with missing teams key (secure default)
        >>> get_scoped_visibility_from_user_context({"email": "admin@x.com", "is_admin": True})
        ('admin@x.com', [])
        >>> # Admin with public-only token (narrowed)
        >>> get_scoped_visibility_from_user_context({"email": "admin@x.com", "teams": [], "is_admin": True})
        ('admin@x.com', [])
        >>> # Regular user with team access
        >>> get_scoped_visibility_from_user_context({"email": "user@x.com", "teams": ["t1"], "is_admin": False})
        ('user@x.com', ['t1'])
        >>> # Unauthenticated request (secure default)
        >>> get_scoped_visibility_from_user_context(None)
        (None, [])
        >>> # Empty context (secure default)
        >>> get_scoped_visibility_from_user_context({})
        (None, [])
    """
    # SECURITY: Empty or None context returns public-only, not admin bypass.
    if not user_context:
        return None, []

    user_email = user_context.get("email")
    is_admin = user_context.get("is_admin", False)

    # Distinguish missing "teams" key from explicit teams=None
    if "teams" not in user_context:
        return user_email, []

    token_teams = user_context["teams"]

    # Admin bypass - only when token has NO team restrictions (token_teams is None)
    # If token has explicit team scope (even empty [] for public-only), respect it
    # Preserve user_email so downstream RBAC can verify admin status via is_user_admin()
    if is_admin and token_teams is None:
        return user_email, None

    # Non-admin without teams = public-only (secure default)
    if token_teams is None:
        return user_email, []

    return user_email, token_teams


async def set_user_context_from_token(request: Request, payload: dict, db: Session) -> None:
    """Set user context on request state from JWT payload.

    Resolves user ID to email and caches on request.state for performance.
    This helper supports the token migration from email-based to user-ID-based
    tokens by using get_user_email_from_token() which handles both formats.

    Args:
        request: FastAPI request object
        payload: JWT payload dictionary
        db: Database session for user lookup

    Side Effects:
        Sets the following attributes on request.state:
        - user_email: Resolved user email (from UUID lookup or direct if legacy email sub)
        - user_id: Value of the sub claim (UUID in new tokens, email in legacy tokens)
        - is_admin: Admin flag resolved from DB (not from JWT)
        - auth_provider: Auth provider from payload

    Examples:
        >>> # New format: sub contains UUID
        >>> payload = {"sub": "550e8400-e29b-41d4-a716-446655440000", "auth_provider": "local"}
        >>> await set_user_context_from_token(request, payload, db)  # doctest: +SKIP
        >>> request.state.user_email  # doctest: +SKIP
        'user@example.com'
        >>> request.state.user_id  # doctest: +SKIP
        '550e8400-e29b-41d4-a716-446655440000'

        >>> # Legacy format: sub contains email
        >>> payload = {"sub": "user@example.com"}
        >>> await set_user_context_from_token(request, payload, db)  # doctest: +SKIP
        >>> request.state.user_email  # doctest: +SKIP
        'user@example.com'
        >>> request.state.user_id  # doctest: +SKIP
        'user@example.com'
    """
    from mcpgateway.auth import get_user_email_from_token

    from mcpgateway.auth import _get_user_by_email_sync  # pylint: disable=import-outside-toplevel

    user_email = await get_user_email_from_token(payload, db)
    request.state.user_email = user_email
    request.state.user_id = payload.get("sub")
    db_user = await asyncio.to_thread(_get_user_by_email_sync, user_email) if user_email else None
    request.state.is_admin = db_user.is_admin if db_user else False
    request.state.auth_provider = payload.get("auth_provider", "local")
