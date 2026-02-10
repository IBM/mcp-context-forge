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
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.embedding_service import EmbeddingService
from mcpgateway.db import ToolEmbedding

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

# ============================================================================
# NEW TESTS FOR STORAGE METHODS
# ============================================================================


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    mock_session = MagicMock(spec=Session)
    return mock_session


@pytest.fixture
def mock_tool_embedding():
    """Create a mock ToolEmbedding object."""
    embedding = MagicMock(spec=ToolEmbedding)
    embedding.id = "embedding-123"
    embedding.tool_id = "tool-456"
    embedding.embedding = [0.1] * 1536
    embedding.model_name = "text-embedding-3-small"
    return embedding


class TestStoreToolEmbedding:
    """Test the store_tool_embedding method."""

    def test_store_new_embedding_success(self, mock_db_session):
        """Test storing a new embedding."""
        service = EmbeddingService()
        
        # Mock query to return None (no existing embedding)
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        embedding = [0.5] * 1536
        tool_id = "tool-789"
        model_name = "text-embedding-3-small"
        
        result = service.store_tool_embedding(mock_db_session, tool_id, embedding, model_name)
        
        # Verify add was called
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()
        mock_db_session.refresh.assert_called_once()

    def test_update_existing_embedding_success(self, mock_db_session, mock_tool_embedding):
        """Test updating an existing embedding."""
        service = EmbeddingService()
        
        # Mock query to return existing embedding
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_tool_embedding
        
        new_embedding = [0.9] * 1536
        tool_id = "tool-456"
        model_name = "text-embedding-3-large"
        
        result = service.store_tool_embedding(mock_db_session, tool_id, new_embedding, model_name)
        
        # Verify embedding was updated
        assert mock_tool_embedding.embedding == new_embedding
        assert mock_tool_embedding.model_name == model_name
        mock_db_session.commit.assert_called_once()
        mock_db_session.refresh.assert_called_once_with(mock_tool_embedding)
        assert result == mock_tool_embedding

    def test_store_embedding_invalid_empty_list(self, mock_db_session):
        """Test that empty embedding list raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Embedding must be a non-empty list"):
            service.store_tool_embedding(mock_db_session, "tool-123", [], "model")

    def test_store_embedding_invalid_not_list(self, mock_db_session):
        """Test that non-list embedding raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Embedding must be a non-empty list"):
            service.store_tool_embedding(mock_db_session, "tool-123", "not a list", "model")

    def test_store_embedding_invalid_non_numeric_values(self, mock_db_session):
        """Test that embedding with non-numeric values raises ValueError."""
        service = EmbeddingService()
        
        invalid_embedding = [0.1, "string", 0.3]
        
        with pytest.raises(ValueError, match="Embedding must contain only numbers"):
            service.store_tool_embedding(mock_db_session, "tool-123", invalid_embedding, "model")

    def test_store_embedding_database_error_rolls_back(self, mock_db_session):
        """Test that database errors trigger rollback."""
        service = EmbeddingService()
        
        # Mock query to return None
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        # Mock commit to raise exception
        mock_db_session.commit.side_effect = Exception("DB connection lost")
        
        embedding = [0.5] * 1536
        
        with pytest.raises(RuntimeError, match="Database operation failed: DB connection lost"):
            service.store_tool_embedding(mock_db_session, "tool-123", embedding, "model")
        
        mock_db_session.rollback.assert_called_once()


