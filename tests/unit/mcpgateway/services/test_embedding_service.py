# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_embedding_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for EmbeddingService and related embedding utilities.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.embedding_service import EmbeddingService


class TestEmbeddingServiceBasic:
    """Test basic EmbeddingService functionality."""

    def test_service_creation(self):
        """Test that service can be created without errors."""
        service = EmbeddingService()
        assert service._initialized is False
        assert service._provider is None
        assert service._embedding_model is None

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_initialize_success(self, mock_factory):
        """Test successful service initialization."""
        # Set up the mock chain: Factory -> Provider -> EmbeddingModel
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        
        service = EmbeddingService()
        await service.initialize()
        
        assert service._initialized is True
        assert service._provider == mock_provider
        assert service._embedding_model == mock_embedding_model
        mock_factory.create.assert_called_once()

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_query_success(self, mock_factory):
        """Test successful query embedding."""
        # Set up the mock chain
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embedding = [0.1, 0.2, 0.3] * 512  # 1536 dimensions
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.return_value = expected_embedding
        
        service = EmbeddingService()
        
        result = await service.embed_query("weather tools")
        
        assert result == expected_embedding
        assert service._initialized is True  # Should auto-initialize
        mock_embedding_model.aembed_query.assert_called_once_with("weather tools")

    @pytest.mark.asyncio
    async def test_embed_query_not_initialized_auto_initializes(self):
        """Test that embed_query auto-initializes if not initialized."""
        with patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory') as mock_factory:
            mock_provider = MagicMock()
            mock_embedding_model = AsyncMock()
            mock_embedding_model.aembed_query.return_value = [0.1] * 1536
            
            mock_factory.create.return_value = mock_provider
            mock_provider.get_embedding_model.return_value = mock_embedding_model
            
            service = EmbeddingService()
            assert service._initialized is False
            
            await service.embed_query("test")
            
            assert service._initialized is True


class TestPrepareToolText:
    """Test the prepare_tool_text method."""

    def test_prepare_tool_text_complete(self):
        """Test prepare_tool_text with full tool data."""
        service = EmbeddingService()
        tool_data = {
            'original_name': 'weather_api',
            'description': 'Get current weather information for any city',
            'input_schema': {
                'properties': {
                    'city': {'description': 'City name'},
                    'units': {'description': 'Temperature units'}
                }
            },
            'tags': ['weather', 'api', 'data'],
            'integration_type': 'REST'
        }
        
        result = service.prepare_tool_text(tool_data)
        
        expected = "weather_api | Get current weather information for any city | parameters: city: City name, units: Temperature units | tags: weather, api, data | type: REST"
        assert result == expected

    def test_prepare_tool_text_minimal(self):
        """Test prepare_tool_text with minimal tool data."""
        service = EmbeddingService()
        tool_data = {
            'original_name': 'simple_tool',
            'description': 'A simple tool'
        }
        
        result = service.prepare_tool_text(tool_data)
        
        expected = "simple_tool | A simple tool"
        assert result == expected

    def test_prepare_tool_text_no_description(self):
        """Test prepare_tool_text without description."""
        service = EmbeddingService()
        tool_data = {
            'original_name': 'no_desc_tool'
        }
        
        result = service.prepare_tool_text(tool_data)
        
        expected = "no_desc_tool"
        assert result == expected

    def test_prepare_tool_text_with_tags_only(self):
        """Test prepare_tool_text with tags but no other metadata."""
        service = EmbeddingService()
        tool_data = {
            'original_name': 'tagged_tool',
            'description': 'Tool with tags',
            'tags': ['tag1', 'tag2']
        }
        
        result = service.prepare_tool_text(tool_data)
        
        expected = "tagged_tool | Tool with tags | tags: tag1, tag2"
        assert result == expected


@pytest.fixture
def sample_tool_data():
    """Sample tool data for testing."""
    return {
        'original_name': 'weather_api',
        'description': 'Get weather information',
        'input_schema': {
            'properties': {
                'city': {'description': 'City name'}
            }
        },
        'tags': ['weather', 'api'],
        'integration_type': 'REST'
    }


class TestEmbedTool:
    """Test the embed_tool method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_tool_success(self, mock_factory, sample_tool_data):
        """Test successful tool embedding."""
        # Set up the mock chain
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embedding = [0.1] * 1536
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.return_value = expected_embedding
        
        service = EmbeddingService()
        
        result = await service.embed_tool(sample_tool_data)
        
        assert result == expected_embedding
        # Verify the prepared text was passed to aembed_query
        expected_text = "weather_api | Get weather information | parameters: city: City name | tags: weather, api | type: REST"
        mock_embedding_model.aembed_query.assert_called_once_with(expected_text)

    @pytest.mark.asyncio
    async def test_embed_tool_missing_name(self):
        """Test embed_tool with missing original_name raises error."""
        service = EmbeddingService()
        
        invalid_tool = {'description': 'Tool without name'}
        
        with pytest.raises(ValueError, match="Tool data must include 'original_name'"):
            await service.embed_tool(invalid_tool)

    @pytest.mark.asyncio
    async def test_embed_tool_invalid_data_type(self):
        """Test embed_tool with non-dict data raises error."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Tool data must be a dictionary"):
            await service.embed_tool("not a dict")


