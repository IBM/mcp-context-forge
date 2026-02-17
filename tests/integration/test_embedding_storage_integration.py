# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_embedding_storage_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for EmbeddingService storage operations with real database.
"""

# Standard
import time
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.db import Base, Tool, ToolEmbedding
from mcpgateway.services.embedding_service import EmbeddingService


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def test_db_engine():
    """Create a test database engine using SQLite in-memory.
    
    Each test gets a fresh database.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine) -> Generator[Session, None, None]:
    """Create a test database session.
    
    Automatically commits/rollsback after each test.
    """
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_tools(test_db_session):
    """Create sample tools in the test database.
    
    Returns:
        List of 3 Tool objects with different characteristics
    """
    tools = [
        Tool(
            id="tool-weather-1",
            original_name="weather_api",
            name="weather_api",
            custom_name="Weather API",
            custom_name_slug="weather-api",
            description="Get current weather information for any city",
            input_schema={
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "units": {"type": "string", "description": "Temperature units (celsius/fahrenheit)"}
                }
            },
            tags=["weather", "api", "data"],
            integration_type="REST",
            gateway_id="gateway-1",
            enabled=True
        ),
        Tool(
            id="tool-email-2",
            original_name="email_sender",
            name="email_sender",
            custom_name="Email Sender",
            custom_name_slug="email-sender",
            description="Send email notifications to users",
            input_schema={
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Email body content"}
                }
            },
            tags=["email", "communication", "notifications"],
            integration_type="SMTP",
            gateway_id="gateway-1",
            enabled=True
        ),
        Tool(
            id="tool-db-3",
            original_name="database_query",
            name="database_query",
            custom_name="Database Query",
            custom_name_slug="database-query",
            description="Execute SQL queries on the database",
            input_schema={
                "properties": {
                    "query": {"type": "string", "description": "SQL query to execute"},
                    "database": {"type": "string", "description": "Target database name"}
                }
            },
            tags=["database", "query", "sql"],
            integration_type="SQL",
            gateway_id="gateway-2",
            enabled=True
        ),
    ]
    
    for tool in tools:
        test_db_session.add(tool)
    
    test_db_session.commit()
    
    for tool in tools:
        test_db_session.refresh(tool)
    
    return tools


@pytest.fixture
def embedding_service():
    """Create a mock embedding service for testing storage operations.
    
    This fixture mocks the embedding provider so tests can run without
    requiring langchain-openai or OpenAI API access.
    
    Returns:
        EmbeddingService: Mock service that doesn't require API initialization
    """
    service = EmbeddingService()
    
    # Mock the initialization so it doesn't require langchain-openai
    service._initialized = True
    service._provider = MagicMock()
    service._embedding_model = AsyncMock()
    
    # Mock the embedding methods to return fake but realistic embeddings
    async def mock_embed_query(text):
        # Return a fake 1536-dimensional embedding based on text hash
        # This ensures different texts get different embeddings
        import hashlib
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        base_value = (text_hash % 1000) / 1000.0
        return [base_value + i * 0.0001 for i in range(1536)]
    
    async def mock_embed_documents(texts):
        # Return fake embeddings for each text
        embeddings = []
        for text in texts:
            import hashlib
            text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
            base_value = (text_hash % 1000) / 1000.0
            embeddings.append([base_value + j * 0.0001 for j in range(1536)])
        return embeddings
    
    service._embedding_model.aembed_query = mock_embed_query
    service._embedding_model.aembed_documents = mock_embed_documents
    
    # Mock the config model name
    service.embedding_config.config.model = "text-embedding-3-small"
    
    return service


# ============================================================================
# BASIC STORAGE OPERATIONS
# ============================================================================


