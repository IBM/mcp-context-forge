# -*- coding: utf-8 -*-
"""Gateway populator - creates gateways via POST /gateways."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator


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
