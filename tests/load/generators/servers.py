# -*- coding: utf-8 -*-
"""Virtual server generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import Server

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class ServerGenerator(BaseGenerator):
    """Generate Server (virtual server) records."""

    def get_count(self) -> int:
        """Get total number of servers to generate."""
        user_count = self.get_scale_config("users", 100)
        avg_servers = self.get_scale_config("servers_per_user_avg", 10)
        return int(user_count * avg_servers)

    def get_dependencies(self) -> List[str]:
        """Servers depend on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[Server, None, None]:
        """Generate virtual server records.

        Yields:
            Server instances
        """
        user_count = self.get_scale_config("users", 100)
        min_servers = self.get_scale_config("servers_per_user_min", 1)
        max_servers = self.get_scale_config("servers_per_user_max", 20)
        avg_servers = self.get_scale_config("servers_per_user_avg", 10)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Servers per user distribution
        servers_per_user = normal_distribution(user_count, min_servers, max_servers, avg_servers)
        total_servers = sum(servers_per_user)

        timestamps = exponential_decay_temporal(total_servers, start_date, end_date, recent_percent)

        server_idx = 0

        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"
            num_servers = servers_per_user[user_i]

            for j in range(num_servers):
                if server_idx >= len(timestamps):
                    break

                server_id = str(uuid.uuid4())
                name = f"{self.faker.word()}-server-{user_i+1}-{j+1}"

                server = Server(
                    id=server_id,
                    name=name,
                    description=self.faker.sentence(),
                    created_by=user_email,
                    enabled=random.choice([True, True, True, False]),  # 75% active
                    tags=[],
                    version=1,
                    visibility=random.choice(["public", "private", "team"]),
                    created_at=timestamps[server_idx],
                    updated_at=timestamps[server_idx],
                )

                server_idx += 1
                yield server
