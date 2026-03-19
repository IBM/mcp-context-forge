# -*- coding: utf-8 -*-
"""Server populator - creates virtual servers via POST /servers."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator


class ServerPopulator(BasePopulator):
    """Create virtual MCP servers via REST API."""

    def get_name(self) -> str:
        return "servers"

    def get_count(self) -> int:
        users = self.get_scale_config("users", 100)
        avg = self.get_scale_config("servers_per_user_avg", 2)
        return int(users * avg)

    def get_dependencies(self) -> List[str]:
        return ["users", "tools", "resources", "prompts"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        min_servers = self.get_scale_config("servers_per_user_min", 1)
        max_servers = self.get_scale_config("servers_per_user_max", 5)

        payloads = []
        for user_i in range(user_count):
            num_servers = random.randint(min_servers, max_servers)

            for j in range(num_servers):
                server_name = f"{self.faker.word()}-server-{user_i + 1}-{j + 1}"
                payloads.append(
                    {
                        "server": {
                            "name": server_name,
                            "description": self.faker.catch_phrase(),
                            "tags": random.sample(["production", "staging", "dev", "test", "internal", "external"], k=random.randint(1, 3)),
                        },
                        "team_id": None,
                        "visibility": "public",
                    }
                )

        result = await self._batch_create(payloads, "/servers", id_field="id")
        self.existing_data["server_ids"] = result["ids"]
        return result
