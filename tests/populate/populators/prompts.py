# -*- coding: utf-8 -*-
"""Prompt populator - creates prompts via POST /prompts."""

# Standard
import random
from typing import Any, Dict, List
import uuid

# Local
from .base import BasePopulator
from mcpgateway.db import Prompt, utc_now
from mcpgateway.utils.create_slug import slugify

PROMPT_TEMPLATES = [
    "Summarize the following text: {input}",
    "Translate to {language}: {text}",
    "Analyze the sentiment of: {content}",
    "Generate a {format} report from: {data}",
    "Extract key entities from: {document}",
    "Classify the following into categories: {items}",
    "Compare and contrast: {item_a} vs {item_b}",
    "Write a {style} about {topic}",
    "Debug the following code: {code}",
    "Explain {concept} in simple terms",
]


class PromptPopulator(BasePopulator):
    """Create prompts via REST API."""

    def get_name(self) -> str:
        return "prompts"

    def get_count(self) -> int:
        users = self.get_scale_config("users", 100)
        avg = self.get_scale_config("prompts_per_user_avg", 20)
        return int(users * avg)

    def get_dependencies(self) -> List[str]:
        return ["users"]

    async def populate(self) -> Dict[str, Any]:
        user_count = self.get_scale_config("users", 100)
        min_prompts = self.get_scale_config("prompts_per_user_min", 10)
        max_prompts = self.get_scale_config("prompts_per_user_max", 50)

        # Use bulk mode if enabled
        if self.use_bulk_mode:
            return await self._populate_bulk(user_count, min_prompts, max_prompts)

        # REST API mode (original implementation)
        payloads = []
        for user_i in range(user_count):
            num_prompts = random.randint(min_prompts, max_prompts)

            for j in range(num_prompts):
                template = random.choice(PROMPT_TEMPLATES)
                payloads.append(
                    {
                        "prompt": {
                            "name": f"{self.faker.word()}-prompt-{user_i + 1}-{j + 1}",
                            "description": self.faker.sentence(),
                            "template": template,
                        },
                        "team_id": None,
                        "visibility": "public",
                    }
                )

        result = await self._batch_create(payloads, "/prompts", id_field="id")
        self.existing_data["prompt_ids"] = result["ids"]
        return result

    async def _populate_bulk(self, user_count: int, min_prompts: int, max_prompts: int) -> Dict[str, Any]:
        """Bulk insert prompts directly into database for performance."""
        now = utc_now()
        mappings = []
        prompt_ids = []

        for user_i in range(user_count):
            email = f"user{user_i + 1}@{self.email_domain}"
            num_prompts = random.randint(min_prompts, max_prompts)

            for j in range(num_prompts):
                prompt_id = uuid.uuid4().hex
                prompt_ids.append(prompt_id)
                template = random.choice(PROMPT_TEMPLATES)
                prompt_name = f"{self.faker.word()}-prompt-{user_i + 1}-{j + 1}"
                custom_name_slug = slugify(prompt_name)

                mappings.append({
                    "id": prompt_id,
                    "original_name": prompt_name,
                    "custom_name": prompt_name,
                    "custom_name_slug": custom_name_slug,
                    "display_name": prompt_name,
                    "name": custom_name_slug,
                    "description": self.faker.sentence(),
                    "template": template,
                    "argument_schema": {"type": "object", "properties": {}},
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
                    "gateway_id": None,
                    "team_id": None,
                    "owner_email": email,
                    "visibility": "public",
                })

        result = self._bulk_insert_mappings(Prompt, mappings, return_id_field="id")
        self.existing_data["prompt_ids"] = prompt_ids
        return result
