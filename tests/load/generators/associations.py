# -*- coding: utf-8 -*-
"""Association table generators for load testing."""

import random
from abc import abstractmethod
from typing import Generator, List

from sqlalchemy import text

from .base import BaseGenerator


class AssociationGenerator(BaseGenerator):
    """Base class for association table generators that use dict-based inserts."""

    @abstractmethod
    def get_table_name(self) -> str:
        """Get the database table name for this association."""
        pass

    def run(self) -> dict:
        """Run the generator with custom table-based insertion."""
        self.logger.info(f"Starting {self.get_name()} generation...")

        batch = []
        commit_frequency = self.config.get("performance", {}).get("commit_frequency", 10000)

        for record in self.generate():
            batch.append(record)
            self.generated_count += 1

            if len(batch) >= self.batch_size:
                self.batch_insert(batch, table_name=self.get_table_name())
                batch = []

                if self.inserted_count % commit_frequency == 0:
                    self.commit()

        if batch:
            self.batch_insert(batch, table_name=self.get_table_name())

        self.commit()

        self.logger.info(f"Completed {self.get_name()} generation: {self.generated_count} records")

        return {
            "generated": self.generated_count,
            "inserted": self.inserted_count,
        }


class ServerToolAssociationGenerator(AssociationGenerator):
    """Generate server-tool associations for virtual server composition."""

    def get_table_name(self) -> str:
        """Get the database table name for this association."""
        return "server_tool_association"

    def get_count(self) -> int:
        """Get total number of associations to generate."""
        # Each server will have multiple tools
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        tools_per_server_avg = self.get_scale_config("tools_per_server_avg", 5)
        return int(server_count * tools_per_server_avg)

    def get_dependencies(self) -> List[str]:
        """Depends on servers and tools."""
        return ["ServerGenerator", "ToolGenerator"]

    def generate(self) -> Generator[dict, None, None]:
        """Generate server-tool associations.

        Yields:
            Dict with server_id and tool_id
        """
        # Fetch actual server and tool IDs
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        tool_result = self.db.execute(text("SELECT id FROM tools ORDER BY created_at"))
        tool_ids = [row[0] for row in tool_result.fetchall()]

        if not server_ids or not tool_ids:
            self.logger.warning("No servers or tools found - cannot generate associations")
            return

        min_tools = self.get_scale_config("tools_per_server_min", 1)
        max_tools = self.get_scale_config("tools_per_server_max", 20)
        avg_tools = self.get_scale_config("tools_per_server_avg", 5)

        associations_generated = set()

        for server_id in server_ids:
            # Random number of tools per server
            num_tools = max(min_tools, min(max_tools, int(random.gauss(avg_tools, avg_tools / 3))))

            # Select random unique tools for this server
            selected_tools = random.sample(tool_ids, min(num_tools, len(tool_ids)))

            for tool_id in selected_tools:
                # Avoid duplicates
                pair = (server_id, tool_id)
                if pair not in associations_generated:
                    associations_generated.add(pair)
                    yield {"server_id": server_id, "tool_id": tool_id}


class ServerResourceAssociationGenerator(AssociationGenerator):
    """Generate server-resource associations."""

    def get_table_name(self) -> str:
        """Get the database table name for this association."""
        return "server_resource_association"

    def get_count(self) -> int:
        """Get total number of associations to generate."""
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        resources_per_server_avg = self.get_scale_config("resources_per_server_avg", 10)
        return int(server_count * resources_per_server_avg)

    def get_dependencies(self) -> List[str]:
        """Depends on servers and resources."""
        return ["ServerGenerator", "ResourceGenerator"]

    def generate(self) -> Generator[dict, None, None]:
        """Generate server-resource associations.

        Yields:
            Dict with server_id and resource_id
        """
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        resource_result = self.db.execute(text("SELECT id FROM resources ORDER BY created_at"))
        resource_ids = [row[0] for row in resource_result.fetchall()]

        if not server_ids or not resource_ids:
            self.logger.warning("No servers or resources found - cannot generate associations")
            return

        min_resources = self.get_scale_config("resources_per_server_min", 1)
        max_resources = self.get_scale_config("resources_per_server_max", 50)
        avg_resources = self.get_scale_config("resources_per_server_avg", 10)

        associations_generated = set()

        for server_id in server_ids:
            num_resources = max(min_resources, min(max_resources, int(random.gauss(avg_resources, avg_resources / 3))))
            selected_resources = random.sample(resource_ids, min(num_resources, len(resource_ids)))

            for resource_id in selected_resources:
                pair = (server_id, resource_id)
                if pair not in associations_generated:
                    associations_generated.add(pair)
                    yield {"server_id": server_id, "resource_id": resource_id}


