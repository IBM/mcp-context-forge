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
"""

# Standard
import asyncio

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
        """Test search_tools stub returns placeholder response."""
        service = MetaServerService()
        result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "database"}))
        assert result["query"] == "database"
        assert result["tools"] == []
        assert result["totalCount"] == 0

    def test_stub_list_tools(self):
        """Test list_tools stub returns placeholder response."""
        service = MetaServerService()
        result = asyncio.run(service.handle_meta_tool_call("list_tools", {}))
        assert result["tools"] == []
        assert result["totalCount"] == 0

    def test_stub_describe_tool(self):
        """Test describe_tool stub returns placeholder response."""
        service = MetaServerService()
        result = asyncio.run(service.handle_meta_tool_call("describe_tool", {"tool_name": "my_tool"}))
        assert result["name"] == "my_tool"
        assert "Stub description" in result["description"]

    def test_stub_execute_tool(self):
        """Test execute_tool stub returns not-implemented response."""
        service = MetaServerService()
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
        """Test get_similar_tools stub returns placeholder response."""
        service = MetaServerService()
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
