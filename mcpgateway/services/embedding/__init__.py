# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/embedding/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Services Package.
Provides embedding generation functionality with pluggable providers.
"""

from mcpgateway.services.embedding.providers import DummyProvider, EmbeddingProvider, OpenAIProvider

__all__ = [
    "EmbeddingProvider",
    "DummyProvider",
    "OpenAIProvider",
]
