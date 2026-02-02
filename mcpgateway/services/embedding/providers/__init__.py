# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding/providers/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Providers Package.
Provides various embedding provider implementations.
"""

from mcpgateway.services.embedding.providers.base import EmbeddingProvider
from mcpgateway.services.embedding.providers.dummy import DummyProvider
from mcpgateway.services.embedding.providers.openai import OpenAIProvider

__all__ = [
    "EmbeddingProvider",
    "DummyProvider",
    "OpenAIProvider",
]
