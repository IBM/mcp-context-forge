# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding/providers/openai.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

OpenAI Embedding Provider.
This module provides an embedding provider using OpenAI's embedding API.
"""

# Standard
import logging
from typing import List, Optional

# First-Party
from mcpgateway.services.embedding.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(EmbeddingProvider):
    """Embedding provider using OpenAI's embedding API.

    This provider connects to OpenAI's API to generate text embeddings
    using models like text-embedding-ada-002 or text-embedding-3-small.

    Args:
        api_key: OpenAI API key for authentication.
        model: The embedding model to use. Defaults to "text-embedding-3-small".
        dimension: Optional dimension for models that support it. Defaults to None.

    Examples:
        >>> provider = OpenAIProvider(api_key="test-key")
        >>> isinstance(provider, EmbeddingProvider)
        True
        >>> provider.get_model_name()
        'text-embedding-3-small'
        >>> provider.get_dimension()
        1536
    """

    DEFAULT_MODEL = "text-embedding-3-small"
    MODEL_DIMENSIONS = {
        "text-embedding-ada-002": 1536,
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, dimension: Optional[int] = None):
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key for authentication.
            model: The embedding model to use.
            dimension: Optional dimension override for models that support variable dimensions.
        """
        self._api_key = api_key
        self._model = model
        self._dimension = dimension or self.MODEL_DIMENSIONS.get(model, 1536)

    async def embed(self, text: str) -> List[float]:
        """Generate an embedding for a single text input using OpenAI's API.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            NotImplementedError: This is a skeleton implementation.

        Examples:
            >>> import asyncio
            >>> provider = OpenAIProvider(api_key="test-key")
            >>> try:
            ...     asyncio.run(provider.embed("hello"))
            ... except NotImplementedError:
            ...     print("Not implemented")
            Not implemented
        """
        raise NotImplementedError("OpenAI embedding API integration not yet implemented")

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple text inputs using OpenAI's API.

        Args:
            texts: A list of input texts to embed.

        Returns:
            A list of embedding vectors, one for each input text.

        Raises:
            NotImplementedError: This is a skeleton implementation.

        Examples:
            >>> import asyncio
            >>> provider = OpenAIProvider(api_key="test-key")
            >>> try:
            ...     asyncio.run(provider.embed_batch(["hello", "world"]))
            ... except NotImplementedError:
            ...     print("Not implemented")
            Not implemented
        """
        raise NotImplementedError("OpenAI embedding API integration not yet implemented")

    def get_dimension(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions for the configured model.

        Examples:
            >>> OpenAIProvider(api_key="key").get_dimension()
            1536
            >>> OpenAIProvider(api_key="key", model="text-embedding-3-large").get_dimension()
            3072
            >>> OpenAIProvider(api_key="key", dimension=512).get_dimension()
            512
        """
        return self._dimension

    def get_model_name(self) -> str:
        """Return the name of the embedding model.

        Returns:
            The OpenAI model identifier.

        Examples:
            >>> OpenAIProvider(api_key="key").get_model_name()
            'text-embedding-3-small'
            >>> OpenAIProvider(api_key="key", model="text-embedding-ada-002").get_model_name()
            'text-embedding-ada-002'
        """
        return self._model
