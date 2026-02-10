# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_vector_search_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for VectorSearchService.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import ToolEmbedding
from mcpgateway.services.vector_search_service import VectorSearchService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def vector_search_service(mock_db_session):
    """Create a VectorSearchService instance with mock db."""
    return VectorSearchService(db=mock_db_session)


@pytest.fixture
def sample_tool_embedding():
    """Create a sample ToolEmbedding object."""
    embedding = ToolEmbedding(
        id=1,
        tool_id="tool-123",
        embedding=[0.1, 0.2, 0.3] * 512,  # 1536 dimensions
        model_name="text-embedding-3-small"
    )
    return embedding


# ============================================================================
# TEST GET_TOOL_EMBEDDING
# ============================================================================


class TestGetToolEmbedding:
    """Tests for get_tool_embedding method."""

    def test_get_tool_embedding_found(
        self, 
        vector_search_service, 
        mock_db_session,
        sample_tool_embedding
    ):
        """Test retrieving an existing tool embedding."""
        # Arrange
        tool_id = "tool-123"
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = sample_tool_embedding
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is not None
        assert result.tool_id == tool_id
        assert result.id == 1
        assert len(result.embedding) == 1536
        assert result.model_name == "text-embedding-3-small"
        
        # Verify database was queried correctly
        mock_db_session.query.assert_called_once_with(ToolEmbedding)
        mock_query.filter.assert_called_once()
        mock_filter.first.assert_called_once()

    def test_get_tool_embedding_not_found(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test retrieving a non-existent tool embedding."""
        # Arrange
        tool_id = "non-existent-tool"
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is None
        mock_db_session.query.assert_called_once_with(ToolEmbedding)
        mock_query.filter.assert_called_once()
        mock_filter.first.assert_called_once()

    def test_get_tool_embedding_different_tool_ids(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test retrieving embeddings for different tool IDs."""
        # Arrange
        tool_ids = ["tool-1", "tool-2", "tool-3"]
        embeddings = [
            ToolEmbedding(id=i, tool_id=tid, embedding=[0.1] * 1536, model_name="test-model")
            for i, tid in enumerate(tool_ids, 1)
        ]
        
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        
        # Return different embeddings based on call
        mock_filter.first.side_effect = embeddings
        
        # Act & Assert
        for tool_id, expected_embedding in zip(tool_ids, embeddings):
            result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
            assert result is not None
            assert result.tool_id == tool_id

    def test_get_tool_embedding_with_empty_string_id(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test retrieving embedding with empty string tool_id."""
        # Arrange
        tool_id = ""
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is None


# ============================================================================
# TEST DELETE_TOOL_EMBEDDING
# ============================================================================


class TestDeleteToolEmbedding:
    """Tests for delete_tool_embedding method."""

    def test_delete_tool_embedding_success(
        self,
        vector_search_service,
        mock_db_session,
        sample_tool_embedding
    ):
        """Test successfully deleting an existing embedding."""
        # Arrange
        tool_id = "tool-123"
        
        # Mock get_tool_embedding to return the sample embedding
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ):
            # Act
            result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is True
        mock_db_session.delete.assert_called_once_with(sample_tool_embedding)
        mock_db_session.commit.assert_called_once()

    def test_delete_tool_embedding_not_found(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test deleting a non-existent embedding."""
        # Arrange
        tool_id = "non-existent-tool"
        
        # Mock get_tool_embedding to return None
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=None
        ):
            # Act
            result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is False
        mock_db_session.delete.assert_not_called()
        mock_db_session.commit.assert_not_called()

    def test_delete_tool_embedding_multiple_calls(
        self,
        vector_search_service,
        mock_db_session,
        sample_tool_embedding
    ):
        """Test deleting the same embedding multiple times."""
        # Arrange
        tool_id = "tool-123"
        
        # First call: embedding exists
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ):
            result1 = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Second call: embedding no longer exists
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=None
        ):
            result2 = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result1 is True
        assert result2 is False

    def test_delete_tool_embedding_logs_success(
        self,
        vector_search_service,
        mock_db_session,
        sample_tool_embedding,
        caplog
    ):
        """Test that successful deletion logs an info message."""
        # Arrange
        tool_id = "tool-123"
        
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ):
            # Act
            with caplog.at_level("INFO"):
                result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is True
        assert f"Deleted embedding for tool {tool_id}" in caplog.text

    def test_delete_tool_embedding_logs_not_found(
        self,
        vector_search_service,
        mock_db_session,
        caplog
    ):
        """Test that failed deletion logs a warning message."""
        # Arrange
        tool_id = "non-existent-tool"
        
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=None
        ):
            # Act
            with caplog.at_level("WARNING"):
                result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is False
        assert f"No embedding found for tool {tool_id}" in caplog.text

    def test_delete_tool_embedding_with_different_embeddings(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test deleting different tool embeddings."""
        # Arrange
        embeddings = [
            ToolEmbedding(id=1, tool_id="tool-1", embedding=[0.1] * 1536, model_name="model-1"),
            ToolEmbedding(id=2, tool_id="tool-2", embedding=[0.2] * 1536, model_name="model-2"),
            ToolEmbedding(id=3, tool_id="tool-3", embedding=[0.3] * 1536, model_name="model-3"),
        ]
        
        # Act & Assert
        for embedding in embeddings:
            with patch.object(
                vector_search_service, 
                'get_tool_embedding', 
                return_value=embedding
            ):
                result = vector_search_service.delete_tool_embedding(
                    mock_db_session, 
                    embedding.tool_id
                )
                
                assert result is True
                # Verify the correct embedding was deleted
                assert mock_db_session.delete.called
                call_args = mock_db_session.delete.call_args[0][0]
                assert call_args.tool_id == embedding.tool_id


class TestVectorSearchServiceIntegration:
    """Integration tests for common workflows."""

    def test_get_then_delete_workflow(
        self,
        vector_search_service,
        mock_db_session,
        sample_tool_embedding
    ):
        """Test common workflow: get embedding, verify it exists, then delete."""
        # Arrange
        tool_id = "tool-123"
        
        # Step 1: Get embedding (exists)
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ) as mock_get:
            embedding = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
            assert embedding is not None
        
        # Step 2: Delete embedding
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ):
            deleted = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
            assert deleted is True
        
        # Step 3: Try to get again (should not exist)
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=None
        ):
            embedding_after = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
            assert embedding_after is None

    def test_check_before_delete_pattern(
        self,
        vector_search_service,
        mock_db_session,
        sample_tool_embedding
    ):
        """Test pattern: check if embedding exists before attempting delete."""
        # Arrange
        tool_id = "tool-123"
        
        # Check if embedding exists
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=sample_tool_embedding
        ):
            embedding = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
            
            # Only delete if it exists
            if embedding:
                result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
                assert result is True

    def test_batch_delete_multiple_tools(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test deleting embeddings for multiple tools."""
        # Arrange
        tool_ids = ["tool-1", "tool-2", "tool-3"]
        embeddings = [
            ToolEmbedding(id=i, tool_id=tid, embedding=[0.1] * 1536, model_name="test")
            for i, tid in enumerate(tool_ids, 1)
        ]
        
        deleted_count = 0
        
        # Act
        for tool_id, embedding in zip(tool_ids, embeddings):
            with patch.object(
                vector_search_service, 
                'get_tool_embedding', 
                return_value=embedding
            ):
                result = vector_search_service.delete_tool_embedding(mock_db_session, tool_id)
                if result:
                    deleted_count += 1
        
        # Assert
        assert deleted_count == len(tool_ids)



class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_get_embedding_with_none_tool_id(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test getting embedding with None as tool_id."""
        # Arrange
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, None)
        
        # Assert
        assert result is None

    def test_delete_embedding_with_none_tool_id(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test deleting embedding with None as tool_id."""
        # Arrange
        with patch.object(
            vector_search_service, 
            'get_tool_embedding', 
            return_value=None
        ):
            # Act
            result = vector_search_service.delete_tool_embedding(mock_db_session, None)
        
        # Assert
        assert result is False

    def test_get_embedding_with_special_characters_in_id(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test getting embedding with special characters in tool_id."""
        # Arrange
        tool_id = "tool-with-special-chars-!@#$%"
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is None
        mock_db_session.query.assert_called_once()

    def test_get_embedding_with_very_long_tool_id(
        self,
        vector_search_service,
        mock_db_session
    ):
        """Test getting embedding with very long tool_id."""
        # Arrange
        tool_id = "tool-" + "a" * 1000
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act
        result = vector_search_service.get_tool_embedding(mock_db_session, tool_id)
        
        # Assert
        assert result is None


class TestVectorSearchServiceInitialization:
    """Tests for VectorSearchService initialization."""

    def test_init_with_db_session(self, mock_db_session):
        """Test initializing service with database session."""
        # Act
        service = VectorSearchService(db=mock_db_session)
        
        # Assert
        assert service.db is mock_db_session

    def test_init_without_db_session(self):
        """Test initializing service without database session."""
        # Act
        service = VectorSearchService()
        
        # Assert
        assert service.db is None

    def test_service_can_use_different_db_sessions(self, mock_db_session):
        """Test that service methods can use different db sessions."""
        # Arrange
        service = VectorSearchService(db=mock_db_session)
        different_db_session = MagicMock()
        
        mock_query = MagicMock()
        mock_filter = MagicMock()
        
        different_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None
        
        # Act - Use different session than initialized with
        result = service.get_tool_embedding(different_db_session, "tool-123")
        
        # Assert
        assert result is None
        different_db_session.query.assert_called_once()
        # Verify the original session was not used
        mock_db_session.query.assert_not_called()