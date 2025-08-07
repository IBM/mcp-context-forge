# -*- coding: utf-8 -*-
"""Tag Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

This module implements tag management and retrieval for all entities in the MCP Gateway.
It handles:
- Fetching all unique tags across entities
- Filtering tags by entity type
- Tag statistics and counts
"""

# Standard
from typing import Dict, List, Optional

# Third-Party
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import TagInfo, TagStats


class TagService:
    """Service for managing and retrieving tags across all entities."""

    async def get_all_tags(self, db: Session, entity_types: Optional[List[str]] = None) -> List[TagInfo]:
        """Retrieve all unique tags across specified entity types.

        Args:
            db: Database session
            entity_types: List of entity types to filter by (tools, resources, prompts, servers, gateways)
                         If None, returns tags from all entity types

        Returns:
            List of TagInfo objects containing tag details
        """
        tag_data: Dict[str, TagStats] = {}

        # Define entity type mapping
        entity_map = {
            "tools": DbTool,
            "resources": DbResource,
            "prompts": DbPrompt,
            "servers": DbServer,
            "gateways": DbGateway,
        }

        # If no entity types specified, use all
        if entity_types is None:
            entity_types = list(entity_map.keys())

        # Collect tags from each requested entity type
        for entity_type in entity_types:
            if entity_type not in entity_map:
                continue

            model = entity_map[entity_type]

            # Query all tags from this entity type
            stmt = select(model.tags).where(model.tags.isnot(None))
            result = db.execute(stmt)

            for row in result:
                tags = row[0] if row[0] else []
                for tag in tags:
                    if tag not in tag_data:
                        tag_data[tag] = TagStats(tools=0, resources=0, prompts=0, servers=0, gateways=0, total=0)

                    # Increment count for this entity type
                    if entity_type == "tools":
                        tag_data[tag].tools += 1
                    elif entity_type == "resources":
                        tag_data[tag].resources += 1
                    elif entity_type == "prompts":
                        tag_data[tag].prompts += 1
                    elif entity_type == "servers":
                        tag_data[tag].servers += 1
                    elif entity_type == "gateways":
                        tag_data[tag].gateways += 1

                    tag_data[tag].total += 1

        # Convert to TagInfo list
        tags = [TagInfo(name=tag, stats=stats) for tag, stats in sorted(tag_data.items())]

        return tags

    async def get_tag_counts(self, db: Session) -> Dict[str, int]:
        """Get count of unique tags per entity type.

        Args:
            db: Database session

        Returns:
            Dictionary mapping entity type to count of unique tags
        """
        counts = {}

        # Count unique tags for tools
        tool_tags_stmt = select(func.json_array_length(DbTool.tags)).where(DbTool.tags.isnot(None))
        tool_tags = db.execute(tool_tags_stmt).scalars().all()
        counts["tools"] = sum(tool_tags)

        # Count unique tags for resources
        resource_tags_stmt = select(func.json_array_length(DbResource.tags)).where(DbResource.tags.isnot(None))
        resource_tags = db.execute(resource_tags_stmt).scalars().all()
        counts["resources"] = sum(resource_tags)

        # Count unique tags for prompts
        prompt_tags_stmt = select(func.json_array_length(DbPrompt.tags)).where(DbPrompt.tags.isnot(None))
        prompt_tags = db.execute(prompt_tags_stmt).scalars().all()
        counts["prompts"] = sum(prompt_tags)

        # Count unique tags for servers
        server_tags_stmt = select(func.json_array_length(DbServer.tags)).where(DbServer.tags.isnot(None))
        server_tags = db.execute(server_tags_stmt).scalars().all()
        counts["servers"] = sum(server_tags)

        # Count unique tags for gateways
        gateway_tags_stmt = select(func.json_array_length(DbGateway.tags)).where(DbGateway.tags.isnot(None))
        gateway_tags = db.execute(gateway_tags_stmt).scalars().all()
        counts["gateways"] = sum(gateway_tags)

        return counts
