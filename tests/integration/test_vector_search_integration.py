# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_vector_search_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for VectorSearchService similarity search with real SQLite database.

Uses known directional embeddings so similarity ordering is deterministic:
- weather tool: points along dimension 0
- climate tool: mostly dimension 0 with a small dimension 1 component (similar to weather)
- email tool: points along dimension 1 (orthogonal to weather)
"""

# Standard
from typing import Generator

# Third-Party
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway.db import Base, Tool, ToolEmbedding
from mcpgateway.services.vector_search_service import VectorSearchService


# ============================================================================
# FIXTURES
# ============================================================================

DIM = 1536


@pytest.fixture(scope="function")
def test_db_engine():
    """Create a fresh in-memory SQLite database per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine) -> Generator[Session, None, None]:
    """Create a database session for the test."""
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_tools_with_embeddings(test_db_session):
    """Create 3 tools with known directional embeddings for predictable similarity.

    weather -> [1, 0, 0, ...]  (unit vector along dim 0)
    climate -> [0.9, 0.1, 0, ...]  (similar to weather)
    email   -> [0, 1, 0, ...]  (orthogonal to weather)
    """
    weather_vec = np.zeros(DIM)
    weather_vec[0] = 1.0

    climate_vec = np.zeros(DIM)
    climate_vec[0] = 0.9
    climate_vec[1] = 0.1

    email_vec = np.zeros(DIM)
    email_vec[1] = 1.0

    tools_data = [
        ("tool-weather", "weather-api", "Get current weather", weather_vec.tolist()),
        ("tool-climate", "climate-info", "Get climate data", climate_vec.tolist()),
        ("tool-email", "email-sender", "Send emails", email_vec.tolist()),
    ]

    for tool_id, name, desc, emb_vec in tools_data:
        tool = Tool(
            id=tool_id,
            original_name=name,
            name=name,
            custom_name=name,
            custom_name_slug=name,
            description=desc,
            input_schema={},
            tags=[],
            integration_type="REST",
            gateway_id=None,
            enabled=True,
        )
        test_db_session.add(tool)
        test_db_session.flush()

        embedding = ToolEmbedding(
            tool_id=tool_id,
            embedding=emb_vec,
            model_name="test-model",
        )
        test_db_session.add(embedding)

    test_db_session.commit()
    return tools_data


# ============================================================================
# TESTS — SIMILARITY SEARCH ORDERING
# ============================================================================


class TestSimilaritySearchOrdering:
    """Test that search results are ordered correctly by cosine similarity."""

    @pytest.mark.asyncio
    async def test_similar_tool_ranked_first(self, test_db_session, sample_tools_with_embeddings):
        """Querying with weather-like vector should rank weather first, climate second, email last."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0  # Same direction as weather

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10)

        assert len(results) == 3
        assert results[0].tool_name == "weather-api"
        assert results[1].tool_name == "climate-info"
        assert results[2].tool_name == "email-sender"

    @pytest.mark.asyncio
    async def test_scores_descend(self, test_db_session, sample_tools_with_embeddings):
        """Similarity scores should be in descending order."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10)

        for i in range(len(results) - 1):
            assert results[i].similarity_score >= results[i + 1].similarity_score

    @pytest.mark.asyncio
    async def test_email_query_ranks_email_first(self, test_db_session, sample_tools_with_embeddings):
        """Querying with email-like vector should rank email tool first."""
        query_vec = np.zeros(DIM)
        query_vec[1] = 1.0  # Same direction as email

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10)

        assert results[0].tool_name == "email-sender"


# ============================================================================
# TESTS — THRESHOLD AND LIMIT
# ============================================================================


class TestThresholdFiltering:
    """Test that threshold parameter correctly filters results."""

    @pytest.mark.asyncio
    async def test_threshold_filters_dissimilar(self, test_db_session, sample_tools_with_embeddings):
        """Threshold of 0.9 with weather query should exclude the email tool."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10, threshold=0.9)

        names = [r.tool_name for r in results]
        assert "weather-api" in names
        assert "email-sender" not in names

    @pytest.mark.asyncio
    async def test_threshold_one_returns_only_exact_match(self, test_db_session, sample_tools_with_embeddings):
        """Threshold of 1.0 should only return exact matches."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10, threshold=1.0)

        assert len(results) == 1
        assert results[0].tool_name == "weather-api"


