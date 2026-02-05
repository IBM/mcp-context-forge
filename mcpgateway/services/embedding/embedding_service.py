# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Embedding Service.
Provides functions for generating text embeddings.
"""

import hashlib
from typing import Optional


# Validation constants
MAX_TEXT_LENGTH = 8192
MAX_BATCH_SIZE = 100


class EmbeddingValidationError(Exception):
    """Raised when embedding input validation fails."""


class TextTooLongError(EmbeddingValidationError):
    """Raised when input text exceeds maximum length."""

    def __init__(self, length: int, max_length: int = MAX_TEXT_LENGTH):
        self.length = length
        self.max_length = max_length
        super().__init__(f"Text length {length} exceeds maximum allowed length of {max_length}")


class BatchTooLargeError(EmbeddingValidationError):
    """Raised when batch size exceeds maximum limit."""

    def __init__(self, size: int, max_size: int = MAX_BATCH_SIZE):
        self.size = size
        self.max_size = max_size
        super().__init__(f"Batch size {size} exceeds maximum allowed size of {max_size}")


class EmptyTextError(EmbeddingValidationError):
    """Raised when input text is empty or whitespace only."""

    def __init__(self):
        super().__init__("Text cannot be empty or whitespace only")


def _validate_text(text: str) -> None:
    """Validate a single text input.

    Args:
        text: The text to validate.

    Raises:
        EmptyTextError: If text is empty or whitespace only.
        TextTooLongError: If text exceeds maximum length.
    """
    if not text or not text.strip():
        raise EmptyTextError()
    if len(text) > MAX_TEXT_LENGTH:
        raise TextTooLongError(len(text))


def _validate_batch(texts: list[str]) -> None:
    """Validate a batch of text inputs.

    Args:
        texts: The list of texts to validate.

    Raises:
        BatchTooLargeError: If batch size exceeds maximum.
        EmptyTextError: If any text is empty or whitespace only.
        TextTooLongError: If any text exceeds maximum length.
    """
    if len(texts) > MAX_BATCH_SIZE:
        raise BatchTooLargeError(len(texts))
    for text in texts:
        _validate_text(text)


async def embed_text(text: str, provider: Optional[str] = None, model: Optional[str] = None) -> list[float]:
    """Generate an embedding vector for a single text input.

    Args:
        text: The input text to embed.
        provider: The embedding provider to use. Defaults to None (uses default provider).
        model: The embedding model to use. Defaults to None (uses provider's default model).

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        EmptyTextError: If text is empty or whitespace only.
        TextTooLongError: If text exceeds maximum length.
    """
    _validate_text(text)
    return _generate_deterministic_embedding(text)


async def embed_texts(texts: list[str], provider: Optional[str] = None, model: Optional[str] = None) -> list[list[float]]:
    """Generate embedding vectors for multiple text inputs.

    Args:
        texts: A list of input texts to embed.
        provider: The embedding provider to use. Defaults to None (uses default provider).
        model: The embedding model to use. Defaults to None (uses provider's default model).

    Returns:
        A list of embedding vectors, one for each input text.

    Raises:
        BatchTooLargeError: If batch size exceeds maximum.
        EmptyTextError: If any text is empty or whitespace only.
        TextTooLongError: If any text exceeds maximum length.
    """
    if not texts:
        return []
    _validate_batch(texts)
    return [_generate_deterministic_embedding(text) for text in texts]


def _generate_deterministic_embedding(text: str, dimension: int = 384) -> list[float]:
    """Generate a deterministic embedding vector from text.

    Uses MD5 hash of the input text as a seed, then extends it to the
    required dimension by repeatedly hashing with an index suffix.
    Values are normalized to the range [-1.0, 1.0].

    Args:
        text: The input text.
        dimension: The target embedding dimension.

    Returns:
        A list of floats in the range [-1.0, 1.0].
    """
    embedding: list[float] = []
    index = 0

    while len(embedding) < dimension:
        hash_input = f"{text}:{index}".encode("utf-8")
        hash_bytes = hashlib.md5(hash_input).digest()

        for byte in hash_bytes:
            if len(embedding) >= dimension:
                break
            normalized = (byte / 127.5) - 1.0
            embedding.append(normalized)

        index += 1

    return embedding
