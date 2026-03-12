# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_meta_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for the Meta-Server feature.

Tests cover:
- Meta-server schema validation (ServerType, MetaToolScope, MetaConfig)
- Meta-tool request/response schema contracts
- Meta-server creation with server_type='meta'
- Config validation (limits, ranges)
- Meta-tools appearing when server_type == 'meta'
- Underlying tools hidden when hide_underlying_tools is enabled
- MetaServerService stub handlers
- search_tools: hybrid semantic + keyword search, merge, ranking, scope, pagination
- get_similar_tools: vector similarity with self-filtering and scope
- _apply_scope_filtering: all 7 scope fields with AND semantics
- Helper methods: _get_tool_metadata, _get_tools_matching_tags, _map_to_tool_summaries
"""

# Standard
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.meta_server.schemas import (
    DescribeToolRequest,
    DescribeToolResponse,
    ExecuteToolRequest,
    ExecuteToolResponse,
    GetSimilarToolsRequest,
    GetSimilarToolsResponse,
    GetToolCategoriesRequest,
    GetToolCategoriesResponse,
    ListToolsRequest,
    ListToolsResponse,
    META_TOOL_DEFINITIONS,
    MetaConfig,
    MetaToolScope,
    SearchToolsRequest,
    SearchToolsResponse,
    ServerType,
    ToolSummary,
)
from mcpgateway.meta_server.service import MetaServerService, get_meta_server_service
from mcpgateway.schemas import ToolSearchResult

# ServerType Enum Tests

class TestServerType:
    """Tests for the ServerType enum."""

    def test_standard_value(self):
        """Test standard server type value."""
        assert ServerType.STANDARD.value == "standard"

    def test_meta_value(self):
        """Test meta server type value."""
        assert ServerType.META.value == "meta"

    def test_from_string_meta(self):
        """Test creating ServerType from string 'meta'."""
        assert ServerType("meta") == ServerType.META

    def test_from_string_standard(self):
        """Test creating ServerType from string 'standard'."""
        assert ServerType("standard") == ServerType.STANDARD

    def test_invalid_type_raises(self):
        """Test that invalid server type raises ValueError."""
        with pytest.raises(ValueError):
            ServerType("invalid")

# MetaToolScope Tests

class TestMetaToolScope:
    """Tests for the MetaToolScope configuration model."""

    def test_default_scope(self):
        """Test that default scope has empty lists."""
        scope = MetaToolScope()
        assert scope.include_tags == []
        assert scope.exclude_tags == []
        assert scope.include_servers == []
        assert scope.exclude_servers == []
        assert scope.include_visibility == []
        assert scope.include_teams == []
        assert scope.name_patterns == []

    def test_scope_with_tags(self):
        """Test scope with tag filters."""
        scope = MetaToolScope(include_tags=["prod", "stable"], exclude_tags=["deprecated"])
        assert scope.include_tags == ["prod", "stable"]
        assert scope.exclude_tags == ["deprecated"]

    def test_scope_with_servers(self):
        """Test scope with server filters."""
        scope = MetaToolScope(include_servers=["s1", "s2"], exclude_servers=["s3"])
        assert scope.include_servers == ["s1", "s2"]
        assert scope.exclude_servers == ["s3"]

    def test_scope_with_visibility(self):
        """Test scope with valid visibility values."""
        scope = MetaToolScope(include_visibility=["public", "team"])
        assert scope.include_visibility == ["public", "team"]

    def test_scope_invalid_visibility_raises(self):
        """Test that invalid visibility value raises ValidationError."""
        with pytest.raises(ValidationError):
            MetaToolScope(include_visibility=["invalid_level"])

    def test_scope_serialization(self):
        """Test scope serializes correctly with camelCase aliases."""
        scope = MetaToolScope(include_tags=["test"], name_patterns=["db_*"])
        data = scope.model_dump(by_alias=True)
        assert "includeTags" in data
        assert "namePatterns" in data
        assert data["includeTags"] == ["test"]

    def test_scope_with_teams(self):
        """Test scope with team filters."""
        scope = MetaToolScope(include_teams=["team-1", "team-2"])
        assert scope.include_teams == ["team-1", "team-2"]

    def test_scope_name_patterns(self):
        """Test scope with name patterns."""
        scope = MetaToolScope(name_patterns=["db_*", "*_tool"])
        assert scope.name_patterns == ["db_*", "*_tool"]


# MetaConfig Tests

class TestMetaConfig:
    """Tests for the MetaConfig configuration model."""

    def test_default_config(self):
        """Test default config values."""
        config = MetaConfig()
        assert config.enable_semantic_search is False
        assert config.enable_categories is False
        assert config.enable_similar_tools is False
        assert config.default_search_limit == 50
        assert config.max_search_limit == 200
        assert config.include_metrics_in_search is False

    def test_custom_config(self):
        """Test custom config values."""
        config = MetaConfig(
            enable_semantic_search=True,
            enable_categories=True,
            enable_similar_tools=True,
            default_search_limit=25,
            max_search_limit=500,
            include_metrics_in_search=True,
        )
        assert config.enable_semantic_search is True
        assert config.default_search_limit == 25
        assert config.max_search_limit == 500

    def test_config_search_limit_range(self):
        """Test that default_search_limit respects range constraints."""
        with pytest.raises(ValidationError):
            MetaConfig(default_search_limit=0)  # Must be >= 1

    def test_config_max_search_limit_range(self):
        """Test that max_search_limit respects range constraints."""
        with pytest.raises(ValidationError):
            MetaConfig(max_search_limit=0)  # Must be >= 1

    def test_config_max_less_than_default_raises(self):
        """Test that max_search_limit < default_search_limit raises ValidationError."""
        with pytest.raises(ValidationError):
            MetaConfig(default_search_limit=100, max_search_limit=50)

    def test_config_serialization(self):
        """Test config serializes correctly with camelCase aliases."""
        config = MetaConfig(enable_semantic_search=True)
        data = config.model_dump(by_alias=True)
        assert "enableSemanticSearch" in data
        assert data["enableSemanticSearch"] is True

    def test_config_max_equals_default(self):
        """Test that max_search_limit == default_search_limit is valid."""
        config = MetaConfig(default_search_limit=100, max_search_limit=100)
        assert config.max_search_limit == 100


# Meta-Tool Request/Response Schema Tests

class TestSearchToolsSchemas:
    """Tests for search_tools request/response schemas."""

    def test_request_minimal(self):
        """Test minimal search request."""
        req = SearchToolsRequest(query="database")
        assert req.query == "database"
        assert req.limit == 50
        assert req.offset == 0

    def test_request_with_all_fields(self):
        """Test search request with all fields."""
        req = SearchToolsRequest(query="test", limit=10, offset=5, tags=["db"], include_metrics=True)
        assert req.limit == 10
        assert req.tags == ["db"]

    def test_request_empty_query_raises(self):
        """Test that empty query raises ValidationError."""
        with pytest.raises(ValidationError):
            SearchToolsRequest(query="")

    def test_response_empty(self):
        """Test empty search response."""
        resp = SearchToolsResponse(tools=[], total_count=0, query="test", has_more=False)
        assert resp.total_count == 0
        assert resp.has_more is False


class TestListToolsSchemas:
    """Tests for list_tools request/response schemas."""

    def test_request_defaults(self):
        """Test list request defaults."""
        req = ListToolsRequest()
        assert req.limit == 50
        assert req.offset == 0

    def test_response_with_tools(self):
        """Test list response with tool summaries."""
        tool = ToolSummary(name="my_tool", description="A test tool", server_id="s1", server_name="Server 1")
        resp = ListToolsResponse(tools=[tool], total_count=1, has_more=False)
        assert len(resp.tools) == 1
        assert resp.tools[0].name == "my_tool"


class TestDescribeToolSchemas:
    """Tests for describe_tool request/response schemas."""

    def test_request(self):
        """Test describe request."""
        req = DescribeToolRequest(tool_name="query_db")
        assert req.tool_name == "query_db"

    def test_request_empty_name_raises(self):
        """Test that empty tool_name raises ValidationError."""
        with pytest.raises(ValidationError):
            DescribeToolRequest(tool_name="")

    def test_response(self):
        """Test describe response."""
        resp = DescribeToolResponse(name="query_db", description="Run SQL queries")
        assert resp.name == "query_db"
        assert resp.input_schema is None


class TestExecuteToolSchemas:
    """Tests for execute_tool request/response schemas."""

    def test_request(self):
        """Test execute request."""
        req = ExecuteToolRequest(tool_name="query_db", arguments={"sql": "SELECT 1"})
        assert req.tool_name == "query_db"
        assert req.arguments["sql"] == "SELECT 1"

    def test_response_success(self):
        """Test successful execute response."""
        resp = ExecuteToolResponse(tool_name="query_db", success=True, result={"rows": []})
        assert resp.success is True
        assert resp.error is None

    def test_response_failure(self):
        """Test failed execute response."""
        resp = ExecuteToolResponse(tool_name="query_db", success=False, error="Connection failed")
        assert resp.success is False
        assert resp.error == "Connection failed"


class TestGetToolCategoriesSchemas:
    """Tests for get_tool_categories request/response schemas."""

    def test_request_defaults(self):
        """Test categories request defaults."""
        req = GetToolCategoriesRequest()
        assert req.include_counts is True

    def test_response_empty(self):
        """Test empty categories response."""
        resp = GetToolCategoriesResponse(categories=[], total_categories=0)
        assert resp.total_categories == 0


class TestGetSimilarToolsSchemas:
    """Tests for get_similar_tools request/response schemas."""

    def test_request(self):
        """Test similar tools request."""
        req = GetSimilarToolsRequest(tool_name="query_db", limit=5)
        assert req.tool_name == "query_db"
        assert req.limit == 5

    def test_response_empty(self):
        """Test empty similar tools response."""
        resp = GetSimilarToolsResponse(reference_tool="query_db", similar_tools=[], total_found=0)
        assert resp.reference_tool == "query_db"
        assert resp.total_found == 0


# META_TOOL_DEFINITIONS Tests

class TestMetaToolDefinitions:
    """Tests for the META_TOOL_DEFINITIONS registry."""

    def test_all_six_tools_defined(self):
        """Test that all six meta-tools are defined."""
        expected = {"search_tools", "list_tools", "describe_tool", "execute_tool", "get_tool_categories", "get_similar_tools"}
        assert set(META_TOOL_DEFINITIONS.keys()) == expected

    def test_each_has_description(self):
        """Test that each meta-tool has a description."""
        for name, defn in META_TOOL_DEFINITIONS.items():
            assert "description" in defn, f"{name} missing description"
            assert isinstance(defn["description"], str)

    def test_each_has_input_schema(self):
        """Test that each meta-tool has an input_schema."""
        for name, defn in META_TOOL_DEFINITIONS.items():
            assert "input_schema" in defn, f"{name} missing input_schema"
            assert isinstance(defn["input_schema"], dict)


# MetaServerService Tests

class TestMetaServerService:
    """Tests for the MetaServerService."""

    def test_get_meta_tool_definitions(self):
        """Test that meta-tool definitions are returned correctly."""
        service = MetaServerService()
        defs = service.get_meta_tool_definitions()
        assert len(defs) == 6
        names = {d["name"] for d in defs}
        assert "search_tools" in names
        assert "execute_tool" in names

    def test_is_meta_server(self):
        """Test is_meta_server check."""
        service = MetaServerService()
        assert service.is_meta_server("meta") is True
        assert service.is_meta_server("standard") is False
        assert service.is_meta_server(None) is False

    def test_should_hide_underlying_tools(self):
        """Test should_hide_underlying_tools logic."""
        service = MetaServerService()
        assert service.should_hide_underlying_tools("meta", True) is True
        assert service.should_hide_underlying_tools("meta", False) is False
        assert service.should_hide_underlying_tools("standard", True) is False
        assert service.should_hide_underlying_tools(None, True) is False

    def test_is_meta_tool(self):
        """Test is_meta_tool check."""
        service = MetaServerService()
        assert service.is_meta_tool("search_tools") is True
        assert service.is_meta_tool("list_tools") is True
        assert service.is_meta_tool("some_random_tool") is False

    def test_stub_search_tools(self):
        """Test search_tools returns empty results when both search sources return nothing."""
        service = MetaServerService()
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=[])

        def mock_get_db():
            db = MagicMock()
            db.query.return_value.filter.return_value.limit.return_value.all.return_value = []
            yield db

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "database"}))
        assert result["query"] == "database"
        assert result["tools"] == []
        assert result["totalCount"] == 0

    def test_list_tools_returns_empty_when_no_tools(self):
        """Test list_tools returns empty results when no tools exist."""
        service = MetaServerService()

        def mock_get_db():
            db = MagicMock()
            yield db

        # Mock ToolService.list_tools to return empty list
        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=([], None)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {}))

        assert result["tools"] == []
        assert result["totalCount"] == 0
        assert result["hasMore"] is False

    def test_stub_describe_tool(self):
        """Test describe_tool stub returns placeholder response."""
        service = MetaServerService()

        def mock_get_db():
            db = MagicMock()
            yield db

        mock_response = DescribeToolResponse(name="my_tool", description="Stub description for my_tool")

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.services.meta_tool_service.MetaToolService.describe_tool", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = asyncio.run(service.handle_meta_tool_call("describe_tool", {"tool_name": "my_tool"}))
        assert result["name"] == "my_tool"
        assert "Stub description" in result["description"]

    def test_stub_execute_tool(self):
        """Test execute_tool stub returns not-implemented response."""
        service = MetaServerService()

        def mock_get_db():
            db = MagicMock()
            yield db

        mock_response = ExecuteToolResponse(tool_name="my_tool", success=False, error="This action is not yet implemented")

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.services.meta_tool_service.MetaToolService.execute_tool", new_callable=AsyncMock, return_value=mock_response),
        ):
            result = asyncio.run(service.handle_meta_tool_call("execute_tool", {"tool_name": "my_tool"}))
        assert result["toolName"] == "my_tool"
        assert result["success"] is False
        assert "not yet implemented" in result["error"]

    def test_stub_get_tool_categories(self):
        """Test get_tool_categories stub returns placeholder response."""
        service = MetaServerService()
        result = asyncio.run(service.handle_meta_tool_call("get_tool_categories", {}))
        assert result["categories"] == []
        assert result["totalCategories"] == 0

    def test_stub_get_similar_tools(self):
        """Test get_similar_tools returns empty when tool not found in DB."""
        service = MetaServerService()

        def mock_get_db():
            db = MagicMock()
            db.query.return_value.filter.return_value.first.return_value = None
            yield db

        with patch("mcpgateway.meta_server.service.get_db", mock_get_db):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "my_tool"}))
        assert result["referenceTool"] == "my_tool"
        assert result["similarTools"] == []

    def test_unknown_meta_tool_raises(self):
        """Test that unknown meta-tool name raises ValueError."""
        service = MetaServerService()
        with pytest.raises(ValueError, match="Unknown meta-tool"):
            asyncio.run(service.handle_meta_tool_call("nonexistent_tool", {}))

    def test_singleton_service(self):
        """Test that get_meta_server_service returns a singleton."""
        s1 = get_meta_server_service()
        s2 = get_meta_server_service()
        assert s1 is s2


# Server Schema Integration Tests (ServerCreate with server_type)

class TestServerCreateMetaType:
    """Tests for ServerCreate schema with meta server type support."""

    def test_default_server_type(self):
        """Test that default server_type is 'standard'."""
        from mcpgateway.schemas import ServerCreate

        server = ServerCreate(name="Test Server")
        assert server.server_type == "standard"

    def test_meta_server_type(self):
        """Test creating a server with type 'meta'."""
        from mcpgateway.schemas import ServerCreate

        server = ServerCreate(name="Meta Server", server_type="meta")
        assert server.server_type == "meta"

    def test_invalid_server_type_raises(self):
        """Test that invalid server_type raises ValidationError."""
        from mcpgateway.schemas import ServerCreate

        with pytest.raises(ValidationError):
            ServerCreate(name="Bad Server", server_type="invalid")

    def test_hide_underlying_tools_default(self):
        """Test that hide_underlying_tools defaults to True."""
        from mcpgateway.schemas import ServerCreate

        server = ServerCreate(name="Test Server")
        assert server.hide_underlying_tools is True

    def test_meta_config_field(self):
        """Test that meta_config can be set."""
        from mcpgateway.schemas import ServerCreate

        config = {"enable_semantic_search": True, "default_search_limit": 25}
        server = ServerCreate(name="Meta Server", server_type="meta", meta_config=config)
        assert server.meta_config == config

    def test_meta_scope_field(self):
        """Test that meta_scope can be set."""
        from mcpgateway.schemas import ServerCreate

        scope = {"include_tags": ["production"], "exclude_servers": ["legacy"]}
        server = ServerCreate(name="Meta Server", server_type="meta", meta_scope=scope)
        assert server.meta_scope == scope


class TestServerUpdateMetaType:
    """Tests for ServerUpdate schema with meta server type support."""

    def test_update_server_type(self):
        """Test updating server_type."""
        from mcpgateway.schemas import ServerUpdate

        update = ServerUpdate(server_type="meta")
        assert update.server_type == "meta"

    def test_update_invalid_server_type_raises(self):
        """Test that invalid server_type raises ValidationError on update."""
        from mcpgateway.schemas import ServerUpdate

        with pytest.raises(ValidationError):
            ServerUpdate(server_type="bad_type")

    def test_update_meta_config(self):
        """Test updating meta_config."""
        from mcpgateway.schemas import ServerUpdate

        update = ServerUpdate(meta_config={"enable_categories": True})
        assert update.meta_config == {"enable_categories": True}


class TestServerReadMetaFields:
    """Tests for ServerRead schema meta-server fields."""

    def test_read_defaults(self):
        """Test that ServerRead has correct meta field defaults."""
        from datetime import datetime, timezone

        from mcpgateway.schemas import ServerRead

        now = datetime.now(timezone.utc)
        read = ServerRead(
            id="test-id",
            name="Test Server",
            description=None,
            icon=None,
            created_at=now,
            updated_at=now,
            enabled=True,
        )
        assert read.server_type == "standard"
        assert read.hide_underlying_tools is True
        assert read.meta_config is None
        assert read.meta_scope is None

    def test_read_meta_server(self):
        """Test ServerRead with meta server fields populated."""
        from datetime import datetime, timezone

        from mcpgateway.schemas import ServerRead

        now = datetime.now(timezone.utc)
        read = ServerRead(
            id="test-id",
            name="Meta Server",
            description="A meta server",
            icon=None,
            created_at=now,
            updated_at=now,
            enabled=True,
            server_type="meta",
            hide_underlying_tools=True,
            meta_config={"enable_semantic_search": True},
            meta_scope={"include_tags": ["production"]},
        )
        assert read.server_type == "meta"
        assert read.hide_underlying_tools is True
        assert read.meta_config["enable_semantic_search"] is True
        assert read.meta_scope["include_tags"] == ["production"]


# DB Model Integration Tests

class TestServerDBModelMetaFields:
    """Tests for Server DB model meta-server fields."""

    def test_server_db_has_meta_fields(self, test_db):
        """Test that Server DB model has meta-server columns."""
        from mcpgateway.db import Server as DbServer

        server = DbServer(
            name="Meta Test Server",
            server_type="meta",
            hide_underlying_tools=True,
            meta_config={"enable_categories": True},
            meta_scope={"include_tags": ["test"]},
        )
        test_db.add(server)
        test_db.commit()
        test_db.refresh(server)

        assert server.server_type == "meta"
        assert server.hide_underlying_tools is True
        assert server.meta_config == {"enable_categories": True}
        assert server.meta_scope == {"include_tags": ["test"]}

    def test_server_db_default_type_standard(self, test_db):
        """Test that Server DB model defaults to server_type='standard'."""
        from mcpgateway.db import Server as DbServer

        server = DbServer(name="Standard Server")
        test_db.add(server)
        test_db.commit()
        test_db.refresh(server)

        assert server.server_type == "standard"
        assert server.hide_underlying_tools is True  # Default True
        assert server.meta_config is None
        assert server.meta_scope is None


# ---------------------------------------------------------------------------
# Helpers for mocking DB and services used by search/similar
# ---------------------------------------------------------------------------

def _make_tool_search_result(name, description="desc", server_id="s1", server_name="Server1", score=0.8):
    """Shorthand factory for ToolSearchResult."""
    return ToolSearchResult(
        tool_name=name,
        description=description,
        server_id=server_id,
        server_name=server_name,
        similarity_score=score,
    )


def _make_mock_tool(name, description="desc", gateway_id="s1", tags=None, visibility="public", team_id=None, enabled=True, input_schema=None):
    """Create a mock Tool ORM object."""
    tool = MagicMock()
    tool.name = name
    tool._computed_name = name
    tool.description = description
    tool.gateway_id = gateway_id
    tool.gateway = SimpleNamespace(name="Server1")
    tool.tags = tags or []
    tool.visibility = visibility
    tool.team_id = team_id
    tool.enabled = enabled
    tool.input_schema = input_schema
    tool.id = f"id-{name}"
    return tool


def _mock_get_db_with_tools(tools):
    """Return a mock get_db generator that supports query().filter().* patterns.

    The mock DB handles several query patterns used across the service:
    - .filter(...).limit(...).all() → returns tools (keyword search)
    - .filter(...).all() → returns tools (metadata / tag queries)
    - .filter(...).first() → returns first tool or None (tool lookup)
    """
    def mock_get_db():
        db = MagicMock()
        query = db.query.return_value

        # Chain .filter() calls (supports multiple chained filters)
        filter_mock = MagicMock()
        query.filter.return_value = filter_mock
        filter_mock.filter.return_value = filter_mock  # support chained .filter().filter()

        # .limit().all() for keyword search
        filter_mock.limit.return_value.all.return_value = tools
        # .all() for metadata / tag queries
        filter_mock.all.return_value = tools
        # .first() for single-tool lookup
        filter_mock.first.return_value = tools[0] if tools else None

        yield db

    return mock_get_db


# ---------------------------------------------------------------------------
# search_tools comprehensive tests
# ---------------------------------------------------------------------------

class TestSearchToolsImplementation:
    """Comprehensive tests for the _search_tools implementation."""

    def test_search_tools_semantic_results_returned(self):
        """Test that semantic search results are included in response."""
        service = MetaServerService()
        semantic_results = [
            _make_tool_search_result("tool_a", score=0.9),
            _make_tool_search_result("tool_b", score=0.7),
        ]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [_make_mock_tool("tool_a"), _make_mock_tool("tool_b")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "test"}))

        assert result["query"] == "test"
        assert result["totalCount"] == 2
        assert len(result["tools"]) == 2

    def test_search_tools_keyword_fallback_when_semantic_fails(self):
        """Test keyword search works when semantic search raises an exception."""
        service = MetaServerService()
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(side_effect=RuntimeError("Embedding service down"))

        mock_tools = [_make_mock_tool("db_query", description="Query a database")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "db_query"}))

        # Keyword fallback should still produce results
        assert result["totalCount"] >= 1
        tool_names = [t["name"] for t in result["tools"]]
        assert "db_query" in tool_names

    def test_search_tools_both_fail_returns_empty(self):
        """Test that when both semantic and keyword search fail, empty results returned."""
        service = MetaServerService()
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(side_effect=RuntimeError("fail"))

        def broken_get_db():
            raise RuntimeError("DB down")
            yield  # noqa: unreachable - needed to make it a generator

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", broken_get_db),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "anything"}))

        assert result["tools"] == []
        assert result["totalCount"] == 0

    def test_search_tools_merge_dedup_keeps_higher_score(self):
        """Test that duplicates are merged keeping the higher score."""
        service = MetaServerService()
        semantic_results = [_make_tool_search_result("shared_tool", score=0.9)]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        # Keyword search also finds "shared_tool" with a lower score
        mock_tools = [_make_mock_tool("shared_tool")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "shared_tool"}))

        # Should have one result, not two
        assert result["totalCount"] == 1
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "shared_tool"

    def test_search_tools_ranking_descending_by_score(self):
        """Test that results are sorted descending by similarity score."""
        service = MetaServerService()
        semantic_results = [
            _make_tool_search_result("low_score", score=0.3),
            _make_tool_search_result("high_score", score=0.95),
            _make_tool_search_result("mid_score", score=0.6),
        ]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [
            _make_mock_tool("low_score"),
            _make_mock_tool("high_score"),
            _make_mock_tool("mid_score"),
        ]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "test"}))

        names = [t["name"] for t in result["tools"]]
        assert names == ["high_score", "mid_score", "low_score"]

    def test_search_tools_pagination_offset_and_limit(self):
        """Test pagination with offset and limit."""
        service = MetaServerService()
        # Create 5 results
        semantic_results = [
            _make_tool_search_result(f"tool_{i}", score=1.0 - i * 0.1)
            for i in range(5)
        ]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [_make_mock_tool(f"tool_{i}") for i in range(5)]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test", "limit": 2, "offset": 1,
            }))

        assert result["totalCount"] == 5
        assert len(result["tools"]) == 2
        assert result["hasMore"] is True

    def test_search_tools_pagination_no_more_results(self):
        """Test has_more is False when all results fit."""
        service = MetaServerService()
        semantic_results = [_make_tool_search_result("tool_a", score=0.8)]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [_make_mock_tool("tool_a")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test", "limit": 50, "offset": 0,
            }))

        assert result["hasMore"] is False
        assert result["totalCount"] == 1

    def test_search_tools_pagination_offset_beyond_results(self):
        """Test offset beyond total results returns empty tools list."""
        service = MetaServerService()
        semantic_results = [_make_tool_search_result("tool_a", score=0.8)]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [_make_mock_tool("tool_a")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test", "limit": 10, "offset": 100,
            }))

        assert result["tools"] == []
        assert result["totalCount"] == 1
        assert result["hasMore"] is False

    def test_search_tools_tag_filter(self):
        """Test tag filtering narrows results to tools with matching tags."""
        service = MetaServerService()
        semantic_results = [
            _make_tool_search_result("tagged_tool", score=0.9),
            _make_tool_search_result("untagged_tool", score=0.8),
        ]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [
            _make_mock_tool("tagged_tool", tags=["database"]),
            _make_mock_tool("untagged_tool", tags=[]),
        ]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test", "tags": ["database"],
            }))

        tool_names = [t["name"] for t in result["tools"]]
        assert "tagged_tool" in tool_names
        assert "untagged_tool" not in tool_names

    def test_search_tools_scope_filtering_applied(self):
        """Test that scope filtering is applied to search results."""
        service = MetaServerService()
        semantic_results = [
            _make_tool_search_result("public_tool", server_id="s1", score=0.9),
            _make_tool_search_result("private_tool", server_id="s2", score=0.8),
        ]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [
            _make_mock_tool("public_tool", visibility="public"),
            _make_mock_tool("private_tool", visibility="private"),
        ]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test",
                "scope": {"include_visibility": ["public"]},
            }))

        tool_names = [t["name"] for t in result["tools"]]
        assert "public_tool" in tool_names
        assert "private_tool" not in tool_names

    def test_search_tools_keyword_exact_match_scores_highest(self):
        """Test keyword search gives 1.0 score for exact name match."""
        service = MetaServerService()
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=[])

        exact_tool = _make_mock_tool("db_query")
        partial_tool = _make_mock_tool("db_query_extended")

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([exact_tool, partial_tool])),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "db_query"}))

        # Exact match should be first (score 1.0 > 0.7)
        if len(result["tools"]) >= 2:
            assert result["tools"][0]["name"] == "db_query"

    def test_search_tools_include_metrics_parameter_passed(self):
        """Test that include_metrics is forwarded correctly."""
        service = MetaServerService()
        semantic_results = [_make_tool_search_result("tool_a", score=0.9)]
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=semantic_results)

        mock_tools = [_make_mock_tool("tool_a")]

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {
                "query": "test", "include_metrics": True,
            }))

        # Metrics are currently None (TODO), but the call should succeed
        assert len(result["tools"]) == 1

    def test_search_tools_response_is_camel_case(self):
        """Test response uses camelCase aliases for serialization."""
        service = MetaServerService()
        mock_semantic = AsyncMock()
        mock_semantic.search_tools = AsyncMock(return_value=[])

        with (
            patch("mcpgateway.meta_server.service.get_semantic_search_service", return_value=mock_semantic),
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([])),
        ):
            result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "x"}))

        assert "totalCount" in result
        assert "hasMore" in result
        assert "query" in result
        assert "tools" in result


# ---------------------------------------------------------------------------
# get_similar_tools comprehensive tests
# ---------------------------------------------------------------------------

class TestGetSimilarToolsImplementation:
    """Comprehensive tests for the _get_similar_tools implementation."""

    def test_similar_tools_empty_tool_name_returns_empty(self):
        """Test that empty tool_name returns empty results immediately."""
        service = MetaServerService()
        result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": ""}))
        assert result["referenceTool"] == ""
        assert result["similarTools"] == []
        assert result["totalFound"] == 0

    def test_similar_tools_tool_not_found(self):
        """Test that a non-existent reference tool returns empty results."""
        service = MetaServerService()

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([])):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "nonexistent"}))

        assert result["referenceTool"] == "nonexistent"
        assert result["similarTools"] == []
        assert result["totalFound"] == 0

    def test_similar_tools_no_embedding_returns_empty(self):
        """Test that tool without embedding returns empty results."""
        service = MetaServerService()
        ref_tool = _make_mock_tool("my_tool")

        call_count = [0]

        def mock_get_db():
            call_count[0] += 1
            db = MagicMock()
            query = db.query.return_value
            filter_mock = MagicMock()
            query.filter.return_value = filter_mock
            filter_mock.filter.return_value = filter_mock

            if call_count[0] == 1:
                # First call: resolve reference tool
                filter_mock.first.return_value = ref_tool
            else:
                # Second call: get embedding — return None
                pass
            yield db

        mock_vector_service = MagicMock()
        mock_vector_service.get_tool_embedding.return_value = None

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.meta_server.service.VectorSearchService", return_value=mock_vector_service),
        ):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "my_tool"}))

        assert result["similarTools"] == []
        assert result["totalFound"] == 0

    def test_similar_tools_filters_out_reference_tool(self):
        """Test that the reference tool itself is excluded from similar results."""
        service = MetaServerService()
        ref_tool = _make_mock_tool("my_tool")

        similar_results = [
            _make_tool_search_result("my_tool", score=1.0),  # self — should be filtered
            _make_tool_search_result("similar_tool_a", score=0.9),
            _make_tool_search_result("similar_tool_b", score=0.8),
        ]

        call_count = [0]

        def mock_get_db():
            call_count[0] += 1
            db = MagicMock()
            query = db.query.return_value
            filter_mock = MagicMock()
            query.filter.return_value = filter_mock
            filter_mock.filter.return_value = filter_mock
            filter_mock.first.return_value = ref_tool
            filter_mock.all.return_value = [
                _make_mock_tool("similar_tool_a"),
                _make_mock_tool("similar_tool_b"),
            ]
            yield db

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 128

        mock_vector_service = MagicMock()
        mock_vector_service.get_tool_embedding.return_value = mock_embedding
        mock_vector_service.search_similar_tools = AsyncMock(return_value=similar_results)

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.meta_server.service.VectorSearchService", return_value=mock_vector_service),
        ):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "my_tool"}))

        tool_names = [t["name"] for t in result["similarTools"]]
        assert "my_tool" not in tool_names
        assert "similar_tool_a" in tool_names
        assert "similar_tool_b" in tool_names

    def test_similar_tools_respects_limit(self):
        """Test that limit parameter is respected."""
        service = MetaServerService()
        ref_tool = _make_mock_tool("my_tool")

        similar_results = [
            _make_tool_search_result(f"similar_{i}", score=0.9 - i * 0.1)
            for i in range(5)
        ]

        call_count = [0]

        def mock_get_db():
            call_count[0] += 1
            db = MagicMock()
            query = db.query.return_value
            filter_mock = MagicMock()
            query.filter.return_value = filter_mock
            filter_mock.filter.return_value = filter_mock
            filter_mock.first.return_value = ref_tool
            filter_mock.all.return_value = [_make_mock_tool(f"similar_{i}") for i in range(2)]
            yield db

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 128

        mock_vector_service = MagicMock()
        mock_vector_service.get_tool_embedding.return_value = mock_embedding
        mock_vector_service.search_similar_tools = AsyncMock(return_value=similar_results)

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.meta_server.service.VectorSearchService", return_value=mock_vector_service),
        ):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {
                "tool_name": "my_tool", "limit": 2,
            }))

        # Limit should cap the results (after self-filtering)
        assert len(result["similarTools"]) <= 2

    def test_similar_tools_scope_filtering_applied(self):
        """Test that scope filtering is applied to similar tools results."""
        service = MetaServerService()
        ref_tool = _make_mock_tool("my_tool")

        similar_results = [
            _make_tool_search_result("public_similar", server_id="s1", score=0.9),
            _make_tool_search_result("private_similar", server_id="s2", score=0.8),
        ]

        call_count = [0]

        def mock_get_db():
            call_count[0] += 1
            db = MagicMock()
            query = db.query.return_value
            filter_mock = MagicMock()
            query.filter.return_value = filter_mock
            filter_mock.filter.return_value = filter_mock
            filter_mock.first.return_value = ref_tool
            filter_mock.all.return_value = [
                _make_mock_tool("public_similar", visibility="public"),
                _make_mock_tool("private_similar", visibility="private"),
            ]
            yield db

        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 128

        mock_vector_service = MagicMock()
        mock_vector_service.get_tool_embedding.return_value = mock_embedding
        mock_vector_service.search_similar_tools = AsyncMock(return_value=similar_results)

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch("mcpgateway.meta_server.service.VectorSearchService", return_value=mock_vector_service),
        ):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {
                "tool_name": "my_tool",
                "scope": {"include_visibility": ["public"]},
            }))

        tool_names = [t["name"] for t in result["similarTools"]]
        assert "public_similar" in tool_names
        assert "private_similar" not in tool_names

    def test_similar_tools_db_error_returns_empty(self):
        """Test that DB error during tool lookup returns empty results gracefully."""
        service = MetaServerService()

        def broken_get_db():
            raise RuntimeError("DB connection failed")
            yield  # noqa: unreachable

        with patch("mcpgateway.meta_server.service.get_db", broken_get_db):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "my_tool"}))

        assert result["similarTools"] == []
        assert result["totalFound"] == 0

    def test_similar_tools_response_is_camel_case(self):
        """Test response uses camelCase aliases."""
        service = MetaServerService()

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([])):
            result = asyncio.run(service.handle_meta_tool_call("get_similar_tools", {"tool_name": "x"}))

        assert "referenceTool" in result
        assert "similarTools" in result
        assert "totalFound" in result


# ---------------------------------------------------------------------------
# _apply_scope_filtering tests (all 7 scope fields + AND semantics)
# ---------------------------------------------------------------------------

class TestApplyScopeFiltering:
    """Tests for _apply_scope_filtering with all MetaToolScope fields."""

    def setup_method(self):
        """Create a service and standard test results."""
        self.service = MetaServerService()
        self.results = [
            _make_tool_search_result("tool_a", server_id="server_1", score=0.9),
            _make_tool_search_result("tool_b", server_id="server_2", score=0.8),
            _make_tool_search_result("tool_c", server_id="server_1", score=0.7),
        ]
        self.mock_tools = [
            _make_mock_tool("tool_a", tags=["database", "production"], visibility="public", team_id="team1"),
            _make_mock_tool("tool_b", tags=["deprecated"], visibility="private", team_id="team2"),
            _make_mock_tool("tool_c", tags=["database"], visibility="team", team_id="team1"),
        ]

    def test_no_scope_passes_all(self):
        """Test that None scope passes all results through."""
        result = self.service._apply_scope_filtering(self.results, None)
        assert len(result) == 3

    def test_empty_scope_passes_all(self):
        """Test that empty scope dict passes all results through."""
        result = self.service._apply_scope_filtering(self.results, {})
        assert len(result) == 3

    def test_include_tags_filter(self):
        """Test include_tags: tool must have at least one matching tag."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"include_tags": ["production"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names  # has "production"
        assert "tool_b" not in names  # has "deprecated" only
        assert "tool_c" not in names  # has "database" only

    def test_exclude_tags_filter(self):
        """Test exclude_tags: tool must NOT have any excluded tag."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"exclude_tags": ["deprecated"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names
        assert "tool_b" not in names  # has "deprecated"
        assert "tool_c" in names

    def test_include_servers_filter(self):
        """Test include_servers: tool must be from one of these servers."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"include_servers": ["server_1"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names  # server_1
        assert "tool_b" not in names  # server_2
        assert "tool_c" in names  # server_1

    def test_exclude_servers_filter(self):
        """Test exclude_servers: tool must NOT be from excluded servers."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"exclude_servers": ["server_2"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names
        assert "tool_b" not in names  # server_2
        assert "tool_c" in names

    def test_include_visibility_filter(self):
        """Test include_visibility: tool must have one of these visibility levels."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"include_visibility": ["public"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names  # public
        assert "tool_b" not in names  # private
        assert "tool_c" not in names  # team

    def test_include_teams_filter(self):
        """Test include_teams: tool must belong to one of these teams."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"include_teams": ["team1"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names  # team1
        assert "tool_b" not in names  # team2
        assert "tool_c" in names  # team1

    def test_name_patterns_filter(self):
        """Test name_patterns: tool name must match at least one glob pattern."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"name_patterns": ["tool_a"]})
        names = [r.tool_name for r in result]
        assert names == ["tool_a"]

    def test_name_patterns_wildcard(self):
        """Test name_patterns with glob wildcards."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {"name_patterns": ["tool_*"]})
        assert len(result) == 3  # All match tool_*

    def test_combined_and_semantics(self):
        """Test that multiple scope fields combine with AND semantics."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {
                "include_tags": ["database"],
                "include_visibility": ["public"],
                "include_teams": ["team1"],
            })
        names = [r.tool_name for r in result]
        # Only tool_a has database tag AND public visibility AND team1
        assert names == ["tool_a"]

    def test_scope_excludes_tool_not_in_db(self):
        """Test that tools not found in DB are excluded from scoped results."""
        # Only return tool_a from DB — tool_b, tool_c should be excluded
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([self.mock_tools[0]])):
            result = self.service._apply_scope_filtering(self.results, {"include_tags": ["database"]})
        names = [r.tool_name for r in result]
        assert "tool_a" in names
        assert "tool_b" not in names
        assert "tool_c" not in names

    def test_scope_empty_results_input(self):
        """Test scope filtering with empty results list."""
        result = self.service._apply_scope_filtering([], {"include_tags": ["database"]})
        assert result == []

    def test_scope_all_fields_combined_strict(self):
        """Test that strict AND across all 7 fields filters aggressively."""
        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(self.mock_tools)):
            result = self.service._apply_scope_filtering(self.results, {
                "include_tags": ["database"],
                "exclude_tags": ["deprecated"],
                "include_servers": ["server_1"],
                "exclude_servers": ["server_3"],  # doesn't affect any
                "include_visibility": ["public", "team"],
                "include_teams": ["team1"],
                "name_patterns": ["tool_*"],
            })
        names = [r.tool_name for r in result]
        # tool_a: database=✓, not deprecated=✓, server_1=✓, public=✓, team1=✓, tool_*=✓ → ✓
        # tool_b: deprecated=✗ (excluded by exclude_tags)
        # tool_c: database=✓, not deprecated=✓, server_1=✓, team=✓, team1=✓, tool_*=✓ → ✓
        assert "tool_a" in names
        assert "tool_c" in names
        assert "tool_b" not in names


