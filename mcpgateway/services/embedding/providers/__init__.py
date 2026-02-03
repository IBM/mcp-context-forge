# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Providers Package.
Provides various embedding provider implementations.
"""

from mcpgateway.services.embedding.providers.base import (
    EmbeddingAPIError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
)
from mcpgateway.services.embedding.providers.dummy import DummyProvider
from mcpgateway.services.embedding.providers.openai import OpenAIProvider

__all__ = [
    "EmbeddingAPIError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingRateLimitError",
    "DummyProvider",
    "OpenAIProvider",
]
