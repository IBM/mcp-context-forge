# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Services Package.
Provides embedding generation functionality.
"""

from mcpgateway.services.embedding.embedding_service import (
    MAX_BATCH_SIZE,
    MAX_TEXT_LENGTH,
    BatchTooLargeError,
    EmbeddingValidationError,
    EmptyTextError,
    TextTooLongError,
    embed_text,
    embed_texts,
)

__all__ = [
    "MAX_BATCH_SIZE",
    "MAX_TEXT_LENGTH",
    "BatchTooLargeError",
    "EmbeddingValidationError",
    "EmptyTextError",
    "TextTooLongError",
    "embed_text",
    "embed_texts",
]