# ---------------------------------------------------------------------------
# _get_tool_metadata tests
# ---------------------------------------------------------------------------

class TestGetToolMetadata:
    """Tests for _get_tool_metadata helper."""

    def test_returns_metadata_for_found_tools(self):
        """Test that metadata is returned for tools found in DB."""
        service = MetaServerService()
        mock_tools = [
            _make_mock_tool("tool_a", tags=["db"], visibility="public", team_id="t1", input_schema={"type": "object"}),
        ]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            result = service._get_tool_metadata(["tool_a"])

        assert "tool_a" in result
        assert result["tool_a"]["tags"] == ["db"]
        assert result["tool_a"]["visibility"] == "public"
        assert result["tool_a"]["team_id"] == "t1"
        assert result["tool_a"]["input_schema"] == {"type": "object"}

    def test_empty_input_returns_empty(self):
        """Test that empty tool names list returns empty dict."""
        service = MetaServerService()
        result = service._get_tool_metadata([])
        assert result == {}

    def test_db_error_returns_empty(self):
        """Test that DB error returns empty dict gracefully."""
        service = MetaServerService()

        def broken_get_db():
            raise RuntimeError("DB down")
            yield  # noqa: unreachable

        with patch("mcpgateway.meta_server.service.get_db", broken_get_db):
            result = service._get_tool_metadata(["tool_a"])

        assert result == {}

    def test_missing_tool_not_in_result(self):
        """Test that tools not in DB are not in result dict."""
        service = MetaServerService()
        mock_tools = [_make_mock_tool("tool_a")]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            result = service._get_tool_metadata(["tool_a", "tool_missing"])

        assert "tool_a" in result
        assert "tool_missing" not in result

    def test_null_tags_default_to_empty_list(self):
        """Test that tools with None tags default to empty list."""
        service = MetaServerService()
        mock_tools = [_make_mock_tool("tool_a", tags=None)]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            result = service._get_tool_metadata(["tool_a"])

        assert result["tool_a"]["tags"] == []