class TestBasicStorageOperations:
    """Test basic database storage operations."""

    def test_store_new_embedding_creates_record(self, test_db_session, embedding_service):
        """Test that storing a new embedding creates a database record."""
        # Arrange
        embedding = [0.1, 0.2, 0.3] * 512  # 1536 dimensions
        tool_id = "test-tool-new"
        model_name = "text-embedding-3-small"
        
        # Act
        result = embedding_service.store_tool_embedding(
            test_db_session, 
            tool_id, 
            embedding, 
            model_name
        )
        
        # Assert - Check return value
        assert result is not None
        assert result.id is not None
        assert result.tool_id == tool_id
        assert result.embedding == embedding
        assert result.model_name == model_name
        assert result.created_at is not None
        assert result.updated_at is not None
        
        # Assert - Verify it's in the database
        db_embedding = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first()
        
        assert db_embedding is not None
        assert db_embedding.tool_id == tool_id
        assert len(db_embedding.embedding) == 1536

    def test_update_existing_embedding_modifies_in_place(self, test_db_session, embedding_service):
        """Test that updating an existing embedding modifies the record in-place."""
        # Arrange
        tool_id = "test-tool-update"
        initial_embedding = [0.1] * 1536
        initial_model = "text-embedding-3-small"
        
        # Act - Create initial embedding
        first_result = embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            initial_embedding,
            initial_model
        )
        first_id = first_result.id
        
        # Act - Update with new embedding
        new_embedding = [0.9] * 1536
        new_model = "text-embedding-3-large"
        
        second_result = embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            new_embedding,
            new_model
        )
        
        # Assert - Same record ID (updated, not created new)
        assert second_result.id == first_id
        assert second_result.embedding == new_embedding
        assert second_result.model_name == new_model
        
        # Assert - Only one record exists
        count = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).count()
        
        assert count == 1

    def test_store_multiple_different_tools(self, test_db_session, embedding_service):
        """Test storing embeddings for multiple different tools."""
        # Arrange
        tools_data = [
            ("multi-tool-1", [0.1] * 1536, "model-1"),
            ("multi-tool-2", [0.2] * 1536, "model-2"),
            ("multi-tool-3", [0.3] * 1536, "model-3"),
        ]
        
        # Act
        for tool_id, embedding, model in tools_data:
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                model
            )
        
        # Assert
        total_count = test_db_session.query(ToolEmbedding).count()
        assert total_count == 3
        
        # Verify each one individually
        for tool_id, expected_embedding, expected_model in tools_data:
            db_embedding = test_db_session.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool_id
            ).first()
            
            assert db_embedding is not None
            assert db_embedding.embedding == expected_embedding
            assert db_embedding.model_name == expected_model


# ============================================================================
# BATCH STORAGE OPERATIONS
# ============================================================================


class TestBatchStorageOperations:
    """Test batch storage operations."""

    def test_batch_store_creates_all_records(self, test_db_session, embedding_service):
        """Test that batch storing creates all records in one transaction."""
        # Arrange
        tool_embeddings = [
            ("batch-tool-1", [0.1] * 1536),
            ("batch-tool-2", [0.2] * 1536),
            ("batch-tool-3", [0.3] * 1536),
        ]
        model_name = "text-embedding-3-small"
        
        # Act
        results = embedding_service.batch_store_tool_embeddings(
            test_db_session,
            tool_embeddings,
            model_name
        )
        
        # Assert - All results returned
        assert len(results) == 3
        
        for i, result in enumerate(results):
            assert result.tool_id == tool_embeddings[i][0]
            assert result.embedding == tool_embeddings[i][1]
            assert result.model_name == model_name
        
        # Assert - All in database
        for tool_id, embedding in tool_embeddings:
            db_embedding = test_db_session.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool_id
            ).first()
            
            assert db_embedding is not None
            assert db_embedding.tool_id == tool_id

    def test_batch_store_handles_mixed_create_update(self, test_db_session, embedding_service):
        """Test batch storing handles both new and existing records correctly."""
        # Arrange - Create one existing embedding
        existing_tool_id = "batch-existing"
        existing_embedding = [0.5] * 1536
        
        embedding_service.store_tool_embedding(
            test_db_session,
            existing_tool_id,
            existing_embedding,
            "old-model"
        )
        
        # Act - Batch with mix of new and existing
        tool_embeddings = [
            (existing_tool_id, [0.9] * 1536),  # Update
            ("batch-new-1", [0.1] * 1536),      # Create
            ("batch-new-2", [0.2] * 1536),      # Create
        ]
        model_name = "text-embedding-3-small"
        
        results = embedding_service.batch_store_tool_embeddings(
            test_db_session,
            tool_embeddings,
            model_name
        )
        
        # Assert - All returned
        assert len(results) == 3
        
        # Assert - Existing was updated
        updated = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == existing_tool_id
        ).first()
        
        assert updated.embedding == [0.9] * 1536
        assert updated.model_name == model_name
        
        # Assert - Total count correct
        total_count = test_db_session.query(ToolEmbedding).count()
        assert total_count == 3

    def test_batch_store_all_updates(self, test_db_session, embedding_service):
        """Test batch storing where all records are updates."""
        # Arrange - Create initial embeddings
        initial_data = [
            ("update-tool-1", [0.1] * 1536),
            ("update-tool-2", [0.2] * 1536),
            ("update-tool-3", [0.3] * 1536),
        ]
        
        for tool_id, embedding in initial_data:
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                "old-model"
            )
        
        # Act - Batch update all
        updated_data = [
            ("update-tool-1", [0.9] * 1536),
            ("update-tool-2", [0.8] * 1536),
            ("update-tool-3", [0.7] * 1536),
        ]
        
        results = embedding_service.batch_store_tool_embeddings(
            test_db_session,
            updated_data,
            "new-model"
        )
        
        # Assert
        assert len(results) == 3
        
        # Verify all updated
        for tool_id, expected_embedding in updated_data:
            db_embedding = test_db_session.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool_id
            ).first()
            
            assert db_embedding.embedding == expected_embedding
            assert db_embedding.model_name == "new-model"
        
        # Still only 3 records
        assert test_db_session.query(ToolEmbedding).count() == 3


