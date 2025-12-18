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
        # Optimized from 3 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(EmailTeam.id).label("total_teams"),
                func.sum(case((EmailTeam.is_personal.is_(True), 1), else_=0)).label("personal_teams"),
                func.count(EmailTeamMember.id).label("team_members"),
            )
        ).one()

        total_teams = result.total_teams or 0
        personal_teams = result.personal_teams or 0
        team_members = result.team_members or 0

        return {"total": total_teams, "breakdown": {"personal": personal_teams, "organizational": total_teams - personal_teams, "members": team_members}}

    def _get_mcp_resource_stats(self, db: Session) -> Dict[str, Any]:
        """Get MCP resource metrics in a SINGLE query using UNION ALL.

        Optimized from 6 queries to 1.
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
        # Optimized from 3 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(EmailApiToken.id).label("total"),
                func.sum(case((EmailApiToken.is_active.is_(True), 1), else_=0)).label("active"),
                func.count(TokenRevocation.jti).label("revoked"),
            )
        ).one()

        total = result.total or 0
        active = result.active or 0
        revoked = result.revoked or 0

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
        # Optimized from 4 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(SessionRecord.session_id).label("mcp_sessions"),
                func.count(SessionMessageRecord.id).label("mcp_messages"),
                func.count(ResourceSubscription.id).label("subscriptions"),
                func.count(OAuthToken.access_token).label("oauth_tokens"),
            )
        ).one()

        mcp_sessions = result.mcp_sessions or 0
        mcp_messages = result.mcp_messages or 0
        subscriptions = result.subscriptions or 0
        oauth_tokens = result.oauth_tokens or 0
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
        # Optimized from 6 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(ToolMetric.id).label("tool_metrics"),
                func.count(ResourceMetric.id).label("resource_metrics"),
                func.count(PromptMetric.id).label("prompt_metrics"),
                func.count(ServerMetric.id).label("server_metrics"),
                func.count(A2AAgentMetric.id).label("a2a_agent_metrics"),
                func.count(TokenUsageLog.id).label("token_usage_logs"),
            )
        ).one()

        tool_metrics = result.tool_metrics or 0
        resource_metrics = result.resource_metrics or 0
        prompt_metrics = result.prompt_metrics or 0
        server_metrics = result.server_metrics or 0
        a2a_agent_metrics = result.a2a_agent_metrics or 0
        token_usage_logs = result.token_usage_logs or 0
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
        # Optimized from 4 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.count(EmailAuthEvent.id).label("auth_events"),
                func.count(PermissionAuditLog.id).label("audit_logs"),
                func.sum(case((PendingUserApproval.status == "pending", 1), else_=0)).label("pending_approvals"),
                func.sum(case((SSOProvider.is_enabled.is_(True), 1), else_=0)).label("sso_providers"),
            )
        ).one()

        auth_events = result.auth_events or 0
        audit_logs = result.audit_logs or 0
        pending_approvals = result.pending_approvals or 0
        sso_providers = result.sso_providers or 0
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
        # Optimized from 2 queries to 1 using aggregated SELECT
        result = db.execute(
            select(
                func.sum(case((EmailTeamInvitation.is_active.is_(True), 1), else_=0)).label("invitations"),
                func.sum(case((EmailTeamJoinRequest.status == "pending", 1), else_=0)).label("join_requests"),
            )
        ).one()

        invitations = result.invitations or 0
        join_requests = result.join_requests or 0
        total = invitations + join_requests

        return {"total": total, "breakdown": {"team_invitations": invitations, "join_requests": join_requests}}
