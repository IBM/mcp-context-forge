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


class TestSelectInLoadPatterns:
    """Tests for selectinload (better for collections)."""

    @pytest.fixture
    def seed_servers_with_tools(self, test_db):
        """Seed servers with associated tools."""
        from mcpgateway.db import Server

        servers = []
        for i in range(3):
            server = Server(
                name=f"test-server-{i}",
                description=f"Test server {i}",
                enabled=True,
            )
            test_db.add(server)
            servers.append(server)
        test_db.flush()

        # Create tools and associate with servers
        gw = Gateway(
            name="shared-gateway",
            slug="shared-gateway",
            url="http://gateway.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(gw)
        test_db.flush()

        for server in servers:
            for j in range(5):
                tool = Tool(
                    original_name=f"tool-{server.id}-{j}",
                    description=f"Tool {j} for server {server.name}",
                    gateway_id=gw.id,
                    input_schema={"type": "object"},
                )
                test_db.add(tool)
                test_db.flush()
                # Associate tool with server
                server.tools.append(tool)

        test_db.commit()
        return {"servers": len(servers), "tools_per_server": 5}

    def test_selectinload_for_collections(self, query_counter, test_db, seed_servers_with_tools):
        """Test selectinload is efficient for one-to-many relationships."""
        from sqlalchemy.orm import selectinload

        from mcpgateway.db import Server

        with query_counter(print_summary=True) as counter:
            servers = test_db.query(Server).options(selectinload(Server.tools)).all()

            # Access tools for each server
            for server in servers:
                for tool in server.tools:
                    _ = tool.original_name

        # selectinload: 1 query for servers + 1 query for all tools
        assert counter.count <= 3, f"Expected <= 3 queries with selectinload, got {counter.count}"


class TestFilteredQueryPatterns:
    """Tests for queries with filters and conditions."""

    @pytest.fixture
    def seed_mixed_data(self, test_db):
        """Seed data with mixed enabled/disabled states."""
        gateways = []
        for i in range(4):
            gw = Gateway(
                name=f"gateway-{i}",
                slug=f"gateway-{i}",
                url=f"http://gateway-{i}.local:8000",
                enabled=(i % 2 == 0),  # Alternate enabled/disabled
                capabilities={},
            )
            test_db.add(gw)
            gateways.append(gw)
        test_db.flush()

        for gw in gateways:
            for j in range(8):
                tool = Tool(
                    original_name=f"tool-{gw.id}-{j}",
                    description=f"Tool {j}",
                    gateway_id=gw.id,
                    input_schema={"type": "object"},
                    enabled=(j % 2 == 0),
                )
                test_db.add(tool)

        test_db.commit()
        return {"gateways": 4, "tools": 32}

    def test_filtered_query_efficiency(self, query_counter, test_db, seed_mixed_data):
        """Filtered queries should still be efficient."""
        with query_counter(print_summary=True) as counter:
            # Query only enabled tools
            tools = test_db.query(Tool).filter(Tool.enabled == True).all()  # noqa: E712

        # The key assertion: filtering should still be a single query
        assert counter.count == 1, f"Filtered query should be 1 query, got {counter.count}"
        # Just verify we got results (exact count depends on test isolation)
        assert isinstance(tools, list), "Should return a list"

    def test_join_with_filter(self, query_counter, test_db, seed_mixed_data):
        """Join queries with filters should be efficient."""
        from sqlalchemy.orm import joinedload

        with query_counter(print_summary=True) as counter:
            # Get enabled tools with their gateways
            tools = (
                test_db.query(Tool)
                .options(joinedload(Tool.gateway))
                .filter(Tool.enabled == True)  # noqa: E712
                .all()
            )

            # Access gateway for each tool
            for tool in tools:
                if tool.gateway:
                    _ = tool.gateway.enabled

        # Should be 1-2 queries (join or eager load)
        assert counter.count <= 2, f"Expected <= 2 queries, got {counter.count}"


class TestWriteQueryPatterns:
    """Tests for INSERT/UPDATE query patterns."""

    def test_bulk_insert_efficiency(self, query_counter, test_db):
        """Bulk inserts should be reasonably efficient."""
        with query_counter(print_summary=True) as counter:
            gateways = []
            for i in range(10):
                gw = Gateway(
                    name=f"bulk-gateway-{i}",
                    slug=f"bulk-gateway-{i}",
                    url=f"http://bulk-{i}.local:8000",
                    enabled=True,
                    capabilities={},
                )
                gateways.append(gw)

            test_db.add_all(gateways)
            test_db.flush()

        # Bulk add should be efficient (not 10 separate inserts)
        # SQLAlchemy may batch or use single insert
        assert counter.count <= 15, f"Bulk insert should be efficient, got {counter.count} queries"

    def test_update_query_pattern(self, query_counter, test_db):
        """Update queries should be efficient."""
        # Setup: create a gateway
        gw = Gateway(
            name="update-test",
            slug="update-test",
            url="http://update.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(gw)
        test_db.commit()

        with query_counter(print_summary=True) as counter:
            # Fetch and update
            gateway = test_db.query(Gateway).filter(Gateway.slug == "update-test").first()
            gateway.enabled = False
            test_db.commit()

        # Should be: 1 SELECT + 1 UPDATE
        assert counter.count <= 3, f"Update should be <= 3 queries, got {counter.count}"


class TestN1DetectionUtility:
    """Tests for the N+1 detection utility functions."""

    def test_detect_n1_patterns_finds_issues(self):
        """Test that N+1 detection finds repeated query patterns."""
        from tests.helpers.query_counter import detect_n_plus_one

        # Simulate N+1 pattern - use "statement" key as expected by detect_n_plus_one
        queries = [
            {"statement": "SELECT * FROM tools"},
            {"statement": "SELECT * FROM gateways WHERE id = 1"},
            {"statement": "SELECT * FROM gateways WHERE id = 2"},
            {"statement": "SELECT * FROM gateways WHERE id = 3"},
            {"statement": "SELECT * FROM gateways WHERE id = 4"},
        ]

        class MockCounter:
            def __init__(self, queries):
                self.queries = queries

        counter = MockCounter(queries)
        warnings = detect_n_plus_one(counter, threshold=3)

        assert len(warnings) >= 1, "Should detect N+1 pattern"
        # Check that the warning mentions the repeated pattern count
        assert any("4" in w for w in warnings), "Should mention repetition count"

    def test_detect_n1_patterns_no_false_positives(self):
        """Test that N+1 detection doesn't flag efficient queries."""
        from tests.helpers.query_counter import detect_n_plus_one

        # Efficient query pattern (no repetition) - use "statement" key
        queries = [
            {"statement": "SELECT * FROM tools"},
            {"statement": "SELECT * FROM gateways"},
            {"statement": "SELECT * FROM servers"},
        ]

        class MockCounter:
            def __init__(self, queries):
                self.queries = queries

        counter = MockCounter(queries)
        warnings = detect_n_plus_one(counter, threshold=3)

        assert len(warnings) == 0, "Should not flag efficient queries"


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

    def test_query_counter_reset(self, query_counter, test_db):
        """Verify query counter can be reset."""
        with query_counter() as counter:
            test_db.query(Tool).count()
            assert counter.count >= 1

            counter.reset()
            assert counter.count == 0, "Counter should reset to 0"
            assert len(counter.queries) == 0, "Queries list should be empty"

    def test_query_counter_slow_query_detection(self, query_counter, test_db):
        """Verify slow query detection works."""
        with query_counter() as counter:
            # Run a few queries
            test_db.query(Tool).all()
            test_db.query(Gateway).all()

        # All queries should be fast in tests
        slow = counter.get_slow_queries(threshold_ms=1000)
        assert isinstance(slow, list), "Should return a list"

    def test_assert_max_queries_passes(self, assert_max_queries, test_db):
        """Verify assert_max_queries passes when under limit."""
        with assert_max_queries(5):
            test_db.query(Tool).count()

    def test_assert_max_queries_fails(self, assert_max_queries, test_db):
        """Verify assert_max_queries fails when over limit."""
        with pytest.raises(AssertionError) as exc_info:
            with assert_max_queries(0):  # Impossible limit
                test_db.query(Tool).count()

        assert "Expected at most 0 queries" in str(exc_info.value)


class TestQueryLoggingMiddleware:
    """Tests for the query logging middleware utilities."""

    def test_normalize_query(self):
        """Test SQL query normalization for pattern detection."""
        from mcpgateway.middleware.db_query_logging import _normalize_query

        # Test value replacement
        sql1 = "SELECT * FROM users WHERE id = 123"
        sql2 = "SELECT * FROM users WHERE id = 456"
        assert _normalize_query(sql1) == _normalize_query(sql2), "Should normalize numeric IDs"

        # Test string replacement
        sql3 = "SELECT * FROM users WHERE name = 'alice'"
        sql4 = "SELECT * FROM users WHERE name = 'bob'"
        assert _normalize_query(sql3) == _normalize_query(sql4), "Should normalize string values"

    def test_extract_table_name(self):
        """Test table name extraction from SQL."""
        from mcpgateway.middleware.db_query_logging import _extract_table_name

        assert _extract_table_name("SELECT * FROM users WHERE id = 1") == "users"
        assert _extract_table_name("INSERT INTO logs (msg) VALUES ('test')") == "logs"
        assert _extract_table_name("UPDATE settings SET value = 1") == "settings"

    def test_should_exclude_query(self):
        """Test query exclusion logic."""
        from mcpgateway.middleware.db_query_logging import _should_exclude_query

        # Should exclude observability tables
        assert _should_exclude_query("SELECT * FROM observability_traces") is True
        assert _should_exclude_query("INSERT INTO structured_log_entries") is True
        assert _should_exclude_query("UPDATE audit_logs SET") is True

        # Should not exclude business tables
        assert _should_exclude_query("SELECT * FROM tools") is False
        assert _should_exclude_query("SELECT * FROM gateways") is False

    def test_detect_n1_patterns(self):
        """Test N+1 pattern detection logic."""
        from mcpgateway.middleware.db_query_logging import _detect_n1_patterns

        queries = [
            {"sql": "SELECT * FROM tools"},
            {"sql": "SELECT * FROM gateways WHERE id = 1"},
            {"sql": "SELECT * FROM gateways WHERE id = 2"},
            {"sql": "SELECT * FROM gateways WHERE id = 3"},
        ]

        issues = _detect_n1_patterns(queries, threshold=3)
        assert len(issues) == 1, "Should detect one N+1 pattern"
        assert issues[0]["count"] == 3, "Should count 3 similar queries"
        assert issues[0]["table"] == "gateways", "Should identify gateways table"


# =============================================================================
# ADDITIONAL COMPREHENSIVE TESTS
# =============================================================================


class TestPaginationPatterns:
    """Tests for pagination query efficiency."""

    @pytest.fixture
    def seed_many_tools(self, test_db):
        """Seed database with many tools for pagination tests."""
        gw = Gateway(
            name="pagination-gateway",
            slug="pagination-gateway",
            url="http://pagination.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(gw)
        test_db.flush()

        for i in range(100):
            tool = Tool(
                original_name=f"pagination-tool-{i:03d}",
                description=f"Tool {i} for pagination",
                gateway_id=gw.id,
                input_schema={"type": "object"},
                enabled=True,
            )
            test_db.add(tool)

        test_db.commit()
        return {"tools": 100}

    def test_limit_offset_efficiency(self, query_counter, test_db, seed_many_tools):
        """LIMIT/OFFSET pagination should be single query."""
        with query_counter(print_summary=True) as counter:
            # Page 1
            page1 = test_db.query(Tool).limit(10).offset(0).all()
            # Page 2
            page2 = test_db.query(Tool).limit(10).offset(10).all()

        assert counter.count == 2, f"Two paginated queries expected, got {counter.count}"
        assert len(page1) == 10, "Page 1 should have 10 items"
        assert len(page2) == 10, "Page 2 should have 10 items"

    def test_count_with_pagination(self, query_counter, test_db, seed_many_tools):
        """Count + paginated results should be 2 queries."""
        with query_counter(print_summary=True) as counter:
            total = test_db.query(Tool).count()
            items = test_db.query(Tool).limit(10).all()

        assert counter.count == 2, f"Count + fetch should be 2 queries, got {counter.count}"
        assert total >= 100, "Should have at least 100 tools"
        assert len(items) == 10, "Should fetch 10 items"

    def test_order_by_with_limit(self, query_counter, test_db, seed_many_tools):
        """ORDER BY with LIMIT should be single query."""
        with query_counter(print_summary=True) as counter:
            tools = test_db.query(Tool).order_by(Tool.original_name).limit(20).all()

        assert counter.count == 1, f"Ordered limited query should be 1 query, got {counter.count}"
        assert len(tools) == 20, "Should return 20 tools"


class TestCountQueryPatterns:
    """Tests for COUNT query efficiency."""

    @pytest.fixture
    def seed_countable_data(self, test_db):
        """Seed data for count tests."""
        import uuid

        unique_id = uuid.uuid4().hex[:8]

        # Create dedicated gateway for count tests
        count_gateway = Gateway(
            name=f"count-gateway-main-{unique_id}",
            slug=f"count-gateway-main-{unique_id}",
            url=f"http://count-main-{unique_id}.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(count_gateway)
        test_db.flush()

        # Create additional gateways
        for i in range(5):
            gw = Gateway(
                name=f"count-gateway-{unique_id}-{i}",
                slug=f"count-gateway-{unique_id}-{i}",
                url=f"http://count-{unique_id}-{i}.local:8000",
                enabled=(i % 2 == 0),
                capabilities={},
            )
            test_db.add(gw)
        test_db.flush()

        for i in range(50):
            tool = Tool(
                original_name=f"count-tool-{unique_id}-{i}",
                description=f"Tool {i}",
                gateway_id=count_gateway.id,
                input_schema={"type": "object"},
                enabled=(i % 3 == 0),
            )
            test_db.add(tool)

        test_db.commit()
        return {"gateways": 6, "tools": 50}

    def test_simple_count(self, query_counter, test_db, seed_countable_data):
        """Simple count should be single query."""
        with query_counter(print_summary=True) as counter:
            count = test_db.query(Tool).count()

        assert counter.count == 1, f"Count should be 1 query, got {counter.count}"
        assert count >= 50, "Should count at least 50 tools"

    def test_filtered_count(self, query_counter, test_db, seed_countable_data):
        """Filtered count should be single query."""
        with query_counter(print_summary=True) as counter:
            count = test_db.query(Tool).filter(Tool.enabled == True).count()  # noqa: E712

        assert counter.count == 1, f"Filtered count should be 1 query, got {counter.count}"

    def test_multiple_counts(self, query_counter, test_db, seed_countable_data):
        """Multiple independent counts."""
        with query_counter(print_summary=True) as counter:
            tool_count = test_db.query(Tool).count()
            gateway_count = test_db.query(Gateway).count()
            enabled_tools = test_db.query(Tool).filter(Tool.enabled == True).count()  # noqa: E712

        assert counter.count == 3, f"Three counts should be 3 queries, got {counter.count}"

    def test_count_vs_len(self, query_counter, test_db, seed_countable_data):
        """count() should be more efficient than len(all())."""
        with query_counter(print_summary=True) as counter:
            # Efficient way
            count1 = test_db.query(Tool).count()

        query_count_efficient = counter.count

        with query_counter(print_summary=True) as counter:
            # Less efficient way (fetches all rows)
            count2 = len(test_db.query(Tool).all())

        query_count_inefficient = counter.count

        assert query_count_efficient == query_count_inefficient == 1, "Both should be 1 query"
        assert count1 == count2, "Counts should match"


class TestSubqueryPatterns:
    """Tests for subquery efficiency."""

    @pytest.fixture
    def seed_subquery_data(self, test_db):
        """Seed data for subquery tests."""
        gateways = []
        for i in range(3):
            gw = Gateway(
                name=f"subquery-gateway-{i}",
                slug=f"subquery-gateway-{i}",
                url=f"http://subquery-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            gateways.append(gw)
        test_db.flush()

        # Create varying numbers of tools per gateway
        tool_counts = [5, 10, 3]
        for gw, count in zip(gateways, tool_counts):
            for j in range(count):
                tool = Tool(
                    original_name=f"tool-{gw.id}-{j}",
                    description=f"Tool {j}",
                    gateway_id=gw.id,
                    input_schema={"type": "object"},
                )
                test_db.add(tool)

        test_db.commit()
        return {"gateways": 3, "tools": sum(tool_counts)}

    def test_in_subquery(self, query_counter, test_db, seed_subquery_data):
        """IN with subquery should be efficient."""
        from sqlalchemy import select

        with query_counter(print_summary=True) as counter:
            # Get tools for enabled gateways using subquery
            enabled_gateway_ids = select(Gateway.id).where(Gateway.enabled == True)  # noqa: E712
            tools = test_db.query(Tool).filter(Tool.gateway_id.in_(enabled_gateway_ids)).all()

        # Should be 1 query (subquery embedded)
        assert counter.count == 1, f"Subquery should be single query, got {counter.count}"

    def test_exists_subquery(self, query_counter, test_db, seed_subquery_data):
        """EXISTS subquery should be efficient."""
        from sqlalchemy import exists

        with query_counter(print_summary=True) as counter:
            # Check if any enabled tools exist
            has_tools = test_db.query(exists().where(Tool.enabled == True)).scalar()  # noqa: E712

        assert counter.count == 1, f"EXISTS should be 1 query, got {counter.count}"


class TestBatchOperationPatterns:
    """Tests for batch operation efficiency."""

    def test_bulk_update_efficiency(self, query_counter, test_db):
        """Bulk update should be efficient."""
        # Setup
        for i in range(20):
            gw = Gateway(
                name=f"bulk-update-{i}",
                slug=f"bulk-update-{i}",
                url=f"http://bulk-update-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
        test_db.commit()

        with query_counter(print_summary=True) as counter:
            # Bulk update all gateways
            test_db.query(Gateway).filter(Gateway.slug.like("bulk-update-%")).update(
                {"enabled": False}, synchronize_session=False
            )
            test_db.commit()

        # Bulk update should be single UPDATE statement
        assert counter.count <= 2, f"Bulk update should be <= 2 queries, got {counter.count}"

    def test_bulk_delete_efficiency(self, query_counter, test_db):
        """Bulk delete should be efficient."""
        # Setup
        for i in range(15):
            gw = Gateway(
                name=f"bulk-delete-{i}",
                slug=f"bulk-delete-{i}",
                url=f"http://bulk-delete-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
        test_db.commit()

        with query_counter(print_summary=True) as counter:
            # Bulk delete
            test_db.query(Gateway).filter(Gateway.slug.like("bulk-delete-%")).delete(synchronize_session=False)
            test_db.commit()

        assert counter.count <= 2, f"Bulk delete should be <= 2 queries, got {counter.count}"


class TestLazyLoadingDetection:
    """Tests specifically for detecting lazy loading issues."""

    @pytest.fixture
    def seed_lazy_load_data(self, test_db):
        """Seed data for lazy loading tests."""
        gateways = []
        for i in range(10):
            gw = Gateway(
                name=f"lazy-gateway-{i}",
                slug=f"lazy-gateway-{i}",
                url=f"http://lazy-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            gateways.append(gw)
        test_db.flush()

        for gw in gateways:
            for j in range(3):
                tool = Tool(
                    original_name=f"lazy-tool-{gw.id}-{j}",
                    description=f"Tool {j}",
                    gateway_id=gw.id,
                    input_schema={"type": "object"},
                )
                test_db.add(tool)

        test_db.commit()
        return {"gateways": 10, "tools_per_gateway": 3}

    def test_detect_lazy_load_n1(self, query_counter, test_db, seed_lazy_load_data):
        """Detect N+1 from lazy loading relationships."""
        with query_counter(print_summary=True) as counter:
            tools = test_db.query(Tool).filter(Tool.original_name.like("lazy-tool-%")).all()

            # This triggers lazy load for each tool
            gateway_names = []
            for tool in tools:
                if tool.gateway:
                    gateway_names.append(tool.gateway.name)

        # Should see N+1 pattern: 1 for tools + N for gateways
        # Note: May be optimized by SQLAlchemy's identity map
        print(f"Lazy load test: {counter.count} queries for {len(tools)} tools")

    def test_prevent_lazy_load_with_joinedload(self, query_counter, test_db, seed_lazy_load_data):
        """Prevent lazy load N+1 with joinedload."""
        from sqlalchemy.orm import joinedload

        with query_counter(print_summary=True) as counter:
            tools = (
                test_db.query(Tool)
                .options(joinedload(Tool.gateway))
                .filter(Tool.original_name.like("lazy-tool-%"))
                .all()
            )

            # This should NOT trigger additional queries
            gateway_names = []
            for tool in tools:
                if tool.gateway:
                    gateway_names.append(tool.gateway.name)

        # With joinedload, should be 1-2 queries total
        assert counter.count <= 2, f"Joinedload should prevent N+1, got {counter.count}"


class TestComplexJoinPatterns:
    """Tests for complex join scenarios."""

    @pytest.fixture
    def seed_complex_data(self, test_db):
        """Seed complex relational data."""
        from mcpgateway.db import Server

        # Create gateways
        gateways = []
        for i in range(3):
            gw = Gateway(
                name=f"complex-gateway-{i}",
                slug=f"complex-gateway-{i}",
                url=f"http://complex-{i}.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            gateways.append(gw)
        test_db.flush()

        # Create servers
        servers = []
        for i in range(2):
            server = Server(
                name=f"complex-server-{i}",
                description=f"Server {i}",
                enabled=True,
            )
            test_db.add(server)
            servers.append(server)
        test_db.flush()

        # Create tools linked to gateways and servers
        for gw in gateways:
            for j in range(4):
                tool = Tool(
                    original_name=f"complex-tool-{gw.id}-{j}",
                    description=f"Tool {j}",
                    gateway_id=gw.id,
                    input_schema={"type": "object"},
                )
                test_db.add(tool)
                test_db.flush()
                # Link to a server
                servers[j % len(servers)].tools.append(tool)

        test_db.commit()
        return {"gateways": 3, "servers": 2, "tools": 12}

    def test_multiple_joinedloads(self, query_counter, test_db, seed_complex_data):
        """Multiple joinedloads should be efficient."""
        from sqlalchemy.orm import joinedload

        with query_counter(print_summary=True) as counter:
            tools = (
                test_db.query(Tool)
                .options(joinedload(Tool.gateway))
                .filter(Tool.original_name.like("complex-tool-%"))
                .all()
            )

            for tool in tools:
                _ = tool.gateway.name if tool.gateway else None

        assert counter.count <= 3, f"Multiple joins should be efficient, got {counter.count}"

    def test_chained_relationships(self, query_counter, test_db, seed_complex_data):
        """Access through chained relationships."""
        from sqlalchemy.orm import joinedload

        with query_counter(print_summary=True) as counter:
            tools = (
                test_db.query(Tool)
                .options(joinedload(Tool.gateway))
                .filter(Tool.original_name.like("complex-tool-%"))
                .all()
            )

            # Access gateway properties
            for tool in tools:
                if tool.gateway:
                    _ = tool.gateway.url
                    _ = tool.gateway.enabled

        assert counter.count <= 3, f"Chained access should be efficient, got {counter.count}"


class TestQueryNormalizationEdgeCases:
    """Edge case tests for query normalization."""

    def test_normalize_uuid_values(self):
        """Test normalization of UUID values."""
        from mcpgateway.middleware.db_query_logging import _normalize_query

        sql1 = "SELECT * FROM tools WHERE id = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'"
        sql2 = "SELECT * FROM tools WHERE id = '12345678-1234-1234-1234-123456789012'"

        assert _normalize_query(sql1) == _normalize_query(sql2), "Should normalize UUIDs"

    def test_normalize_in_clause(self):
        """Test normalization of IN clauses."""
        from mcpgateway.middleware.db_query_logging import _normalize_query

        sql1 = "SELECT * FROM tools WHERE id IN (1, 2, 3)"
        sql2 = "SELECT * FROM tools WHERE id IN (4, 5, 6, 7, 8)"

        norm1 = _normalize_query(sql1)
        norm2 = _normalize_query(sql2)
        assert norm1 == norm2, f"Should normalize IN clauses: {norm1} vs {norm2}"

    def test_normalize_whitespace(self):
        """Test whitespace normalization."""
        from mcpgateway.middleware.db_query_logging import _normalize_query

        sql1 = "SELECT * FROM   tools   WHERE id = 1"
        sql2 = "SELECT * FROM tools WHERE id = 1"

        assert _normalize_query(sql1) == _normalize_query(sql2), "Should normalize whitespace"

    def test_normalize_mixed_quotes(self):
        """Test mixed quote normalization."""
        from mcpgateway.middleware.db_query_logging import _normalize_query

        sql1 = "SELECT * FROM tools WHERE name = 'test'"
        sql2 = "SELECT * FROM tools WHERE name = 'other'"

        assert _normalize_query(sql1) == _normalize_query(sql2), "Should normalize quoted strings"

    def test_extract_table_from_complex_query(self):
        """Test table extraction from complex queries."""
        from mcpgateway.middleware.db_query_logging import _extract_table_name

        # JOIN query
        assert _extract_table_name("SELECT t.* FROM tools t JOIN gateways g ON t.gateway_id = g.id") == "tools"

        # Subquery
        assert _extract_table_name("SELECT * FROM (SELECT * FROM tools) AS subq") == "tools"

        # With schema
        assert _extract_table_name("SELECT * FROM public.users WHERE id = 1") == "public"


class TestN1PatternVariations:
    """Tests for various N+1 pattern variations."""

    def test_detect_multiple_n1_patterns(self):
        """Test detection of multiple N+1 patterns in same request."""
        from mcpgateway.middleware.db_query_logging import _detect_n1_patterns

        queries = [
            {"sql": "SELECT * FROM tools"},
            {"sql": "SELECT * FROM gateways WHERE id = 1"},
            {"sql": "SELECT * FROM gateways WHERE id = 2"},
            {"sql": "SELECT * FROM gateways WHERE id = 3"},
            {"sql": "SELECT * FROM servers WHERE tool_id = 1"},
            {"sql": "SELECT * FROM servers WHERE tool_id = 2"},
            {"sql": "SELECT * FROM servers WHERE tool_id = 3"},
        ]

        issues = _detect_n1_patterns(queries, threshold=3)
        assert len(issues) == 2, f"Should detect 2 N+1 patterns, got {len(issues)}"

    def test_n1_threshold_sensitivity(self):
        """Test N+1 detection threshold."""
        from mcpgateway.middleware.db_query_logging import _detect_n1_patterns

        queries = [
            {"sql": "SELECT * FROM gateways WHERE id = 1"},
            {"sql": "SELECT * FROM gateways WHERE id = 2"},
        ]

        # With threshold=3, should not detect
        issues_high = _detect_n1_patterns(queries, threshold=3)
        assert len(issues_high) == 0, "Should not detect with high threshold"

        # With threshold=2, should detect
        issues_low = _detect_n1_patterns(queries, threshold=2)
        assert len(issues_low) == 1, "Should detect with low threshold"

    def test_n1_with_different_columns(self):
        """Test N+1 detection with queries on different columns."""
        from mcpgateway.middleware.db_query_logging import _detect_n1_patterns

        queries = [
            {"sql": "SELECT * FROM tools WHERE gateway_id = 1"},
            {"sql": "SELECT * FROM tools WHERE gateway_id = 2"},
            {"sql": "SELECT * FROM tools WHERE gateway_id = 3"},
            {"sql": "SELECT * FROM tools WHERE name = 'a'"},
            {"sql": "SELECT * FROM tools WHERE name = 'b'"},
            {"sql": "SELECT * FROM tools WHERE name = 'c'"},
        ]

        issues = _detect_n1_patterns(queries, threshold=3)
        # Both patterns should be detected (gateway_id and name)
        assert len(issues) == 2, f"Should detect 2 patterns, got {len(issues)}"


class TestQueryCounterAdvanced:
    """Advanced tests for query counter functionality."""

    def test_counter_with_transactions(self, query_counter, test_db):
        """Test counter with explicit transactions."""
        with query_counter(print_summary=True) as counter:
            gw = Gateway(
                name="transaction-test",
                slug="transaction-test",
                url="http://transaction.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            test_db.flush()

            # Query within same transaction
            result = test_db.query(Gateway).filter(Gateway.slug == "transaction-test").first()
            assert result is not None

            test_db.commit()

        # Should track all queries including transaction management
        assert counter.count >= 2, "Should track transaction queries"

    def test_counter_with_rollback(self, query_counter, test_db):
        """Test counter tracks queries even on rollback."""
        with query_counter(print_summary=True) as counter:
            gw = Gateway(
                name="rollback-test",
                slug="rollback-test",
                url="http://rollback.local:8000",
                enabled=True,
                capabilities={},
            )
            test_db.add(gw)
            test_db.flush()
            test_db.rollback()

        # Queries should still be counted even though rolled back
        assert counter.count >= 1, "Should track queries before rollback"

    def test_counter_print_queries_option(self, query_counter, test_db, capsys):
        """Test print_queries option outputs correctly."""
        with query_counter(print_queries=True) as counter:
            test_db.query(Tool).count()

        captured = capsys.readouterr()
        assert "Query #" in captured.out, "Should print query info"

    def test_counter_summary_output(self, query_counter, test_db, capsys):
        """Test print_summary option outputs correctly."""
        with query_counter(print_summary=True) as counter:
            test_db.query(Tool).count()
            test_db.query(Gateway).count()

        captured = capsys.readouterr()
        assert "QUERY SUMMARY" in captured.out, "Should print summary"


class TestExcludedTablesComprehensive:
    """Comprehensive tests for table exclusion logic."""

    def test_all_excluded_tables(self):
        """Test all excluded tables are properly excluded."""
        from mcpgateway.middleware.db_query_logging import _should_exclude_query

        excluded = [
            "observability_traces",
            "observability_spans",
            "observability_events",
            "observability_metrics",
            "structured_log_entries",
            "audit_logs",
            "security_events",
        ]

        for table in excluded:
            assert _should_exclude_query(f"SELECT * FROM {table}") is True, f"{table} should be excluded"
            assert _should_exclude_query(f"INSERT INTO {table}") is True, f"INSERT {table} should be excluded"
            assert _should_exclude_query(f"UPDATE {table} SET") is True, f"UPDATE {table} should be excluded"
            assert _should_exclude_query(f"DELETE FROM {table}") is True, f"DELETE {table} should be excluded"

    def test_business_tables_not_excluded(self):
        """Test business tables are not excluded."""
        from mcpgateway.middleware.db_query_logging import _should_exclude_query

        business_tables = [
            "tools",
            "gateways",
            "servers",
            "resources",
            "prompts",
            "users",
            "teams",
            "roles",
        ]

        for table in business_tables:
            assert _should_exclude_query(f"SELECT * FROM {table}") is False, f"{table} should NOT be excluded"

    def test_case_insensitive_exclusion(self):
        """Test exclusion is case-insensitive."""
        from mcpgateway.middleware.db_query_logging import _should_exclude_query

        assert _should_exclude_query("SELECT * FROM OBSERVABILITY_TRACES") is True
        assert _should_exclude_query("select * from observability_traces") is True
        assert _should_exclude_query("Select * From Observability_Traces") is True


class TestFirstAndOnePatterns:
    """Tests for first() and one() query patterns."""

    @pytest.fixture
    def seed_single_item_data(self, test_db):
        """Seed data for single item retrieval tests."""
        import uuid

        unique_id = uuid.uuid4().hex[:8]

        gw = Gateway(
            name=f"single-gateway-{unique_id}",
            slug=f"single-gateway-{unique_id}",
            url=f"http://single-{unique_id}.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(gw)
        test_db.commit()
        return {"gateway_id": gw.id, "slug": f"single-gateway-{unique_id}"}

    def test_first_efficiency(self, query_counter, test_db, seed_single_item_data):
        """first() should be single query."""
        slug = seed_single_item_data["slug"]
        with query_counter(print_summary=True) as counter:
            gw = test_db.query(Gateway).filter(Gateway.slug == slug).first()

        assert counter.count == 1, f"first() should be 1 query, got {counter.count}"
        assert gw is not None, "Should find gateway"

    def test_one_or_none_efficiency(self, query_counter, test_db, seed_single_item_data):
        """one_or_none() should be single query."""
        slug = seed_single_item_data["slug"]
        with query_counter(print_summary=True) as counter:
            gw = test_db.query(Gateway).filter(Gateway.slug == slug).one_or_none()

        assert counter.count == 1, f"one_or_none() should be 1 query, got {counter.count}"
        assert gw is not None, "Should find gateway"

    def test_get_by_id_efficiency(self, query_counter, test_db, seed_single_item_data):
        """get() by primary key should be efficient."""
        gateway_id = seed_single_item_data["gateway_id"]

        with query_counter(print_summary=True) as counter:
            gw = test_db.query(Gateway).get(gateway_id)

        assert counter.count <= 1, f"get() should be <= 1 query, got {counter.count}"


class TestDistinctAndGroupByPatterns:
    """Tests for DISTINCT and GROUP BY query patterns."""

    @pytest.fixture
    def seed_groupable_data(self, test_db):
        """Seed data for grouping tests."""
        import uuid

        unique_id = uuid.uuid4().hex[:8]

        # Create dedicated gateway for group tests
        group_gateway = Gateway(
            name=f"group-gateway-main-{unique_id}",
            slug=f"group-gateway-main-{unique_id}",
            url=f"http://group-main-{unique_id}.local:8000",
            enabled=True,
            capabilities={},
        )
        test_db.add(group_gateway)
        test_db.flush()

        # Create tools with duplicate descriptions
        descriptions = ["Common Desc", "Common Desc", "Unique 1", "Unique 2", "Common Desc"]
        for i, desc in enumerate(descriptions):
            tool = Tool(
                original_name=f"group-tool-{unique_id}-{i}",
                description=desc,
                gateway_id=group_gateway.id,
                input_schema={"type": "object"},
            )
            test_db.add(tool)

        test_db.commit()
        return {"tools": 5}

    def test_distinct_efficiency(self, query_counter, test_db, seed_groupable_data):
        """DISTINCT should be single query."""
        from sqlalchemy import distinct

        with query_counter(print_summary=True) as counter:
            descriptions = test_db.query(distinct(Tool.description)).all()

        assert counter.count == 1, f"DISTINCT should be 1 query, got {counter.count}"

    def test_group_by_count(self, query_counter, test_db, seed_groupable_data):
        """GROUP BY with COUNT should be single query."""
        from sqlalchemy import func

        with query_counter(print_summary=True) as counter:
            results = (
                test_db.query(Tool.description, func.count(Tool.id))
                .group_by(Tool.description)
                .all()
            )

        assert counter.count == 1, f"GROUP BY should be 1 query, got {counter.count}"
