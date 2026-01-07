# -*- coding: utf-8 -*-
"""Resource generator for load testing."""

import random
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import Resource

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class ResourceGenerator(BaseGenerator):
    """Generate Resource records with realistic distribution."""

    def get_count(self) -> int:
        """Get total number of resources to generate."""
        user_count = self.get_scale_config("users", 100)
        avg_resources = self.get_scale_config("resources_per_user_avg", 100)
        return int(user_count * avg_resources)

    def get_dependencies(self) -> List[str]:
        """Resources depend on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[Resource, None, None]:
        """Generate resource records.

        Yields:
            Resource instances
        """
        user_count = self.get_scale_config("users", 100)
        min_resources = self.get_scale_config("resources_per_user_min", 10)
        max_resources = self.get_scale_config("resources_per_user_max", 200)
        avg_resources = self.get_scale_config("resources_per_user_avg", 100)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Resources per user distribution
        resources_per_user = normal_distribution(user_count, min_resources, max_resources, avg_resources)
        total_resources = sum(resources_per_user)

        timestamps = exponential_decay_temporal(total_resources, start_date, end_date, recent_percent)

        resource_idx = 0

        resource_types = ["document", "dataset", "configuration", "schema", "template"]
        mime_types = ["text/plain", "application/json", "text/markdown", "application/xml"]

        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"
            num_resources = resources_per_user[user_i]

            for j in range(num_resources):
                if resource_idx >= len(timestamps):
                    break

                resource_type = random.choice(resource_types)
                uri = f"resource://{user_email.split('@')[0]}/{resource_type}/{j+1}"

                resource = Resource(
                    uri=uri,
                    name=f"{resource_type}_{j+1}",
                    description=self.faker.sentence(),
                    mime_type=random.choice(mime_types),
                    size=random.randint(100, 100000),
                    created_by=user_email,
                    enabled=True,
                    tags=[],
                    version=1,
                    visibility=random.choice(["public", "private", "team"]),
                    created_at=timestamps[resource_idx],
                    updated_at=timestamps[resource_idx],
                )

                resource_idx += 1
                yield resource
