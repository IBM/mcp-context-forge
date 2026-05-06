# -*- coding: utf-8 -*-
# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./mcpgateway/services/base_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Abstract base class for services with visibility-filtered listing.
"""

# Standard
from abc import ABC
from typing import Any, List, Optional, Type

# Third-Party
from sqlalchemy import and_
from sqlalchemy import exists as sa_exists
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

# First-Party
from mcpgateway.plugins import get_plugin_manager
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.admin_check import is_user_admin


class BaseService(ABC):
    """Abstract base class for services with visibility-filtered listing."""

    _visibility_model_cls: type

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Ensure subclasses define _visibility_model_cls.

        Args:
            **kwargs: Keyword arguments forwarded to super().__init_subclass__.

        Raises:
            TypeError: If the subclass does not set _visibility_model_cls to a type.
        """
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.__dict__.get("_visibility_model_cls"), type):
            raise TypeError(f"{cls.__name__} must set _visibility_model_cls to a model class")

    async def entity_exists(self, db: Session, entity_id: str) -> bool:
        """Check whether an entity exists in the database by primary key.

        Uses a lightweight ``EXISTS`` subquery — no row data is loaded.
        All ``BaseService`` subclasses inherit this via ``_visibility_model_cls``.

        Args:
            db: Database session.
            entity_id: Primary-key value to look up.

        Returns:
            True if a row with the given id exists, False otherwise.
        """
        model = self._visibility_model_cls
        return db.execute(select(sa_exists().where(model.id == entity_id))).scalar()

    async def _apply_access_control(
        self,
        query: Any,
        db: Session,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        team_id: Optional[str] = None,
    ) -> Any:
        """Resolve team membership and apply visibility filtering to a query.

        Handles the full access-control flow for list endpoints:
        1. Admin bypass: anonymous (user_email=None AND token_teams=None) sees
           public + team rows only. DB-resolved admin (email + token_teams=None)
           also sees their OWN private rows. No bypass shape exposes another
           user's private rows (PR #4341 / issue #4323). The DB-resolved admin
           shape is detected via :func:`~mcpgateway.utils.admin_check.is_user_admin`
           — using the broader ``is_admin_bypass_granted`` here would risk
           re-introducing the leak this PR closes (see PR #4341 review B2/B5).
        2. Resolves effective teams from JWT token_teams or DB lookup.
        3. Suppresses owner matching for public-only tokens (token_teams=[]).
        4. Delegates to _apply_visibility_filter for SQL WHERE construction.

        Args:
            query: SQLAlchemy query to filter.
            db: Database session (for team membership lookup when token_teams is None).
            user_email: User's email. ``None`` = no user context.
            token_teams: Teams from JWT via normalize_token_teams().
                ``None`` = admin bypass or no auth context.
                ``[]`` = public-only token.
                ``[...]`` = team-scoped token.
            team_id: Optional specific team filter.

        Returns:
            Query with visibility WHERE clauses applied. Admin bypass excludes
            another user's private rows (security invariant from PR #4341); the
            caller's own private rows remain visible when the bypass shape is
            DB-resolved admin with an email.
        """
        # Admin bypass: respect PR #4341's invariant that admin bypass NEVER reveals
        # another user's private rows. Anonymous bypass (no email) sees public + team
        # only; DB-resolved admin sessions additionally see their OWN private rows.
        # Matches the pattern in a2a_service._visible_agent_ids.
        model_cls = self._visibility_model_cls
        if user_email is None and token_teams is None:
            return query.where(model_cls.visibility != "private")
        if token_teams is None and user_email and is_user_admin(db, user_email):
            return query.where(
                or_(
                    model_cls.visibility != "private",
                    and_(model_cls.visibility == "private", model_cls.owner_email == user_email),
                )
            )

        effective_teams: List[str] = []
        if token_teams is not None:
            effective_teams = token_teams
        elif user_email:
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            effective_teams = [team.id for team in user_teams]

        # Public-only tokens (explicit token_teams=[]) must not get owner access
        filter_email = None if (token_teams is not None and not token_teams) else user_email

        return self._apply_visibility_filter(query, filter_email, effective_teams, team_id)

    def _apply_visibility_filter(
        self,
        query: Any,
        user_email: Optional[str],
        token_teams: List[str],
        team_id: Optional[str] = None,
    ) -> Any:
        """Apply visibility-based access control to query.

        Note: Callers are responsible for suppressing user_email for public-only
        tokens. Use _apply_access_control() which handles this automatically.

        Access rules:
        - public: visible to all (global listing only; excluded when team_id is set)
        - team: visible to team members (token_teams contains team_id)
        - private: visible only to owner (requires user_email)

        Args:
            query: SQLAlchemy query to filter
            user_email: User's email for owner matching (None suppresses owner access)
            token_teams: Resolved team list (never None; use [] for no teams)
            team_id: Optional specific team filter

        Returns:
            Filtered query
        """
        model_cls = self._visibility_model_cls

        if team_id:
            if team_id not in token_teams:
                return query.where(False)

            access_conditions = [and_(model_cls.team_id == team_id, model_cls.visibility.in_(["team", "public"]))]
            if user_email:
                access_conditions.append(and_(model_cls.team_id == team_id, model_cls.owner_email == user_email, model_cls.visibility == "private"))
            return query.where(or_(*access_conditions))

        access_conditions = [model_cls.visibility == "public"]

        if user_email:
            access_conditions.append(and_(model_cls.owner_email == user_email, model_cls.visibility == "private"))

        if token_teams:
            access_conditions.append(and_(model_cls.team_id.in_(token_teams), model_cls.visibility.in_(["team", "public"])))

        return query.where(or_(*access_conditions))

    @staticmethod
    def _apply_visibility_scope(
        stmt: Select,
        model: Type[Any],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        team_ids: List[str],
        db: Session,
    ) -> Select:
        """Apply token/user visibility scope to a SQLAlchemy statement.

        Static because subclasses and sibling services (completion, tag) call
        it without inheriting from :class:`BaseService`.  The required ``db``
        parameter is intentional: an optional ``db`` turns out to be a
        footgun — any caller that forgets it silently loses the admin
        bypass and re-introduces #4106.

        Semantics (post-PR #4341 / issue #4323):

        - ``token_teams is None and user_email is None`` → public + team rows
          (admin bypass with no identity; private rows excluded).
        - ``token_teams is None and user_email`` set, user is admin in DB
          → public + team rows + caller's own private rows (DB-admin bypass;
          another user's private rows still excluded).
        - ``token_teams == []`` (public-only) → public only, **even for
          DB admins**.  See :mod:`mcpgateway.utils.admin_check` for why.
        - ``token_teams == [...]`` → public + matching team (+ owner if
          ``user_email`` set), even for DB admins.

        Args:
            stmt: SQLAlchemy statement to constrain
            model: ORM model that includes visibility/team/owner columns
            user_email: Caller email used for owner visibility
            token_teams: Explicit token team scope when present
            team_ids: Effective team IDs for team visibility
            db: Required database session for the admin bypass check.

        Returns:
            Scoped SQLAlchemy statement.
        """
        # Admin bypass (PR #4341 invariant): never reveal another user's private rows.
        # Anonymous bypass sees public + team only; a DB-resolved admin session
        # additionally sees their own private rows. Mirrors _apply_access_control.
        if token_teams is None and user_email is None:
            return stmt.where(model.visibility != "private")
        if token_teams is None and user_email and is_user_admin(db, user_email):
            return stmt.where(
                or_(
                    model.visibility != "private",
                    and_(model.visibility == "private", model.owner_email == user_email),
                )
            )

        is_public_only_token = token_teams is not None and len(token_teams) == 0
        access_conditions = [model.visibility == "public"]

        if not is_public_only_token and user_email:
            access_conditions.append(model.owner_email == user_email)

        if team_ids:
            access_conditions.append(and_(model.team_id.in_(team_ids), model.visibility.in_(["team", "public"])))

        return stmt.where(or_(*access_conditions))

    async def _get_plugin_manager(self, server_id: str | None) -> Any:
        """Return the context-scoped plugin manager from the global factory.

        Args:
            server_id: Context identifier used to resolve a specific plugin manager.

        Returns:
            Plugin manager instance when plugins are enabled, otherwise ``None``.
        """
        return await get_plugin_manager(server_id)
