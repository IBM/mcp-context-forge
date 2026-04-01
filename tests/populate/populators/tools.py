# -*- coding: utf-8 -*-
"""Tool populator - creates REST tools via POST /tools.

Note: MCP tools cannot be manually created - they are auto-discovered from
gateways. This populator creates REST integration tools instead.
"""

# Standard
import random
from typing import Any, Dict, List
import uuid

# Local
from .base import BasePopulator
from mcpgateway.db import Tool, utc_now
from mcpgateway.utils.create_slug import slugify

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

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(count)

        # REST API mode (original implementation)
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

    async def _populate_bulk(self, count: int) -> Dict[str, Any]:
        """Bulk insert tools directly into database for performance."""
        now = utc_now()
        mappings = []
        tool_ids = []

        for i in range(count):
            tool_id = uuid.uuid4().hex
            tool_ids.append(tool_id)
            tool_name = f"{random.choice(TOOL_NAME_PREFIXES)}_{i + 1}"
            custom_name_slug = slugify(tool_name)

            mappings.append({
                "id": tool_id,
                "original_name": tool_name,
                "custom_name": tool_name,
                "custom_name_slug": custom_name_slug,
                "_computed_name": custom_name_slug,  # Stored name column
                "display_name": tool_name,
                "url": f"https://api.{self.email_domain}/{tool_name}",
                "description": self.faker.sentence(),
                "original_description": self.faker.sentence(),
                "integration_type": "REST",
                "request_type": random.choice(REQUEST_TYPES),
                "input_schema": {"type": "object", "properties": {"input": {"type": "string"}}},
                "output_schema": None,
                "annotations": {},
                "headers": None,
                "enabled": True,
                "reachable": True,
                "jsonpath_filter": "",
                "tags": [],
                "created_at": now,
                "updated_at": now,
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
                "auth_type": None,
                "auth_value": None,
                "base_url": None,
                "path_template": None,
                "query_mapping": None,
                "header_mapping": None,
                "timeout_ms": None,
                "expose_passthrough": True,
                "allowlist": None,
                "plugin_chain_pre": None,
                "plugin_chain_post": None,
                "gateway_id": None,
                "team_id": None,
                "owner_email": None,
                "visibility": "public",
            })

        result = self._bulk_insert_mappings(Tool, mappings, return_id_field="id")
        self.existing_data["tool_ids"] = tool_ids
        return result
