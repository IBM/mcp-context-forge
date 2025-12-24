# -*- coding: utf-8 -*-
"""Prompt generator for load testing."""

import random
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import Prompt

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class PromptGenerator(BaseGenerator):
    """Generate Prompt records with realistic distribution."""

    def get_count(self) -> int:
        """Get total number of prompts to generate."""
        user_count = self.get_scale_config("users", 100)
        avg_prompts = self.get_scale_config("prompts_per_user_avg", 100)
        return int(user_count * avg_prompts)

    def get_dependencies(self) -> List[str]:
        """Prompts depend on users."""
        return ["UserGenerator"]

    def generate(self) -> Generator[Prompt, None, None]:
        """Generate prompt records.

        Yields:
            Prompt instances
        """
        user_count = self.get_scale_config("users", 100)
        min_prompts = self.get_scale_config("prompts_per_user_min", 10)
        max_prompts = self.get_scale_config("prompts_per_user_max", 200)
        avg_prompts = self.get_scale_config("prompts_per_user_avg", 100)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Prompts per user distribution
        prompts_per_user = normal_distribution(user_count, min_prompts, max_prompts, avg_prompts)
        total_prompts = sum(prompts_per_user)

        timestamps = exponential_decay_temporal(total_prompts, start_date, end_date, recent_percent)

        prompt_idx = 0

        prompt_categories = ["analysis", "generation", "transformation", "validation", "query"]

        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"
            num_prompts = prompts_per_user[user_i]

            for j in range(num_prompts):
                if prompt_idx >= len(timestamps):
                    break

                category = random.choice(prompt_categories)
                name = f"{category}_prompt_{user_i+1}_{j+1}"

                prompt = Prompt(
                    name=name,
                    description=self.faker.sentence(),
                    template=f"Perform {category} on: {{input}}",
                    argument_schema={
                        "type": "object",
                        "properties": {
                            "input": {"type": "string", "description": "Input data"}
                        },
                        "required": ["input"]
                    },
                    created_by=user_email,
                    enabled=True,
                    tags=[],
                    version=1,
                    visibility=random.choice(["public", "private", "team"]),
                    created_at=timestamps[prompt_idx],
                    updated_at=timestamps[prompt_idx],
                )

                prompt_idx += 1
                yield prompt
