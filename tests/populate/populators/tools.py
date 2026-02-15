# -*- coding: utf-8 -*-
"""Tool populator - creates REST tools via POST /tools.

Note: MCP tools cannot be manually created - they are auto-discovered from
gateways. This populator creates REST integration tools instead.
"""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

TOOL_NAME_PREFIXES = [
    "list_files",
    "read_file",
    "write_file",
    "search",
    "query",
    "analyze",
    "transform",
    "validate",
    "process",
    "execute",
    "get_data",
    "set_data",
    "create_record",
    "update_record",
    "delete_record",
    "fetch_url",
    "parse_json",
    "format_text",
    "compress",
    "encrypt",
]

REQUEST_TYPES = ["GET", "POST", "PUT", "DELETE", "PATCH"]


class ToolPopulator(BasePopulator):
    """Create REST tools via REST API."""

    def get_name(self) -> str:
        return "tools"

    def get_count(self) -> int:
        gateways = self.get_scale_config("gateways", 10)
        avg_tools = self.get_scale_config("tools_per_gateway_avg", 20)
        return int(gateways * avg_tools)

    def get_dependencies(self) -> List[str]:
        return []

    async def populate(self) -> Dict[str, Any]:
        count = self.get_count()

        payloads = []
        for i in range(count):
            tool_name = f"{random.choice(TOOL_NAME_PREFIXES)}_{i + 1}"
            payloads.append(
                {
                    "tool": {
                        "name": tool_name,
                        "description": self.faker.sentence(),
                        "inputSchema": {"type": "object", "properties": {"input": {"type": "string"}}},
                        "integration_type": "REST",
                        "url": f"https://api.{self.email_domain}/{tool_name}",
                        "request_type": random.choice(REQUEST_TYPES),
                    },
                    "team_id": None,
                }
            )

        result = await self._batch_create(payloads, "/tools", id_field="id")
        self.existing_data["tool_ids"] = result["ids"]
        return result
