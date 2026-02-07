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
import os
from typing import List
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
        self.embedding_config = EmbeddingConfig(
            provider="openai",
            config=OpenAIEmbeddingConfig(
    model="text-embedding-3-small",
    api_key=os.getenv("OPENAI_API_KEY", "sk-fake-key-for-testing")
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