# ============================================================================
# END-TO-END WORKFLOWS
# ============================================================================


class TestEndToEndWorkflows:
    """Test complete workflows from tool to stored embedding."""

    @pytest.mark.asyncio
    async def test_embed_and_store_single_tool_complete_workflow(
        self, 
        test_db_session, 
        sample_tools, 
        embedding_service
    ):
        """Test complete workflow: fetch tool -> generate embedding -> store."""
        # Arrange
        tool = sample_tools[0]  # weather_api
        
        # Act
        result = await embedding_service.embed_and_store_tool(test_db_session, tool)
        
        # Assert - Result structure
        assert result is not None
        assert result.tool_id == tool.id
        assert len(result.embedding) == 1536
        assert result.model_name == "text-embedding-3-small"
        
        # Assert - In database
        db_embedding = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool.id
        ).first()
        
        assert db_embedding is not None
        assert db_embedding.tool_id == tool.id
        assert isinstance(db_embedding.embedding, list)
        assert len(db_embedding.embedding) == 1536

    @pytest.mark.asyncio
    async def test_embed_and_store_batch_complete_workflow(
        self,
        test_db_session,
        sample_tools,
        embedding_service
    ):
        """Test batch workflow: fetch tools -> generate embeddings -> store all."""
        # Act
        results = await embedding_service.embed_and_store_tools_batch(
            test_db_session,
            sample_tools
        )
        
        # Assert - All results returned
        assert len(results) == len(sample_tools)
        
        for tool, result in zip(sample_tools, results):
            assert result.tool_id == tool.id
            assert len(result.embedding) == 1536
            assert result.model_name == "text-embedding-3-small"
        
        # Assert - All in database
        db_embeddings = test_db_session.query(ToolEmbedding).all()
        assert len(db_embeddings) == len(sample_tools)
        
        # Assert - Each tool has exactly one embedding
        for tool in sample_tools:
            db_embedding = test_db_session.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool.id
            ).first()
            
            assert db_embedding is not None
            assert db_embedding.tool_id == tool.id

    @pytest.mark.asyncio
    async def test_re_embedding_updates_not_duplicates(
        self,
        test_db_session,
        sample_tools,
        embedding_service
    ):
        """Test that re-embedding a tool updates rather than creates duplicate."""
        # Arrange
        tool = sample_tools[0]
        
        # Act - First embedding
        first_result = await embedding_service.embed_and_store_tool(
            test_db_session,
            tool
        )
        first_id = first_result.id
        
        # Act - Second embedding (should update)
        second_result = await embedding_service.embed_and_store_tool(
            test_db_session,
            tool
        )
        
        # Assert - Same record ID
        assert second_result.id == first_id
        
        # Assert - Only one record exists
        count = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool.id
        ).count()
        
        assert count == 1

    @pytest.mark.asyncio
    async def test_embed_tools_with_different_descriptions(
        self,
        test_db_session,
        sample_tools,
        embedding_service
    ):
        """Test that tools with different descriptions get different embeddings."""
        # Act
        results = await embedding_service.embed_and_store_tools_batch(
            test_db_session,
            sample_tools
        )
        
        # Assert - All embeddings are different
        embeddings = [r.embedding for r in results]
        
        # No two embeddings should be identical
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                assert embeddings[i] != embeddings[j], \
                    f"Embeddings {i} and {j} should be different"


# ============================================================================
# DATABASE QUERIES & RELATIONSHIPS
# ============================================================================


