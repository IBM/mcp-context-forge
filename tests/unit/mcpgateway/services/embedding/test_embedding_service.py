# -*- coding: utf-8 -*-
"""Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for the embedding service.
"""

import pytest

from mcpgateway.services.embedding import (
    MAX_BATCH_SIZE,
    MAX_TEXT_LENGTH,
    BatchTooLargeError,
    EmptyTextError,
    TextTooLongError,
    embed_text,
    embed_texts,
)


class TestEmbedText:
    """Tests for embed_text function."""

    @pytest.mark.asyncio
    async def test_returns_list_of_floats(self):
        """embed_text should return a list of floats."""
        result = await embed_text("hello world")
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_default_dimension(self):
        """embed_text should return 384 dimensions by default."""
        result = await embed_text("hello world")
        assert len(result) == 384

    @pytest.mark.asyncio
    async def test_deterministic(self):
        """Same input should produce same output."""
        result1 = await embed_text("hello world")
        result2 = await embed_text("hello world")
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_outputs(self):
        """Different inputs should produce different embeddings."""
        result1 = await embed_text("hello")
        result2 = await embed_text("world")
        assert result1 != result2

    @pytest.mark.asyncio
    async def test_values_in_range(self):
        """Embedding values should be in range [-1.0, 1.0]."""
        result = await embed_text("test input")
        assert all(-1.0 <= v <= 1.0 for v in result)

    @pytest.mark.asyncio
    async def test_accepts_provider_parameter(self):
        """embed_text should accept provider parameter."""
        result = await embed_text("hello", provider="openai")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_accepts_model_parameter(self):
        """embed_text should accept model parameter."""
        result = await embed_text("hello", model="text-embedding-3-small")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_accepts_provider_and_model_parameters(self):
        """embed_text should accept both provider and model parameters."""
        result = await embed_text("hello", provider="openai", model="text-embedding-3-small")
        assert isinstance(result, list)


class TestEmbedTexts:
    """Tests for embed_texts function."""

    @pytest.mark.asyncio
    async def test_returns_list_of_embeddings(self):
        """embed_texts should return a list of embedding vectors."""
        result = await embed_texts(["hello", "world"])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(emb, list) for emb in result)

    @pytest.mark.asyncio
    async def test_each_embedding_has_correct_dimension(self):
        """Each embedding should have the default dimension."""
        result = await embed_texts(["a", "b", "c"])
        assert all(len(emb) == 384 for emb in result)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """embed_texts should handle empty list."""
        result = await embed_texts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_consistent_with_embed_text(self):
        """embed_texts should produce same results as individual embed_text calls."""
        texts = ["hello", "world", "test"]
        batch_result = await embed_texts(texts)
        individual_results = [await embed_text(t) for t in texts]
        assert batch_result == individual_results

    @pytest.mark.asyncio
    async def test_accepts_provider_parameter(self):
        """embed_texts should accept provider parameter."""
        result = await embed_texts(["hello", "world"], provider="openai")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_accepts_model_parameter(self):
        """embed_texts should accept model parameter."""
        result = await embed_texts(["hello", "world"], model="text-embedding-3-small")
        assert isinstance(result, list)


