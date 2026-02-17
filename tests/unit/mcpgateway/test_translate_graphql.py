# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_translate_graphql.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

Tests for GraphQL to MCP translation module.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.translate_graphql import (
    expose_graphql_via_sse,
    GRAPHQL_AVAILABLE,
    GRAPHQL_SCALAR_TYPE_MAP,
    GraphQLEndpoint,
    GraphQLToMcpTranslator,
    QueryBuilder,
)

# ── Sample introspection data ──────────────────────────────────────────────

SAMPLE_SCHEMA = {
    "queryType": {"name": "Query"},
    "mutationType": {"name": "Mutation"},
    "subscriptionType": None,
    "types": [
        {
            "kind": "OBJECT",
            "name": "Query",
            "description": None,
            "fields": [
                {
                    "name": "users",
                    "description": "Fetch all users",
                    "args": [
                        {
                            "name": "limit",
                            "description": "Max results",
                            "type": {"kind": "SCALAR", "name": "Int", "ofType": None},
                            "defaultValue": "10",
                        },
                        {
                            "name": "role",
                            "description": None,
                            "type": {"kind": "ENUM", "name": "Role", "ofType": None},
                            "defaultValue": None,
                        },
                    ],
                    "type": {
                        "kind": "NON_NULL",
                        "name": None,
                        "ofType": {
                            "kind": "LIST",
                            "name": None,
                            "ofType": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "OBJECT", "name": "User", "ofType": None}},
                        },
                    },
                },
                {
                    "name": "user",
                    "description": "Fetch a single user",
                    "args": [
                        {
                            "name": "id",
                            "description": None,
                            "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None}},
                            "defaultValue": None,
                        },
                    ],
                    "type": {"kind": "OBJECT", "name": "User", "ofType": None},
                },
            ],
            "inputFields": None,
            "enumValues": None,
        },
        {
            "kind": "OBJECT",
            "name": "Mutation",
            "description": None,
            "fields": [
                {
                    "name": "createUser",
                    "description": "Create a new user",
                    "args": [
                        {
                            "name": "input",
                            "description": None,
                            "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "INPUT_OBJECT", "name": "CreateUserInput", "ofType": None}},
                            "defaultValue": None,
                        },
                    ],
                    "type": {"kind": "OBJECT", "name": "User", "ofType": None},
                },
                {
                    "name": "deleteUser",
                    "description": "Delete a user",
                    "args": [
                        {
                            "name": "id",
                            "description": None,
                            "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None}},
                            "defaultValue": None,
                        },
                    ],
                    "type": {"kind": "SCALAR", "name": "Boolean", "ofType": None},
                },
            ],
            "inputFields": None,
            "enumValues": None,
        },
        {
            "kind": "OBJECT",
            "name": "User",
            "description": "A user entity",
            "fields": [
                {"name": "id", "description": None, "args": [], "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None}}},
                {"name": "name", "description": None, "args": [], "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}}},
                {"name": "email", "description": None, "args": [], "type": {"kind": "SCALAR", "name": "String", "ofType": None}},
                {"name": "role", "description": None, "args": [], "type": {"kind": "ENUM", "name": "Role", "ofType": None}},
                {"name": "posts", "description": None, "args": [], "type": {"kind": "LIST", "name": None, "ofType": {"kind": "OBJECT", "name": "Post", "ofType": None}}},
            ],
            "inputFields": None,
            "enumValues": None,
        },
        {
            "kind": "OBJECT",
            "name": "Post",
            "description": None,
            "fields": [
                {"name": "id", "description": None, "args": [], "type": {"kind": "SCALAR", "name": "ID", "ofType": None}},
                {"name": "title", "description": None, "args": [], "type": {"kind": "SCALAR", "name": "String", "ofType": None}},
                {"name": "body", "description": None, "args": [], "type": {"kind": "SCALAR", "name": "String", "ofType": None}},
                {"name": "author", "description": None, "args": [], "type": {"kind": "OBJECT", "name": "User", "ofType": None}},
            ],
            "inputFields": None,
            "enumValues": None,
        },
        {
            "kind": "ENUM",
            "name": "Role",
            "description": "User roles",
            "fields": None,
            "inputFields": None,
            "enumValues": [{"name": "ADMIN", "description": None}, {"name": "USER", "description": None}, {"name": "VIEWER", "description": None}],
        },
        {
            "kind": "INPUT_OBJECT",
            "name": "CreateUserInput",
            "description": None,
            "fields": None,
            "inputFields": [
                {
                    "name": "name",
                    "description": "User name",
                    "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}},
                    "defaultValue": None,
                },
                {
                    "name": "email",
                    "description": "User email",
                    "type": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}},
                    "defaultValue": None,
                },
                {
                    "name": "role",
                    "description": None,
                    "type": {"kind": "ENUM", "name": "Role", "ofType": None},
                    "defaultValue": '"USER"',
                },
            ],
            "enumValues": None,
        },
        {"kind": "SCALAR", "name": "String", "description": None, "fields": None, "inputFields": None, "enumValues": None},
        {"kind": "SCALAR", "name": "Int", "description": None, "fields": None, "inputFields": None, "enumValues": None},
        {"kind": "SCALAR", "name": "Float", "description": None, "fields": None, "inputFields": None, "enumValues": None},
        {"kind": "SCALAR", "name": "Boolean", "description": None, "fields": None, "inputFields": None, "enumValues": None},
        {"kind": "SCALAR", "name": "ID", "description": None, "fields": None, "inputFields": None, "enumValues": None},
    ],
}