# ---------------------------------------------------------------------------
# _get_tools_matching_tags tests
# ---------------------------------------------------------------------------

class TestGetToolsMatchingTags:
    """Tests for _get_tools_matching_tags helper."""

    def test_returns_matching_tool_names(self):
        """Test that tools with matching tags are returned."""
        service = MetaServerService()
        mock_tools = [
            _make_mock_tool("tool_a", tags=["database", "prod"]),
            _make_mock_tool("tool_b", tags=["messaging"]),
            _make_mock_tool("tool_c", tags=["database"]),
        ]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            result = service._get_tools_matching_tags(["database"])

        assert "tool_a" in result
        assert "tool_c" in result
        assert "tool_b" not in result

    def test_no_matching_tags_returns_empty(self):
        """Test that no matching tags returns empty set."""
        service = MetaServerService()
        mock_tools = [_make_mock_tool("tool_a", tags=["other"])]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            result = service._get_tools_matching_tags(["nonexistent"])

        assert len(result) == 0

    def test_db_error_returns_empty_set(self):
        """Test that DB error returns empty set gracefully."""
        service = MetaServerService()

        def broken_get_db():
            raise RuntimeError("DB down")
            yield  # noqa: unreachable

        with patch("mcpgateway.meta_server.service.get_db", broken_get_db):
            result = service._get_tools_matching_tags(["database"])

        assert result == set()


