# -*- coding: utf-8 -*-
"""Resource populator - creates resources via POST /resources."""

# Standard
import random
from typing import Any, Dict, List
import uuid

# Local
from .base import BasePopulator
from mcpgateway.db import Resource, utc_now

MIME_TYPES = [
    "text/plain",
    "application/json",
    "text/markdown",
    "text/html",
    "application/xml",
    "application/pdf",
]

RESOURCE_URI_PREFIXES = [
    "file:///data",
    "file:///config",
    "file:///docs",
    "file:///logs",
    "https://api.example.com",
    "https://storage.example.com",
    "s3://bucket/data",
    "gs://bucket/config",
]


class ResourcePopulator(BasePopulator):
    """Create resources via REST API."""

    def get_name(self) -> str:
        return "resources"

    def get_count(self) -> int:
        users = self.get_scale_config("users", 100)
        avg = self.get_scale_config("resources_per_user_avg", 20)
        return int(users * avg)

    def get_dependencies(self) -> List[str]:
        return ["users"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        min_res = self.get_scale_config("resources_per_user_min", 10)
        max_res = self.get_scale_config("resources_per_user_max", 50)

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(user_count, min_res, max_res)

        # REST API mode (original implementation)
        payloads = []
        for user_i in range(user_count):
            num_resources = random.randint(min_res, max_res)

            for j in range(num_resources):
                prefix = random.choice(RESOURCE_URI_PREFIXES)
                username = f"user{user_i + 1}"
                filename = self.faker.file_name()
                mime = random.choice(MIME_TYPES)
                payloads.append(
                    {
                        "resource": {
                            "uri": f"{prefix}/{username}/{filename}",
                            "name": f"{self.faker.word()}-resource-{user_i + 1}-{j + 1}",
                            "description": self.faker.sentence(),
                            "mimeType": mime,
                            "content": self.faker.paragraph() if mime.startswith("text/") else "base64data==",
                        },
                        "team_id": None,
                        "visibility": "public",
                    }
                )

        result = await self._batch_create(payloads, "/resources", id_field="id")
        self.existing_data["resource_ids"] = result["ids"]
        return result

    async def _populate_bulk(self, user_count: int, min_res: int, max_res: int) -> Dict[str, Any]:
        """Bulk insert resources directly into database for performance."""
        now = utc_now()
        mappings = []
        resource_ids = []

        for user_i in range(user_count):
            email = f"user{user_i + 1}@{self.email_domain}"
            num_resources = random.randint(min_res, max_res)

            for j in range(num_resources):
                resource_id = uuid.uuid4().hex
                resource_ids.append(resource_id)
                prefix = random.choice(RESOURCE_URI_PREFIXES)
                username = f"user{user_i + 1}"
                filename = self.faker.file_name()
                mime = random.choice(MIME_TYPES)
                content = self.faker.paragraph() if mime.startswith("text/") else "base64data=="

                mappings.append({
                    "id": resource_id,
                    "uri": f"{prefix}/{username}/{filename}",
                    "name": f"{self.faker.word()}-resource-{user_i + 1}-{j + 1}",
                    "description": self.faker.sentence(),
                    "mime_type": mime,
                    "size": len(content) if content else None,
                    "uri_template": None,
                    "created_at": now,
                    "updated_at": now,
                    "enabled": True,
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
                    "text_content": content if mime.startswith("text/") else None,
                    "binary_content": None,
                    "gateway_id": None,
                    "team_id": None,
                    "owner_email": email,
                    "visibility": "public",
                })

        result = self._bulk_insert_mappings(Resource, mappings, return_id_field="id")
        self.existing_data["resource_ids"] = resource_ids
        return result