class TestEmbedTextValidation:
    """Tests for embed_text input validation."""

    @pytest.mark.asyncio
    async def test_empty_string_raises_error(self):
        """embed_text should raise EmptyTextError for empty string."""
        with pytest.raises(EmptyTextError):
            await embed_text("")

    @pytest.mark.asyncio
    async def test_whitespace_only_raises_error(self):
        """embed_text should raise EmptyTextError for whitespace only."""
        with pytest.raises(EmptyTextError):
            await embed_text("   ")

    @pytest.mark.asyncio
    async def test_tabs_and_newlines_only_raises_error(self):
        """embed_text should raise EmptyTextError for tabs/newlines only."""
        with pytest.raises(EmptyTextError):
            await embed_text("\t\n\r")

    @pytest.mark.asyncio
    async def test_text_too_long_raises_error(self):
        """embed_text should raise TextTooLongError for text exceeding max length."""
        long_text = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(TextTooLongError) as exc_info:
            await embed_text(long_text)
        assert exc_info.value.length == MAX_TEXT_LENGTH + 1
        assert exc_info.value.max_length == MAX_TEXT_LENGTH

    @pytest.mark.asyncio
    async def test_text_at_max_length_succeeds(self):
        """embed_text should accept text at exactly max length."""
        max_text = "a" * MAX_TEXT_LENGTH
        result = await embed_text(max_text)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_text_with_leading_trailing_whitespace_succeeds(self):
        """embed_text should accept text with leading/trailing whitespace."""
        result = await embed_text("  hello world  ")
        assert isinstance(result, list)


class TestEmbedTextsValidation:
    """Tests for embed_texts input validation."""

    @pytest.mark.asyncio
    async def test_batch_too_large_raises_error(self):
        """embed_texts should raise BatchTooLargeError for oversized batch."""
        large_batch = ["text"] * (MAX_BATCH_SIZE + 1)
        with pytest.raises(BatchTooLargeError) as exc_info:
            await embed_texts(large_batch)
        assert exc_info.value.size == MAX_BATCH_SIZE + 1
        assert exc_info.value.max_size == MAX_BATCH_SIZE

    @pytest.mark.asyncio
    async def test_batch_at_max_size_succeeds(self):
        """embed_texts should accept batch at exactly max size."""
        max_batch = ["text"] * MAX_BATCH_SIZE
        result = await embed_texts(max_batch)
        assert len(result) == MAX_BATCH_SIZE

    @pytest.mark.asyncio
    async def test_empty_string_in_batch_raises_error(self):
        """embed_texts should raise EmptyTextError if any text is empty."""
        with pytest.raises(EmptyTextError):
            await embed_texts(["hello", "", "world"])

    @pytest.mark.asyncio
    async def test_whitespace_in_batch_raises_error(self):
        """embed_texts should raise EmptyTextError if any text is whitespace only."""
        with pytest.raises(EmptyTextError):
            await embed_texts(["hello", "   ", "world"])

    @pytest.mark.asyncio
    async def test_long_text_in_batch_raises_error(self):
        """embed_texts should raise TextTooLongError if any text is too long."""
        long_text = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(TextTooLongError):
            await embed_texts(["hello", long_text, "world"])

    @pytest.mark.asyncio
    async def test_empty_list_bypasses_validation(self):
        """embed_texts should return empty list without validation for empty input."""
        result = await embed_texts([])
        assert result == []


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_empty_text_error_is_validation_error(self):
        """EmptyTextError should be subclass of EmbeddingValidationError."""
        from mcpgateway.services.embedding import EmbeddingValidationError
        assert issubclass(EmptyTextError, EmbeddingValidationError)

    def test_text_too_long_error_is_validation_error(self):
        """TextTooLongError should be subclass of EmbeddingValidationError."""
        from mcpgateway.services.embedding import EmbeddingValidationError
        assert issubclass(TextTooLongError, EmbeddingValidationError)

    def test_batch_too_large_error_is_validation_error(self):
        """BatchTooLargeError should be subclass of EmbeddingValidationError."""
        from mcpgateway.services.embedding import EmbeddingValidationError
        assert issubclass(BatchTooLargeError, EmbeddingValidationError)

    def test_can_catch_all_validation_errors(self):
        """All validation errors should be catchable with EmbeddingValidationError."""
        from mcpgateway.services.embedding import EmbeddingValidationError

        with pytest.raises(EmbeddingValidationError):
            raise EmptyTextError()

        with pytest.raises(EmbeddingValidationError):
            raise TextTooLongError(10000)

        with pytest.raises(EmbeddingValidationError):
            raise BatchTooLargeError(200)
