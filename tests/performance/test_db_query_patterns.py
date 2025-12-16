# -*- coding: utf-8 -*-
"""Database query pattern tests for N+1 detection.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

These tests verify that database queries stay within expected bounds
and don't exhibit N+1 query patterns.

Run with:
    uv run pytest -v tests/performance/test_query_patterns.py

Run with query output:
    uv run pytest -v -s tests/performance/test_query_patterns.py
"""

import pytest

from mcpgateway.db import Gateway, Tool


class TestQueryPatterns:
    """Tests for database query efficiency."""

    @pytest.fixture
    def seed_data(self, test_db):
        """Seed test database with sample data."""
        # Create gateways
        gateways = []
        for i in range(5):
            gw = Gateway(
                name=f"test-gateway-{i}",
                slug=f"test-gateway-{i}",
                url=f"http://gateway-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            gateways.append(gw)
        test_db.flush()

        # Create tools for each gateway
        for gw in gateways:
            for j in range(10):
                tool = Tool(
                    original_name=f"tool-{gw.id}-{j}",
                    description=f"Test tool {j} for gateway {gw.name}",
                    gateway_id=gw.id,
                    input_schema={"type": "object", "properties": {}},
                )
                test_db.add(tool)

        test_db.commit()
        return {"gateways": len(gateways), "tools": len(gateways) * 10}

    def test_list_tools_query_count(self, query_counter, test_db, seed_data):
        """Listing tools should not cause excessive queries."""
        with query_counter(print_summary=True) as counter:
            tools = test_db.query(Tool).all()

            # Access each tool's original_name (should not trigger additional queries)
            for tool in tools:
                _ = tool.original_name

        # Should be a single query for all tools
        assert counter.count <= 2, f"Expected 1-2 queries, got {counter.count}"

    def test_list_tools_with_gateway_n1_potential(self, query_counter, test_db, seed_data):
        """Test N+1 when accessing gateway relationship without eager loading.

        This test demonstrates the N+1 problem. Without eager loading,
        accessing tool.gateway triggers a separate query for each tool.
        """
        with query_counter(print_summary=True) as counter:
            tools = test_db.query(Tool).all()

            # This WILL trigger N+1 without eager loading!
            for tool in tools:
                if tool.gateway:
                    _ = tool.gateway.name

        # With N+1: 1 query for tools + N queries for gateways
        # This test documents the problem
        print(f"Query count: {counter.count} (N+1 expected: {1 + seed_data['tools']})")

        # Assert the N+1 pattern exists (to document the issue)
        # In a fixed version, this would be changed to assert counter.count <= 3
        if counter.count > 5:
            print("WARNING: N+1 pattern detected! Consider using joinedload/selectinload")

    def test_list_tools_with_eager_loading(self, query_counter, test_db, seed_data):
        """Test that eager loading prevents N+1.

        This demonstrates the fix for N+1 using joinedload.
        """
        from sqlalchemy.orm import joinedload

        with query_counter(print_summary=True) as counter:
            tools = test_db.query(Tool).options(joinedload(Tool.gateway)).all()

            # This should NOT trigger additional queries
            for tool in tools:
                if tool.gateway:
                    _ = tool.gateway.name

        # With eager loading: 1-2 queries total (join or separate query)
        assert counter.count <= 3, f"Expected <= 3 queries with eager loading, got {counter.count}"

    def test_query_budget_enforcement(self, assert_max_queries, test_db, seed_data):
        """Test that query budget fixture catches violations."""
        from sqlalchemy.orm import joinedload

        # This should pass (eager loading)
        with assert_max_queries(5):
            tools = test_db.query(Tool).options(joinedload(Tool.gateway)).all()
            for tool in tools:
                if tool.gateway:
                    _ = tool.gateway.name


class TestQueryCounterUtilities:
    """Tests for the query counter utility itself."""

    def test_query_counter_tracks_queries(self, query_counter, test_db):
        """Verify query counter accurately tracks queries."""
        with query_counter() as counter:
            # Execute some queries
            test_db.query(Tool).count()
            test_db.query(Gateway).count()

        assert counter.count >= 2, "Counter should track at least 2 queries"

    def test_query_counter_measures_duration(self, query_counter, test_db):
        """Verify query counter measures duration."""
        with query_counter() as counter:
            test_db.query(Tool).all()

        assert counter.total_duration_ms >= 0, "Duration should be non-negative"
        assert len(counter.queries) > 0, "Should have recorded queries"
        assert "duration_ms" in counter.queries[0], "Should have duration_ms"

    def test_query_counter_detects_types(self, query_counter, test_db):
        """Verify query counter detects query types."""
        from mcpgateway.db import Tool

        with query_counter() as counter:
            test_db.query(Tool).all()

        types = counter.get_query_types()
        assert "SELECT" in types, "Should detect SELECT queries"
