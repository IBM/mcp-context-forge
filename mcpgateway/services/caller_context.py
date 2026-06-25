# -*- coding: utf-8 -*-
"""CRUD caller context for authorization decisions (Phase A T20 hardening).

Location: ./mcpgateway/services/caller_context.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

A dedicated, named sentinel for the "this code path runs as the system,
NOT as an authenticated user" escape hatch in CRUD-authorization helpers.
Replaces the earlier pattern where both ``caller_user_email`` and
``caller_token_teams`` being ``None`` was the bypass condition — Momus
(plan critique, this session) flagged the two-Nones magic as
"under-specified for production" because:

- Any caller that *forgot* to thread auth context (mid-stack bug,
  middleware failure, refactor regression) would silently hit the
  bypass.
- A reviewer reading the call site cannot tell from the API whether
  the bypass was intentional or accidental.

Metis (architectural review, same session) independently flagged that
:mod:`mcpgateway.services.import_service` calls
:meth:`ServerService.register_server` without caller context (lines
818 and 846), meaning a non-admin import path could associate any A2A
agent with any server regardless of the importer's visibility scope.

This module fixes both problems by making the bypass **explicit and
named**: callers must opt in via :meth:`CallerContext.system` rather
than fall in by forgetting parameters. Route handlers construct
:meth:`CallerContext.for_user` from the authenticated request, which
makes any missing-context bug observable as a *type error* rather
than a silent privilege escalation.

Usage at user-facing routes:

.. code-block:: python

    caller = CallerContext.for_user(user_email, token_teams)
    await server_service.register_server(db, server_in, caller_context=caller)

Usage at internal / bootstrap / seed / import paths (after explicit
sign-off that the path is admin-only or runs as platform):

.. code-block:: python

    # IMPORT path: admin-only endpoint, intentionally bypasses CRUD auth.
    # If the import endpoint ever opens to non-admin users, thread real
    # caller context through and remove this comment.
    await server_service.register_server(
        db, server_in, caller_context=CallerContext.system()
    )

The CRUD-authorization helpers check :attr:`CallerContext.is_system`
to decide whether to skip the policy evaluation. The two-Nones pattern
is gone.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class CallerContext:
    """Authenticated caller identity for CRUD-authorization decisions.

    Construct via the factories — direct instantiation works but bypasses
    the intent signals that the factories give the reader:

    - :meth:`CallerContext.for_user` documents "this is a real
      authenticated user from a route handler".
    - :meth:`CallerContext.system` documents "this is the system / a
      bootstrap pathway intentionally bypassing user auth".

    The :attr:`is_system` attribute is the **only** condition that
    skips CRUD authorization. Missing ``user_email`` alone does NOT
    bypass — a real anonymous user gets a real authorization check
    (which they would correctly fail for non-public resources). The
    bypass is opt-in, not opt-out.

    Attributes:
        user_email: The caller's authenticated email, or ``None`` for
            anonymous / system contexts.
        token_teams: The caller's JWT-scoped team membership list.
            ``None`` means "JWT did not carry a teams claim" (anonymous
            or admin-context); ``[]`` means "public-only token"; a
            non-empty list means "team-scoped token".
        is_system: ``True`` only when constructed via
            :meth:`CallerContext.system`. Authorization helpers
            interpret this as an explicit opt-in bypass.
    """

    user_email: Optional[str]
    token_teams: Optional[List[str]] = field(default=None)
    is_system: bool = field(default=False)

    @classmethod
    def system(cls) -> "CallerContext":
        """Return an explicit system-context sentinel that bypasses CRUD auth.

        Use ONLY for internal pathways where no real user is acting:
        bootstrap, seed, import (after admin-only verification), tests
        that opt out of CRUD authorization. User-facing route handlers
        MUST use :meth:`for_user` instead.

        Returns:
            A frozen :class:`CallerContext` with ``is_system=True`` and
            both other attributes set to ``None``.
        """
        return cls(user_email=None, token_teams=None, is_system=True)

    @classmethod
    def for_user(cls, user_email: Optional[str], token_teams: Optional[List[str]]) -> "CallerContext":
        """Construct a real-user caller context from a route handler.

        ``user_email`` may be ``None`` for anonymous public-discovery
        paths, but this is still NOT a system context — the
        authorization helper will run the agent-visibility check and
        the anonymous caller will only see public resources. This is
        the correct behavior; do not substitute :meth:`system` to
        "make it work".

        Args:
            user_email: Authenticated caller's email, or ``None`` for
                anonymous.
            token_teams: JWT-scoped team list. See class-level docstring.

        Returns:
            A frozen :class:`CallerContext` with ``is_system=False``.
        """
        return cls(user_email=user_email, token_teams=token_teams, is_system=False)
