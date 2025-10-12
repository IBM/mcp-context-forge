# -*- coding: utf-8 -*-
"""Gateway generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import Gateway

from ..utils.distributions import exponential_decay_temporal
from .base import BaseGenerator


class GatewayGenerator(BaseGenerator):
    """Generate Gateway (MCP server) records."""

    def get_count(self) -> int:
        """Get total number of gateways to generate."""
        return self.get_scale_config("gateways", 100)

    def get_dependencies(self) -> List[str]:
        """Gateways have no dependencies."""
        return []

    def generate(self) -> Generator[Gateway, None, None]:
        """Generate gateway records.

        Yields:
            Gateway instances
        """
        count = self.get_count()

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        timestamps = exponential_decay_temporal(count, start_date, end_date, recent_percent)

        for i in range(count):
            gateway_id = str(uuid.uuid4())
            name = f"{self.faker.company()}-mcp-server-{i+1}".lower().replace(" ", "-")

            # Typical MCP server capabilities
            capabilities = {
                "tools": random.choice([True, False]),
                "resources": random.choice([True, False]),
                "prompts": random.choice([True, False]),
            }

            gateway = Gateway(
                id=gateway_id,
                name=name,
                slug=name,
                url=f"https://{name}.example.com:8000",
                description=self.faker.catch_phrase(),
                transport=random.choice(["sse", "stdio", "websocket"]),
                capabilities=capabilities,
                enabled=random.choice([True, True, True, False]),  # 75% enabled
                reachable=random.choice([True, True, True, False]),
                created_at=timestamps[i],
                updated_at=timestamps[i],
                tags=[],
                version=1,
                visibility=random.choice(["public", "private", "team"]),
            )

            yield gateway