def _make_endpoint_with_schema(include_mutations=True, include_subscriptions=False, max_depth=3):
    """Create a GraphQLEndpoint pre-loaded with sample schema data."""
    ep = GraphQLEndpoint(
        url="https://api.example.com/graphql",
        include_mutations=include_mutations,
        include_subscriptions=include_subscriptions,
        max_depth=max_depth,
    )
    ep._schema = SAMPLE_SCHEMA
    ep._query_type_name = "Query"
    ep._mutation_type_name = "Mutation"
    ep._subscription_type_name = None
    ep._types = {t["name"]: t for t in SAMPLE_SCHEMA["types"] if not t["name"].startswith("__")}
    return ep


# ── GraphQLEndpoint tests ──────────────────────────────────────────────────


class TestGraphQLEndpoint:
    """Test suite for GraphQLEndpoint."""

    def test_initialization_defaults(self):
        """Test basic endpoint initialization with defaults."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        assert ep._url == "https://api.example.com/graphql"
        assert ep._auth_type is None
        assert ep._auth_value is None
        assert ep._max_depth == 3
        assert ep._include_mutations is True
        assert ep._include_subscriptions is False
        assert ep._schema is None

    def test_initialization_with_auth(self):
        """Test endpoint initialization with authentication."""
        ep = GraphQLEndpoint(
            "https://api.example.com/graphql",
            auth_type="bearer",
            auth_value="my-token",
            max_depth=5,
            include_subscriptions=True,
        )
        assert ep._auth_type == "bearer"
        assert ep._auth_value == "my-token"
        assert ep._max_depth == 5
        assert ep._include_subscriptions is True

    def test_build_headers_no_auth(self):
        """Test header building without authentication."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        headers = ep._build_headers()
        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers

    def test_build_headers_bearer_auth(self):
        """Test header building with bearer token."""
        ep = GraphQLEndpoint("https://api.example.com/graphql", auth_type="bearer", auth_value="tok123")
        headers = ep._build_headers()
        assert headers["Authorization"] == "Bearer tok123"

    def test_build_headers_basic_auth(self):
        """Test header building with basic authentication."""
        ep = GraphQLEndpoint("https://api.example.com/graphql", auth_type="basic", auth_value="dXNlcjpwYXNz")
        headers = ep._build_headers()
        assert headers["Authorization"] == "Basic dXNlcjpwYXNz"

    def test_build_headers_header_auth(self):
        """Test header building with custom header authentication."""
        ep = GraphQLEndpoint("https://api.example.com/graphql", auth_type="header", auth_value="X-API-Key: secret123")
        headers = ep._build_headers()
        assert headers["X-API-Key"] == "secret123"

    def test_build_headers_extra_headers(self):
        """Test header building with extra headers."""
        ep = GraphQLEndpoint("https://api.example.com/graphql", headers={"X-Custom": "value"})
        headers = ep._build_headers()
        assert headers["X-Custom"] == "value"
        assert headers["Content-Type"] == "application/json"

    def test_get_queries(self):
        """Test query field discovery."""
        ep = _make_endpoint_with_schema()
        queries = ep.get_queries()
        assert "users" in queries
        assert "user" in queries
        assert len(queries) == 2

    def test_get_mutations(self):
        """Test mutation field discovery."""
        ep = _make_endpoint_with_schema()
        mutations = ep.get_mutations()
        assert "createUser" in mutations
        assert "deleteUser" in mutations
        assert len(mutations) == 2

    def test_get_mutations_disabled(self):
        """Test mutations are excluded when disabled."""
        ep = _make_endpoint_with_schema(include_mutations=False)
        assert ep.get_mutations() == []

    def test_get_subscriptions_empty(self):
        """Test subscriptions when none exist."""
        ep = _make_endpoint_with_schema()
        assert ep.get_subscriptions() == []

    def test_get_queries_no_schema(self):
        """Test queries return empty when no schema loaded."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        assert ep.get_queries() == []

    @pytest.mark.asyncio
    async def test_start_without_httpx(self):
        """Test start raises error when httpx not available."""
        with patch("mcpgateway.translate_graphql.GRAPHQL_AVAILABLE", False):
            ep = GraphQLEndpoint("https://api.example.com/graphql")
            with pytest.raises(RuntimeError, match="httpx is required"):
                await ep.start()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing the HTTP client."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        mock_client = AsyncMock()
        ep._client = mock_client
        await ep.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        """Test closing when no client exists."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        await ep.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_introspect_schema_success(self):
        """Test successful schema introspection."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {"__schema": SAMPLE_SCHEMA}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        await ep._introspect_schema()
        assert ep._query_type_name == "Query"
        assert ep._mutation_type_name == "Mutation"
        assert "User" in ep._types
        assert "Role" in ep._types

    @pytest.mark.asyncio
    async def test_introspect_schema_with_errors(self):
        """Test introspection failure on GraphQL errors."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errors": [{"message": "Introspection not allowed"}]}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        with pytest.raises(RuntimeError, match="Introspection not allowed"):
            await ep._introspect_schema()

    @pytest.mark.asyncio
    async def test_introspect_schema_no_data(self):
        """Test introspection failure when no schema data returned."""
        ep = GraphQLEndpoint("https://api.example.com/graphql")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        with pytest.raises(RuntimeError, match="no schema data"):
            await ep._introspect_schema()

    @pytest.mark.asyncio
    async def test_invoke_query(self):
        """Test invoking a GraphQL query."""
        ep = _make_endpoint_with_schema()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {"users": [{"id": "1", "name": "Alice"}]}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        result = await ep.invoke("query", "users", {"limit": 10})
        assert result == {"result": [{"id": "1", "name": "Alice"}]}
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "query" in payload["query"]

    @pytest.mark.asyncio
    async def test_invoke_with_graphql_errors(self):
        """Test invoke raises on GraphQL errors."""
        ep = _make_endpoint_with_schema()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"errors": [{"message": "Field not found"}]}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        with pytest.raises(RuntimeError, match="Field not found"):
            await ep.invoke("query", "users", {})

    @pytest.mark.asyncio
    async def test_invoke_no_query_type(self):
        """Test invoke raises for missing query type."""
        ep = _make_endpoint_with_schema()
        ep._mutation_type_name = None
        with pytest.raises(ValueError, match="no mutation type"):
            await ep.invoke("mutation", "createUser", {})

    @pytest.mark.asyncio
    async def test_invoke_raw(self):
        """Test raw query execution."""
        ep = _make_endpoint_with_schema()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {"users": []}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        result = await ep.invoke_raw("query { users { id } }")
        assert result == {"users": []}

    @pytest.mark.asyncio
    async def test_invoke_raw_with_variables(self):
        """Test raw query with variables."""
        ep = _make_endpoint_with_schema()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {"user": {"id": "1", "name": "Alice"}}}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        ep._client = mock_client

        result = await ep.invoke_raw("query($id: ID!) { user(id: $id) { id name } }", {"id": "1"})
        assert result["user"]["id"] == "1"
        call_payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        assert call_payload["variables"] == {"id": "1"}


