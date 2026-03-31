# -*- coding: utf-8 -*-
"""Server populator - creates virtual servers via POST /servers."""

# Standard
import random
from typing import Any, Dict, List
import uuid

# Local
from .base import BasePopulator
from mcpgateway.db import Server, utc_now


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

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(user_count, min_servers, max_servers)

        # REST API mode (original implementation)
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

    async def _populate_bulk(self, user_count: int, min_servers: int, max_servers: int) -> Dict[str, Any]:
        """Bulk insert servers directly into database for performance."""
        now = utc_now()
        mappings = []
        server_ids = []

        for user_i in range(user_count):
            email = f"user{user_i + 1}@{self.email_domain}"
            num_servers = random.randint(min_servers, max_servers)

            for j in range(num_servers):
                server_id = uuid.uuid4().hex
                server_ids.append(server_id)
                server_name = f"{self.faker.word()}-server-{user_i + 1}-{j + 1}"

                mappings.append({
                    "id": server_id,
                    "name": server_name,
                    "description": self.faker.catch_phrase(),
                    "icon": None,
                    "created_at": now,
                    "updated_at": now,
                    "enabled": True,
                    "tags": random.sample(["production", "staging", "dev", "test", "internal", "external"], k=random.randint(1, 3)),
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
                })

        result = self._bulk_insert_mappings(Server, mappings, return_id_field="id")
        self.existing_data["server_ids"] = server_ids
        return result