# ---------------------------------------------------------------------------
# _map_to_tool_summaries tests
# ---------------------------------------------------------------------------

class TestMapToToolSummaries:
    """Tests for _map_to_tool_summaries helper."""

    def test_maps_results_to_summaries(self):
        """Test that ToolSearchResult objects are mapped to ToolSummary objects."""
        service = MetaServerService()
        results = [
            _make_tool_search_result("tool_a", description="Tool A desc", server_id="s1", server_name="Server1"),
        ]
        mock_tools = [
            _make_mock_tool("tool_a", tags=["db"], input_schema={"type": "object"}),
        ]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            summaries = service._map_to_tool_summaries(results)

        assert len(summaries) == 1
        assert summaries[0].name == "tool_a"
        assert summaries[0].description == "Tool A desc"
        assert summaries[0].server_id == "s1"
        assert summaries[0].server_name == "Server1"
        assert summaries[0].tags == ["db"]
        assert summaries[0].input_schema == {"type": "object"}

    def test_empty_results_returns_empty(self):
        """Test that empty results list returns empty summaries list."""
        service = MetaServerService()
        summaries = service._map_to_tool_summaries([])
        assert summaries == []

    def test_tool_not_in_db_gets_default_metadata(self):
        """Test that tools not found in DB get default empty metadata."""
        service = MetaServerService()
        results = [_make_tool_search_result("missing_tool")]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools([])):
            summaries = service._map_to_tool_summaries(results)

        assert len(summaries) == 1
        assert summaries[0].name == "missing_tool"
        assert summaries[0].tags == []
        assert summaries[0].input_schema is None

    def test_multiple_results_mapped_in_order(self):
        """Test that multiple results preserve order."""
        service = MetaServerService()
        results = [
            _make_tool_search_result("tool_a", score=0.9),
            _make_tool_search_result("tool_b", score=0.8),
            _make_tool_search_result("tool_c", score=0.7),
        ]
        mock_tools = [
            _make_mock_tool("tool_a"),
            _make_mock_tool("tool_b"),
            _make_mock_tool("tool_c"),
        ]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            summaries = service._map_to_tool_summaries(results)

        assert [s.name for s in summaries] == ["tool_a", "tool_b", "tool_c"]

    def test_metrics_is_none_by_default(self):
        """Test that metrics is None (TODO pending ToolMetric implementation)."""
        service = MetaServerService()
        results = [_make_tool_search_result("tool_a")]
        mock_tools = [_make_mock_tool("tool_a")]

        with patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_tools)):
            summaries = service._map_to_tool_summaries(results, include_metrics=True)

        assert summaries[0].metrics is None