# ── QueryBuilder tests ─────────────────────────────────────────────────────


class TestQueryBuilder:
    """Test suite for QueryBuilder."""

    @pytest.fixture
    def types(self):
        """Return parsed types from sample schema."""
        return {t["name"]: t for t in SAMPLE_SCHEMA["types"] if not t["name"].startswith("__")}

    def test_type_ref_to_string_scalar(self):
        """Test scalar type reference to string."""
        qb = QueryBuilder({}, 3)
        assert qb._type_ref_to_string({"kind": "SCALAR", "name": "String", "ofType": None}) == "String"
        assert qb._type_ref_to_string({"kind": "SCALAR", "name": "Int", "ofType": None}) == "Int"

    def test_type_ref_to_string_non_null(self):
        """Test NON_NULL wrapper type reference."""
        qb = QueryBuilder({}, 3)
        result = qb._type_ref_to_string({"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}})
        assert result == "String!"

    def test_type_ref_to_string_list(self):
        """Test LIST wrapper type reference."""
        qb = QueryBuilder({}, 3)
        result = qb._type_ref_to_string({"kind": "LIST", "name": None, "ofType": {"kind": "SCALAR", "name": "Int", "ofType": None}})
        assert result == "[Int]"

    def test_type_ref_to_string_nested(self):
        """Test nested NON_NULL + LIST type reference."""
        qb = QueryBuilder({}, 3)
        result = qb._type_ref_to_string(
            {
                "kind": "NON_NULL",
                "name": None,
                "ofType": {
                    "kind": "LIST",
                    "name": None,
                    "ofType": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "OBJECT", "name": "User", "ofType": None}},
                },
            }
        )
        assert result == "[User!]!"

    def test_unwrap_type(self):
        """Test type unwrapping."""
        qb = QueryBuilder({}, 3)
        assert qb._unwrap_type({"kind": "SCALAR", "name": "String", "ofType": None}) == "String"
        assert qb._unwrap_type({"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "Int", "ofType": None}}) == "Int"
        assert (
            qb._unwrap_type(
                {
                    "kind": "NON_NULL",
                    "name": None,
                    "ofType": {
                        "kind": "LIST",
                        "name": None,
                        "ofType": {"kind": "OBJECT", "name": "User", "ofType": None},
                    },
                }
            )
            == "User"
        )

    def test_build_field_selection_scalar_type(self, types):
        """Test field selection returns empty for scalar types."""
        qb = QueryBuilder(types, 3)
        assert qb._build_field_selection("String", 0, set()) == ""

    def test_build_field_selection_simple_object(self, types):
        """Test field selection for a simple object."""
        qb = QueryBuilder(types, 1)
        selection = qb._build_field_selection("User", 0, set())
        assert "id" in selection
        assert "name" in selection
        assert "email" in selection
        assert "role" in selection
        # At depth 1, nested objects should not be included
        assert "posts" not in selection

    def test_build_field_selection_with_nesting(self, types):
        """Test field selection with nested objects."""
        qb = QueryBuilder(types, 2)
        selection = qb._build_field_selection("User", 0, set())
        assert "id" in selection
        assert "name" in selection
        assert "posts" in selection

    def test_build_field_selection_cycle_detection(self, types):
        """Test cycle detection in recursive types (User -> posts -> Post -> author -> User)."""
        qb = QueryBuilder(types, 10)
        selection = qb._build_field_selection("User", 0, set())
        # Should include posts but not infinite recursion
        assert "posts" in selection
        # The author field within Post references User, which should be detected as a cycle
        assert selection.count("User") == 0  # No actual "User" text in selection

    def test_build_field_selection_max_depth(self, types):
        """Test field selection respects max depth."""
        qb = QueryBuilder(types, 0)
        selection = qb._build_field_selection("User", 0, set())
        assert selection == ""

    def test_build_query_with_variables(self, types):
        """Test building a query with typed variables."""
        qb = QueryBuilder(types, 2)
        query, variables = qb.build("query", "Query", "users", {"limit": 10, "role": "ADMIN"})
        assert "query(" in query
        assert "$limit: Int" in query
        assert "$role: Role" in query
        assert "users(limit: $limit, role: $role)" in query
        assert variables == {"limit": 10, "role": "ADMIN"}

    def test_build_query_with_explicit_field_selection(self, types):
        """Test building a query with explicit field selection."""
        qb = QueryBuilder(types, 2)
        query, variables = qb.build("query", "Query", "users", {"limit": 5}, field_selection="{ id name }")
        assert "{ id name }" in query
        assert variables == {"limit": 5}

    def test_build_query_no_arguments(self, types):
        """Test building a query with no arguments."""
        qb = QueryBuilder(types, 2)
        query, variables = qb.build("query", "Query", "users", {})
        assert "users" in query
        assert variables == {}

    def test_build_query_unknown_field(self, types):
        """Test building a query for an unknown field (fallback)."""
        qb = QueryBuilder(types, 2)
        query, variables = qb.build("query", "Query", "nonexistent", {"foo": "bar"})
        assert "nonexistent" in query
        assert variables == {}

    def test_build_mutation(self, types):
        """Test building a mutation query."""
        qb = QueryBuilder(types, 2)
        query, variables = qb.build("mutation", "Mutation", "deleteUser", {"id": "123"})
        assert "mutation(" in query
        assert "$id: ID!" in query
        assert "deleteUser(id: $id)" in query
        assert variables == {"id": "123"}

    def test_format_inline_args(self):
        """Test inline argument formatting."""
        qb = QueryBuilder({}, 3)
        result = qb._format_inline_args({"limit": 10, "name": "Alice"})
        assert "limit: 10" in result
        assert 'name: "Alice"' in result

    def test_format_inline_args_skips_underscore_keys(self):
        """Test inline args skip keys starting with underscore."""
        qb = QueryBuilder({}, 3)
        result = qb._format_inline_args({"limit": 10, "_fields": "id name"})
        assert "limit: 10" in result
        assert "_fields" not in result

    def test_format_inline_args_empty(self):
        """Test inline args with empty dict."""
        qb = QueryBuilder({}, 3)
        assert qb._format_inline_args({}) == ""


# ── GraphQLToMcpTranslator tests ───────────────────────────────────────────


class TestGraphQLToMcpTranslator:
    """Test suite for GraphQLToMcpTranslator."""

    @pytest.fixture
    def translator(self):
        """Create a translator with sample schema."""
        ep = _make_endpoint_with_schema()
        return GraphQLToMcpTranslator(ep)

    def test_graphql_fields_to_mcp_tools(self, translator):
        """Test converting GraphQL fields to MCP tools."""
        tools = translator.graphql_fields_to_mcp_tools()
        tool_names = [t["name"] for t in tools]
        assert "query_users" in tool_names
        assert "query_user" in tool_names
        assert "mutation_createUser" in tool_names
        assert "mutation_deleteUser" in tool_names
        assert len(tools) == 4

    def test_graphql_fields_mutations_disabled(self):
        """Test mutations excluded when disabled."""
        ep = _make_endpoint_with_schema(include_mutations=False)
        tr = GraphQLToMcpTranslator(ep)
        tools = tr.graphql_fields_to_mcp_tools()
        tool_names = [t["name"] for t in tools]
        assert "mutation_createUser" not in tool_names
        assert len(tools) == 2

    def test_tool_has_input_schema(self, translator):
        """Test generated tools have correct input schema."""
        tools = translator.graphql_fields_to_mcp_tools()
        users_tool = next(t for t in tools if t["name"] == "query_users")
        schema = users_tool["inputSchema"]
        assert schema["type"] == "object"
        assert "limit" in schema["properties"]
        assert schema["properties"]["limit"]["type"] == "integer"
        assert "role" in schema["properties"]
        assert "enum" in schema["properties"]["role"]

    def test_tool_has_description(self, translator):
        """Test generated tools have descriptions."""
        tools = translator.graphql_fields_to_mcp_tools()
        users_tool = next(t for t in tools if t["name"] == "query_users")
        assert users_tool["description"] == "Fetch all users"

    def test_tool_default_description(self, translator):
        """Test tool gets default description when none in schema."""
        tools = translator.graphql_fields_to_mcp_tools()
        delete_tool = next(t for t in tools if t["name"] == "mutation_deleteUser")
        assert "Delete a user" in delete_tool["description"]

    def test_required_fields_in_schema(self, translator):
        """Test NON_NULL args become required in JSON Schema."""
        tools = translator.graphql_fields_to_mcp_tools()
        user_tool = next(t for t in tools if t["name"] == "query_user")
        schema = user_tool["inputSchema"]
        assert "id" in schema.get("required", [])

    def test_input_object_type_conversion(self, translator):
        """Test INPUT_OBJECT types are converted to nested JSON Schema."""
        tools = translator.graphql_fields_to_mcp_tools()
        create_tool = next(t for t in tools if t["name"] == "mutation_createUser")
        schema = create_tool["inputSchema"]
        assert "input" in schema.get("required", [])
        input_prop = schema["properties"]["input"]
        assert input_prop["type"] == "object"
        assert "name" in input_prop["properties"]
        assert "email" in input_prop["properties"]
        assert "role" in input_prop["properties"]
        assert input_prop["properties"]["name"]["type"] == "string"

    def test_enum_type_conversion(self, translator):
        """Test ENUM types are converted to JSON Schema enum."""
        tools = translator.graphql_fields_to_mcp_tools()
        users_tool = next(t for t in tools if t["name"] == "query_users")
        role_schema = users_tool["inputSchema"]["properties"]["role"]
        assert role_schema["type"] == "string"
        assert "enum" in role_schema
        assert set(role_schema["enum"]) == {"ADMIN", "USER", "VIEWER"}

    def test_list_type_conversion(self, translator):
        """Test LIST types are converted to JSON Schema array."""
        schema = translator._graphql_type_to_json_schema(
            {"kind": "LIST", "name": None, "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}},
            set(),
        )
        assert schema == {"type": "array", "items": {"type": "string"}}

    def test_scalar_type_mappings(self, translator):
        """Test all scalar type mappings."""
        for gql_name, json_type in GRAPHQL_SCALAR_TYPE_MAP.items():
            schema = translator._graphql_type_to_json_schema({"kind": "SCALAR", "name": gql_name, "ofType": None}, set())
            assert schema == {"type": json_type}, f"Failed for {gql_name}"

    def test_custom_scalar_fallback(self, translator):
        """Test custom scalars fall back to string."""
        schema = translator._graphql_type_to_json_schema({"kind": "SCALAR", "name": "DateTime", "ofType": None}, set())
        assert schema == {"type": "string"}

    def test_cycle_detection_in_input_object(self):
        """Test cycle detection for recursive input objects."""
        ep = _make_endpoint_with_schema()
        # Add a recursive input type
        ep._types["RecursiveInput"] = {
            "kind": "INPUT_OBJECT",
            "name": "RecursiveInput",
            "inputFields": [
                {"name": "value", "description": None, "type": {"kind": "SCALAR", "name": "String", "ofType": None}, "defaultValue": None},
                {"name": "children", "description": None, "type": {"kind": "LIST", "name": None, "ofType": {"kind": "INPUT_OBJECT", "name": "RecursiveInput", "ofType": None}}, "defaultValue": None},
            ],
        }
        tr = GraphQLToMcpTranslator(ep)
        schema = tr._graphql_type_to_json_schema({"kind": "INPUT_OBJECT", "name": "RecursiveInput", "ofType": None}, set())
        assert schema["type"] == "object"
        assert "value" in schema["properties"]
        # The recursive reference should be a simple object (cycle detected)
        children_schema = schema["properties"]["children"]
        assert children_schema["type"] == "array"
        assert children_schema["items"]["type"] == "object"

    def test_default_value_parsing(self, translator):
        """Test default values are parsed into JSON Schema."""
        tools = translator.graphql_fields_to_mcp_tools()
        users_tool = next(t for t in tools if t["name"] == "query_users")
        limit_prop = users_tool["inputSchema"]["properties"]["limit"]
        assert limit_prop.get("default") == 10
        assert limit_prop.get("description") == "Max results"

    def test_graphql_schema_to_mcp_server(self, translator):
        """Test full schema to MCP server definition."""
        server = translator.graphql_schema_to_mcp_server()
        assert "graphql-" in server["name"]
        assert "sse" in server["transport"]
        assert len(server["tools"]) == 4

    def test_object_type_fallback(self, translator):
        """Test OBJECT types used as input fall back to object."""
        schema = translator._graphql_type_to_json_schema({"kind": "OBJECT", "name": "User", "ofType": None}, set())
        assert schema == {"type": "object"}

    def test_non_null_unwrapping(self, translator):
        """Test NON_NULL wrapper is properly unwrapped."""
        schema = translator._graphql_type_to_json_schema(
            {"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "Boolean", "ofType": None}},
            set(),
        )
        assert schema == {"type": "boolean"}


# ── Constant and module-level tests ────────────────────────────────────────


class TestModuleConstants:
    """Test module-level constants and availability."""

    def test_graphql_available(self):
        """Test GRAPHQL_AVAILABLE is a boolean."""
        assert isinstance(GRAPHQL_AVAILABLE, bool)

    def test_scalar_type_map_completeness(self):
        """Test all standard GraphQL scalars are mapped."""
        assert "String" in GRAPHQL_SCALAR_TYPE_MAP
        assert "Int" in GRAPHQL_SCALAR_TYPE_MAP
        assert "Float" in GRAPHQL_SCALAR_TYPE_MAP
        assert "Boolean" in GRAPHQL_SCALAR_TYPE_MAP
        assert "ID" in GRAPHQL_SCALAR_TYPE_MAP

    def test_scalar_type_map_values(self):
        """Test scalar type map values are valid JSON Schema types."""
        valid_types = {"string", "integer", "number", "boolean"}
        for value in GRAPHQL_SCALAR_TYPE_MAP.values():
            assert value in valid_types


# ── expose_graphql_via_sse tests ───────────────────────────────────────────


class TestExposeGraphqlViaSse:
    """Test the CLI utility function."""

    @pytest.mark.asyncio
    async def test_expose_graphql_basic(self):
        """Test expose function performs introspection and logs tools."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": {"__schema": SAMPLE_SCHEMA}}

        with patch("mcpgateway.translate_graphql.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_httpx.AsyncClient.return_value = mock_client

            task = asyncio.create_task(
                expose_graphql_via_sse(
                    endpoint_url="https://api.example.com/graphql",
                    port=9001,
                )
            )
            # Let the task start and perform introspection
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
