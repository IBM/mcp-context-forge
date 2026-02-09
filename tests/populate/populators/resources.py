# -*- coding: utf-8 -*-
"""Resource populator - creates resources via POST /resources."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

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