class ServerPromptAssociationGenerator(AssociationGenerator):
    """Generate server-prompt associations."""

    def get_table_name(self) -> str:
        """Get the database table name for this association."""
        return "server_prompt_association"

    def get_count(self) -> int:
        """Get total number of associations to generate."""
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        prompts_per_server_avg = self.get_scale_config("prompts_per_server_avg", 8)
        return int(server_count * prompts_per_server_avg)

    def get_dependencies(self) -> List[str]:
        """Depends on servers and prompts."""
        return ["ServerGenerator", "PromptGenerator"]

    def generate(self) -> Generator[dict, None, None]:
        """Generate server-prompt associations.

        Yields:
            Dict with server_id and prompt_id
        """
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        prompt_result = self.db.execute(text("SELECT id FROM prompts ORDER BY created_at"))
        prompt_ids = [row[0] for row in prompt_result.fetchall()]

        if not server_ids or not prompt_ids:
            self.logger.warning("No servers or prompts found - cannot generate associations")
            return

        min_prompts = self.get_scale_config("prompts_per_server_min", 1)
        max_prompts = self.get_scale_config("prompts_per_server_max", 30)
        avg_prompts = self.get_scale_config("prompts_per_server_avg", 8)

        associations_generated = set()

        for server_id in server_ids:
            num_prompts = max(min_prompts, min(max_prompts, int(random.gauss(avg_prompts, avg_prompts / 3))))
            selected_prompts = random.sample(prompt_ids, min(num_prompts, len(prompt_ids)))

            for prompt_id in selected_prompts:
                pair = (server_id, prompt_id)
                if pair not in associations_generated:
                    associations_generated.add(pair)
                    yield {"server_id": server_id, "prompt_id": prompt_id}


class ServerA2AAssociationGenerator(AssociationGenerator):
    """Generate server-A2A agent associations."""

    def get_table_name(self) -> str:
        """Get the database table name for this association."""
        return "server_a2a_association"

    def get_count(self) -> int:
        """Get total number of associations to generate."""
        server_count = self.get_scale_config("servers_per_user_avg", 10) * self.get_scale_config("users", 100)
        agents_per_server_avg = self.get_scale_config("a2a_agents_per_server_avg", 1)
        return int(server_count * agents_per_server_avg)

    def get_dependencies(self) -> List[str]:
        """Depends on servers and A2A agents."""
        return ["ServerGenerator", "A2AAgentGenerator"]

    def generate(self) -> Generator[dict, None, None]:
        """Generate server-A2A agent associations.

        Yields:
            Dict with server_id and a2a_agent_id
        """
        server_result = self.db.execute(text("SELECT id FROM servers ORDER BY created_at"))
        server_ids = [row[0] for row in server_result.fetchall()]

        agent_result = self.db.execute(text("SELECT id FROM a2a_agents ORDER BY created_at"))
        agent_ids = [row[0] for row in agent_result.fetchall()]

        if not server_ids:
            self.logger.warning("No servers found - cannot generate associations")
            return

        if not agent_ids:
            self.logger.info("No A2A agents found - skipping A2A associations")
            return

        min_agents = self.get_scale_config("a2a_agents_per_server_min", 0)
        max_agents = self.get_scale_config("a2a_agents_per_server_max", 3)
        avg_agents = self.get_scale_config("a2a_agents_per_server_avg", 1)

        associations_generated = set()

        for server_id in server_ids:
            # Some servers won't have any A2A agents
            num_agents = max(0, min(max_agents, int(random.gauss(avg_agents, max(1, avg_agents / 2)))))

            if num_agents == 0:
                continue

            selected_agents = random.sample(agent_ids, min(num_agents, len(agent_ids)))

            for agent_id in selected_agents:
                pair = (server_id, agent_id)
                if pair not in associations_generated:
                    associations_generated.add(pair)
                    yield {"server_id": server_id, "a2a_agent_id": agent_id}
