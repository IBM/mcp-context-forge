# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Services Package.
Provides embedding generation functionality with pluggable providers.
"""

from mcpgateway.services.embedding.providers import (
    DummyProvider,
    EmbeddingAPIError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    OpenAIProvider,
)

__all__ = [
    "DummyProvider",
    "EmbeddingAPIError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingRateLimitError",
    "OpenAIProvider",
]
