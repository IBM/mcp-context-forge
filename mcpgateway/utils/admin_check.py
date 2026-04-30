# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/admin_check.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared admin detection helper used by Layer-1 visibility filters.

This module is the **single source of truth** for answering "is this email
an admin for the purpose of visibility bypass?" at the service layer.

IMPORTANT security semantics:

- The auth layer (``mcpgateway/auth.py``) is the authority on whether an admin
  has been granted un-narrowed scope.  Callers MUST gate invocation of
  :func:`is_user_admin` on ``token_teams is None`` — i.e., only consult the
  DB when the token-scoping layer has already said "this caller is
  unrestricted".  Calling :func:`is_user_admin` for a caller whose token is
  narrowed (``token_teams == []`` or ``["t1", ...]``) and granting bypass on
  the result violates the contract in
  :func:`mcpgateway.auth.normalize_token_teams` that public-only and
  team-scoped tokens narrow even admins.  See AGENTS.md / #4106.

- The helper is **fail-closed**: any exception from the DB lookup returns
  ``False``.

- Results are memoized on ``db.info`` for the lifetime of the SQLAlchemy
  session, so list operations and per-entity access checks do not pay for
  repeated admin lookups.  The cache is keyed by ``user_email`` and scoped
  to a single Session — it does not persist across requests.
"""

# Standard
import logging
from typing import List, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Key used to memoize admin-check results on ``Session.info``.
_ADMIN_CACHE_KEY = "_admin_check_cache"


def is_user_admin(db: Optional[Session], user_email: Optional[str]) -> bool:
    """Return ``True`` if the given email identifies an admin user.

    Performs two checks in order:

    1. Match against ``settings.platform_admin_email`` (no DB round-trip).
    2. Look up ``EmailUser`` row and check ``is_admin is True``.

    Results are cached on ``db.info[_ADMIN_CACHE_KEY]`` for the lifetime of
    the session to avoid N+1 lookups during list operations or loops.

    Args:
        db: Active SQLAlchemy session.  ``None`` returns ``False`` after
            the platform-admin fast-path — the DB check cannot run without
            a session (fail-closed).
        user_email: Email to test.  ``None`` or empty returns ``False``
            immediately (no identity → no admin).

    Returns:
        ``True`` if the user is a platform admin or has ``is_admin=True``
        in the database; ``False`` otherwise (including on DB errors or a
        ``None`` session, matching the fail-closed policy required by
        AGENTS.md).

    Caller contract:
        Callers MUST gate this on ``token_teams is None`` — see module
        docstring.  Calling ``is_user_admin`` for a narrowed token and
        acting on the result reintroduces the bypass regression guarded
        against in PR #4107.
    """
    if not user_email:
        return False

    # First-Party
    from mcpgateway.config import settings  # pylint: disable=import-outside-toplevel
    from mcpgateway.db import EmailUser  # pylint: disable=import-outside-toplevel

    # Platform admin fast-path — no DB round-trip.
    if user_email == getattr(settings, "platform_admin_email", ""):
        return True

    # Fail-closed: no session means we cannot verify is_admin.
    if db is None:
        return False

    # Session-scoped memoization.  ``db.info`` is a plain dict that
    # SQLAlchemy makes available for caller use; it lives for the session
    # lifetime and is not shared across sessions.
    cache = db.info.setdefault(_ADMIN_CACHE_KEY, {})
    if user_email in cache:
        return cache[user_email]

    try:
        user = db.execute(select(EmailUser).where(EmailUser.email == user_email)).scalar_one_or_none()
        # Explicitly check for is_admin attribute and that it's True (not just truthy)
        # This handles mock objects that return MagicMock for any attribute
        result = user is not None and hasattr(user, "is_admin") and user.is_admin is True
    except Exception:  # pylint: disable=broad-except
        # Fail-closed: if we can't verify admin status, assume not admin.
        # Debug-log so ops can distinguish mis-configuration from
        # deliberate denials without leaking caller email at INFO.
        logger.debug("admin check failed for %s", user_email, exc_info=True)
        result = False

    cache[user_email] = result
    return result


def is_admin_bypass_granted(
    db: Optional[Session],
    user_email: Optional[str],
    token_teams: Optional[List[str]],
) -> bool:
    """Return ``True`` when the caller should receive Layer-1 admin bypass.

    This is the single place the "does this caller bypass visibility
    filtering?" question is answered.  Encodes the full security contract
    so callers don't replicate the ``token_teams is None`` guard that
    prevents the #4106 regression.

    Bypass applies in exactly two cases:

    1. ``token_teams is None and user_email is None`` — no auth context,
       pre-auth admin or a fully unscoped call.
    2. ``token_teams is None and user_email`` is set and the user is an
       admin in the DB — the auth layer resolved an admin session.

    Narrowed tokens (``token_teams == []`` or ``token_teams == ["t1", ...]``)
    **never** grant bypass, even for DB admins.  This matches the contract
    in :func:`mcpgateway.auth.normalize_token_teams` that public-only and
    team-scoped tokens constrain all callers.

    Args:
        db: Active SQLAlchemy session; may be ``None``.  The DB lookup
            fails closed (False) when the session is missing.
        user_email: Caller email, or ``None``.
        token_teams: Token team scope from
            :func:`mcpgateway.auth.normalize_token_teams` /
            :func:`mcpgateway.auth.resolve_session_teams`.  ``None`` means
            the auth layer granted unrestricted access; ``[]`` means
            public-only; a non-empty list means team-scoped.

    Returns:
        ``True`` when the caller should see all rows; ``False`` when the
        caller must be constrained by normal visibility rules.
    """
    if token_teams is None and user_email is None:
        return True
    if token_teams is None and user_email and is_user_admin(db, user_email):
        return True
    return False
