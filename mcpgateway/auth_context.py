# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Consolidated auth context dataclasses.

AuthContext and QueryScope are the canonical representations of a resolved
authentication/authorization state. They encode the security rules that are
currently scattered across 10+ layers into frozen, testable dataclasses.

This module is Tier 0 of the auth context consolidation — dataclass
definitions only, no callers yet. The existing auth paths are untouched.
"""

# Future
from __future__ import annotations

# Standard
from dataclasses import dataclass, field
from typing import Any, List, Optional

# Third-Party
from sqlalchemy import or_
from sqlalchemy.orm import Query


@dataclass(frozen=True)
class AuthContext:
    """Canonical output of auth resolution — one per request.

    Encodes the security rules from normalize_token_teams, _get_rpc_filter_context,
    AdminAuthMiddleware, _auth_jwt, and all inline token_teams checks.

    Semantics of effective_teams:
        None  → admin bypass (sees all resources across all teams)
        []    → public-only (sees only visibility="public" resources)
        [ids] → team-scoped (sees public + resources owned by listed teams)
    """

    user_email: Optional[str]
    is_admin: bool
    effective_teams: Optional[List[str]]  # None=bypass, []=public, [ids]=scoped
    token_use: str  # "session" | "api" | "anonymous"
    auth_method: str  # "bearer_token" | "cookie" | "api_token_hash" | "proxy" | "anonymous" | "basic"
    scoped_permissions: List[str] = field(default_factory=list)  # token-level permission caps
    is_active: bool = True  # user account active status (checked once by resolver)

    # ── Derived properties ────────────────────────────────────────────

    @property
    def is_admin_bypass(self) -> bool:
        """Admin bypass requires BOTH is_admin AND effective_teams=None.

        Source: normalize_token_teams — only ``teams: null + is_admin: true`` yields None.
        Source: _get_rpc_filter_context — public-only tokens (teams=[]) never bypass.
        """
        return self.effective_teams is None and self.is_admin

    @property
    def is_public_only(self) -> bool:
        """True when caller can see only visibility="public" resources.

        Source: normalize_token_teams — missing key, null+non-admin, or explicit [].
        """
        return self.effective_teams is not None and len(self.effective_teams) == 0

    def allows_admin_paths(self) -> bool:
        """Whether this context may access /admin/* routes.

        Source: AdminAuthMiddleware line 1842 — public-only tokens with is_admin=True
        are STILL denied admin paths. You need is_admin AND non-empty/None teams.
        """
        return self.is_admin and not self.is_public_only

    def effective_is_admin(self) -> bool:
        """is_admin with the public-only override applied.

        Source: _get_rpc_filter_context (main.py:440) —
        ``if token_teams is not None and len(token_teams) == 0: is_admin = False``

        This ensures admin tokens with explicit empty teams cannot bypass
        visibility filtering. Use this instead of raw ``is_admin`` when making
        data-access decisions.
        """
        if self.is_public_only:
            return False
        return self.is_admin

    def to_query_scope(self) -> QueryScope:
        """Convert to the opaque scope object passed to services.

        Services should never see effective_teams or is_admin directly.
        """
        return QueryScope(
            _effective_teams=self.effective_teams,
            _user_email=self.user_email,
            _is_unrestricted=self.is_admin_bypass,
        )

    def to_transport_dict(self) -> dict[str, Any]:
        """Bridge to user_context_var for StreamableHTTP transport.

        Standardizes key name to ``"teams"`` (not ``"token_teams"``),
        eliminating the existing drift between HTTP and transport layers.

        Source: _auth_jwt user_context_var.set() shape.
        """
        return {
            "email": self.user_email,
            "teams": self.effective_teams,
            "is_admin": self.is_admin,
            "token_use": self.token_use,
            "scoped_permissions": self.scoped_permissions,
            "is_authenticated": True,
        }


@dataclass(frozen=True)
class QueryScope:
    """Opaque auth scope passed to services — replaces raw token_teams parameter.

    Cannot be constructed directly by services — only via AuthContext.to_query_scope().
    Services call apply_visibility_filter() instead of writing inline token_teams checks.

    This collapses the ~135 inline ``token_teams is None`` / ``len(token_teams) == 0``
    patterns into a single method call per query.
    """

    _effective_teams: Optional[List[str]]
    _user_email: Optional[str]
    _is_unrestricted: bool

    def apply_visibility_filter(self, query: Query, model: Any, *, visibility_col: str = "visibility", public_value: str = "public") -> Query:
        """Apply team-based visibility filtering to a SQLAlchemy query.

        Handles two column conventions found across models:
        - ``model.visibility == "public"`` (Tool, Resource, Prompt, A2AAgent, Gateway, Server, GrpcService, EmailTeam)
        - ``model.is_public == True`` (if visibility_col not found, falls back to is_public)

        Args:
            query: SQLAlchemy query to filter.
            model: ORM model class (must have team_id column).
            visibility_col: Column name for visibility (default "visibility").
            public_value: Value that means "public" (default "public").

        Returns:
            Filtered query.

        Source: inline patterns in tool_service.py, resource_service.py, a2a_service.py,
        prompt_service.py, tag_service.py, completion_service.py, gateway_service.py, etc.
        """
        if self._is_unrestricted:
            return query

        vis_attr = getattr(model, visibility_col, None)

        if vis_attr is None:
            # Fallback: some models may use is_public boolean instead
            is_public_attr = getattr(model, "is_public", None)
            if is_public_attr is not None:
                if not self._effective_teams:  # public-only
                    return query.filter(is_public_attr.is_(True))
                return query.filter(or_(is_public_attr.is_(True), model.team_id.in_(self._effective_teams)))
            # No visibility column — return unfiltered (caller's responsibility)
            return query

        if not self._effective_teams:  # public-only (empty list)
            return query.filter(vis_attr == public_value)

        return query.filter(or_(vis_attr == public_value, model.team_id.in_(self._effective_teams)))

    def apply_ownership_filter(self, query: Query, model: Any) -> Query:
        """Apply ownership-based filtering (user's own resources + team resources).

        For models with an ``owner_email`` column, allows access to:
        - Resources owned by the current user
        - Resources belonging to the user's teams (if team-scoped)

        Falls back to apply_visibility_filter if no owner_email column exists.

        Args:
            query: SQLAlchemy query to filter.
            model: ORM model class.

        Returns:
            Filtered query.
        """
        if self._is_unrestricted:
            return query

        owner_attr = getattr(model, "owner_email", None)
        if owner_attr is not None and self._user_email:
            conditions = [owner_attr == self._user_email]
            if self._effective_teams:
                team_id_attr = getattr(model, "team_id", None)
                if team_id_attr is not None:
                    conditions.append(team_id_attr.in_(self._effective_teams))
            return query.filter(or_(*conditions))

        return self.apply_visibility_filter(query, model)

    @property
    def is_unrestricted(self) -> bool:
        """Whether this scope has no restrictions (admin bypass)."""
        return self._is_unrestricted

    @property
    def user_email(self) -> Optional[str]:
        """The authenticated user's email, if any."""
        return self._user_email
