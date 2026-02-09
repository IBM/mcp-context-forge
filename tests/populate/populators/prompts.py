# -*- coding: utf-8 -*-
"""Prompt populator - creates prompts via POST /prompts."""

# Standard
import random
from typing import Any, Dict, List

# Local
from .base import BasePopulator

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
