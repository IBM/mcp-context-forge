# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Abstract base class for services with visibility-filtered listing."""

# Standard
from abc import ABC
from typing import Any, List, Optional

# Third-Party
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.team_management_service import TeamManagementService


class BaseService(ABC):
    """Abstract base class for services with visibility-filtered listing."""

    _visibility_model_cls: type  # Subclasses MUST set this

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
        1. Returns query unmodified when no auth context is present (admin bypass)
        2. Resolves effective teams from JWT token_teams or DB lookup
        3. Suppresses owner matching for public-only tokens (token_teams=[])
        4. Delegates to _apply_visibility_filter for SQL WHERE construction

        Args:
            query: SQLAlchemy query to filter
            db: Database session (for team membership lookup when token_teams is None)
            user_email: User's email. None = no user context.
            token_teams: Teams from JWT via normalize_token_teams().
                None = admin bypass or no auth context.
                [] = public-only token.
                [...] = team-scoped token.
            team_id: Optional specific team filter

        Returns:
            Query with visibility WHERE clauses applied, or unmodified
            if no auth context is present.
        """
        if user_email is None and token_teams is None:
            return query

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
            # User requesting specific team - verify access
            if team_id not in token_teams:
                return query.where(False)

            # Scope results strictly to the requested team
            access_conditions = [and_(model_cls.team_id == team_id, model_cls.visibility.in_(["team", "public"]))]
            if user_email:
                access_conditions.append(and_(model_cls.team_id == team_id, model_cls.owner_email == user_email))
            return query.where(or_(*access_conditions))

        # Global listing: public resources visible to everyone
        access_conditions = [model_cls.visibility == "public"]

        # Owner can see their own private resources (but NOT team resources
        # from teams outside token scope — those are covered by the
        # token_teams condition below)
        if user_email:
            access_conditions.append(and_(model_cls.owner_email == user_email, model_cls.visibility == "private"))

        if token_teams:
            access_conditions.append(and_(model_cls.team_id.in_(token_teams), model_cls.visibility.in_(["team", "public"])))

        return query.where(or_(*access_conditions))
