# -*- coding: utf-8 -*-
"""Metrics generators for load testing."""

import random
from datetime import datetime, timedelta
from typing import Generator, List

from sqlalchemy import text

from mcpgateway.db import (
    ToolMetric,
    ResourceMetric,
    PromptMetric,
    ServerMetric,
    A2AAgentMetric,
)

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class ToolMetricsGenerator(BaseGenerator):
    """Generate tool usage metrics."""

    def get_count(self) -> int:
        """Get total number of metric records to generate."""
        tool_count = self.get_scale_config("gateways", 100) * self.get_scale_config("tools_per_gateway_avg", 50)
        metrics_per_tool = self.get_scale_config("metrics_per_tool_avg", 100)
        return int(tool_count * metrics_per_tool)

    def get_dependencies(self) -> List[str]:
        """Depends on tools."""
        return ["ToolGenerator"]

    def generate(self) -> Generator[ToolMetric, None, None]:
        """Generate tool metric records.

        Yields:
            ToolMetric instances
        """
        tool_result = self.db.execute(text("SELECT id FROM tools ORDER BY created_at"))
        tool_ids = [row[0] for row in tool_result.fetchall()]

        if not tool_ids:
            self.logger.warning("No tools found - cannot generate metrics")
            return

        min_metrics = self.get_scale_config("metrics_per_tool_min", 10)
        max_metrics = self.get_scale_config("metrics_per_tool_max", 500)
        avg_metrics = self.get_scale_config("metrics_per_tool_avg", 100)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for tool_id in tool_ids:
            num_metrics = max(min_metrics, min(max_metrics, int(random.gauss(avg_metrics, avg_metrics / 3))))
            timestamps = exponential_decay_temporal(num_metrics, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                # 95% success rate
                is_success = random.random() < 0.95
                response_time = random.expovariate(1 / 150) if is_success else random.expovariate(1 / 500)

                yield ToolMetric(
                    tool_id=tool_id,
                    timestamp=timestamp,
                    response_time=round(response_time, 2),
                    is_success=is_success,
                    error_message=None if is_success else random.choice([
                        "Connection timeout",
                        "Rate limit exceeded",
                        "Invalid request",
                        "Gateway unavailable",
                    ]),
                )


class ResourceMetricsGenerator(BaseGenerator):
    """Generate resource access metrics."""

    def get_count(self) -> int:
        """Get total number of metric records to generate."""
        user_count = self.get_scale_config("users", 100)
        resources_per_user = self.get_scale_config("resources_per_user_avg", 100)
        metrics_per_resource = self.get_scale_config("metrics_per_resource_avg", 50)
        return int(user_count * resources_per_user * metrics_per_resource)

    def get_dependencies(self) -> List[str]:
        """Depends on resources."""
        return ["ResourceGenerator"]

    def generate(self) -> Generator[ResourceMetric, None, None]:
        """Generate resource metric records.

        Yields:
            ResourceMetric instances
        """
        resource_result = self.db.execute(text("SELECT id FROM resources ORDER BY created_at"))
        resource_ids = [row[0] for row in resource_result.fetchall()]

        if not resource_ids:
            self.logger.warning("No resources found - cannot generate metrics")
            return

        min_metrics = self.get_scale_config("metrics_per_resource_min", 5)
        max_metrics = self.get_scale_config("metrics_per_resource_max", 200)
        avg_metrics = self.get_scale_config("metrics_per_resource_avg", 50)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for resource_id in resource_ids:
            num_metrics = max(min_metrics, min(max_metrics, int(random.gauss(avg_metrics, avg_metrics / 3))))
            timestamps = exponential_decay_temporal(num_metrics, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                is_success = random.random() < 0.97
                response_time = random.expovariate(1 / 80) if is_success else random.expovariate(1 / 300)

                yield ResourceMetric(
                    resource_id=resource_id,
                    timestamp=timestamp,
                    response_time=round(response_time, 2),
                    is_success=is_success,
                    error_message=None if is_success else random.choice([
                        "Resource not found",
                        "Access denied",
                        "Resource unavailable",
                    ]),
                )


class PromptMetricsGenerator(BaseGenerator):
    """Generate prompt usage metrics."""

    def get_count(self) -> int:
        """Get total number of metric records to generate."""
        user_count = self.get_scale_config("users", 100)
        prompts_per_user = self.get_scale_config("prompts_per_user_avg", 100)
        metrics_per_prompt = self.get_scale_config("metrics_per_prompt_avg", 30)
        return int(user_count * prompts_per_user * metrics_per_prompt)

    def get_dependencies(self) -> List[str]:
        """Depends on prompts."""
        return ["PromptGenerator"]

    def generate(self) -> Generator[PromptMetric, None, None]:
        """Generate prompt metric records.

        Yields:
            PromptMetric instances
        """
        prompt_result = self.db.execute(text("SELECT id FROM prompts ORDER BY created_at"))
        prompt_ids = [row[0] for row in prompt_result.fetchall()]

        if not prompt_ids:
            self.logger.warning("No prompts found - cannot generate metrics")
            return

        min_metrics = self.get_scale_config("metrics_per_prompt_min", 5)
        max_metrics = self.get_scale_config("metrics_per_prompt_max", 150)
        avg_metrics = self.get_scale_config("metrics_per_prompt_avg", 30)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for prompt_id in prompt_ids:
            num_metrics = max(min_metrics, min(max_metrics, int(random.gauss(avg_metrics, avg_metrics / 3))))
            timestamps = exponential_decay_temporal(num_metrics, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                is_success = random.random() < 0.96
                response_time = random.expovariate(1 / 100) if is_success else random.expovariate(1 / 400)

                yield PromptMetric(
                    prompt_id=prompt_id,
                    timestamp=timestamp,
                    response_time=round(response_time, 2),
                    is_success=is_success,
                    error_message=None if is_success else "Prompt execution failed",
                )


class ServerMetricsGenerator(BaseGenerator):
    """Generate server usage metrics."""

    def get_count(self) -> int:
        """Get total number of metric records to generate."""
        user_count = self.get_scale_config("users", 100)
        servers_per_user = self.get_scale_config("servers_per_user_avg", 10)
        metrics_per_server = self.get_scale_config("metrics_per_server_avg", 200)
        return int(user_count * servers_per_user * metrics_per_server)

    def get_dependencies(self) -> List[str]:
        """Depends on servers."""
        return ["ServerGenerator"]

    def generate(self) -> Generator[ServerMetric, None, None]:
        """Generate server metric records.

        Yields:
            ServerMetric instances
        """
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        if not server_ids:
            self.logger.warning("No servers found - cannot generate metrics")
            return

        min_metrics = self.get_scale_config("metrics_per_server_min", 20)
        max_metrics = self.get_scale_config("metrics_per_server_max", 1000)
        avg_metrics = self.get_scale_config("metrics_per_server_avg", 200)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for server_id in server_ids:
            num_metrics = max(min_metrics, min(max_metrics, int(random.gauss(avg_metrics, avg_metrics / 3))))
            timestamps = exponential_decay_temporal(num_metrics, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                is_success = random.random() < 0.98
                response_time = random.expovariate(1 / 200) if is_success else random.expovariate(1 / 800)

                yield ServerMetric(
                    server_id=server_id,
                    timestamp=timestamp,
                    response_time=round(response_time, 2),
                    is_success=is_success,
                    error_message=None if is_success else "Server error",
                )


class A2AAgentMetricsGenerator(BaseGenerator):
    """Generate A2A agent usage metrics."""

    def get_count(self) -> int:
        """Get total number of metric records to generate."""
        user_count = self.get_scale_config("users", 100)
        agents_per_user = self.get_scale_config("a2a_agents_per_user_avg", 2)
        metrics_per_agent = self.get_scale_config("metrics_per_a2a_agent_avg", 150)
        return int(user_count * agents_per_user * metrics_per_agent)

    def get_dependencies(self) -> List[str]:
        """Depends on A2A agents."""
        return ["A2AAgentGenerator"]

    def generate(self) -> Generator[A2AAgentMetric, None, None]:
        """Generate A2A agent metric records.

        Yields:
            A2AAgentMetric instances
        """
        agent_result = self.db.execute(text("SELECT id FROM a2a_agents ORDER BY created_at"))
        agent_ids = [row[0] for row in agent_result.fetchall()]

        if not agent_ids:
            self.logger.info("No A2A agents found - skipping metrics generation")
            return

        min_metrics = self.get_scale_config("metrics_per_a2a_agent_min", 10)
        max_metrics = self.get_scale_config("metrics_per_a2a_agent_max", 500)
        avg_metrics = self.get_scale_config("metrics_per_a2a_agent_avg", 150)

        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        for agent_id in agent_ids:
            num_metrics = max(min_metrics, min(max_metrics, int(random.gauss(avg_metrics, avg_metrics / 3))))
            timestamps = exponential_decay_temporal(num_metrics, start_date, end_date, recent_percent)

            for timestamp in timestamps:
                is_success = random.random() < 0.94
                response_time = random.expovariate(1 / 1200) if is_success else random.expovariate(1 / 3000)
                tokens_used = random.randint(50, 2000) if is_success else 0

                yield A2AAgentMetric(
                    a2a_agent_id=agent_id,
                    timestamp=timestamp,
                    response_time=round(response_time, 2),
                    is_success=is_success,
                    interaction_type=random.choice(["text_generation", "code_generation", "analysis", "translation"]),
                    error_message=None if is_success else random.choice([
                        "API rate limit exceeded",
                        "Authentication failed",
                        "Model unavailable",
                        "Request timeout",
                    ]),
                )
