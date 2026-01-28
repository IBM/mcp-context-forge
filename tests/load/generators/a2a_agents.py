# -*- coding: utf-8 -*-
"""A2A agent generator for load testing."""

import random
import uuid
from datetime import datetime
from typing import Generator, List

from mcpgateway.db import A2AAgent

from ..utils.distributions import exponential_decay_temporal, normal_distribution
from .base import BaseGenerator


class A2AAgentGenerator(BaseGenerator):
    """Generate A2A Agent records with realistic distribution."""

    def get_count(self) -> int:
        """Get total number of A2A agents to generate."""
        user_count = self.get_scale_config("users", 100)
        avg_agents = self.get_scale_config("a2a_agents_per_user_avg", 2)
        return int(user_count * avg_agents)

    def get_dependencies(self) -> List[str]:
        """A2A agents depend on users and teams."""
        return ["UserGenerator", "TeamGenerator"]

    def generate(self) -> Generator[A2AAgent, None, None]:
        """Generate A2A agent records.

        Yields:
            A2AAgent instances
        """
        user_count = self.get_scale_config("users", 100)
        min_agents = self.get_scale_config("a2a_agents_per_user_min", 0)
        max_agents = self.get_scale_config("a2a_agents_per_user_max", 5)
        avg_agents = self.get_scale_config("a2a_agents_per_user_avg", 2)

        # Get temporal distribution
        start_date = datetime.fromisoformat(self.config.get("temporal", {}).get("start_date", "2023-01-01"))
        end_date = datetime.fromisoformat(self.config.get("temporal", {}).get("end_date", datetime.now().isoformat()))
        recent_percent = self.config.get("temporal", {}).get("recent_data_percent", 80) / 100

        # Agents per user distribution
        agents_per_user = normal_distribution(user_count, min_agents, max_agents, avg_agents)
        total_agents = sum(agents_per_user)

        if total_agents == 0:
            return

        timestamps = exponential_decay_temporal(total_agents, start_date, end_date, recent_percent)

        agent_idx = 0

        # Agent types and their typical configurations
        agent_types = [
            ("openai", "https://api.openai.com/v1", "1.0"),
            ("anthropic", "https://api.anthropic.com/v1", "1.0"),
            ("custom", "https://custom-agent.example.com/api", "1.0"),
            ("huggingface", "https://api-inference.huggingface.co/models", "1.0"),
        ]

        for user_i in range(user_count):
            user_email = f"user{user_i+1}@{self.email_domain}"
            num_agents = agents_per_user[user_i]

            for j in range(num_agents):
                if agent_idx >= len(timestamps):
                    break

                agent_type, base_url, protocol = random.choice(agent_types)
                agent_id = str(uuid.uuid4())
                name = f"{agent_type}_agent_{user_i+1}_{j+1}"
                slug = name.lower().replace("_", "-")

                # Capabilities vary by agent type
                capabilities = {
                    "text_generation": True,
                    "code_generation": random.choice([True, False]),
                    "image_understanding": random.choice([True, False]) if agent_type in ["openai", "anthropic"] else False,
                    "function_calling": random.choice([True, False]),
                }

                # Config varies by agent type
                config = {
                    "model": self._get_model_for_type(agent_type),
                    "temperature": round(random.uniform(0.0, 1.0), 2),
                    "max_tokens": random.choice([1000, 2000, 4000, 8000]),
                }

                agent = A2AAgent(
                    id=agent_id,
                    name=name,
                    slug=slug,
                    description=self.faker.sentence(),
                    endpoint_url=f"{base_url}/{name}",
                    agent_type=agent_type,
                    protocol_version=protocol,
                    capabilities=capabilities,
                    config=config,
                    auth_type=random.choice(["bearer", "api_key", None]),
                    auth_value=f"sk-{uuid.uuid4().hex}" if random.random() < 0.8 else None,
                    enabled=random.random() < 0.9,  # 90% enabled
                    reachable=random.choice([True, True, True, False]),  # 75% reachable
                    created_at=timestamps[agent_idx],
                    updated_at=timestamps[agent_idx],
                    last_interaction=timestamps[agent_idx] if random.random() < 0.6 else None,
                    tags=[],
                    created_by=user_email,
                    version=1,
                    visibility=random.choice(["public", "private", "team"]),
                )

                agent_idx += 1
                yield agent

    def _get_model_for_type(self, agent_type: str) -> str:
        """Get a realistic model name for the agent type."""
        models = {
            "openai": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
            "anthropic": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
            "custom": ["custom-model-v1", "custom-model-v2"],
            "huggingface": ["meta-llama/Llama-2-7b", "mistralai/Mistral-7B"],
        }
        return random.choice(models.get(agent_type, ["default-model"]))
