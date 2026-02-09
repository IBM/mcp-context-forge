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
import logging
import os
from typing import List, Dict, Any, Optional
from mcpgateway.config import settings
from mcpgateway.services.mcp_client_chat_service import (
    EmbeddingConfig,
    EmbeddingProviderFactory, 
    OpenAIEmbeddingConfig,
)

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
            parts.append(f"tags: {', '.join(tool_data['tags'])}")
        
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
