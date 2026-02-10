# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/vector_search_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Team B

Vector Search Service using PostgreSQL with pgvector.

Team B is responsible for:
1. Enabling pgvector extension in docker-compose.yml
2. Adding vector column to Tool table in db.py (e.g., embedding vector(768))
3. Implementing this service to search stored tool embeddings
4. Storing embedded tools as vectors in the database

Required interface:
- search_similar_tools(embedding, limit, threshold) -> List[ToolSearchResult]
"""

# Standard
import logging
from typing import List, Optional

# Third-Party
from sqlalchemy.orm import Session
from sqlalchemy import select

# First-Party
from mcpgateway.db import Tool, ToolEmbedding
from mcpgateway.schemas import ToolSearchResult

logger = logging.getLogger(__name__)


class VectorSearchService:
    """Service for vector similarity search over tool embeddings.
    
    Team B: Implement this class using PostgreSQL with pgvector extension.
    
    Prerequisites (Team B):
    - docker-compose.yml: Enable pgvector extension
    - db.py: Add embedding column to Tool model (vector type)
    - Store tool embeddings in DB when tools are created/updated
    """

    def __init__(self, db: Optional[Session] = None):
        """Initialize the vector search service.
        
        Args:
            db: Optional database session for queries
            
        Team B: Add your pgvector initialization here.
        """
        self.db = db

    async def search_similar_tools(
        self,
        embedding: List[float],
        limit: int = 10,
        threshold: Optional[float] = None,
    ) -> List[ToolSearchResult]:
        """Search for tools similar to the given embedding vector.

        Args:
            embedding: Query embedding vector (e.g., 768-dimensional)
            limit: Maximum number of results to return (1-50)
            threshold: Optional similarity threshold (0-1). 
                      Only return results with similarity >= threshold

        Returns:
            List of ToolSearchResult objects ranked by similarity (highest first)
            Each result should include:
            - tool_name: str
            - description: Optional[str]
            - server_id: Optional[str]
            - server_name: Optional[str]
            - similarity_score: float (0-1, higher = more similar)

        Raises:
            RuntimeError: If vector search fails

        Team B: Implement your pgvector search logic here.
        
        Steps:
        1. Query Tool table where embedding column exists
        2. Use pgvector's <=> operator for cosine distance
        3. Apply threshold filter if provided
        4. Order by similarity (lowest distance = highest similarity)
        5. Limit results
        6. Convert distance to similarity score: similarity = 1 - distance
        
        Example with SQLAlchemy + pgvector:
        ```python
        from mcpgateway.db import Tool
        from sqlalchemy import select
        
        query = select(Tool).where(Tool.embedding.isnot(None))
        query = query.order_by(Tool.embedding.cosine_distance(embedding))
        
        if threshold:
            # Filter: only tools with similarity >= threshold
            query = query.filter(Tool.embedding.cosine_distance(embedding) <= (1 - threshold))
        
        results = db.execute(query.limit(limit)).scalars().all()
        
        return [
            ToolSearchResult(
                tool_name=tool.name,
                description=tool.description,
                server_id=tool.gateway_id,
                server_name=tool.gateway.name if tool.gateway else None,
                similarity_score=1 - distance  # convert distance to similarity
            )
            for tool in results
        ]
        ```
        """
        # TODO: Team B - Replace this stub with actual pgvector search
        # Once you've added the embedding column to Tool model in db.py
        
        # Placeholder: Return empty results
        return []

 
    def get_tool_embedding(
        self, 
        db: Session, 
        tool_id: str
    ) -> Optional[ToolEmbedding]:
        """Retrieve stored embedding for a tool.
        
        Args:
            db: Database session
            tool_id: ID of the tool
        
        Returns:
            ToolEmbedding if found, None otherwise
            
        Example:
            >>> embedding = search_service.get_tool_embedding(db, "tool-123")
            >>> if embedding:
            ...     print(f"Found embedding with {len(embedding.embedding)} dimensions")
            ...     print(f"Model: {embedding.model_name}")
            ...     print(f"Created: {embedding.created_at}")
        """
        return db.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first()

    def delete_tool_embedding(
        self, 
        db: Session, 
        tool_id: str
    ) -> bool:
        """Delete stored embedding for a tool.
        
        Args:
            db: Database session
            tool_id: ID of the tool
        
        Returns:
            True if deleted, False if not found
            
        Example:
            >>> # Delete old embedding before regenerating
            >>> deleted = search_service.delete_tool_embedding(db, "tool-123")
            >>> if deleted:
            ...     print("Embedding deleted successfully")
            ...     # Now regenerate with new model
            ...     await embedding_service.embed_and_store_tool(db, tool)
        """
        embedding = self.get_tool_embedding(db, tool_id)
        if embedding:
            db.delete(embedding)
            db.commit()
            logger.info(f"Deleted embedding for tool {tool_id}")
            return True
        logger.warning(f"No embedding found for tool {tool_id}")
        return False
    