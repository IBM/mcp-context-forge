# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Team A

Embedding Service for generating text embeddings.

Team A is responsible for implementing this service.
This file will contain the embedding model and related functions.

Required interface:
- embed_query(query: str) -> List[float]: Generate embedding for a query string
"""

# Standard
import asyncio
import logging
import os
from typing import List, Dict, Any, Optional

from mcpgateway.config import settings
from mcpgateway.services.mcp_client_chat_service import (
    EmbeddingConfig,
    EmbeddingProviderFactory,
    OpenAIEmbeddingConfig,
)
from sqlalchemy.orm import Session
from mcpgateway.db import ToolEmbedding

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Service for generating text embeddings.
    
    Team A: Implement this class with your chosen embedding model
    (e.g., OpenAI embeddings, sentence-transformers, etc.)
    """

    def __init__(self):
        """Initialize the embedding model.
        
        Team A: Add your model initialization here.
        Example: Load sentence-transformers model, initialize OpenAI client, etc.
        """
        # Set up attributes first
        # Get config from settings instead of hardcoding
        self.embedding_config = EmbeddingConfig(
            provider=settings.embedding_provider,
            config=OpenAIEmbeddingConfig(
                model=settings.embedding_model,
                api_key=settings.embedding_api_key.get_secret_value()
            )
        )
        self._provider = None
        self._embedding_model = None
        self._initialized = False

    async def initialize(self):
        """Initialize the embedding provider (separate async method)."""
        if self._initialized:
            return
        
        self._provider = EmbeddingProviderFactory.create(self.embedding_config)
        self._embedding_model = self._provider.get_embedding_model()
        self._initialized = True

    async def embed_query(self, query: str) -> List[float]:
        """Generate embedding vector for a query string.

        Args:
            query: The text query to embed

        Returns:
            List of floats representing the embedding vector
            Expected dimensions: 768 for most models (but can vary)

        Raises:
            RuntimeError: If embedding generation fails

        Team A: Implement your embedding logic here.
        """
        # TODO: Team A - Replace this stub with actual embedding generation
        # Example with sentence-transformers:
        # embedding = self.model.encode(query)
        # return embedding.tolist()
        
        if not self._initialized:
            await self.initialize()

        embedding = await self._embedding_model.aembed_query(query)
        return embedding

    async def embed_tool(self, tool_data: dict) -> List[float]:
        """Generate embedding for a tool based on its metadata."""
        # Validate tool data 
        if not isinstance(tool_data, dict):
            raise ValueError("Tool data must be a dictionary")
        
        if not tool_data.get('original_name'):
            raise ValueError("Tool data must include 'original_name'")
        
        # Convert tool data to searchable text
        tool_text = self.prepare_tool_text(tool_data)
        
        # Generate embedding using embed_text
        try:
            embedding = await self.embed_text(tool_text)
            return embedding
        except Exception as e:
            raise RuntimeError(f"Tool embedding failed: {e}")

    async def embed_tool_from_db(self, tool) -> List[float]:
        """Generate embedding for tool from database object."""
        tool_data = {
            'original_name': tool.original_name,
            'description': tool.description,
            'tags': tool.tags if tool.tags else [],
            'integration_type': tool.integration_type,
            'input_schema': tool.input_schema if tool.input_schema else {},
            'gateway_id': tool.gateway_id
        }
        
        return await self.embed_tool(tool_data)

    def prepare_tool_text(self, tool_data: dict) -> str:
        """Convert tool metadata to searchable text."""
        parts = []
        
        # Core info
        parts.append(tool_data['original_name'])
        if tool_data.get('description'):
            parts.append(tool_data['description'])
        
        # Add parameter descriptions for better search
        if tool_data.get('input_schema', {}).get('properties'):
            param_parts = []
            for name, schema in tool_data['input_schema']['properties'].items():
                if schema.get('description'):
                    param_parts.append(f"{name}: {schema['description']}")
            if param_parts:
                parts.append(f"parameters: {', '.join(param_parts)}")
        
        # Tags and metadata
        if tool_data.get('tags'):
            # Handle tags as either strings or dict objects
            tag_strs = []
            for tag in tool_data['tags']:
                if isinstance(tag, dict):
                    tag_strs.append(tag.get('id') or tag.get('label', str(tag)))
                else:
                    tag_strs.append(str(tag))
            parts.append(f"tags: {', '.join(tag_strs)}")
        
        if tool_data.get('integration_type'):
            parts.append(f"type: {tool_data['integration_type']}")
        
        return " | ".join(parts)

    async def embed_text(self, text: str) -> List[float]:
        """Generate embedding for arbitrary text."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty or whitespace only")
        
        if len(text) > 8192:  # Most embedding models have limits
            raise ValueError(f"Text too long: {len(text)} characters (max 8192)")
        
        if not self._initialized:
            await self.initialize()
        
        try:
            embedding = await self._embedding_model.aembed_query(text.strip())
            return embedding
        except Exception as e:
            logging.error(f"Failed to generate embedding for text: {e}")
            raise RuntimeError(f"Text embedding failed: {e}")

    async def batch_embed_tools(self, tools: List[dict]) -> List[List[float]]:
        """Generate embeddings for multiple tools efficiently using true batching."""
        if not tools:
            return []
        
        if not self._initialized:
            await self.initialize()
        
        # Convert all tools to text in one step
        texts = [self.prepare_tool_text(tool) for tool in tools]
        
        try:
            # ✅ True batch processing - single API call for all texts
            embeddings = await self._embedding_model.aembed_documents(texts)
            
            logging.info(f"Successfully generated embeddings for {len(embeddings)} tools in batch")
            return embeddings
            
        except Exception as e:
            logging.error(f"Batch embedding failed: {e}")
            raise RuntimeError(f"Batch embedding failed: {e}")

    async def batch_embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts efficiently."""
        if not texts:
            return []
        
        # Validate input
        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValueError(f"Text at index {i} cannot be empty")
            if len(text) > 8192:
                raise ValueError(f"Text at index {i} too long: {len(text)} characters")
        
        if not self._initialized:
            await self.initialize()
        
        try:
            # ✅ True batch processing
            embeddings = await self._embedding_model.aembed_documents(texts)
            return embeddings
        except Exception as e:
            logging.error(f"Batch text embedding failed: {e}")
            raise RuntimeError(f"Batch text embedding failed: {e}")

    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the current embedding provider."""
        return {
            'provider': self.embedding_config.provider,
            'model': self.embedding_config.config.model,
            'initialized': self._initialized
            }

    def store_tool_embedding(
        self, 
        db: Session, 
        tool_id: str, 
        embedding: List[float], 
        model_name: str
    ) -> ToolEmbedding:
        """Store or update tool embedding in database.
        
        Args:
            db: Database session
            tool_id: ID of the tool
            embedding: Embedding vector (list of floats)
            model_name: Name of the embedding model used
        
        Returns:
            ToolEmbedding: The created or updated embedding record
        
        Raises:
            ValueError: If embedding is invalid
            RuntimeError: If database operation fails
        """
        # Validate embedding
        if not embedding or not isinstance(embedding, list):
            raise ValueError("Embedding must be a non-empty list")
        
        if not all(isinstance(x, (int, float)) for x in embedding):
            raise ValueError("Embedding must contain only numbers")
        
        try:
            # Check if embedding already exists for this tool
            existing = db.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool_id
            ).first()
            
            if existing:
                # Update existing embedding
                existing.embedding = embedding
                existing.model_name = model_name
                # updated_at will be automatically set by onupdate
                db.commit()
                db.refresh(existing)
                logging.info(f"Updated embedding for tool {tool_id}")
                return existing
            else:
                # Create new embedding
                db_embedding = ToolEmbedding(
                    tool_id=tool_id,
                    embedding=embedding,
                    model_name=model_name,
                )
                db.add(db_embedding)
                db.commit()
                db.refresh(db_embedding)
                logging.info(f"Created embedding for tool {tool_id}")
                return db_embedding
                
        except Exception as e:
            db.rollback()
            logging.error(f"Failed to store embedding for tool {tool_id}: {e}")
            raise RuntimeError(f"Database operation failed: {e}")

    def batch_store_tool_embeddings(
        self,
        db: Session,
        tool_embeddings: List[tuple[str, List[float]]],
        model_name: str
    ) -> List[ToolEmbedding]:
        """Store multiple tool embeddings efficiently.
        
        Args:
            db: Database session
            tool_embeddings: List of (tool_id, embedding) tuples
            model_name: Name of the embedding model used
        
        Returns:
            List of created/updated ToolEmbedding records
        """
        if not tool_embeddings:
            return []
        
        try:
            results = []
            
            # Get existing embeddings in one query
            tool_ids = [tool_id for tool_id, _ in tool_embeddings]
            existing_map = {
                emb.tool_id: emb 
                for emb in db.query(ToolEmbedding).filter(
                    ToolEmbedding.tool_id.in_(tool_ids)
                ).all()
            }
            
            # Process each embedding
            for tool_id, embedding in tool_embeddings:
                if tool_id in existing_map:
                    # Update existing
                    existing = existing_map[tool_id]
                    existing.embedding = embedding
                    existing.model_name = model_name
                    results.append(existing)
                else:
                    # Create new
                    new_embedding = ToolEmbedding(
                        tool_id=tool_id,
                        embedding=embedding,
                        model_name=model_name,
                    )
                    db.add(new_embedding)
                    results.append(new_embedding)
            
            # Commit all changes at once
            db.commit()
            
            # Refresh all objects
            for result in results:
                db.refresh(result)
            
            logging.info(f"Stored {len(results)} tool embeddings")
            return results
            
        except Exception as e:
            db.rollback()
            logging.error(f"Batch store failed: {e}")
            raise RuntimeError(f"Batch storage failed: {e}")
    
    async def embed_and_store_tool(
        self, 
        db: Session, 
        tool
    ) -> ToolEmbedding:
        """Generate and store embedding for a single tool.
        
        Args:
            db: Database session
            tool: Tool object from database
        
        Returns:
            ToolEmbedding: The stored embedding record
        """
        # Generate embedding
        embedding = await self.embed_tool_from_db(tool)
        
        # Store in database
        model_name = self.embedding_config.config.model
        return self.store_tool_embedding(db, tool.id, embedding, model_name)


    async def embed_and_store_tools_batch(
        self,
        db: Session,
        tools: List
    ) -> List[ToolEmbedding]:
        """Generate and store embeddings for multiple tools efficiently.
        
        Args:
            db: Database session
            tools: List of Tool objects from database
        
        Returns:
            List of stored ToolEmbedding records
        """
        if not tools:
            return []
        
        # Convert tools to dict format
        tools_data = []
        for tool in tools:
            tool_data = {
                'original_name': tool.original_name,
                'description': tool.description,
                'tags': tool.tags if tool.tags else [],
                'integration_type': tool.integration_type,
                'input_schema': tool.input_schema if tool.input_schema else {},
                'gateway_id': tool.gateway_id
            }
            tools_data.append(tool_data)
        
        # Generate all embeddings in batch
        embeddings = await self.batch_embed_tools(tools_data)
        
        # Prepare for batch storage
        tool_embeddings = [(tool.id, embedding) for tool, embedding in zip(tools, embeddings)]
        
        # Store all embeddings
        model_name = self.embedding_config.config.model
        return self.batch_store_tool_embeddings(db, tool_embeddings, model_name)


# ---------------------------------------------------------------------------
# Module-level convenience functions (used by main.py and cli.py)
# ---------------------------------------------------------------------------

async def index_tool_fire_and_forget(tool_id: str) -> None:
    """Index a single tool's embedding in the background.

    Creates its own DB session and EmbeddingService instance so it can run
    as a fire-and-forget ``asyncio.create_task()`` without affecting the
    caller's latency.  All exceptions are caught and logged.

    Args:
        tool_id: Primary key of the tool to index.
    """
    from mcpgateway.db import SessionLocal, Tool  # pylint: disable=import-outside-toplevel

    db = SessionLocal()
    try:
        tool = db.query(Tool).filter(Tool.id == tool_id).first()
        if tool is None:
            logger.warning("index_tool_fire_and_forget: tool %s not found", tool_id)
            return

        service = EmbeddingService()
        await service.embed_and_store_tool(db, tool)
        logger.info("Successfully indexed embedding for tool %s", tool_id)
    except Exception:
        logger.exception("Failed to index embedding for tool %s", tool_id)
    finally:
        db.close()


async def reindex_all_tools(db: Session) -> Dict[str, int]:
    """Re-index embeddings for every enabled tool in the database.

    Args:
        db: An open SQLAlchemy session.

    Returns:
        Dict with keys ``total``, ``succeeded``, ``failed``.
    """
    from mcpgateway.db import Tool  # pylint: disable=import-outside-toplevel

    tools = db.query(Tool).filter(Tool.enabled.is_(True)).all()
    total = len(tools)
    succeeded = 0
    failed = 0

    service = EmbeddingService()

    for tool in tools:
        try:
            await service.embed_and_store_tool(db, tool)
            succeeded += 1
        except Exception:
            logger.exception("Failed to index tool %s (%s)", tool.id, tool.original_name)
            failed += 1

    return {"total": total, "succeeded": succeeded, "failed": failed}
