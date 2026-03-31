# -*- coding: utf-8 -*-
"""A2A agent populator - creates A2A agents via POST /a2a."""

# Standard
import random
from typing import Any, Dict, List
import uuid

# Local
from .base import BasePopulator
from mcpgateway.db import A2AAgent, utc_now
from mcpgateway.utils.create_slug import slugify

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

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(user_count, min_agents, max_agents)

        # REST API mode (original implementation)
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

    async def _populate_bulk(self, user_count: int, min_agents: int, max_agents: int) -> Dict[str, Any]:
        """Bulk insert A2A agents directly into database for performance."""
        now = utc_now()
        mappings = []
        agent_ids = []

        for user_i in range(user_count):
            email = f"user{user_i + 1}@{self.email_domain}"
            num_agents = random.randint(min_agents, max_agents)

            for j in range(num_agents):
                agent_id = uuid.uuid4().hex
                agent_ids.append(agent_id)
                name = f"{self.faker.word()}-agent-{user_i + 1}-{j + 1}"
                slug = slugify(name)

                mappings.append({
                    "id": agent_id,
                    "name": name,
                    "slug": slug,
                    "description": self.faker.sentence(),
                    "endpoint_url": f"https://{name}.{self.email_domain}:9000",
                    "agent_type": "generic",
                    "protocol_version": random.choice(A2A_PROTOCOLS),
                    "capabilities": random.choice(A2A_CAPABILITIES),
                    "config": {},
                    "auth_type": None,
                    "auth_value": None,
                    "auth_query_params": None,
                    "oauth_config": None,
                    "passthrough_headers": None,
                    "enabled": True,
                    "reachable": True,
                    "created_at": now,
                    "updated_at": now,
                    "last_interaction": None,
                    "tags": [],
                    "created_by": None,
                    "created_from_ip": None,
                    "created_via": "bulk_populator",
                    "created_user_agent": None,
                    "modified_by": None,
                    "modified_from_ip": None,
                    "modified_via": None,
                    "modified_user_agent": None,
                    "import_batch_id": None,
                    "federation_source": None,
                    "version": 1,
                    "team_id": None,
                    "owner_email": email,
                    "visibility": "public",
                    "tool_id": None,
                })

        result = self._bulk_insert_mappings(A2AAgent, mappings, return_id_field="id")
        self.existing_data["a2a_agent_ids"] = agent_ids
        return result
