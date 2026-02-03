# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Base Embedding Provider Interface.
This module defines the abstract base class for embedding providers.
All embedding providers must implement this interface.
"""

# Standard
from abc import ABC, abstractmethod


class EmbeddingProviderError(Exception):
    """Base exception for embedding provider errors."""


class EmbeddingRateLimitError(EmbeddingProviderError):
    """Raised when the provider rate limit is exceeded."""


class EmbeddingAPIError(EmbeddingProviderError):
    """Raised when the embedding API returns an error."""


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    This class defines the interface that all embedding providers must implement.
    Providers are responsible for generating vector embeddings from text input.

    Implementations should:
        - Initialize with any required credentials (API keys, endpoints, etc.)
        - Handle rate limiting and retries internally where appropriate
        - Raise EmbeddingProviderError subclasses on failures

    Error Handling:
        - EmbeddingRateLimitError: When rate limits are exceeded
        - EmbeddingAPIError: When the underlying API returns an error
        - EmbeddingProviderError: For other provider-specific errors
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text input.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            EmbeddingProviderError: If embedding generation fails.
        """

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for multiple text inputs.

        Args:
            texts: A list of input texts to embed.

        Returns:
            A list of embedding vectors, one for each input text.

        Raises:
            EmbeddingProviderError: If embedding generation fails.
        """

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions in the embedding vectors produced by this provider.
        """

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the name of the embedding model.

        Returns:
            A string identifier for the embedding model used by this provider.
        """

    def get_max_batch_size(self) -> int:
        """Return the maximum batch size supported by this provider.

        Override this method if the provider has batch size limits.

        Returns:
            The maximum number of texts that can be embedded in a single batch.
            Defaults to 100.
        """
        return 100

    async def close(self) -> None:
        """Clean up provider resources.

        Override this method if the provider needs to close connections
        or release resources. Default implementation does nothing.
        """

    def is_available(self) -> bool:
        """Check if the provider is configured and available.

        Override this method to perform availability checks
        (e.g., API key validation, connectivity tests).

        Returns:
            True if the provider is ready to generate embeddings.
            Defaults to True.
        """
        return True