class TestDatabaseQueriesAndRelationships:
    """Test querying embeddings and tool relationships."""

    def test_query_embedding_by_tool_id(self, test_db_session, embedding_service):
        """Test retrieving a specific embedding by tool_id."""
        # Arrange
        embeddings_data = [
            ("query-tool-1", [0.1] * 1536),
            ("query-tool-2", [0.2] * 1536),
            ("query-tool-3", [0.3] * 1536),
        ]
        
        for tool_id, embedding in embeddings_data:
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                "test-model"
            )
        
        # Act
        target_tool_id = "query-tool-2"
        result = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == target_tool_id
        ).first()
        
        # Assert
        assert result is not None
        assert result.tool_id == target_tool_id
        assert result.embedding == [0.2] * 1536

    def test_query_all_embeddings(self, test_db_session, embedding_service):
        """Test retrieving all embeddings."""
        # Arrange
        embeddings_data = [
            ("all-tool-1", [0.1] * 1536),
            ("all-tool-2", [0.2] * 1536),
        ]
        
        for tool_id, embedding in embeddings_data:
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                "test-model"
            )
        
        # Act
        all_embeddings = test_db_session.query(ToolEmbedding).all()
        
        # Assert
        assert len(all_embeddings) == 2
        tool_ids = [e.tool_id for e in all_embeddings]
        assert "all-tool-1" in tool_ids
        assert "all-tool-2" in tool_ids

    @pytest.mark.asyncio
    async def test_join_tools_with_embeddings(
        self,
        test_db_session,
        sample_tools,
        embedding_service
    ):
        """Test joining Tool and ToolEmbedding tables."""
        # Arrange - Create embeddings
        await embedding_service.embed_and_store_tools_batch(
            test_db_session,
            sample_tools
        )
        
        # Act - Join query
        results = (
            test_db_session.query(Tool, ToolEmbedding)
            .join(ToolEmbedding, Tool.id == ToolEmbedding.tool_id)
            .all()
        )
        
        # Assert
        assert len(results) == len(sample_tools)
        
        for tool, embedding in results:
            assert tool.id == embedding.tool_id
            assert isinstance(embedding.embedding, list)
            assert len(embedding.embedding) == 1536

    @pytest.mark.asyncio
    async def test_find_tools_without_embeddings(
        self,
        test_db_session,
        sample_tools,
        embedding_service
    ):
        """Test finding tools that don't have embeddings yet."""
        # Arrange - Only embed first 2 tools
        tools_to_embed = sample_tools[:2]
        
        await embedding_service.embed_and_store_tools_batch(
            test_db_session,
            tools_to_embed
        )
        
        # Act - Find tools without embeddings
        tools_without_embeddings = (
            test_db_session.query(Tool)
            .outerjoin(ToolEmbedding, Tool.id == ToolEmbedding.tool_id)
            .filter(ToolEmbedding.id.is_(None))
            .all()
        )
        
        # Assert
        assert len(tools_without_embeddings) == 1
        assert tools_without_embeddings[0].id == sample_tools[2].id

    def test_count_embeddings_by_model(self, test_db_session, embedding_service):
        """Test counting embeddings grouped by model name."""
        # Arrange
        embeddings_data = [
            ("count-tool-1", [0.1] * 1536, "model-a"),
            ("count-tool-2", [0.2] * 1536, "model-a"),
            ("count-tool-3", [0.3] * 1536, "model-b"),
        ]
        
        for tool_id, embedding, model in embeddings_data:
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                model
            )
        
        # Act
        from sqlalchemy import func
        results = (
            test_db_session.query(
                ToolEmbedding.model_name,
                func.count(ToolEmbedding.id)
            )
            .group_by(ToolEmbedding.model_name)
            .all()
        )
        
        # Assert
        counts = {model: count for model, count in results}
        assert counts["model-a"] == 2
        assert counts["model-b"] == 1


# ============================================================================
# DATA INTEGRITY & CONSTRAINTS
# ============================================================================


