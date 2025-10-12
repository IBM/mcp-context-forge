# -*- coding: utf-8 -*-
"""Activity log generators for load testing."""

import random
from datetime import datetime
from typing import Generator, List

from sqlalchemy import text

from mcpgateway.db import (
    TokenUsageLog,
    EmailAuthEvent,
    PermissionAuditLog,
)

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class TokenUsageLogGenerator(BaseGenerator):
    """Generate token usage logs."""

    def get_count(self) -> int:
        """Get total number of usage log records to generate."""
        token_count = self.get_scale_config("users", 100) * self.get_scale_config("tokens_per_user_avg", 3)
        logs_per_token = self.get_scale_config("logs_per_token_avg", 500)
        return int(token_count * logs_per_token)

    def get_dependencies(self) -> List[str]:
        """Depends on tokens."""
        return ["TokenGenerator"]

    def generate(self) -> Generator[TokenUsageLog, None, None]:
        """Generate token usage log records.

        Yields:
            TokenUsageLog instances
        """
        token_result = self.db.execute(text("SELECT jti, user_email FROM email_api_tokens ORDER BY created_at"))
        tokens = [(row[0], row[1]) for row in token_result.fetchall()]

        if not tokens:
            self.logger.warning("No tokens found - cannot generate usage logs")
            return

        min_logs = self.get_scale_config("logs_per_token_min", 50)
        max_logs = self.get_scale_config("logs_per_token_max", 2000)
        avg_logs = self.get_scale_config("logs_per_token_avg", 500)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        endpoints = [
            "/tools",
            "/resources",
            "/prompts",
            "/servers",
            "/gateways",
            "/a2a",
            "/tools/{id}/invoke",
            "/resources/{id}",
            "/prompts/{name}",
        ]

        methods = ["GET", "POST", "PUT", "DELETE"]
        status_codes = [200, 200, 200, 200, 201, 204, 400, 401, 403, 404, 500]

        for token_jti, user_email in tokens:
            num_logs = max(min_logs, min(max_logs, int(random.gauss(avg_logs, avg_logs / 3))))
            timestamps = exponential_decay_temporal(num_logs, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                status_code = random.choice(status_codes)
                blocked = status_code == 429 or (status_code == 403 and random.random() < 0.3)

                yield TokenUsageLog(
                    token_jti=token_jti,
                    user_email=user_email,
                    timestamp=timestamp,
                    endpoint=random.choice(endpoints),
                    method=random.choice(methods),
                    ip_address=f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
                    user_agent=random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "curl/7.68.0",
                        "Python/3.11 aiohttp/3.8.0",
                        "PostmanRuntime/7.32.3",
                    ]),
                    status_code=status_code,
                    response_time_ms=int(random.expovariate(1 / 150)),
                    blocked=blocked,
                    block_reason="Rate limit exceeded" if blocked else None,
                )


class EmailAuthEventGenerator(BaseGenerator):
    """Generate email authentication event logs."""

    def get_count(self) -> int:
        """Get total number of auth event records to generate."""
        user_count = self.get_scale_config("users", 100)
        events_per_user = self.get_scale_config("auth_events_per_user_avg", 50)
        return int(user_count * events_per_user)

    def get_dependencies(self) -> List[str]:
        """Depends on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[EmailAuthEvent, None, None]:
        """Generate auth event records.

        Yields:
            EmailAuthEvent instances
        """
        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        if not user_emails:
            self.logger.warning("No users found - cannot generate auth events")
            return

        min_events = self.get_scale_config("auth_events_per_user_min", 5)
        max_events = self.get_scale_config("auth_events_per_user_max", 200)
        avg_events = self.get_scale_config("auth_events_per_user_avg", 50)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        event_types = ["login", "logout", "password_change", "token_refresh", "mfa_verify"]

        for user_email in user_emails:
            num_events = max(min_events, min(max_events, int(random.gauss(avg_events, avg_events / 3))))
            timestamps = exponential_decay_temporal(num_events, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                event_type = random.choice(event_types)
                success = random.random() < 0.95  # 95% success rate

                yield EmailAuthEvent(
                    timestamp=timestamp,
                    user_email=user_email,
                    event_type=event_type,
                    success=success,
                    ip_address=f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
                    user_agent=random.choice([
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
                        "Mozilla/5.0 (X11; Linux x86_64) Firefox/109.0",
                    ]),
                    failure_reason=None if success else random.choice([
                        "Invalid credentials",
                        "Account locked",
                        "MFA failed",
                        "Session expired",
                    ]),
                    details=None,
                )


class PermissionAuditLogGenerator(BaseGenerator):
    """Generate permission audit logs."""

    def get_count(self) -> int:
        """Get total number of audit log records to generate."""
        user_count = self.get_scale_config("users", 100)
        audits_per_user = self.get_scale_config("permission_audits_per_user_avg", 100)
        return int(user_count * audits_per_user)

    def get_dependencies(self) -> List[str]:
        """Depends on users and teams."""
        return ["UserGenerator", "TeamGenerator"]

    def generate(self) -> Generator[PermissionAuditLog, None, None]:
        """Generate permission audit log records.

        Yields:
            PermissionAuditLog instances
        """
        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        team_result = self.db.execute(text("SELECT id FROM email_teams ORDER BY created_at"))
        team_ids = [row[0] for row in team_result.fetchall()]

        if not user_emails:
            self.logger.warning("No users found - cannot generate permission audits")
            return

        min_audits = self.get_scale_config("permission_audits_per_user_min", 10)
        max_audits = self.get_scale_config("permission_audits_per_user_max", 500)
        avg_audits = self.get_scale_config("permission_audits_per_user_avg", 100)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        permissions = [
            "tool:read",
            "tool:write",
            "tool:delete",
            "resource:read",
            "resource:write",
            "server:read",
            "server:write",
            "team:admin",
        ]

        resource_types = ["tool", "resource", "prompt", "server", "gateway", "team"]

        for user_email in user_emails:
            num_audits = max(min_audits, min(max_audits, int(random.gauss(avg_audits, avg_audits / 3))))
            timestamps = exponential_decay_temporal(num_audits, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                granted = random.random() < 0.85  # 85% granted

                yield PermissionAuditLog(
                    timestamp=timestamp,
                    user_email=user_email,
                    permission=random.choice(permissions),
                    resource_type=random.choice(resource_types),
                    resource_id=f"res-{random.randint(1, 1000)}",
                    team_id=random.choice(team_ids) if team_ids and random.random() < 0.7 else None,
                    granted=granted,
                    roles_checked=["viewer", "developer"] if granted else ["viewer"],
                    ip_address=f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}",
                    user_agent="Mozilla/5.0 (compatible)",
                )
