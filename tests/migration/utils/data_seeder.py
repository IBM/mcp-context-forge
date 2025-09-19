# -*- coding: utf-8 -*-
"""Data seeding utilities for migration testing.

This module provides comprehensive test data generation and seeding
capabilities for validating data integrity across migrations.
"""

# Standard
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import random
import string
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class DataGenerationConfig:
    """Configuration for test data generation."""
    tools_count: int = 10
    servers_count: int = 5
    gateways_count: int = 3
    resources_count: int = 8
    prompts_count: int = 5
    a2a_agents_count: int = 2
    include_relationships: bool = True
    randomize_data: bool = True
    seed: Optional[int] = None


class DataSeeder:
    """Generates and manages test data for migration testing.

    Provides capabilities for:
    - Realistic test data generation
    - Data seeding across different database states
    - Relationship management between entities
    - Data integrity validation
    - Performance testing with large datasets
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize data seeder.

        Args:
            seed: Random seed for reproducible data generation
        """
        self.seed = seed or int(time.time())
        random.seed(self.seed)

        logger.info(f"🌱 Initialized DataSeeder with seed={self.seed}")

        # Load schema information for realistic data generation
        self.tool_categories = [
            "database", "filesystem", "network", "system", "ai", "web",
            "development", "monitoring", "security", "communication"
        ]

        self.server_types = ["sse", "websocket", "stdio", "http"]
        self.transport_types = ["sse", "websocket", "stdio"]

        # Sample schemas for different tool types
        self.tool_schemas = {
            "simple": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input parameter"}
                },
                "required": ["input"]
            },
            "complex": {
                "type": "object",
                "properties": {
                    "config": {
                        "type": "object",
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "timeout": {"type": "integer", "minimum": 0},
                            "retries": {"type": "integer", "minimum": 1, "maximum": 10}
                        }
                    },
                    "data": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            },
            "advanced": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "filters": {
                        "type": "object",
                        "additionalProperties": {"type": "string"}
                    },
                    "pagination": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "integer", "minimum": 1},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100}
                        }
                    }
                }
            }
        }

    def generate_realistic_dataset(self, config: DataGenerationConfig) -> Dict[str, List[Dict]]:
        """Generate a realistic dataset for testing.

        Args:
            config: Data generation configuration

        Returns:
            Dictionary containing generated test data
        """
        logger.info(f"🎲 Generating realistic dataset with config: {config}")

        dataset = {
            "tools": self._generate_tools(config.tools_count),
            "servers": self._generate_servers(config.servers_count),
            "gateways": self._generate_gateways(config.gateways_count),
            "resources": self._generate_resources(config.resources_count),
            "prompts": self._generate_prompts(config.prompts_count)
        }

        # Add A2A agents if specified
        if config.a2a_agents_count > 0:
            dataset["a2a_agents"] = self._generate_a2a_agents(config.a2a_agents_count)

        # Create relationships if enabled
        if config.include_relationships:
            dataset = self._create_relationships(dataset)

        # Log generation summary
        total_records = sum(len(entities) for entities in dataset.values())
        logger.info(f"✅ Generated {total_records} total records:")
        for entity_type, entities in dataset.items():
            logger.info(f"   {entity_type}: {len(entities)}")

        return dataset

    def _generate_tools(self, count: int) -> List[Dict]:
        """Generate realistic tool test data."""
        logger.debug(f"🔧 Generating {count} tools")

        tools = []
        for i in range(count):
            category = random.choice(self.tool_categories)
            schema_type = random.choice(list(self.tool_schemas.keys()))

            tool = {
                "name": f"{category}_tool_{i:03d}",
                "description": f"A {category} tool for {self._generate_description_fragment()}",
                "schema": self.tool_schemas[schema_type].copy(),
                "annotations": {
                    "category": category,
                    "complexity": schema_type,
                    "version": f"{random.randint(1, 3)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
                    "author": f"team_{random.choice(['alpha', 'beta', 'gamma', 'delta'])}",
                    "created_by": "migration_test"
                }
            }

            # Add random metadata
            if random.random() < 0.3:
                tool["annotations"]["deprecated"] = "false"

            if random.random() < 0.2:
                tool["annotations"]["experimental"] = "true"

            tools.append(tool)

        return tools

    def _generate_servers(self, count: int) -> List[Dict]:
        """Generate realistic server test data."""
        logger.debug(f"🖥️ Generating {count} servers")

        servers = []
        for i in range(count):
            transport = random.choice(self.transport_types)

            server = {
                "name": f"test_server_{i:03d}",
                "description": f"Test server for {self._generate_description_fragment()}",
                "transport": transport,
                "annotations": {
                    "environment": random.choice(["development", "testing", "staging"]),
                    "region": random.choice(["us-east-1", "eu-west-1", "ap-southeast-1"]),
                    "transport": transport,
                    "created_by": "migration_test"
                }
            }

            # Add transport-specific configuration
            if transport == "sse":
                server["connection_string"] = f"http://test-server-{i}.example.com:8080/sse"
            elif transport == "websocket":
                server["connection_string"] = f"ws://test-server-{i}.example.com:8080/ws"
            elif transport == "stdio":
                server["command"] = f"test-server-{i} --mode stdio --verbose"

            servers.append(server)

        return servers

    def _generate_gateways(self, count: int) -> List[Dict]:
        """Generate realistic gateway test data."""
        logger.debug(f"🌐 Generating {count} gateways")

        gateways = []
        for i in range(count):
            gateway = {
                "name": f"test_gateway_{i:03d}",
                "base_url": f"http://test-gateway-{i}.example.com:4444",
                "description": f"Test gateway for {self._generate_description_fragment()}",
                "annotations": {
                    "type": random.choice(["federation", "proxy", "load_balancer"]),
                    "region": random.choice(["us", "eu", "asia"]),
                    "capacity": str(random.randint(100, 1000)),
                    "created_by": "migration_test"
                }
            }

            # Add health check configuration
            if random.random() < 0.7:
                gateway["health_check_url"] = f"{gateway['base_url']}/health"
                gateway["health_check_interval"] = random.randint(30, 300)

            gateways.append(gateway)

        return gateways

    def _generate_resources(self, count: int) -> List[Dict]:
        """Generate realistic resource test data."""
        logger.debug(f"📄 Generating {count} resources")

        resource_types = [
            ("text/plain", "txt"), ("application/json", "json"),
            ("text/csv", "csv"), ("application/yaml", "yaml"),
            ("text/markdown", "md"), ("application/xml", "xml")
        ]

        resources = []
        for i in range(count):
            mime_type, extension = random.choice(resource_types)

            resource = {
                "name": f"test_resource_{i:03d}",
                "uri": f"file:///app/test_data/resource_{i:03d}.{extension}",
                "description": f"Test resource containing {self._generate_description_fragment()}",
                "mimeType": mime_type,
                "annotations": {
                    "category": random.choice(["config", "data", "template", "schema"]),
                    "size": str(random.randint(1024, 1024*1024)),  # 1KB to 1MB
                    "encoding": "utf-8" if "text" in mime_type else "binary",
                    "created_by": "migration_test"
                }
            }

            # Add optional metadata
            if random.random() < 0.4:
                resource["annotations"]["version"] = f"v{random.randint(1, 5)}"

            if random.random() < 0.3:
                resource["annotations"]["cached"] = str(random.choice([True, False])).lower()

            resources.append(resource)

        return resources

    def _generate_prompts(self, count: int) -> List[Dict]:
        """Generate realistic prompt test data."""
        logger.debug(f"💬 Generating {count} prompts")

        prompt_templates = [
            "Hello {{name}}, how can I help you with {{task}}?",
            "Please analyze the following {{data_type}}: {{content}}",
            "Generate a {{format}} report for {{subject}} with details about {{aspects}}",
            "Explain {{concept}} in {{complexity}} terms for {{audience}}",
            "Create a {{item_type}} that {{requirements}} and follows {{standards}}"
        ]

        prompts = []
        for i in range(count):
            template = random.choice(prompt_templates)

            prompt = {
                "name": f"test_prompt_{i:03d}",
                "description": f"Test prompt for {self._generate_description_fragment()}",
                "template": template,
                "annotations": {
                    "category": random.choice(["greeting", "analysis", "generation", "explanation"]),
                    "complexity": random.choice(["simple", "medium", "complex"]),
                    "variables": str(len([t for t in template.split('{{') if '}}' in t])),
                    "created_by": "migration_test"
                }
            }

            prompts.append(prompt)

        return prompts

    def _generate_a2a_agents(self, count: int) -> List[Dict]:
        """Generate realistic A2A agent test data."""
        logger.debug(f"🤖 Generating {count} A2A agents")

        agent_providers = ["openai", "anthropic", "azure", "local"]
        agent_models = {
            "openai": ["gpt-4", "gpt-3.5-turbo"],
            "anthropic": ["claude-3-opus", "claude-3-sonnet"],
            "azure": ["gpt-4-azure", "gpt-35-turbo-azure"],
            "local": ["llama-2", "mistral-7b"]
        }

        agents = []
        for i in range(count):
            provider = random.choice(agent_providers)
            model = random.choice(agent_models[provider])

            agent = {
                "name": f"test_a2a_agent_{i:03d}",
                "description": f"Test A2A agent using {provider} {model}",
                "provider": provider,
                "model": model,
                "endpoint_url": f"https://api.{provider}.example.com/v1/chat",
                "annotations": {
                    "provider": provider,
                    "model_family": model.split('-')[0],
                    "capabilities": json.dumps(["text", "analysis", "generation"]),
                    "max_tokens": str(random.choice([2048, 4096, 8192])),
                    "created_by": "migration_test"
                }
            }

            # Add provider-specific configuration
            if provider == "openai":
                agent["annotations"]["temperature"] = str(random.uniform(0.1, 1.0))
            elif provider == "anthropic":
                agent["annotations"]["max_tokens_to_sample"] = str(random.randint(1000, 4000))

            agents.append(agent)

        return agents

    def _create_relationships(self, dataset: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """Create realistic relationships between entities."""
        logger.debug("🔗 Creating entity relationships")

        # Associate tools with servers
        if "tools" in dataset and "servers" in dataset:
            server_tools = {}  # server_name -> [tool_names]

            for server in dataset["servers"]:
                # Each server gets 2-5 tools
                num_tools = min(random.randint(2, 5), len(dataset["tools"]))
                selected_tools = random.sample(dataset["tools"], num_tools)
                server_tools[server["name"]] = [tool["name"] for tool in selected_tools]

                if "annotations" not in server:
                    server["annotations"] = {}
                server["annotations"]["associated_tools"] = json.dumps(server_tools[server["name"]])

        # Associate resources with servers
        if "resources" in dataset and "servers" in dataset:
            for server in dataset["servers"]:
                # Each server might have 1-3 resources
                if random.random() < 0.6:  # 60% chance of having resources
                    num_resources = min(random.randint(1, 3), len(dataset["resources"]))
                    selected_resources = random.sample(dataset["resources"], num_resources)
                    resource_names = [res["name"] for res in selected_resources]

                    if "annotations" not in server:
                        server["annotations"] = {}
                    server["annotations"]["associated_resources"] = json.dumps(resource_names)

        # Associate A2A agents with servers
        if "a2a_agents" in dataset and "servers" in dataset:
            for server in dataset["servers"]:
                # Some servers might have A2A agents
                if random.random() < 0.4:  # 40% chance
                    num_agents = min(random.randint(1, 2), len(dataset["a2a_agents"]))
                    selected_agents = random.sample(dataset["a2a_agents"], num_agents)
                    agent_ids = [str(i+1) for i, _ in enumerate(selected_agents)]

                    if "annotations" not in server:
                        server["annotations"] = {}
                    server["annotations"]["associated_a2a_agents"] = json.dumps(agent_ids)

        return dataset

    def _generate_description_fragment(self) -> str:
        """Generate a random description fragment."""
        fragments = [
            "data processing and analysis",
            "system monitoring and alerts",
            "file management operations",
            "network connectivity testing",
            "user authentication flows",
            "configuration management",
            "performance optimization",
            "security scanning and validation",
            "content generation tasks",
            "workflow automation"
        ]
        return random.choice(fragments)

    def generate_performance_dataset(self, scale_factor: int = 1) -> Dict[str, List[Dict]]:
        """Generate large dataset for performance testing.

        Args:
            scale_factor: Multiplier for base dataset sizes

        Returns:
            Large test dataset
        """
        logger.info(f"🚀 Generating performance dataset with scale_factor={scale_factor}")

        config = DataGenerationConfig(
            tools_count=100 * scale_factor,
            servers_count=20 * scale_factor,
            gateways_count=10 * scale_factor,
            resources_count=50 * scale_factor,
            prompts_count=30 * scale_factor,
            a2a_agents_count=5 * scale_factor,
            include_relationships=True,
            randomize_data=True
        )

        dataset = self.generate_realistic_dataset(config)

        # Add performance testing metadata
        for entity_type, entities in dataset.items():
            for entity in entities:
                if "annotations" not in entity:
                    entity["annotations"] = {}
                entity["annotations"]["performance_test"] = "true"
                entity["annotations"]["scale_factor"] = str(scale_factor)

        total_records = sum(len(entities) for entities in dataset.values())
        logger.info(f"✅ Generated performance dataset: {total_records} total records")

        return dataset

    def save_dataset(self, dataset: Dict[str, List[Dict]], output_file: str) -> Path:
        """Save dataset to JSON file.

        Args:
            dataset: Dataset to save
            output_file: Output file path

        Returns:
            Path to saved file
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Add metadata
        dataset_with_metadata = {
            "metadata": {
                "generator": "DataSeeder",
                "seed": self.seed,
                "timestamp": time.time(),
                "total_records": sum(len(entities) for entities in dataset.values())
            },
            "data": dataset
        }

        with open(output_path, 'w') as f:
            json.dump(dataset_with_metadata, f, indent=2)

        logger.info(f"💾 Saved dataset to {output_path}")
        return output_path

    def load_dataset(self, input_file: str) -> Dict[str, List[Dict]]:
        """Load dataset from JSON file.

        Args:
            input_file: Input file path

        Returns:
            Loaded dataset
        """
        logger.info(f"📂 Loading dataset from {input_file}")

        with open(input_file, 'r') as f:
            data = json.load(f)

        if "data" in data:
            dataset = data["data"]
            metadata = data.get("metadata", {})
            logger.info(f"📊 Loaded dataset: {metadata.get('total_records', 'unknown')} total records")
        else:
            dataset = data
            logger.info("📊 Loaded legacy dataset format")

        return dataset

    def create_version_specific_datasets(self, base_dataset: Dict[str, List[Dict]],
                                       versions: List[str]) -> Dict[str, Dict[str, List[Dict]]]:
        """Create version-specific datasets for migration testing.

        Args:
            base_dataset: Base dataset to modify
            versions: List of versions to create datasets for

        Returns:
            Dictionary mapping versions to datasets
        """
        logger.info(f"🔄 Creating version-specific datasets for {len(versions)} versions")

        version_datasets = {}

        for version in versions:
            # Create a copy of the base dataset
            # Standard
            import copy
            dataset = copy.deepcopy(base_dataset)

            # Modify dataset based on version-specific features
            dataset = self._apply_version_modifications(dataset, version)

            version_datasets[version] = dataset

            total_records = sum(len(entities) for entities in dataset.values())
            logger.info(f"✅ Created dataset for {version}: {total_records} records")

        return version_datasets

    def _apply_version_modifications(self, dataset: Dict[str, List[Dict]],
                                   version: str) -> Dict[str, List[Dict]]:
        """Apply version-specific modifications to dataset."""

        # Version 0.2.0 and earlier - simpler schemas
        if version in ["0.2.0"]:
            # Remove complex annotations
            for entity_type, entities in dataset.items():
                for entity in entities:
                    if "annotations" in entity:
                        # Keep only basic annotations
                        basic_annotations = {
                            "created_by": entity["annotations"].get("created_by"),
                            "category": entity["annotations"].get("category")
                        }
                        entity["annotations"] = {k: v for k, v in basic_annotations.items() if v}

        # Version 0.3.0 - added display names
        elif version in ["0.3.0", "0.4.0"]:
            # Add display names where missing
            for entity_type, entities in dataset.items():
                for entity in entities:
                    if "display_name" not in entity:
                        entity["display_name"] = entity["name"].replace("_", " ").title()

        # Version 0.5.0+ - full feature set
        # (no modifications needed, use dataset as-is)

        return dataset

    def validate_data_integrity(self, dataset_before: Dict[str, List[Dict]],
                               dataset_after: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Validate data integrity between two datasets.

        Args:
            dataset_before: Dataset before operation
            dataset_after: Dataset after operation

        Returns:
            Validation results
        """
        logger.info("🔍 Validating data integrity between datasets")

        results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "statistics": {}
        }

        # Compare record counts
        for entity_type in dataset_before.keys():
            count_before = len(dataset_before[entity_type])
            count_after = len(dataset_after.get(entity_type, []))

            results["statistics"][entity_type] = {
                "before": count_before,
                "after": count_after,
                "delta": count_after - count_before
            }

            if count_after < count_before:
                results["errors"].append(f"Data loss in {entity_type}: {count_before} → {count_after}")
                results["valid"] = False
            elif count_after > count_before:
                results["warnings"].append(f"New records in {entity_type}: {count_before} → {count_after}")

        # Check for new entity types
        new_types = set(dataset_after.keys()) - set(dataset_before.keys())
        if new_types:
            results["warnings"].append(f"New entity types: {new_types}")

        removed_types = set(dataset_before.keys()) - set(dataset_after.keys())
        if removed_types:
            results["errors"].append(f"Removed entity types: {removed_types}")
            results["valid"] = False

        # Validate specific entity integrity
        for entity_type in set(dataset_before.keys()) & set(dataset_after.keys()):
            entity_validation = self._validate_entity_integrity(
                dataset_before[entity_type],
                dataset_after[entity_type],
                entity_type
            )

            if not entity_validation["valid"]:
                results["valid"] = False
                results["errors"].extend(entity_validation["errors"])

            results["warnings"].extend(entity_validation["warnings"])

        logger.info(f"✅ Data integrity validation completed: valid={results['valid']}")
        return results

    def _validate_entity_integrity(self, entities_before: List[Dict],
                                  entities_after: List[Dict],
                                  entity_type: str) -> Dict[str, Any]:
        """Validate integrity of specific entity type."""

        validation = {
            "valid": True,
            "errors": [],
            "warnings": []
        }

        # Create lookup by name
        before_by_name = {e["name"]: e for e in entities_before}
        after_by_name = {e["name"]: e for e in entities_after}

        # Check for missing entities
        missing_names = set(before_by_name.keys()) - set(after_by_name.keys())
        if missing_names:
            validation["errors"].append(f"Missing {entity_type}: {missing_names}")
            validation["valid"] = False

        # Check for new entities
        new_names = set(after_by_name.keys()) - set(before_by_name.keys())
        if new_names:
            validation["warnings"].append(f"New {entity_type}: {new_names}")

        # Check entity field integrity
        common_names = set(before_by_name.keys()) & set(after_by_name.keys())
        for name in common_names:
            entity_before = before_by_name[name]
            entity_after = after_by_name[name]

            # Check required fields
            required_fields = ["name", "description"]
            for field in required_fields:
                if field in entity_before and field not in entity_after:
                    validation["errors"].append(f"Missing field {field} in {entity_type}.{name}")
                    validation["valid"] = False

        return validation
