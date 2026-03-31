# -*- coding: utf-8 -*-
"""Gateway populator - creates gateways via POST /gateways."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator
from mcpgateway.db import Gateway, utc_now
from mcpgateway.utils.create_slug import slugify


class GatewayPopulator(BasePopulator):
    """Create MCP gateway (backend server) registrations via REST API."""

    def get_name(self) -> str:
        return "gateways"

    def get_count(self) -> int:
        return self.get_scale_config("gateways", 10)

    def get_dependencies(self) -> List[str]:
        return ["users", "rbac"]

    async def populate(self) -> Dict[str, Any]:
        count = self.get_count()

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(count)

        # REST API mode (original implementation)
        payloads = []
        for i in range(count):
            name = f"{self.faker.company()}-mcp-{i + 1}".lower().replace(" ", "-").replace(",", "").replace(".", "")[:60]
            transport = random.choice(["SSE", "STDIO", "HTTP", "STREAMABLEHTTP"])
            payloads.append(
                {
                    "name": name,
                    "url": f"https://{name}.{self.email_domain}:8000",
                    "description": self.faker.catch_phrase(),
                    "transport": transport,
                }
            )

        result = await self._batch_create(payloads, "/gateways", id_field="id")
        self.existing_data["gateway_ids"] = result["ids"]
        return result

    async def _populate_bulk(self, count: int) -> Dict[str, Any]:
        """Bulk insert gateways directly into database for performance."""
        import uuid
        
        # Build gateway mappings
        mappings = []
        ids: List[str] = []
        
        for i in range(count):
            name = f"{self.faker.company()}-mcp-{i + 1}".lower().replace(" ", "-").replace(",", "").replace(".", "")[:60]
            gateway_id = uuid.uuid4().hex
            transport = random.choice(["SSE", "STDIO", "HTTP", "STREAMABLEHTTP"])
            
            mappings.append({
                "id": gateway_id,
                "name": name,
                "slug": slugify(name),
                "url": f"https://{name}.{self.email_domain}:8000",
                "description": self.faker.catch_phrase(),
                "transport": transport,
                "capabilities": {},
                "enabled": True,
                "reachable": True,
                "tags": [],
                "visibility": "public",
                "version": 1,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            })
            ids.append(gateway_id)

        # Bulk insert
        result = self._bulk_insert_mappings(Gateway, mappings, return_id_field="id")
        self.existing_data["gateway_ids"] = ids
        return result
