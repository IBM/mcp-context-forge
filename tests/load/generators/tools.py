# -*- coding: utf-8 -*-
"""Tool generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import Tool

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class ToolGenerator(BaseGenerator):
    """Generate Tool records with realistic distribution."""

    def get_count(self) -> int:
        """Get total number of tools to generate."""
        gateway_count = self.get_scale_config("gateways", 100)
        avg_tools = self.get_scale_config("tools_per_gateway_avg", 50)
        return int(gateway_count * avg_tools)

    def get_dependencies(self) -> List[str]:
        """Tools depend on gateways."""
        return ["GatewayGenerator"]

    def generate(self) -> Generator[Tool, None, None]:
        """Generate tool records.

        Yields:
            Tool instances
        """
        from sqlalchemy import text

        gateway_count = self.get_scale_config("gateways", 100)
        min_tools = self.get_scale_config("tools_per_gateway_min", 10)
        max_tools = self.get_scale_config("tools_per_gateway_max", 100)
        avg_tools = self.get_scale_config("tools_per_gateway_avg", 50)
        enabled_percent = self.get_scale_config("tools_enabled_percent", 95)

        # Fetch actual gateway IDs from database
        result = self.db.execute(text("SELECT id FROM gateways ORDER BY created_at"))
        gateway_ids = [row[0] for row in result.fetchall()]

        if not gateway_ids:
            self.logger.warning("No gateways found - cannot generate tools")
            return

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Tools per gateway distribution
        tools_per_gateway = normal_distribution(len(gateway_ids), min_tools, max_tools, avg_tools)
        total_tools = sum(tools_per_gateway)

        timestamps = exponential_decay_temporal(total_tools, start_date, end_date, recent_percent)

        tool_idx = 0

        # Common tool names
        tool_names = [
            "list_files", "read_file", "write_file", "search", "query",
            "analyze", "transform", "validate", "process", "execute",
            "get_data", "set_data", "create", "update", "delete"
        ]

        for gateway_i, gateway_id in enumerate(gateway_ids):
            if gateway_i >= len(tools_per_gateway):
                break

            num_tools = tools_per_gateway[gateway_i]

            for j in range(num_tools):
                if tool_idx >= len(timestamps):
                    break

                # Make tool name globally unique by including gateway index
                tool_name = f"{random.choice(tool_names)}_{gateway_i+1}_{j+1}"
                url = f"https://gateway-{gateway_i+1}.example.com/{tool_name}"

                tool = Tool(
                    id=str(uuid.uuid4()),
                    name=tool_name,  # Globally unique name
                    original_name=tool_name,
                    custom_name=tool_name,
                    custom_name_slug=tool_name.lower().replace("_", "-"),
                    url=url,
                    description=self.faker.sentence(),
                    gateway_id=gateway_id,
                    created_by=f"user{random.randint(1, self.get_scale_config('users', 100))}@{self.email_domain}",
                    enabled=random.random() < (enabled_percent / 100),
                    reachable=random.choice([True, True, True, False]),
                    integration_type="MCP",
                    request_type="POST",
                    jsonpath_filter="$",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "input": {"type": "string"}
                        }
                    },
                    annotations={},
                    tags=[],
                    version=1,
                    visibility=random.choice(["public", "private", "team"]),
                    created_at=timestamps[tool_idx],
                    updated_at=timestamps[tool_idx],
                )

                tool_idx += 1
                yield tool
