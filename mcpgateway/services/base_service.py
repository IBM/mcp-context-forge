# Copyright (c) 2025 IBM Corp. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Abstract base class for services with visibility-filtered listing."""

# Standard
from abc import ABC
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import EmailTeam
from mcpgateway.services.team_management_service import TeamManagementService


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
                access_conditions.append(and_(model_cls.team_id == team_id, model_cls.owner_email == user_email, model_cls.visibility == "private"))
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

    @staticmethod
    async def check_item_access(
        visibility: str,
        item_team_id: Optional[str],
        item_owner_email: Optional[str],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        db: Optional[Session] = None,
    ) -> bool:
        """Check if a user has access to a single item based on visibility rules.

        Unified per-item access check for all visibility-scoped resources
        (tools, resources, prompts, agents). For query-level filtering of
        list operations, use _apply_access_control() instead.

        Access rules:
        - public: accessible by everyone
        - admin bypass: token_teams=None AND user_email=None → unrestricted
        - no user context (but not admin) → deny non-public items
        - public-only token (token_teams=[]) → deny non-public items
        - private: accessible only by owner (owner_email matches user_email)
        - team: accessible by team members (item_team_id in token_teams)

        Args:
            visibility: Item visibility level (public, team, private).
            item_team_id: Team ID assigned to the item, if any.
            item_owner_email: Email of the item owner, if any.
            user_email: Requesting user's email. None = no user context.
            token_teams: Teams from JWT via normalize_token_teams().
                None = admin bypass, [] = public-only, [...] = team-scoped.
            db: Optional database session for team membership lookup when
                token_teams is not available (fallback path).

        Returns:
            True if access is allowed, False otherwise.
        """
        if visibility == "public":
            return True

        # Admin bypass: token_teams=None AND user_email=None means unrestricted admin
        if token_teams is None and user_email is None:
            return True

        # No user context (but not admin) → deny non-public items
        if not user_email:
            return False

        # Public-only tokens (empty teams array) can ONLY access public items
        if token_teams is not None and len(token_teams) == 0:
            return False  # Already checked public above

        # Owner can access their own private items
        if visibility == "private" and item_owner_email and item_owner_email == user_email:
            return True

        # Team items: check team membership
        if item_team_id:
            if token_teams is not None:
                team_ids = token_teams
            elif db is not None:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]
            else:
                return False

            if visibility in ("team", "public") and item_team_id in team_ids:
                return True

        return False

    def _get_team_name(self, db: Session, team_id: Optional[str]) -> Optional[str]:
        """Retrieve the team name given a team ID.

        Args:
            db: Database session for querying teams.
            team_id: The ID of the team.

        Returns:
            The name of the team if found, otherwise None.
        """
        if not team_id:
            return None
        team = db.query(EmailTeam).filter(EmailTeam.id == team_id, EmailTeam.is_active.is_(True)).first()
        db.commit()  # Release transaction to avoid idle-in-transaction
        return team.name if team else None

    def _batch_get_team_names(self, db: Session, team_ids: List[str]) -> Dict[str, str]:
        """Batch retrieve team names for multiple team IDs.

        Fetches team names in a single query to avoid N+1 issues
        when converting multiple items to schemas in list operations.

        Args:
            db: Database session for querying teams.
            team_ids: List of team IDs to look up.

        Returns:
            Mapping of team_id -> team_name for active teams.
        """
        if not team_ids:
            return {}
        teams = db.query(EmailTeam.id, EmailTeam.name).filter(EmailTeam.id.in_(team_ids), EmailTeam.is_active.is_(True)).all()
        db.commit()  # Release transaction to avoid idle-in-transaction
        return {team.id: team.name for team in teams}