class TestEmbedText:
    """Test the embed_text method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_text_success(self, mock_factory):
        """Test successful text embedding."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embedding = [0.5] * 1536
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.return_value = expected_embedding
        
        service = EmbeddingService()
        
        result = await service.embed_text("Some text to embed")
        
        assert result == expected_embedding
        mock_embedding_model.aembed_query.assert_called_once_with("Some text to embed")

    @pytest.mark.asyncio
    async def test_embed_text_empty_raises_error(self):
        """Test that empty text raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Text cannot be empty or whitespace only"):
            await service.embed_text("")

    @pytest.mark.asyncio
    async def test_embed_text_whitespace_only_raises_error(self):
        """Test that whitespace-only text raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Text cannot be empty or whitespace only"):
            await service.embed_text("   \n\t  ")

    @pytest.mark.asyncio
    async def test_embed_text_too_long_raises_error(self):
        """Test that text over 8192 characters raises ValueError."""
        service = EmbeddingService()
        long_text = "a" * 8193  # Over the limit
        
        with pytest.raises(ValueError, match="Text too long.*max 8192"):
            await service.embed_text(long_text)


class TestUtilityMethods:
    """Test utility methods."""

    def test_get_provider_info(self):
        """Test getting provider information."""
        service = EmbeddingService()
        
        info = service.get_provider_info()
        
        assert 'provider' in info
        assert 'model' in info
        assert 'initialized' in info
        assert info['initialized'] is False  # Not yet initialized


class TestEmbedToolFromDb:
    """Test the embed_tool_from_db method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_tool_from_db_success(self, mock_factory):
        """Test embedding generation for a Tool ORM-like object."""
        # Set up the mock chain
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embedding = [0.2] * 1536

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.return_value = expected_embedding

        class DummyTool:
            def __init__(self):
                self.original_name = 'db_tool'
                self.description = 'Tool from DB'
                self.tags = ['one', 'two']
                self.integration_type = 'MCP'
                self.input_schema = {
                    'properties': {
                        'param': {'description': 'Param description'}
                    }
                }
                self.gateway_id = 'gateway-123'

        tool = DummyTool()
        service = EmbeddingService()

        result = await service.embed_tool_from_db(tool)

        assert result == expected_embedding

        expected_text = (
            "db_tool | Tool from DB | parameters: param: Param description | "
            "tags: one, two | type: MCP"
        )
        mock_embedding_model.aembed_query.assert_called_once_with(expected_text)


class TestBatchEmbedTools:
    """Test the batch_embed_tools method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_batch_embed_tools_success(self, mock_factory, sample_tool_data):
        """Test batch embedding for multiple tools."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embeddings = [[0.1] * 1536, [0.2] * 1536]

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_documents.return_value = expected_embeddings

        service = EmbeddingService()

        tools = [
            sample_tool_data,
            {
                'original_name': 'db_tool',
                'description': 'Tool from DB',
                'input_schema': {
                    'properties': {
                        'param': {'description': 'Param description'}
                    }
                },
                'tags': ['one', 'two'],
                'integration_type': 'MCP',
            },
        ]

        result = await service.batch_embed_tools(tools)

        assert result == expected_embeddings

        expected_texts = [service.prepare_tool_text(t) for t in tools]
        mock_embedding_model.aembed_documents.assert_called_once_with(expected_texts)

    @pytest.mark.asyncio
    async def test_batch_embed_tools_empty_list_returns_empty(self):
        """Test that empty tool list returns empty embeddings without init."""
        service = EmbeddingService()

        result = await service.batch_embed_tools([])

        assert result == []
        assert service._initialized is False


class TestBatchEmbedTexts:
    """Test the batch_embed_texts method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_batch_embed_texts_success(self, mock_factory):
        """Test successful batch text embedding."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embeddings = [[0.3] * 1536, [0.4] * 1536]

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_documents.return_value = expected_embeddings

        service = EmbeddingService()
        texts = ["first text", "second text"]

        result = await service.batch_embed_texts(texts)

        assert result == expected_embeddings
        mock_embedding_model.aembed_documents.assert_called_once_with(texts)

    @pytest.mark.asyncio
    async def test_batch_embed_texts_empty_list_returns_empty(self):
        """Test that empty text list returns empty embeddings without init."""
        service = EmbeddingService()

        result = await service.batch_embed_texts([])

        assert result == []
        assert service._initialized is False

    @pytest.mark.asyncio
    async def test_batch_embed_texts_invalid_text_raises_error(self):
        """Test validation for empty and too-long texts in batch_embed_texts."""
        service = EmbeddingService()

        # Empty text
        with pytest.raises(ValueError, match="Text at index 0 cannot be empty"):
            await service.batch_embed_texts(["", "valid"])

        # Too long text
        long_text = "a" * 8193
        with pytest.raises(ValueError, match="Text at index 0 too long: 8193 characters"):
            await service.batch_embed_texts([long_text])


class TestErrorHandling:
    """Test error handling paths for embedding operations."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_text_provider_error_raises_runtime_error(self, mock_factory):
        """Test that provider errors are wrapped in RuntimeError in embed_text."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.side_effect = Exception("provider failure")

        service = EmbeddingService()

        with pytest.raises(RuntimeError, match="Text embedding failed: provider failure"):
            await service.embed_text("some text")

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_batch_embed_tools_provider_error_raises_runtime_error(self, mock_factory, sample_tool_data):
        """Test that provider errors are wrapped in RuntimeError in batch_embed_tools."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_documents.side_effect = Exception("batch failure")

        service = EmbeddingService()

        with pytest.raises(RuntimeError, match="Batch embedding failed: batch failure"):
            await service.batch_embed_tools([sample_tool_data])

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_batch_embed_texts_provider_error_raises_runtime_error(self, mock_factory):
        """Test that provider errors are wrapped in RuntimeError in batch_embed_texts."""
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()

        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_documents.side_effect = Exception("batch text failure")

        service = EmbeddingService()

        with pytest.raises(RuntimeError, match="Batch text embedding failed: batch text failure"):
            await service.batch_embed_texts(["one", "two"])
