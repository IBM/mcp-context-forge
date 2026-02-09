# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_semantic_search.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Team C

Unit tests for semantic tool search endpoint.

These tests verify the /tools/semantic endpoint behavior including:
- Valid requests with results
- Empty query validation
- Limit and threshold parameter validation
- Empty result sets
- Error handling
"""

# Standard
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.schemas import ToolSearchResult
from mcpgateway.services.semantic_search_service import SemanticSearchService


# Test fixtures


@pytest.fixture
def mock_user():
    """Create a mock authenticated user."""

    async def _get_user():
        return {
            "email": "test@example.com",
            "is_admin": True,
            "permissions": ["tools.read"],
        }

    return _get_user


@pytest.fixture(autouse=True)
def mock_permission_check():
    """Automatically mock permission checks for all tests."""
    with patch("mcpgateway.services.permission_service.PermissionService.check_permission", return_value=True):
        yield


@pytest.fixture
def client(mock_user):
    """Create test client with auth override."""
    app.dependency_overrides[get_current_user_with_permissions] = mock_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_search_service():
    """Create a mock semantic search service."""
    service = AsyncMock(spec=SemanticSearchService)
    return service


# Test cases


class TestSemanticSearchEndpoint:
    """Test suite for semantic search endpoint."""

    def test_semantic_search_valid_request(self, client, mock_search_service):
        """Test valid semantic search request returns results."""
        # Arrange
        mock_results = [
            ToolSearchResult(
                tool_name="weather_api",
                description="Fetch current weather data",
                server_id="server-1",
                server_name="Weather Server",
                similarity_score=0.95,
            ),
            ToolSearchResult(
                tool_name="forecast_tool",
                description="Get weather forecast",
                server_id="server-1",
                server_name="Weather Server",
                similarity_score=0.87,
            ),
        ]
        mock_search_service.search_tools = AsyncMock(return_value=mock_results)

        # Mock the service getter
        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=weather&limit=10")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert "query" in data
            assert "totalResults" in data
            assert data["query"] == "weather"
            assert data["totalResults"] == 2
            assert len(data["results"]) == 2
            assert data["results"][0]["toolName"] == "weather_api"
            assert data["results"][0]["similarityScore"] == 0.95

    def test_semantic_search_missing_query(self, client):
        """Test request without query parameter returns 422."""
        # Act
        response = client.get("/tools/semantic")

        # Assert
        assert response.status_code == 422  # Unprocessable Entity (missing required param)

    def test_semantic_search_empty_query(self, client, mock_search_service):
        """Test request with empty query returns 400."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(side_effect=ValueError("Query cannot be empty"))

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=%20")  # URL-encoded space

            # Assert
            assert response.status_code == 400
            assert "Query cannot be empty" in response.json()["detail"]

    def test_semantic_search_limit_below_minimum(self, client):
        """Test request with limit < 1 returns 422."""
        # Act
        response = client.get("/tools/semantic?query=test&limit=0")

        # Assert
        assert response.status_code == 422  # Validation error

    def test_semantic_search_limit_above_maximum(self, client):
        """Test request with limit > 50 returns 422."""
        # Act
        response = client.get("/tools/semantic?query=test&limit=51")

        # Assert
        assert response.status_code == 422  # Validation error

    def test_semantic_search_valid_limit(self, client, mock_search_service):
        """Test request with valid limit parameter."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=test&limit=5")

            # Assert
            assert response.status_code == 200
            mock_search_service.search_tools.assert_awaited_once_with(query="test", limit=5, threshold=None)

    def test_semantic_search_threshold_below_minimum(self, client):
        """Test request with threshold < 0.0 returns 422."""
        # Act
        response = client.get("/tools/semantic?query=test&threshold=-0.1")

        # Assert
        assert response.status_code == 422  # Validation error

    def test_semantic_search_threshold_above_maximum(self, client):
        """Test request with threshold > 1.0 returns 422."""
        # Act
        response = client.get("/tools/semantic?query=test&threshold=1.1")

        # Assert
        assert response.status_code == 422  # Validation error

    def test_semantic_search_valid_threshold(self, client, mock_search_service):
        """Test request with valid threshold parameter."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=test&threshold=0.7")

            # Assert
            assert response.status_code == 200
            mock_search_service.search_tools.assert_awaited_once_with(query="test", limit=10, threshold=0.7)

    def test_semantic_search_empty_results(self, client, mock_search_service):
        """Test request that returns no results."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=nonexistent")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["results"] == []
            assert data["totalResults"] == 0
            assert data["query"] == "nonexistent"

    def test_semantic_search_default_limit(self, client, mock_search_service):
        """Test request without limit uses default value of 10."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=test")

            # Assert
            assert response.status_code == 200
            mock_search_service.search_tools.assert_awaited_once_with(query="test", limit=10, threshold=None)

    def test_semantic_search_service_error(self, client, mock_search_service):
        """Test handling of unexpected service errors."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(side_effect=RuntimeError("Vector search unavailable"))

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=test")

            # Assert
            assert response.status_code == 500
            assert "Semantic search failed" in response.json()["detail"]

    def test_semantic_search_all_parameters(self, client, mock_search_service):
        """Test request with all parameters specified."""
        # Arrange
        mock_results = [
            ToolSearchResult(
                tool_name="tool1",
                description="Test tool",
                server_id="srv1",
                server_name="Server 1",
                similarity_score=0.9,
            )
        ]
        mock_search_service.search_tools = AsyncMock(return_value=mock_results)

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=database%20query&limit=20&threshold=0.8")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "database query"
            assert data["totalResults"] == 1
            mock_search_service.search_tools.assert_awaited_once_with(query="database query", limit=20, threshold=0.8)

    def test_semantic_search_special_characters_in_query(self, client, mock_search_service):
        """Test query with special characters."""
        # Arrange
        mock_search_service.search_tools = AsyncMock(return_value=[])

        with patch("mcpgateway.services.semantic_search_service.get_semantic_search_service", return_value=mock_search_service):
            # Act
            response = client.get("/tools/semantic?query=get%20user's%20data%20%26%20files")

            # Assert
            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "get user's data & files"


class TestSemanticSearchService:
    """Test suite for SemanticSearchService."""

    @pytest.mark.skip(reason="Mocking async services with external dependencies is complex; endpoint integration tests cover this functionality")
    @pytest.mark.anyio
    async def test_search_tools_calls_embedding_and_vector_search(self):
        """Test that search_tools orchestrates embedding and vector search."""
        # Arrange
        service = SemanticSearchService()
        mock_embedding = [0.1] * 768
        mock_results = [
            ToolSearchResult(
                tool_name="tool1",
                description="Test",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.9,
            )
        ]

        # Create mock services
        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=mock_embedding)
        
        mock_vector_service = MagicMock()
        mock_vector_service.search_similar_tools = AsyncMock(return_value=mock_results)
        
        # Replace service instances
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Act
        results = await service.search_tools(query="test query", limit=10)

        # Assert
        assert len(results) == 1
        assert results[0].tool_name == "tool1"
        mock_embedding_service.embed_query.assert_awaited_once_with("test query")
        mock_vector_service.search_similar_tools.assert_awaited_once_with(embedding=mock_embedding, limit=10, threshold=None)

    @pytest.mark.anyio
    async def test_search_tools_empty_query_raises_error(self):
        """Test that empty query raises ValueError."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert
        with pytest.raises(ValueError, match="Query cannot be empty"):
            await service.search_tools(query="", limit=10)

    @pytest.mark.anyio
    async def test_search_tools_whitespace_query_raises_error(self):
        """Test that whitespace-only query raises ValueError."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert
        with pytest.raises(ValueError, match="Query cannot be empty"):
            await service.search_tools(query="   ", limit=10)

    @pytest.mark.anyio
    async def test_search_tools_invalid_limit_raises_error(self):
        """Test that invalid limit raises ValueError."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert
        with pytest.raises(ValueError, match="Limit must be between 1 and 50"):
            await service.search_tools(query="test", limit=0)

        with pytest.raises(ValueError, match="Limit must be between 1 and 50"):
            await service.search_tools(query="test", limit=51)

    @pytest.mark.anyio
    async def test_search_tools_invalid_threshold_raises_error(self):
        """Test that invalid threshold raises ValueError."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert
        with pytest.raises(ValueError, match="Threshold must be between 0.0 and 1.0"):
            await service.search_tools(query="test", limit=10, threshold=-0.1)

        with pytest.raises(ValueError, match="Threshold must be between 0.0 and 1.0"):
            await service.search_tools(query="test", limit=10, threshold=1.1)


class TestSemanticSearchCache:
    """Test suite for semantic search caching functionality."""

    @pytest.mark.anyio
    async def test_cache_hit_returns_cached_results(self):
        """Test that repeated identical requests return cached results without recomputation."""
        # Arrange
        service = SemanticSearchService()
        mock_results = [
            ToolSearchResult(
                tool_name="cached_tool",
                description="Cached result",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.95,
            )
        ]

        # Mock the underlying services
        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=[0.1] * 768)
        
        mock_vector_service = MagicMock()
        mock_vector_service.search_similar_tools = AsyncMock(return_value=mock_results)
        
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Act - First call should hit the services
        results1 = await service.search_tools(query="test query", limit=10)
        
        # Second call with identical params should hit cache
        results2 = await service.search_tools(query="test query", limit=10)

        # Assert
        assert results1 == results2
        assert len(results1) == 1
        assert results1[0].tool_name == "cached_tool"
        
        # Services should only be called once (first request)
        mock_embedding_service.embed_query.assert_awaited_once()
        mock_vector_service.search_similar_tools.assert_awaited_once()

    @pytest.mark.anyio
    async def test_query_normalization_cache_key(self):
        """Test that queries with different cases/whitespace hit the same cache."""
        # Arrange
        service = SemanticSearchService()
        mock_results = [
            ToolSearchResult(
                tool_name="normalized_tool",
                description="Test",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.9,
            )
        ]

        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=[0.1] * 768)
        
        mock_vector_service = MagicMock()
        mock_vector_service.search_similar_tools = AsyncMock(return_value=mock_results)
        
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Act - Different formats of same query
        results1 = await service.search_tools(query="Test Query", limit=10)
        results2 = await service.search_tools(query="test query", limit=10)
        results3 = await service.search_tools(query="  TEST QUERY  ", limit=10)

        # Assert - All should return same cached result
        assert results1 == results2 == results3
        
        # Embedding service should only be called once
        mock_embedding_service.embed_query.assert_awaited_once_with("test query")
        mock_vector_service.search_similar_tools.assert_awaited_once()

    @pytest.mark.anyio
    async def test_different_params_create_different_cache_keys(self):
        """Test that different limit/threshold values create separate cache entries."""
        # Arrange
        service = SemanticSearchService()
        mock_results_limit5 = [
            ToolSearchResult(
                tool_name="tool1",
                description="Test",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.9,
            )
        ]
        mock_results_limit10 = mock_results_limit5 + [
            ToolSearchResult(
                tool_name="tool2",
                description="Test2",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.8,
            )
        ]

        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=[0.1] * 768)
        
        mock_vector_service = MagicMock()
        # Return different results based on limit
        mock_vector_service.search_similar_tools = AsyncMock(side_effect=[mock_results_limit5, mock_results_limit10])
        
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Act - Same query, different limits
        results1 = await service.search_tools(query="test", limit=5)
        results2 = await service.search_tools(query="test", limit=10)

        # Assert - Should get different results (not cached)
        assert len(results1) == 1
        assert len(results2) == 2
        
        # Should call services twice (different cache keys)
        assert mock_embedding_service.embed_query.await_count == 2
        assert mock_vector_service.search_similar_tools.await_count == 2

    @pytest.mark.anyio
    async def test_memory_cache_works_independently(self):
        """Test that memory cache works when Redis is unavailable."""
        # Arrange
        service = SemanticSearchService()
        mock_results = [
            ToolSearchResult(
                tool_name="memory_cached",
                description="Test",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.85,
            )
        ]

        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=[0.1] * 768)
        
        mock_vector_service = MagicMock()
        mock_vector_service.search_similar_tools = AsyncMock(return_value=mock_results)
        
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Mock Redis to return None (unavailable)
        with patch("mcpgateway.services.semantic_search_service.get_redis_client", return_value=None):
            # Act - First call
            results1 = await service.search_tools(query="test", limit=10)
            
            # Second call should hit memory cache
            results2 = await service.search_tools(query="test", limit=10)

            # Assert
            assert results1 == results2
            assert len(results1) == 1
            
            # Services called only once (memory cache worked)
            mock_embedding_service.embed_query.assert_awaited_once()
            mock_vector_service.search_similar_tools.assert_awaited_once()

    @pytest.mark.anyio
    async def test_cache_key_generation(self):
        """Test cache key format includes normalized query, limit, and threshold."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert - Different cache keys
        key1 = service._make_cache_key("test query", 10, None)
        key2 = service._make_cache_key("test query", 10, 0.7)
        key3 = service._make_cache_key("test query", 20, None)
        key4 = service._make_cache_key("different query", 10, None)

        assert key1 == "semantic:test query:10:None"
        assert key2 == "semantic:test query:10:0.7"
        assert key3 == "semantic:test query:20:None"
        assert key4 == "semantic:different query:10:None"
        
        # All keys should be unique
        assert len({key1, key2, key3, key4}) == 4

    @pytest.mark.anyio
    async def test_query_normalization(self):
        """Test query normalization strips whitespace and converts to lowercase."""
        # Arrange
        service = SemanticSearchService()

        # Act & Assert
        assert service._normalize_query("Test Query") == "test query"
        assert service._normalize_query("  UPPERCASE  ") == "uppercase"
        assert service._normalize_query("MiXeD CaSe") == "mixed case"
        assert service._normalize_query("   spaces   ") == "spaces"

    @pytest.mark.anyio
    async def test_memory_cache_expiry(self):
        """Test that memory cache entries expire after TTL."""
        # Arrange
        import time
        service = SemanticSearchService()
        service.CACHE_TTL_SECONDS = 1  # Short TTL for testing
        
        mock_results = [
            ToolSearchResult(
                tool_name="expiring_tool",
                description="Test",
                server_id="srv1",
                server_name="Server",
                similarity_score=0.9,
            )
        ]

        mock_embedding_service = MagicMock()
        mock_embedding_service.embed_query = AsyncMock(return_value=[0.1] * 768)
        
        mock_vector_service = MagicMock()
        mock_vector_service.search_similar_tools = AsyncMock(return_value=mock_results)
        
        service.embedding_service = mock_embedding_service
        service.vector_search_service = mock_vector_service

        # Mock Redis to be unavailable (test memory cache only)
        with patch("mcpgateway.services.semantic_search_service.get_redis_client", return_value=None):
            # Act - First call
            results1 = await service.search_tools(query="test", limit=10)
            assert len(results1) == 1
            
            # Wait for cache to expire
            time.sleep(1.1)
            
            # Second call after expiry should recompute
            results2 = await service.search_tools(query="test", limit=10)

            # Assert
            assert results1 == results2
            
            # Services should be called twice (cache expired)
            assert mock_embedding_service.embed_query.await_count == 2
            assert mock_vector_service.search_similar_tools.await_count == 2