class TestLimitRespected:
    """Test that limit parameter is respected."""

    @pytest.mark.asyncio
    async def test_limit_one_returns_top_result(self, test_db_session, sample_tools_with_embeddings):
        """limit=1 should return only the most similar tool."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=1)

        assert len(results) == 1
        assert results[0].tool_name == "weather-api"

    @pytest.mark.asyncio
    async def test_limit_two_returns_top_two(self, test_db_session, sample_tools_with_embeddings):
        """limit=2 should return the top two results."""
        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=2)

        assert len(results) == 2


# ============================================================================
# TESTS — EDGE CASES
# ============================================================================


class TestEdgeCases:
    """Integration tests for edge cases."""

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty(self, test_db_session):
        """No embeddings in DB returns empty results."""
        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=[0.1] * DIM, limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_disabled_tools_excluded(self, test_db_session, sample_tools_with_embeddings):
        """Disabled tools should not appear in search results."""
        tool = test_db_session.query(Tool).filter(Tool.id == "tool-weather").first()
        tool.enabled = False
        test_db_session.commit()

        query_vec = np.zeros(DIM)
        query_vec[0] = 1.0

        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=query_vec.tolist(), limit=10)

        names = [r.tool_name for r in results]
        assert "weather-api" not in names

    @pytest.mark.asyncio
    async def test_similarity_scores_in_valid_range(self, test_db_session, sample_tools_with_embeddings):
        """All similarity scores should be between 0.0 and 1.0."""
        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=[0.1] * DIM, limit=10)
        for r in results:
            assert 0.0 <= r.similarity_score <= 1.0

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, test_db_session, sample_tools_with_embeddings):
        """All returned ToolSearchResult objects have required fields."""
        service = VectorSearchService(db=test_db_session)
        results = await service.search_similar_tools(embedding=[0.1] * DIM, limit=10)
        for r in results:
            assert isinstance(r.tool_name, str)
            assert isinstance(r.similarity_score, float)


# ============================================================================
# TESTS — ToolEmbedding.similar_to()
# ============================================================================


class TestToolEmbeddingSimilarTo:
    """Test the ToolEmbedding.similar_to() instance method on SQLite."""

    def test_similar_to_returns_ordered_results(self, test_db_session, sample_tools_with_embeddings):
        """similar_to() should return other embeddings ordered by similarity."""
        weather_emb = test_db_session.query(ToolEmbedding).filter(ToolEmbedding.tool_id == "tool-weather").first()
        results = weather_emb.similar_to(test_db_session, limit=10)

        assert len(results) == 2  # excludes self
        # climate should be more similar to weather than email
        assert results[0][0].tool_id == "tool-climate"
        assert results[1][0].tool_id == "tool-email"
        assert results[0][1] > results[1][1]  # similarity scores descending

    def test_similar_to_respects_limit(self, test_db_session, sample_tools_with_embeddings):
        """similar_to() should respect the limit parameter."""
        weather_emb = test_db_session.query(ToolEmbedding).filter(ToolEmbedding.tool_id == "tool-weather").first()
        results = weather_emb.similar_to(test_db_session, limit=1)

        assert len(results) == 1
        assert results[0][0].tool_id == "tool-climate"

    def test_similar_to_respects_threshold(self, test_db_session, sample_tools_with_embeddings):
        """similar_to() with high threshold should filter out dissimilar embeddings."""
        weather_emb = test_db_session.query(ToolEmbedding).filter(ToolEmbedding.tool_id == "tool-weather").first()
        results = weather_emb.similar_to(test_db_session, limit=10, threshold=0.9)

        tool_ids = [te.tool_id for te, _ in results]
        assert "tool-email" not in tool_ids

    def test_similar_to_excludes_self(self, test_db_session, sample_tools_with_embeddings):
        """similar_to() should never include the calling embedding itself."""
        weather_emb = test_db_session.query(ToolEmbedding).filter(ToolEmbedding.tool_id == "tool-weather").first()
        results = weather_emb.similar_to(test_db_session, limit=10)

        result_ids = [te.id for te, _ in results]
        assert weather_emb.id not in result_ids
