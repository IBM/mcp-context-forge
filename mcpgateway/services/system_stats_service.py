# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/system_stats_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

System Metrics Service Implementation.
This module provides comprehensive system metrics for monitoring deployment scale
and resource utilization across all entity types in the MCP Gateway.

It includes:
- User and team counts (users, teams, memberships)
- MCP resource counts (servers, tools, resources, prompts, A2A agents, gateways)
- API token counts (active, revoked, total)
- Session and activity metrics
- Comprehensive metrics and analytics counts
- Security and audit log counts
- Workflow state tracking

Examples:
    >>> from mcpgateway.services.system_stats_service import SystemStatsService
    >>> service = SystemStatsService()
    >>> # Get all metrics (requires database session)
    >>> # stats = service.get_comprehensive_stats(db)
    >>> # stats["users"]["total"]  # Total user count
    >>> # stats["mcp_resources"]["breakdown"]["tools"]  # Tool count
"""

# Standard
import logging
from typing import Any, Dict

# Third-Party
from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import (
    A2AAgent,
    A2AAgentMetric,
    EmailApiToken,
    EmailAuthEvent,
    EmailTeam,
    EmailTeamInvitation,
    EmailTeamJoinRequest,
    EmailTeamMember,
    EmailUser,
    Gateway,
    OAuthToken,
    PendingUserApproval,
    PermissionAuditLog,
    Prompt,
    PromptMetric,
    Resource,
    ResourceMetric,
    ResourceSubscription,
    Server,
    ServerMetric,
    SessionMessageRecord,
    SessionRecord,
    SSOProvider,
    TokenRevocation,
    TokenUsageLog,
    Tool,
    ToolMetric,
)

logger = logging.getLogger(__name__)

# Cache import (lazy to avoid circular dependencies)
_ADMIN_STATS_CACHE = None


def _get_admin_stats_cache():
    """Get admin stats cache singleton lazily.

    Returns:
        AdminStatsCache instance.
    """
    global _ADMIN_STATS_CACHE  # pylint: disable=global-statement
    if _ADMIN_STATS_CACHE is None:
        # First-Party
        from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

        _ADMIN_STATS_CACHE = admin_stats_cache
    return _ADMIN_STATS_CACHE


# pylint: disable=not-callable
# SQLAlchemy's func.count() is callable at runtime but pylint cannot detect this
class SystemStatsService:
    """Service for retrieving comprehensive system metrics.

    This service provides read-only access to system-wide metrics across
    all entity types, providing administrators with at-a-glance visibility
    into deployment scale and resource utilization.

    Examples:
        >>> service = SystemStatsService()
        >>> # With database session
        >>> # stats = service.get_comprehensive_stats(db)
        >>> # print(f"Total users: {stats['users']['total']}")
        >>> # print(f"Total tools: {stats['mcp_resources']['breakdown']['tools']}")
    """

    def get_comprehensive_stats(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive system metrics across all categories.

        Args:
            db: Database session for querying metrics

        Returns:
            Dictionary containing categorized metrics with totals and breakdowns

        Raises:
            Exception: If database queries fail or metrics collection encounters errors

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service.get_comprehensive_stats(db)
            >>> # assert "users" in stats
            >>> # assert "mcp_resources" in stats
            >>> # assert "total" in stats["users"]
            >>> # assert "breakdown" in stats["users"]
        """
        logger.info("Collecting comprehensive system metrics")

        try:
            stats = {
                "users": self._get_user_stats(db),
                "teams": self._get_team_stats(db),
                "mcp_resources": self._get_mcp_resource_stats(db),
                "tokens": self._get_token_stats(db),
                "sessions": self._get_session_stats(db),
                "metrics": self._get_metrics_stats(db),
                "security": self._get_security_stats(db),
                "workflow": self._get_workflow_stats(db),
            }

            logger.info("Successfully collected system metrics")
            return stats

        except Exception as e:
            logger.error(f"Error collecting system metrics: {str(e)}")
            raise

    async def get_comprehensive_stats_cached(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive system metrics with caching.

        This is the async-friendly version that uses the admin stats cache.
        Call this from async endpoints for optimal performance.

        Args:
            db: Database session for querying metrics

        Returns:
            Dictionary containing categorized metrics with totals and breakdowns

        Examples:
            >>> service = SystemStatsService()
            >>> # import asyncio
            >>> # stats = asyncio.run(service.get_comprehensive_stats_cached(db))
        """
        cache = _get_admin_stats_cache()
        cached = await cache.get_system_stats()
        if cached is not None:
            return cached

        # Cache miss - compute and cache
        stats = self.get_comprehensive_stats(db)
        await cache.set_system_stats(stats)
        return stats

    def _get_user_stats(self, db: Session) -> Dict[str, Any]:
        """Get user-related metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total user count and breakdown by status

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_user_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "breakdown" in stats
            >>> # assert "active" in stats["breakdown"]
        """
        # Optimized from 3 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(EmailUser.email).label("total"),
                func.sum(case((EmailUser.is_active.is_(True), 1), else_=0)).label("active"),
                func.sum(case((EmailUser.is_admin.is_(True), 1), else_=0)).label("admins"),
            )
        ).one()

        total = result.total or 0
        active = result.active or 0
        admins = result.admins or 0

        return {"total": total, "breakdown": {"active": active, "inactive": total - active, "admins": admins}}

    def _get_team_stats(self, db: Session) -> Dict[str, Any]:
        """Get team-related metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total team count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_team_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "personal" in stats["breakdown"]
            >>> # assert "organizational" in stats["breakdown"]
        """
        # Optimized from 3 queries to 2 using aggregated SELECT (separate tables need separate queries)
        team_result = db.execute(
            select(
                func.count(EmailTeam.id).label("total_teams"),
                func.sum(case((EmailTeam.is_personal.is_(True), 1), else_=0)).label("personal_teams"),
            ).select_from(EmailTeam)
        ).one()
        team_members = db.execute(select(func.count(EmailTeamMember.id))).scalar() or 0

        total_teams = team_result.total_teams or 0
        personal_teams = team_result.personal_teams or 0

        return {"total": total_teams, "breakdown": {"personal": personal_teams, "organizational": total_teams - personal_teams, "members": team_members}}

    def _get_mcp_resource_stats(self, db: Session) -> Dict[str, Any]:
        """Get MCP resource metrics in a SINGLE query using UNION ALL.

        Optimized from 6 queries to 1.

        Args:
            db: Database session

        Returns:
            Dictionary with total MCP resource count and breakdown by type
        """
        # Create a single query that combines counts from all tables with consistent column labels
        stmt = (
            select(literal("servers").label("type"), func.count(Server.id).label("cnt"))
            .select_from(Server)
            .union_all(
                select(literal("gateways").label("type"), func.count(Gateway.id).label("cnt")).select_from(Gateway),
                select(literal("tools").label("type"), func.count(Tool.id).label("cnt")).select_from(Tool),
                select(literal("resources").label("type"), func.count(Resource.uri).label("cnt")).select_from(Resource),
                select(literal("prompts").label("type"), func.count(Prompt.name).label("cnt")).select_from(Prompt),
                select(literal("a2a_agents").label("type"), func.count(A2AAgent.id).label("cnt")).select_from(A2AAgent),
            )
        )

        # Execute once - this is now a single database query instead of 6 separate queries
        results = db.execute(stmt).all()

        # Convert list of rows to a dictionary
        counts = {row.type: row.cnt for row in results}

        # Safe lookups (defaults to 0 if table is empty)
        servers = counts.get("servers", 0)
        gateways = counts.get("gateways", 0)
        tools = counts.get("tools", 0)
        resources = counts.get("resources", 0)
        prompts = counts.get("prompts", 0)
        agents = counts.get("a2a_agents", 0)

        total = servers + gateways + tools + resources + prompts + agents

        return {"total": total, "breakdown": {"servers": servers, "gateways": gateways, "tools": tools, "resources": resources, "prompts": prompts, "a2a_agents": agents}}

    def _get_token_stats(self, db: Session) -> Dict[str, Any]:
        """Get API token metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total token count and breakdown by status

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_token_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "active" in stats["breakdown"]
        """
        # Optimized from 3 queries to 2 using aggregated SELECT (separate tables need separate queries)
        token_result = db.execute(
            select(
                func.count(EmailApiToken.id).label("total"),
                func.sum(case((EmailApiToken.is_active.is_(True), 1), else_=0)).label("active"),
            ).select_from(EmailApiToken)
        ).one()
        revoked = db.execute(select(func.count(TokenRevocation.jti))).scalar() or 0

        total = token_result.total or 0
        active = token_result.active or 0

        return {"total": total, "breakdown": {"active": active, "inactive": total - active, "revoked": revoked}}

    def _get_session_stats(self, db: Session) -> Dict[str, Any]:
        """Get session and activity metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total session count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_session_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "mcp_sessions" in stats["breakdown"]
        """
        # Optimized from 4 queries to 1 using UNION ALL (separate tables need separate selects)
        stmt = (
            select(literal("mcp_sessions").label("type"), func.count(SessionRecord.session_id).label("cnt"))
            .select_from(SessionRecord)
            .union_all(
                select(literal("mcp_messages").label("type"), func.count(SessionMessageRecord.id).label("cnt")).select_from(SessionMessageRecord),
                select(literal("subscriptions").label("type"), func.count(ResourceSubscription.id).label("cnt")).select_from(ResourceSubscription),
                select(literal("oauth_tokens").label("type"), func.count(OAuthToken.access_token).label("cnt")).select_from(OAuthToken),
            )
        )
        results = db.execute(stmt).all()
        counts = {row.type: row.cnt for row in results}

        mcp_sessions = counts.get("mcp_sessions", 0)
        mcp_messages = counts.get("mcp_messages", 0)
        subscriptions = counts.get("subscriptions", 0)
        oauth_tokens = counts.get("oauth_tokens", 0)
        total = mcp_sessions + mcp_messages + subscriptions + oauth_tokens

        return {"total": total, "breakdown": {"mcp_sessions": mcp_sessions, "mcp_messages": mcp_messages, "subscriptions": subscriptions, "oauth_tokens": oauth_tokens}}

    def _get_metrics_stats(self, db: Session) -> Dict[str, Any]:
        """Get metrics and analytics counts.

        Args:
            db: Database session

        Returns:
            Dictionary with total metrics count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_metrics_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "tool_metrics" in stats["breakdown"]
        """
        # Optimized from 6 queries to 1 using UNION ALL (separate tables need separate selects)
        stmt = (
            select(literal("tool_metrics").label("type"), func.count(ToolMetric.id).label("cnt"))
            .select_from(ToolMetric)
            .union_all(
                select(literal("resource_metrics").label("type"), func.count(ResourceMetric.id).label("cnt")).select_from(ResourceMetric),
                select(literal("prompt_metrics").label("type"), func.count(PromptMetric.id).label("cnt")).select_from(PromptMetric),
                select(literal("server_metrics").label("type"), func.count(ServerMetric.id).label("cnt")).select_from(ServerMetric),
                select(literal("a2a_agent_metrics").label("type"), func.count(A2AAgentMetric.id).label("cnt")).select_from(A2AAgentMetric),
                select(literal("token_usage_logs").label("type"), func.count(TokenUsageLog.id).label("cnt")).select_from(TokenUsageLog),
            )
        )
        results = db.execute(stmt).all()
        counts = {row.type: row.cnt for row in results}

        tool_metrics = counts.get("tool_metrics", 0)
        resource_metrics = counts.get("resource_metrics", 0)
        prompt_metrics = counts.get("prompt_metrics", 0)
        server_metrics = counts.get("server_metrics", 0)
        a2a_agent_metrics = counts.get("a2a_agent_metrics", 0)
        token_usage_logs = counts.get("token_usage_logs", 0)
        total = tool_metrics + resource_metrics + prompt_metrics + server_metrics + a2a_agent_metrics + token_usage_logs

        return {
            "total": total,
            "breakdown": {
                "tool_metrics": tool_metrics,
                "resource_metrics": resource_metrics,
                "prompt_metrics": prompt_metrics,
                "server_metrics": server_metrics,
                "a2a_agent_metrics": a2a_agent_metrics,
                "token_usage_logs": token_usage_logs,
            },
        }

    def _get_security_stats(self, db: Session) -> Dict[str, Any]:
        """Get security and audit metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total security event count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_security_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "auth_events" in stats["breakdown"]
        """
        # Optimized from 4 queries to 1 using UNION ALL (separate tables need separate selects)
        stmt = (
            select(literal("auth_events").label("type"), func.count(EmailAuthEvent.id).label("cnt"))
            .select_from(EmailAuthEvent)
            .union_all(
                select(literal("audit_logs").label("type"), func.count(PermissionAuditLog.id).label("cnt")).select_from(PermissionAuditLog),
                select(literal("pending_approvals").label("type"), func.count(PendingUserApproval.id).label("cnt")).select_from(PendingUserApproval).where(PendingUserApproval.status == "pending"),
                select(literal("sso_providers").label("type"), func.count(SSOProvider.id).label("cnt")).select_from(SSOProvider).where(SSOProvider.is_enabled.is_(True)),
            )
        )
        results = db.execute(stmt).all()
        counts = {row.type: row.cnt for row in results}

        auth_events = counts.get("auth_events", 0)
        audit_logs = counts.get("audit_logs", 0)
        pending_approvals = counts.get("pending_approvals", 0)
        sso_providers = counts.get("sso_providers", 0)
        total = auth_events + audit_logs + pending_approvals

        return {"total": total, "breakdown": {"auth_events": auth_events, "audit_logs": audit_logs, "pending_approvals": pending_approvals, "sso_providers": sso_providers}}

    def _get_workflow_stats(self, db: Session) -> Dict[str, Any]:
        """Get workflow state metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total workflow item count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_workflow_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "team_invitations" in stats["breakdown"]
        """
        # Optimized from 2 queries to 1 using UNION ALL (separate tables need separate selects)
        stmt = (
            select(literal("invitations").label("type"), func.count(EmailTeamInvitation.id).label("cnt"))
            .select_from(EmailTeamInvitation)
            .where(EmailTeamInvitation.is_active.is_(True))
            .union_all(
                select(literal("join_requests").label("type"), func.count(EmailTeamJoinRequest.id).label("cnt")).select_from(EmailTeamJoinRequest).where(EmailTeamJoinRequest.status == "pending"),
            )
        )
        results = db.execute(stmt).all()
        counts = {row.type: row.cnt for row in results}

        invitations = counts.get("invitations", 0)
        join_requests = counts.get("join_requests", 0)
        total = invitations + join_requests

        return {"total": total, "breakdown": {"team_invitations": invitations, "join_requests": join_requests}}