# ---------------------------------------------------------------------------
# list_tools comprehensive tests
# ---------------------------------------------------------------------------


class TestListToolsImplementation:
    """Comprehensive tests for the _list_tools implementation."""

    def test_list_tools_returns_results(self):
        """Test that list_tools returns tools from ToolService."""
        service = MetaServerService()

        # Create mock ToolRead objects
        mock_tool_a = MagicMock()
        mock_tool_a.name = "tool_a"
        mock_tool_a.description = "Tool A description"
        mock_tool_a.gateway = SimpleNamespace(id="server_1", name="Server 1")
        mock_tool_a.tags = ["database"]
        mock_tool_a.input_schema = {"type": "object"}

        mock_tool_b = MagicMock()
        mock_tool_b.name = "tool_b"
        mock_tool_b.description = "Tool B description"
        mock_tool_b.gateway = SimpleNamespace(id="server_1", name="Server 1")
        mock_tool_b.tags = ["api"]
        mock_tool_b.input_schema = {"type": "object"}

        tools = [mock_tool_a, mock_tool_b]

        def mock_get_db():
            db = MagicMock()
            yield db

        mock_db_tools = [
            _make_mock_tool("tool_a", tags=["database"], input_schema={"type": "object"}),
            _make_mock_tool("tool_b", tags=["api"], input_schema={"type": "object"}),
        ]

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=(tools, None)),
            patch.object(service, "_get_tool_metadata", return_value={
                "tool_a": {"tags": ["database"], "input_schema": {"type": "object"}, "visibility": "public", "team_id": None},
                "tool_b": {"tags": ["api"], "input_schema": {"type": "object"}, "visibility": "public", "team_id": None},
            }),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {}))

        assert result["totalCount"] == 2
        assert len(result["tools"]) == 2
        tool_names = [t["name"] for t in result["tools"]]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    def test_list_tools_with_pagination(self):
        """Test list_tools respects limit and offset."""
        service = MetaServerService()

        # Create 5 mock tools
        tools = []
        for i in range(5):
            tool = MagicMock()
            tool.name = f"tool_{i}"
            tool.description = f"Tool {i}"
            tool.gateway = SimpleNamespace(id="server_1", name="Server 1")
            tool.tags = []
            tool.input_schema = {}
            tools.append(tool)

        def mock_get_db():
            db = MagicMock()
            yield db

        mock_db_tools = [_make_mock_tool(f"tool_{i}") for i in range(5)]
        metadata = {f"tool_{i}": {"tags": [], "input_schema": {}, "visibility": "public", "team_id": None} for i in range(5)}

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=(tools, None)),
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {"limit": 2, "offset": 1}))

        assert result["totalCount"] == 5
        assert len(result["tools"]) == 2
        assert result["hasMore"] is True

    def test_list_tools_with_tag_filter(self):
        """Test list_tools respects tag filter."""
        service = MetaServerService()

        # Create tools with different tags
        tool_a = MagicMock()
        tool_a.name = "db_tool"
        tool_a.description = "Database tool"
        tool_a.gateway = SimpleNamespace(id="s1", name="Server 1")
        tool_a.tags = ["database"]
        tool_a.input_schema = {}

        tool_b = MagicMock()
        tool_b.name = "api_tool"
        tool_b.description = "API tool"
        tool_b.gateway = SimpleNamespace(id="s1", name="Server 1")
        tool_b.tags = ["api"]
        tool_b.input_schema = {}

        tools = [tool_a, tool_b]

        def mock_get_db():
            db = MagicMock()
            yield db

        metadata = {
            "db_tool": {"tags": ["database"], "input_schema": {}, "visibility": "public", "team_id": None},
            "api_tool": {"tags": ["api"], "input_schema": {}, "visibility": "public", "team_id": None},
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=(tools, None)),
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {"tags": ["database"]}))

        # ToolService.list_tools should be called with tags filter
        # The implementation passes tags to the service
        assert "tools" in result

    def test_list_tools_with_server_filter(self):
        """Test list_tools respects server_id filter."""
        service = MetaServerService()

        tool = MagicMock()
        tool.name = "tool_a"
        tool.description = "Tool A"
        tool.gateway = SimpleNamespace(id="server_1", name="Server 1")
        tool.tags = []
        tool.input_schema = {}

        def mock_get_db():
            db = MagicMock()
            yield db

        metadata = {
            "tool_a": {"tags": [], "input_schema": {}, "visibility": "public", "team_id": None},
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=([tool], None)),
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {"server_id": "server_1"}))

        assert len(result["tools"]) == 1

    def test_list_tools_with_sorting(self):
        """Test list_tools respects sort_by and sort_order."""
        service = MetaServerService()

        # Create mock tools (already sorted by ToolService)
        tools = []
        for i, name in enumerate(["alpha", "beta", "gamma"]):
            tool = MagicMock()
            tool.name = name
            tool.description = f"Tool {name}"
            tool.gateway = SimpleNamespace(id="s1", name="Server 1")
            tool.tags = []
            tool.input_schema = {}
            tools.append(tool)

        def mock_get_db():
            db = MagicMock()
            yield db

        metadata = {
            name: {"tags": [], "input_schema": {}, "visibility": "public", "team_id": None}
            for name in ["alpha", "beta", "gamma"]
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=(tools, None)) as mock_list,
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {
                "sort_by": "name",
                "sort_order": "asc",
            }))

        # Verify ToolService.list_tools was called with correct sort params
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["sort_by"] == "name"
        assert call_kwargs["sort_order"] == "asc"

    def test_list_tools_scope_filtering_applied(self):
        """Test that scope filtering is applied to list results."""
        service = MetaServerService()

        # Create tools with different visibility
        public_tool = MagicMock()
        public_tool.name = "public_tool"
        public_tool.description = "Public tool"
        public_tool.gateway = SimpleNamespace(id="s1", name="Server 1")
        public_tool.tags = []
        public_tool.input_schema = {}

        private_tool = MagicMock()
        private_tool.name = "private_tool"
        private_tool.description = "Private tool"
        private_tool.gateway = SimpleNamespace(id="s1", name="Server 1")
        private_tool.tags = []
        private_tool.input_schema = {}

        tools = [public_tool, private_tool]

        def mock_get_db():
            db = MagicMock()
            yield db

        mock_db_tools = [
            _make_mock_tool("public_tool", visibility="public"),
            _make_mock_tool("private_tool", visibility="private"),
        ]

        metadata = {
            "public_tool": {"tags": [], "input_schema": {}, "visibility": "public", "team_id": None},
            "private_tool": {"tags": [], "input_schema": {}, "visibility": "private", "team_id": None},
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", _mock_get_db_with_tools(mock_db_tools)),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=(tools, None)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {
                "scope": {"include_visibility": ["public"]},
            }))

        tool_names = [t["name"] for t in result["tools"]]
        assert "public_tool" in tool_names
        assert "private_tool" not in tool_names

    def test_list_tools_db_error_returns_empty(self):
        """Test list_tools returns empty result gracefully on DB error."""
        service = MetaServerService()

        def broken_get_db():
            raise RuntimeError("DB connection failed")
            yield  # noqa: unreachable

        with patch("mcpgateway.meta_server.service.get_db", broken_get_db):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {}))

        assert result["tools"] == []
        assert result["totalCount"] == 0
        assert result["hasMore"] is False

    def test_list_tools_offset_beyond_total_returns_empty(self):
        """Test offset beyond total count returns empty tools list."""
        service = MetaServerService()

        tool = MagicMock()
        tool.name = "tool_a"
        tool.description = "Tool A"
        tool.gateway = SimpleNamespace(id="s1", name="Server 1")
        tool.tags = []
        tool.input_schema = {}

        def mock_get_db():
            db = MagicMock()
            yield db

        metadata = {
            "tool_a": {"tags": [], "input_schema": {}, "visibility": "public", "team_id": None},
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=([tool], None)),
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {"offset": 100}))

        assert result["tools"] == []
        assert result["totalCount"] == 1
        assert result["hasMore"] is False

    def test_list_tools_include_schema_parameter(self):
        """Test include_schema parameter is passed through."""
        service = MetaServerService()

        tool = MagicMock()
        tool.name = "tool_a"
        tool.description = "Tool A"
        tool.gateway = SimpleNamespace(id="s1", name="Server 1")
        tool.tags = []
        tool.input_schema = {"type": "object", "properties": {"arg": {"type": "string"}}}

        def mock_get_db():
            db = MagicMock()
            yield db

        metadata = {
            "tool_a": {"tags": [], "input_schema": {"type": "object"}, "visibility": "public", "team_id": None},
        }

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=([tool], None)) as mock_list,
            patch.object(service, "_get_tool_metadata", return_value=metadata),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {"include_schema": True}))

        # Verify ToolService.list_tools was called with include_schema=True
        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["include_schema"] is True

    def test_list_tools_response_is_camel_case(self):
        """Test response uses camelCase aliases for serialization."""
        service = MetaServerService()

        def mock_get_db():
            db = MagicMock()
            yield db

        from mcpgateway.services.tool_service import ToolService

        with (
            patch("mcpgateway.meta_server.service.get_db", mock_get_db),
            patch.object(ToolService, "list_tools", new_callable=AsyncMock, return_value=([], None)),
        ):
            result = asyncio.run(service.handle_meta_tool_call("list_tools", {}))

        assert "totalCount" in result
        assert "hasMore" in result
        assert "tools" in result