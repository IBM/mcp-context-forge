"""Tests for EmbeddingService."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from mcpgateway.services.embedding_service import EmbeddingService


class TestEmbeddingServiceBasic:
    """Test basic EmbeddingService functionality."""

    def test_service_creation(self):
        """Test that service can be created without errors."""
        service = EmbeddingService()
        assert service._initialized is False
        assert service._provider is None
        assert service._embedding_model is None

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

    async def test_embed_tool_missing_name(self):
        """Test embed_tool with missing original_name raises error."""
        service = EmbeddingService()
        
        invalid_tool = {'description': 'Tool without name'}
        
        with pytest.raises(ValueError, match="Tool data must include 'original_name'"):
            await service.embed_tool(invalid_tool)

    async def test_embed_tool_invalid_data_type(self):
        """Test embed_tool with non-dict data raises error."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Tool data must be a dictionary"):
            await service.embed_tool("not a dict")


class TestEmbedText:
    """Test the embed_text method."""

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

    async def test_embed_text_empty_raises_error(self):
        """Test that empty text raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Text cannot be empty or whitespace only"):
            await service.embed_text("")

    async def test_embed_text_whitespace_only_raises_error(self):
        """Test that whitespace-only text raises ValueError."""
        service = EmbeddingService()
        
        with pytest.raises(ValueError, match="Text cannot be empty or whitespace only"):
            await service.embed_text("   \n\t  ")

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
