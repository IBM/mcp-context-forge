# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding/providers/dummy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Dummy Embedding Provider.
This module provides a deterministic embedding provider for testing purposes.
It generates consistent embeddings based on input text without calling external APIs.
"""

# Standard
import hashlib
from typing import List

# First-Party
from mcpgateway.services.embedding.providers.base import EmbeddingProvider


class DummyProvider(EmbeddingProvider):
    """Deterministic embedding provider for testing.

    This provider generates embeddings based on a hash of the input text,
    ensuring that the same input always produces the same output. This makes
    tests reliable and fast since no external API calls are required.

    Args:
        dimension: The dimensionality of embedding vectors to generate. Defaults to 384.

    Examples:
        >>> import asyncio
        >>> provider = DummyProvider()
        >>> isinstance(provider, EmbeddingProvider)
        True

        >>> # Same input produces same output (deterministic)
        >>> embedding1 = asyncio.run(provider.embed("hello world"))
        >>> embedding2 = asyncio.run(provider.embed("hello world"))
        >>> embedding1 == embedding2
        True

        >>> # Different inputs produce different outputs
        >>> embedding3 = asyncio.run(provider.embed("goodbye world"))
        >>> embedding1 == embedding3
        False

        >>> # Check embedding dimension
        >>> len(embedding1)
        384
        >>> provider.get_dimension()
        384

        >>> # Check model name
        >>> provider.get_model_name()
        'dummy-384'
    """

    def __init__(self, dimension: int = 384):
        """Initialize the dummy provider.

        Args:
            dimension: The dimensionality of embedding vectors to generate.
        """
        self._dimension = dimension

    async def embed(self, text: str) -> List[float]:
        """Generate a deterministic embedding for a single text input.

        The embedding is derived from an MD5 hash of the input text, extended
        to the required dimension using a deterministic algorithm.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Examples:
            >>> import asyncio
            >>> provider = DummyProvider(dimension=128)
            >>> embedding = asyncio.run(provider.embed("test"))
            >>> len(embedding)
            128
            >>> all(isinstance(v, float) for v in embedding)
            True
            >>> all(-1.0 <= v <= 1.0 for v in embedding)
            True
        """
        return self._generate_deterministic_embedding(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate deterministic embeddings for multiple text inputs.

        Args:
            texts: A list of input texts to embed.

        Returns:
            A list of embedding vectors, one for each input text.

        Examples:
            >>> import asyncio
            >>> provider = DummyProvider()
            >>> texts = ["hello", "world", "test"]
            >>> embeddings = asyncio.run(provider.embed_batch(texts))
            >>> len(embeddings)
            3
            >>> all(len(e) == 384 for e in embeddings)
            True
        """
        return [self._generate_deterministic_embedding(text) for text in texts]

    def get_dimension(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions in the embedding vectors.

        Examples:
            >>> DummyProvider().get_dimension()
            384
            >>> DummyProvider(dimension=512).get_dimension()
            512
        """
        return self._dimension

    def get_model_name(self) -> str:
        """Return the name of the embedding model.

        Returns:
            A string identifier including the dimension.

        Examples:
            >>> DummyProvider().get_model_name()
            'dummy-384'
            >>> DummyProvider(dimension=768).get_model_name()
            'dummy-768'
        """
        return f"dummy-{self._dimension}"

    def _generate_deterministic_embedding(self, text: str) -> List[float]:
        """Generate a deterministic embedding vector from text.

        Uses MD5 hash of the input text as a seed, then extends it to the
        required dimension by repeatedly hashing with an index suffix.
        Values are normalized to the range [-1.0, 1.0].

        Args:
            text: The input text.

        Returns:
            A list of floats in the range [-1.0, 1.0].
        """
        embedding: List[float] = []
        index = 0

        while len(embedding) < self._dimension:
            hash_input = f"{text}:{index}".encode("utf-8")
            hash_bytes = hashlib.md5(hash_input).digest()

            for byte in hash_bytes:
                if len(embedding) >= self._dimension:
                    break
                normalized = (byte / 127.5) - 1.0
                embedding.append(normalized)

            index += 1

        return embedding
