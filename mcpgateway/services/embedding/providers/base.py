# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding/providers/base.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Base Embedding Provider Interface.
This module defines the abstract base class for embedding providers.
All embedding providers must implement this interface.
"""

# Standard
from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    This class defines the interface that all embedding providers must implement.
    Providers are responsible for generating vector embeddings from text input.

    Examples:
        >>> # EmbeddingProvider is abstract and cannot be instantiated directly
        >>> try:
        ...     EmbeddingProvider()
        ... except TypeError as e:
        ...     print("Cannot instantiate abstract class")
        Cannot instantiate abstract class

        >>> # Check if EmbeddingProvider is an abstract base class
        >>> from abc import ABC
        >>> issubclass(EmbeddingProvider, ABC)
        True

        >>> # Verify abstract methods are defined
        >>> hasattr(EmbeddingProvider, 'embed')
        True
        >>> hasattr(EmbeddingProvider, 'embed_batch')
        True
        >>> hasattr(EmbeddingProvider, 'get_dimension')
        True
        >>> hasattr(EmbeddingProvider, 'get_model_name')
        True
    """

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text input.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> hasattr(EmbeddingProvider, 'embed')
            True
        """

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple text inputs.

        Args:
            texts: A list of input texts to embed.

        Returns:
            A list of embedding vectors, one for each input text.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> hasattr(EmbeddingProvider, 'embed_batch')
            True
        """

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions in the embedding vectors produced by this provider.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> hasattr(EmbeddingProvider, 'get_dimension')
            True
        """

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the name of the embedding model.

        Returns:
            A string identifier for the embedding model used by this provider.

        Examples:
            >>> # This is an abstract method - implementation required in subclasses
            >>> import inspect
            >>> hasattr(EmbeddingProvider, 'get_model_name')
            True
        """
