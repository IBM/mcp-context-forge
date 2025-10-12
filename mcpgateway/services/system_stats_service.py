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
from sqlalchemy import func
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
        total = db.query(func.count(EmailUser.email)).scalar() or 0
        active = db.query(func.count(EmailUser.email)).filter(EmailUser.is_active.is_(True)).scalar() or 0
        admins = db.query(func.count(EmailUser.email)).filter(EmailUser.is_admin.is_(True)).scalar() or 0

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
        total_teams = db.query(func.count(EmailTeam.id)).scalar() or 0
        personal_teams = db.query(func.count(EmailTeam.id)).filter(EmailTeam.is_personal.is_(True)).scalar() or 0
        team_members = db.query(func.count(EmailTeamMember.id)).scalar() or 0

        return {"total": total_teams, "breakdown": {"personal": personal_teams, "organizational": total_teams - personal_teams, "members": team_members}}

    def _get_mcp_resource_stats(self, db: Session) -> Dict[str, Any]:
        """Get MCP resource metrics.

        Args:
            db: Database session

        Returns:
            Dictionary with total MCP resource count and breakdown by type

        Examples:
            >>> service = SystemStatsService()
            >>> # stats = service._get_mcp_resource_stats(db)
            >>> # assert stats["total"] >= 0
            >>> # assert "tools" in stats["breakdown"]
            >>> # assert "servers" in stats["breakdown"]
        """
        servers = db.query(func.count(Server.id)).scalar() or 0
        gateways = db.query(func.count(Gateway.id)).scalar() or 0
        tools = db.query(func.count(Tool.id)).scalar() or 0
        resources = db.query(func.count(Resource.uri)).scalar() or 0
        prompts = db.query(func.count(Prompt.name)).scalar() or 0
        a2a_agents = db.query(func.count(A2AAgent.id)).scalar() or 0

        total = servers + gateways + tools + resources + prompts + a2a_agents

        return {"total": total, "breakdown": {"servers": servers, "gateways": gateways, "tools": tools, "resources": resources, "prompts": prompts, "a2a_agents": a2a_agents}}

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
        total = db.query(func.count(EmailApiToken.id)).scalar() or 0
        active = db.query(func.count(EmailApiToken.id)).filter(EmailApiToken.is_active.is_(True)).scalar() or 0
        revoked = db.query(func.count(TokenRevocation.jti)).scalar() or 0

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
        mcp_sessions = db.query(func.count(SessionRecord.session_id)).scalar() or 0
        mcp_messages = db.query(func.count(SessionMessageRecord.id)).scalar() or 0
        subscriptions = db.query(func.count(ResourceSubscription.id)).scalar() or 0
        oauth_tokens = db.query(func.count(OAuthToken.access_token)).scalar() or 0

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
        tool_metrics = db.query(func.count(ToolMetric.id)).scalar() or 0
        resource_metrics = db.query(func.count(ResourceMetric.id)).scalar() or 0
        prompt_metrics = db.query(func.count(PromptMetric.id)).scalar() or 0
        server_metrics = db.query(func.count(ServerMetric.id)).scalar() or 0
        a2a_agent_metrics = db.query(func.count(A2AAgentMetric.id)).scalar() or 0
        token_usage_logs = db.query(func.count(TokenUsageLog.id)).scalar() or 0

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
        auth_events = db.query(func.count(EmailAuthEvent.id)).scalar() or 0
        audit_logs = db.query(func.count(PermissionAuditLog.id)).scalar() or 0
        pending_approvals = db.query(func.count(PendingUserApproval.id)).filter(PendingUserApproval.status == "pending").scalar() or 0
        sso_providers = db.query(func.count(SSOProvider.id)).filter(SSOProvider.is_enabled.is_(True)).scalar() or 0

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
        invitations = db.query(func.count(EmailTeamInvitation.id)).filter(EmailTeamInvitation.is_active.is_(True)).scalar() or 0
        join_requests = db.query(func.count(EmailTeamJoinRequest.id)).filter(EmailTeamJoinRequest.status == "pending").scalar() or 0

        total = invitations + join_requests

        return {"total": total, "breakdown": {"team_invitations": invitations, "join_requests": join_requests}}