class TestDataIntegrityAndConstraints:
    """Test data integrity and constraints."""

    def test_embedding_dimensions_preserved(self, test_db_session, embedding_service):
        """Test that embedding dimensions are preserved correctly."""
        # Test different dimension sizes
        test_cases = [
            (512, "model-512"),
            (1536, "model-1536"),
            (3072, "model-3072"),
        ]
        
        for dimensions, model_name in test_cases:
            tool_id = f"tool-dim-{dimensions}"
            embedding = [0.1] * dimensions
            
            # Store
            embedding_service.store_tool_embedding(
                test_db_session,
                tool_id,
                embedding,
                model_name
            )
            
            # Retrieve
            db_embedding = test_db_session.query(ToolEmbedding).filter(
                ToolEmbedding.tool_id == tool_id
            ).first()
            
            # Verify dimensions preserved
            assert len(db_embedding.embedding) == dimensions

    def test_timestamps_created_correctly(self, test_db_session, embedding_service):
        """Test that created_at and updated_at timestamps are created."""
        # Arrange
        tool_id = "tool-timestamp-create"
        embedding = [0.1] * 1536
        
        # Act
        result = embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            embedding,
            "test-model"
        )
        
        # Assert
        assert result.created_at is not None
        assert result.updated_at is not None

    def test_timestamps_updated_on_modify(self, test_db_session, embedding_service):
        """Test that updated_at changes when embedding is modified."""
        # Arrange
        tool_id = "tool-timestamp-update"
        embedding = [0.1] * 1536
        
        # Act - Create
        result = embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            embedding,
            "test-model"
        )
        
        created_at = result.created_at
        
        # Wait a bit
        time.sleep(0.1)
        
        # Act - Update
        new_embedding = [0.9] * 1536
        updated_result = embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            new_embedding,
            "new-model"
        )
        
        # Assert - created_at unchanged
        assert updated_result.created_at == created_at
        # updated_at exists
        assert updated_result.updated_at is not None

    def test_delete_embedding_removes_from_database(self, test_db_session, embedding_service):
        """Test that deleting an embedding removes it from database."""
        # Arrange
        tool_id = "tool-delete"
        embedding = [0.5] * 1536
        
        embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            embedding,
            "test-model"
        )
        
        # Verify exists
        assert test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first() is not None
        
        # Act - Delete
        db_embedding = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first()
        
        test_db_session.delete(db_embedding)
        test_db_session.commit()
        
        # Assert - Gone
        assert test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first() is None

    def test_embedding_values_are_floats(self, test_db_session, embedding_service):
        """Test that embedding values are stored as floats."""
        # Arrange
        tool_id = "tool-float-check"
        embedding = [0.1, 0.2, 0.3] * 512
        
        # Act
        embedding_service.store_tool_embedding(
            test_db_session,
            tool_id,
            embedding,
            "test-model"
        )
        
        # Assert
        db_embedding = test_db_session.query(ToolEmbedding).filter(
            ToolEmbedding.tool_id == tool_id
        ).first()
        
        for value in db_embedding.embedding:
            assert isinstance(value, (int, float))


# ============================================================================
# ERROR HANDLING & EDGE CASES
# ============================================================================


class TestErrorHandlingAndEdgeCases:
    """Test error handling in integration scenarios."""

    def test_invalid_embedding_raises_error(self, test_db_session, embedding_service):
        """Test that invalid embeddings raise appropriate errors."""
        # Test 1: Empty embedding
        with pytest.raises(ValueError, match="Embedding must be a non-empty list"):
            embedding_service.store_tool_embedding(
                test_db_session,
                "tool-123",
                [],  # Empty
                "test-model"
            )
        
        # Test 2: Non-list embedding
        with pytest.raises(ValueError, match="Embedding must be a non-empty list"):
            embedding_service.store_tool_embedding(
                test_db_session,
                "tool-123",
                "not a list",  # Wrong type
                "test-model"
            )
        
        # Test 3: Non-numeric values
        with pytest.raises(ValueError, match="Embedding must contain only numbers"):
            embedding_service.store_tool_embedding(
                test_db_session,
                "tool-123",
                [0.1, "invalid", 0.3],  # Contains string
                "test-model"
            )

    def test_empty_batch_returns_empty_list(self, test_db_session, embedding_service):
        """Test that empty batch returns empty list without errors."""
        # Act
        results = embedding_service.batch_store_tool_embeddings(
            test_db_session,
            [],
            "test-model"
        )
        
        # Assert
        assert results == []
        assert test_db_session.query(ToolEmbedding).count() == 0

    @pytest.mark.asyncio
    async def test_tool_with_no_description_works(
        self,
        test_db_session,
        embedding_service
    ):
        """Test that tools with no description can still be embedded."""
        # Arrange
        class MinimalTool:
            def __init__(self):
                self.id = "minimal-tool"
                self.original_name = "minimal"
                self.description = None  # No description
                self.tags = []
                self.integration_type = "TEST"
                self.input_schema = {}
                self.gateway_id = "test"
        
        tool = MinimalTool()
        
        # Act
        result = await embedding_service.embed_and_store_tool(
            test_db_session,
            tool
        )
        
        # Assert
        assert result is not None
        assert result.tool_id == tool.id
        assert len(result.embedding) == 1536