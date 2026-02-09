# -*- coding: utf-8 -*-
"""A2A agent populator - creates A2A agents via POST /a2a."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

A2A_PROTOCOLS = ["1.0", "1.1"]
A2A_CAPABILITIES = [
    {"streaming": True, "tools": True},
    {"streaming": False, "tools": True},
    {"streaming": True, "tools": False},
    {"streaming": True, "tools": True, "resources": True},
]


class A2AAgentPopulator(BasePopulator):
    """Create A2A agents via REST API."""

    def get_name(self) -> str:
        return "a2a_agents"

    def get_count(self) -> int:
        users = self.get_scale_config("users", 100)
        avg = self.get_scale_config("a2a_agents_per_user_avg", 1)
        return int(users * avg)

    def get_dependencies(self) -> List[str]:
        return ["users"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        min_agents = self.get_scale_config("a2a_agents_per_user_min", 0)
        max_agents = self.get_scale_config("a2a_agents_per_user_max", 3)

        payloads = []
        for user_i in range(user_count):
            num_agents = random.randint(min_agents, max_agents)

            for j in range(num_agents):
                name = f"{self.faker.word()}-agent-{user_i + 1}-{j + 1}"
                payloads.append(
                    {
                        "agent": {
                            "name": name,
                            "endpoint_url": f"https://{name}.{self.email_domain}:9000",
                            "protocol_version": random.choice(A2A_PROTOCOLS),
                            "capabilities": random.choice(A2A_CAPABILITIES),
                        },
                        "team_id": None,
                        "visibility": "public",
                    }
                )

        result = await self._batch_create(payloads, "/a2a", id_field="id")
        self.existing_data["a2a_agent_ids"] = result["ids"]
        return result