class TestBatchStoreToolEmbeddings:
    """Test the batch_store_tool_embeddings method."""

    def test_batch_store_new_embeddings_success(self, mock_db_session):
        """Test batch storing new embeddings."""
        service = EmbeddingService()
        
        # Mock query to return empty (no existing embeddings)
        mock_db_session.query.return_value.filter.return_value.all.return_value = []
        
        tool_embeddings = [
            ("tool-1", [0.1] * 1536),
            ("tool-2", [0.2] * 1536),
            ("tool-3", [0.3] * 1536),
        ]
        model_name = "text-embedding-3-small"
        
        result = service.batch_store_tool_embeddings(mock_db_session, tool_embeddings, model_name)
        
        # Verify add was called 3 times
        assert mock_db_session.add.call_count == 3
        mock_db_session.commit.assert_called_once()
        assert len(result) == 3

    def test_batch_store_update_existing_embeddings(self, mock_db_session):
        """Test batch updating existing embeddings."""
        service = EmbeddingService()
        
        # Create mock existing embeddings
        existing1 = MagicMock(spec=ToolEmbedding)
        existing1.tool_id = "tool-1"
        existing1.embedding = [0.1] * 1536
        
        existing2 = MagicMock(spec=ToolEmbedding)
        existing2.tool_id = "tool-2"
        existing2.embedding = [0.2] * 1536
        
        # Mock query to return existing embeddings
        mock_db_session.query.return_value.filter.return_value.all.return_value = [existing1, existing2]
        
        tool_embeddings = [
            ("tool-1", [0.9] * 1536),
            ("tool-2", [0.8] * 1536),
        ]
        model_name = "text-embedding-3-large"
        
        result = service.batch_store_tool_embeddings(mock_db_session, tool_embeddings, model_name)
        
        # Verify embeddings were updated
        assert existing1.embedding == [0.9] * 1536
        assert existing1.model_name == model_name
        assert existing2.embedding == [0.8] * 1536
        assert existing2.model_name == model_name
        
        # No add calls (only updates)
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_called_once()
        assert len(result) == 2

    def test_batch_store_mixed_new_and_existing(self, mock_db_session):
        """Test batch storing with mix of new and existing embeddings."""
        service = EmbeddingService()
        
        # Create one existing embedding
        existing = MagicMock(spec=ToolEmbedding)
        existing.tool_id = "tool-1"
        existing.embedding = [0.1] * 1536
        
        mock_db_session.query.return_value.filter.return_value.all.return_value = [existing]
        
        tool_embeddings = [
            ("tool-1", [0.9] * 1536),  # Update existing
            ("tool-2", [0.8] * 1536),  # Create new
            ("tool-3", [0.7] * 1536),  # Create new
        ]
        model_name = "text-embedding-3-small"
        
        result = service.batch_store_tool_embeddings(mock_db_session, tool_embeddings, model_name)
        
        # Verify one update and two adds
        assert mock_db_session.add.call_count == 2
        assert existing.embedding == [0.9] * 1536
        mock_db_session.commit.assert_called_once()
        assert len(result) == 3

    def test_batch_store_empty_list_returns_empty(self, mock_db_session):
        """Test that empty list returns empty without DB calls."""
        service = EmbeddingService()
        
        result = service.batch_store_tool_embeddings(mock_db_session, [], "model")
        
        assert result == []
        mock_db_session.query.assert_not_called()
        mock_db_session.commit.assert_not_called()

    def test_batch_store_database_error_rolls_back(self, mock_db_session):
        """Test that database errors trigger rollback in batch store."""
        service = EmbeddingService()
        
        mock_db_session.query.return_value.filter.return_value.all.return_value = []
        mock_db_session.commit.side_effect = Exception("Batch commit failed")
        
        tool_embeddings = [("tool-1", [0.1] * 1536)]
        
        with pytest.raises(RuntimeError, match="Batch storage failed: Batch commit failed"):
            service.batch_store_tool_embeddings(mock_db_session, tool_embeddings, "model")
        
        mock_db_session.rollback.assert_called_once()


class TestEmbedAndStoreTool:
    """Test the embed_and_store_tool method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_and_store_tool_success(self, mock_factory, mock_db_session):
        """Test embedding and storing a single tool."""
        # Setup mocks
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embedding = [0.5] * 1536
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_query.return_value = expected_embedding
        
        # Mock query to return None (new embedding)
        mock_db_session.query.return_value.filter.return_value.first.return_value = None
        
        # Create dummy tool
        class DummyTool:
            def __init__(self):
                self.id = "tool-123"
                self.original_name = "test_tool"
                self.description = "Test tool"
                self.tags = []
                self.integration_type = "MCP"
                self.input_schema = {}
                self.gateway_id = "gateway-1"
        
        tool = DummyTool()
        service = EmbeddingService()
        service.embedding_config.config.model = "text-embedding-3-small"
        
        result = await service.embed_and_store_tool(mock_db_session, tool)
        
        # Verify embedding was generated and stored
        mock_embedding_model.aembed_query.assert_called_once()
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()


class TestEmbedAndStoreToolsBatch:
    """Test the embed_and_store_tools_batch method."""

    @pytest.mark.asyncio
    @patch('mcpgateway.services.embedding_service.EmbeddingProviderFactory')
    async def test_embed_and_store_batch_success(self, mock_factory, mock_db_session):
        """Test embedding and storing multiple tools in batch."""
        # Setup mocks
        mock_provider = MagicMock()
        mock_embedding_model = AsyncMock()
        expected_embeddings = [[0.1] * 1536, [0.2] * 1536]
        
        mock_factory.create.return_value = mock_provider
        mock_provider.get_embedding_model.return_value = mock_embedding_model
        mock_embedding_model.aembed_documents.return_value = expected_embeddings
        
        # Mock query to return empty (no existing embeddings)
        mock_db_session.query.return_value.filter.return_value.all.return_value = []
        
        # Create dummy tools
        class DummyTool:
            def __init__(self, tool_id, name):
                self.id = tool_id
                self.original_name = name
                self.description = f"Description for {name}"
                self.tags = []
                self.integration_type = "MCP"
                self.input_schema = {}
                self.gateway_id = "gateway-1"
        
        tools = [
            DummyTool("tool-1", "tool_one"),
            DummyTool("tool-2", "tool_two"),
        ]
        
        service = EmbeddingService()
        service.embedding_config.config.model = "text-embedding-3-small"
        
        result = await service.embed_and_store_tools_batch(mock_db_session, tools)
        
        # Verify batch embedding was called
        mock_embedding_model.aembed_documents.assert_called_once()
        
        # Verify batch store was called
        assert mock_db_session.add.call_count == 2
        mock_db_session.commit.assert_called_once()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_embed_and_store_batch_empty_list(self, mock_db_session):
        """Test that empty tool list returns empty without processing."""
        service = EmbeddingService()
        
        result = await service.embed_and_store_tools_batch(mock_db_session, [])
        
        assert result == []
        mock_db_session.query.assert_not_called()