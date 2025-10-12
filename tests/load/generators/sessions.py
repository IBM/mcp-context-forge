# -*- coding: utf-8 -*-
"""MCP session and subscription generators for load testing."""

import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Generator, List

from sqlalchemy import text

from mcpgateway.db import (
    SessionRecord,
    SessionMessageRecord,
    ResourceSubscription,
)

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class MCPSessionGenerator(BaseGenerator):
    """Generate MCP protocol sessions."""

    def get_count(self) -> int:
        """Get total number of MCP sessions to generate."""
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        sessions_per_server = self.get_scale_config("mcp_sessions_per_server_avg", 10)
        return int(server_count * sessions_per_server)

    def get_dependencies(self) -> List[str]:
        """Depends on servers."""
        return ["ServerGenerator"]

    def generate(self) -> Generator[SessionRecord, None, None]:
        """Generate MCP session records.

        Yields:
            SessionRecord instances
        """
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        if not server_ids:
            self.logger.warning("No servers found - cannot generate MCP sessions")
            return

        min_sessions = self.get_scale_config("mcp_sessions_per_server_min", 1)
        max_sessions = self.get_scale_config("mcp_sessions_per_server_max", 50)
        avg_sessions = self.get_scale_config("mcp_sessions_per_server_avg", 10)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for server_id in server_ids:
            num_sessions = max(min_sessions, min(max_sessions, int(random.gauss(avg_sessions, avg_sessions / 3))))
            timestamps = exponential_decay_temporal(num_sessions, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                session_id = str(uuid.uuid4())
                last_accessed = timestamp + timedelta(minutes=random.randint(1, 120))

                data = {
                    "server_id": server_id,
                    "client_info": {
                        "name": random.choice(["mcp-client", "claude-desktop", "custom-client"]),
                        "version": f"{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,20)}",
                    },
                    "transport": random.choice(["sse", "websocket", "stdio"]),
                }

                yield SessionRecord(
                    session_id=session_id,
                    created_at=timestamp,
                    last_accessed=last_accessed,
                    data=json.dumps(data),
                )


class MCPMessageGenerator(BaseGenerator):
    """Generate MCP protocol messages."""

    def get_count(self) -> int:
        """Get total number of MCP messages to generate."""
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        sessions_per_server = self.get_scale_config("mcp_sessions_per_server_avg", 10)
        messages_per_session = self.get_scale_config("mcp_messages_per_session_avg", 20)
        return int(server_count * sessions_per_server * messages_per_session)

    def get_dependencies(self) -> List[str]:
        """Depends on MCP sessions."""
        return ["MCPSessionGenerator"]

    def generate(self) -> Generator[SessionMessageRecord, None, None]:
        """Generate MCP message records.

        Yields:
            SessionMessageRecord instances
        """
        session_result = self.db.execute(text("SELECT session_id, created_at FROM mcp_sessions ORDER BY created_at"))
        sessions = [(row[0], datetime.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]) for row in session_result.fetchall()]

        if not sessions:
            self.logger.warning("No MCP sessions found - cannot generate messages")
            return

        min_messages = self.get_scale_config("mcp_messages_per_session_min", 5)
        max_messages = self.get_scale_config("mcp_messages_per_session_max", 100)
        avg_messages = self.get_scale_config("mcp_messages_per_session_avg", 20)

        message_types = [
            {"jsonrpc": "2.0", "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "example_tool"}},
            {"jsonrpc": "2.0", "method": "resources/list", "params": {}},
            {"jsonrpc": "2.0", "method": "resources/read", "params": {"uri": "file:///example"}},
            {"jsonrpc": "2.0", "method": "prompts/list", "params": {}},
            {"jsonrpc": "2.0", "method": "prompts/get", "params": {"name": "example_prompt"}},
        ]

        for session_id, session_created in sessions:
            num_messages = max(min_messages, min(max_messages, int(random.gauss(avg_messages, avg_messages / 3))))

            for i in range(num_messages):
                created_at = session_created + timedelta(seconds=random.randint(1, 3600))
                last_accessed = created_at + timedelta(milliseconds=random.randint(10, 5000))

                yield SessionMessageRecord(
                    session_id=session_id,
                    message=json.dumps(random.choice(message_types)),
                    created_at=created_at,
                    last_accessed=last_accessed,
                )


class ResourceSubscriptionGenerator(BaseGenerator):
    """Generate resource subscriptions."""

    def get_count(self) -> int:
        """Get total number of resource subscriptions to generate."""
        user_count = self.get_scale_config("users", 100)
        resources_per_user = self.get_scale_config("resources_per_user_avg", 100)
        subscription_rate = self.get_scale_config("resource_subscription_rate", 0.1)  # 10% subscribed
        return int(user_count * resources_per_user * subscription_rate)

    def get_dependencies(self) -> List[str]:
        """Depends on resources and users."""
        return ["ResourceGenerator", "UserGenerator"]

    def generate(self) -> Generator[ResourceSubscription, None, None]:
        """Generate resource subscription records.

        Yields:
            ResourceSubscription instances
        """
        resource_result = self.db.execute(text("SELECT id FROM resources ORDER BY created_at"))
        resource_ids = [row[0] for row in resource_result.fetchall()]

        user_result = self.db.execute(text("SELECT email FROM email_users ORDER BY created_at"))
        user_emails = [row[0] for row in user_result.fetchall()]

        if not resource_ids or not user_emails:
            self.logger.warning("No resources or users found - cannot generate subscriptions")
            return

        subscription_rate = self.get_scale_config("resource_subscription_rate", 0.1)
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))

        # Create subscriptions for a random sample of resources
        num_subscriptions = int(len(resource_ids) * subscription_rate)
        sampled_resources = random.sample(resource_ids, min(num_subscriptions, len(resource_ids)))

        for resource_id in sampled_resources:
            # Each resource can have multiple subscribers
            num_subscribers = random.randint(1, min(5, len(user_emails)))
            selected_subscribers = random.sample(user_emails, num_subscribers)

            for subscriber_email in selected_subscribers:
                created_at = start_date + (end_date - start_date) * random.random()
                last_notification = created_at + timedelta(days=random.randint(1, 30)) if random.random() < 0.5 else None

                yield ResourceSubscription(
                    resource_id=resource_id,
                    subscriber_id=subscriber_email,
                    created_at=created_at,
                    last_notification=last_notification,
                )
