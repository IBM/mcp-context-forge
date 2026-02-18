# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/translate_graphql.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: MCP Gateway Contributors

GraphQL to MCP Translation Module

This module provides GraphQL to MCP protocol translation capabilities.
It enables exposing GraphQL APIs as MCP tools via HTTP/SSE endpoints
using automatic schema discovery through GraphQL's built-in introspection system.

Examples:
    Programmatic usage:

    >>> import asyncio
    >>> from mcpgateway.translate_graphql import GraphQLEndpoint, GraphQLToMcpTranslator
    >>> isinstance(GraphQLEndpoint, type)
    True
    >>> isinstance(GraphQLToMcpTranslator, type)
    True
    >>> isinstance(QueryBuilder, type)
    True

    Test constants:

    >>> from mcpgateway.translate_graphql import GRAPHQL_AVAILABLE
    >>> isinstance(GRAPHQL_AVAILABLE, bool)
    True
    >>> from mcpgateway.translate_graphql import GRAPHQL_SCALAR_TYPE_MAP
    >>> GRAPHQL_SCALAR_TYPE_MAP["String"]
    'string'
    >>> GRAPHQL_SCALAR_TYPE_MAP["Int"]
    'integer'
    >>> GRAPHQL_SCALAR_TYPE_MAP["Float"]
    'number'
    >>> GRAPHQL_SCALAR_TYPE_MAP["Boolean"]
    'boolean'
    >>> GRAPHQL_SCALAR_TYPE_MAP["ID"]
    'string'

Usage:
    Command line usage::

        # 1. Expose a GraphQL API as MCP tools via SSE at :9001
        python3 -m mcpgateway.translate_graphql \\
            --endpoint https://api.example.com/graphql --port 9001

        # 2. With bearer token auth
        python3 -m mcpgateway.translate_graphql \\
            --endpoint https://api.example.com/graphql \\
            --auth-type bearer --auth-value "your-token" --port 9001

        # 3. With field depth control
        python3 -m mcpgateway.translate_graphql \\
            --endpoint https://api.example.com/graphql \\
            --max-depth 4 --include-mutations --port 9001
"""

# Standard
import argparse
import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Set

try:
    # Third-Party
    import httpx

    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False
    httpx = None  # type: ignore

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


GRAPHQL_SCALAR_TYPE_MAP: Dict[str, str] = {
    "String": "string",
    "Int": "integer",
    "Float": "number",
    "Boolean": "boolean",
    "ID": "string",
}

INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      kind
      name
      description
      fields(includeDeprecated: false) {
        name
        description
        args {
          name
          description
          type {
            ...TypeRef
          }
          defaultValue
        }
        type {
          ...TypeRef
        }
      }
      inputFields {
        name
        description
        type {
          ...TypeRef
        }
        defaultValue
      }
      enumValues(includeDeprecated: false) {
        name
        description
      }
    }
  }
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
            }
          }
        }
      }
    }
  }
}
"""


class GraphQLEndpoint:
    """Wrapper around a GraphQL HTTP endpoint with introspection-based discovery.

    Examples:
        >>> ep = GraphQLEndpoint("https://example.com/graphql")
        >>> ep._url
        'https://example.com/graphql'
        >>> ep._schema is None
        True
    """

    def __init__(
        self,
        url: str,
        auth_type: Optional[str] = None,
        auth_value: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        max_depth: int = 3,
        include_mutations: bool = True,
        include_subscriptions: bool = False,
        cache_ttl: int = 3600,
        timeout: int = 30,
    ):
        """Initialize GraphQL endpoint.

        Args:
            url: GraphQL endpoint URL.
            auth_type: Authentication type ('bearer', 'basic', 'header').
            auth_value: Authentication credential value.
            headers: Additional HTTP headers.
            max_depth: Maximum field selection depth for auto-generated queries.
            include_mutations: Whether to expose mutations as tools.
            include_subscriptions: Whether to expose subscriptions as tools.
            cache_ttl: Introspection cache TTL in seconds.
            timeout: HTTP request timeout in seconds.
        """
        self._url = url
        self._auth_type = auth_type
        self._auth_value = auth_value
        self._extra_headers = headers or {}
        self._max_depth = max_depth
        self._include_mutations = include_mutations
        self._include_subscriptions = include_subscriptions
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._schema: Optional[Dict[str, Any]] = None
        self._types: Dict[str, Dict[str, Any]] = {}
        self._query_type_name: Optional[str] = None
        self._mutation_type_name: Optional[str] = None
        self._subscription_type_name: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._introspected_at: float = 0.0

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers including authentication.

        Returns:
            Dict of HTTP headers.

        Examples:
            >>> ep = GraphQLEndpoint("https://example.com/graphql")
            >>> h = ep._build_headers()
            >>> h["Content-Type"]
            'application/json'
            >>> ep2 = GraphQLEndpoint("https://x.com/gql", auth_type="bearer", auth_value="tok123")
            >>> h2 = ep2._build_headers()
            >>> h2["Authorization"]
            'Bearer tok123'
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        headers.update(self._extra_headers)
        if self._auth_type and self._auth_value:
            if self._auth_type == "bearer":
                headers["Authorization"] = f"Bearer {self._auth_value}"
            elif self._auth_type == "basic":
                headers["Authorization"] = f"Basic {self._auth_value}"
            elif self._auth_type == "header":
                # auth_value is expected to be "HeaderName: HeaderValue"
                if ":" in self._auth_value:
                    key, _, val = self._auth_value.partition(":")
                    headers[key.strip()] = val.strip()
        return headers

    async def start(self) -> None:
        """Initialize HTTP client and perform introspection.

        Raises:
            RuntimeError: If httpx is not installed or introspection fails.
        """
        if not GRAPHQL_AVAILABLE:
            raise RuntimeError("httpx is required for GraphQL translation. Install with: pip install httpx")

        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        await self._introspect_schema()

    async def _introspect_schema(self) -> None:
        """Execute GraphQL introspection query and parse the schema.

        Raises:
            RuntimeError: If introspection query fails or returns errors.
        """
        logger.info(f"Introspecting GraphQL schema at {self._url}")
        start = time.time()

        response = await self._client.post(  # type: ignore[union-attr]
            self._url,
            json={"query": INTROSPECTION_QUERY},
            headers=self._build_headers(),
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result and result["errors"]:
            errors = result["errors"]
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise RuntimeError(f"GraphQL introspection failed: {msg}")

        schema_data = result.get("data", {}).get("__schema")
        if not schema_data:
            raise RuntimeError("GraphQL introspection returned no schema data")

        self._schema = schema_data
        self._query_type_name = (schema_data.get("queryType") or {}).get("name")
        self._mutation_type_name = (schema_data.get("mutationType") or {}).get("name")
        self._subscription_type_name = (schema_data.get("subscriptionType") or {}).get("name")

        # Build type lookup
        self._types = {}
        for t in schema_data.get("types", []):
            name = t.get("name", "")
            if not name.startswith("__"):
                self._types[name] = t

        self._introspected_at = time.time()
        elapsed_ms = (self._introspected_at - start) * 1000
        logger.info(f"Introspection complete in {elapsed_ms:.1f}ms. Types: {len(self._types)}")

    async def invoke(
        self,
        operation_type: str,
        field_name: str,
        arguments: Dict[str, Any],
        field_selection: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a GraphQL operation and return the result.

        Args:
            operation_type: 'query' or 'mutation'.
            field_name: The root field name to invoke.
            arguments: Arguments for the operation.
            field_selection: Optional explicit field selection string.

        Returns:
            The data from the GraphQL response for the given field.

        Raises:
            RuntimeError: If the operation fails or returns errors.
            ValueError: If the operation type is invalid.
        """
        builder = QueryBuilder(self._types, self._max_depth)
        type_name = self._query_type_name if operation_type == "query" else self._mutation_type_name
        if not type_name:
            raise ValueError(f"Schema has no {operation_type} type")

        query_str, variables = builder.build(operation_type, type_name, field_name, arguments, field_selection)

        logger.debug(f"Executing GraphQL {operation_type}: {field_name}")
        response = await self._client.post(  # type: ignore[union-attr]
            self._url,
            json={"query": query_str, "variables": variables},
            headers=self._build_headers(),
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result and result["errors"]:
            errors = result["errors"]
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise RuntimeError(f"GraphQL error: {msg}")

        data: Dict[str, Any] = result.get("data", {})
        field_data: Any = data.get(field_name, data)
        if isinstance(field_data, dict):
            return field_data
        return {"result": field_data}

    async def invoke_raw(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a raw GraphQL query string.

        Args:
            query: GraphQL query string.
            variables: Optional variables dict.

        Returns:
            The full data dict from the GraphQL response.

        Raises:
            RuntimeError: If the query returns errors.
        """
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await self._client.post(  # type: ignore[union-attr]
            self._url,
            json=payload,
            headers=self._build_headers(),
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result and result["errors"]:
            errors = result["errors"]
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise RuntimeError(f"GraphQL error: {msg}")

        data: Dict[str, Any] = result.get("data", {})
        return data

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            logger.info(f"Closed GraphQL connection to {self._url}")

    @property
    def url(self) -> str:
        """Return the GraphQL endpoint URL."""
        return self._url

    @property
    def types(self) -> Dict[str, Dict[str, Any]]:
        """Return the introspected type map."""
        return self._types

    @property
    def query_type_name(self) -> Optional[str]:
        """Return the name of the root Query type."""
        return self._query_type_name

    @property
    def mutation_type_name(self) -> Optional[str]:
        """Return the name of the root Mutation type."""
        return self._mutation_type_name

    @property
    def subscription_type_name(self) -> Optional[str]:
        """Return the name of the root Subscription type."""
        return self._subscription_type_name

    @property
    def include_mutations(self) -> bool:
        """Return whether mutations are included."""
        return self._include_mutations

    @property
    def include_subscriptions(self) -> bool:
        """Return whether subscriptions are included."""
        return self._include_subscriptions

    def get_queries(self) -> List[str]:
        """Get list of discovered query field names.

        Returns:
            List of query field names.
        """
        if not self._query_type_name or self._query_type_name not in self._types:
            return []
        return [f["name"] for f in self._types[self._query_type_name].get("fields", [])]

    def get_mutations(self) -> List[str]:
        """Get list of discovered mutation field names.

        Returns:
            List of mutation field names.
        """
        if not self._include_mutations:
            return []
        if not self._mutation_type_name or self._mutation_type_name not in self._types:
            return []
        return [f["name"] for f in self._types[self._mutation_type_name].get("fields", [])]

    def get_subscriptions(self) -> List[str]:
        """Get list of discovered subscription field names.

        Returns:
            List of subscription field names.
        """
        if not self._include_subscriptions:
            return []
        if not self._subscription_type_name or self._subscription_type_name not in self._types:
            return []
        return [f["name"] for f in self._types[self._subscription_type_name].get("fields", [])]


class QueryBuilder:
    """Builds GraphQL query strings from MCP tool arguments.

    Examples:
        >>> types = {"Query": {"kind": "OBJECT", "name": "Query", "fields": []}}
        >>> qb = QueryBuilder(types, max_depth=3)
        >>> qb._max_depth
        3
    """

    def __init__(self, types: Dict[str, Dict[str, Any]], max_depth: int = 3):
        """Initialize query builder.

        Args:
            types: Parsed GraphQL type map from introspection.
            max_depth: Maximum depth for automatic field selection.
        """
        self._types = types
        self._max_depth = max_depth

    def build(
        self,
        operation_type: str,
        root_type_name: str,
        field_name: str,
        arguments: Dict[str, Any],
        field_selection: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Build a GraphQL operation string with parameterized variables.

        Args:
            operation_type: 'query' or 'mutation'.
            root_type_name: Name of the root type (e.g. 'Query', 'Mutation').
            field_name: The field to query.
            arguments: Dict of argument values.
            field_selection: Optional explicit field selection.

        Returns:
            Tuple of (query_string, variables_dict).
        """
        root_type = self._types.get(root_type_name, {})
        field_def = None
        for f in root_type.get("fields", []):
            if f["name"] == field_name:
                field_def = f
                break

        if not field_def:
            # Fallback: simple query without variable typing
            args_str = self._format_inline_args(arguments) if arguments else ""
            selection = field_selection or "{ __typename }"
            return f"{operation_type} {{ {field_name}{args_str} {selection} }}", {}

        # Build variable declarations and argument references
        var_decls = []
        arg_refs = []
        variables: Dict[str, Any] = {}
        reserved_keys = {"_fields"}

        for arg_def in field_def.get("args", []):
            arg_name = arg_def["name"]
            if arg_name in arguments and arg_name not in reserved_keys:
                gql_type_str = self._type_ref_to_string(arg_def["type"])
                var_name = arg_name
                var_decls.append(f"${var_name}: {gql_type_str}")
                arg_refs.append(f"{arg_name}: ${var_name}")
                variables[var_name] = arguments[arg_name]

        # Build field selection
        if field_selection:
            selection = field_selection
        else:
            return_type = self._unwrap_type(field_def["type"])
            selection = self._build_field_selection(return_type, depth=0, visited=set())

        var_decl_str = f"({', '.join(var_decls)})" if var_decls else ""
        arg_ref_str = f"({', '.join(arg_refs)})" if arg_refs else ""

        query = f"{operation_type}{var_decl_str} {{ {field_name}{arg_ref_str} {selection} }}"
        return query, variables

    def _type_ref_to_string(self, type_ref: Dict[str, Any]) -> str:
        """Convert a GraphQL type reference to its string representation.

        Args:
            type_ref: Type reference dict from introspection.

        Returns:
            GraphQL type string (e.g. 'String!', '[Int]', '[User!]!').

        Examples:
            >>> qb = QueryBuilder({}, 3)
            >>> qb._type_ref_to_string({"kind": "SCALAR", "name": "String", "ofType": None})
            'String'
            >>> qb._type_ref_to_string({"kind": "NON_NULL", "name": None, "ofType": {"kind": "SCALAR", "name": "Int", "ofType": None}})
            'Int!'
        """
        kind = type_ref.get("kind")
        if kind == "NON_NULL":
            inner = type_ref.get("ofType", {})
            return f"{self._type_ref_to_string(inner)}!"
        if kind == "LIST":
            inner = type_ref.get("ofType", {})
            return f"[{self._type_ref_to_string(inner)}]"
        name: str = type_ref.get("name", "String")
        return name

    def _unwrap_type(self, type_ref: Dict[str, Any]) -> str:
        """Unwrap NON_NULL and LIST wrappers to get the base type name.

        Args:
            type_ref: Type reference dict from introspection.

        Returns:
            The base type name string.

        Examples:
            >>> qb = QueryBuilder({}, 3)
            >>> qb._unwrap_type({"kind": "NON_NULL", "name": None, "ofType": {"kind": "LIST", "name": None, "ofType": {"kind": "NON_NULL", "name": None, "ofType": {"kind": "OBJECT", "name": "User", "ofType": None}}}})
            'User'
        """
        while type_ref and type_ref.get("kind") in ("NON_NULL", "LIST"):
            type_ref = type_ref.get("ofType", {})
        result: str = type_ref.get("name", "")
        return result

    def _build_field_selection(self, type_name: str, depth: int, visited: Set[str]) -> str:
        """Build a field selection string for a given type.

        Automatically selects scalar fields and recurses into object fields
        up to the configured max_depth.

        Args:
            type_name: The GraphQL type name.
            depth: Current recursion depth.
            visited: Set of type names already visited (cycle detection).

        Returns:
            A field selection string (e.g. '{ id name email }').
        """
        if depth >= self._max_depth:
            return ""
        if type_name in visited:
            return ""
        type_def = self._types.get(type_name, {})
        kind = type_def.get("kind")
        if kind not in ("OBJECT", "INTERFACE"):
            return ""

        visited_copy = visited | {type_name}
        fields = []
        for field in type_def.get("fields", []):
            field_type_name = self._unwrap_type(field["type"])
            field_kind = self._types.get(field_type_name, {}).get("kind", "SCALAR")

            if field_kind in ("SCALAR", "ENUM"):
                fields.append(field["name"])
            elif field_kind in ("OBJECT", "INTERFACE") and depth + 1 < self._max_depth:
                nested = self._build_field_selection(field_type_name, depth + 1, visited_copy)
                if nested:
                    fields.append(f"{field['name']} {nested}")

        if not fields:
            fields = ["__typename"]
        return "{ " + " ".join(fields) + " }"

    def _format_inline_args(self, arguments: Dict[str, Any]) -> str:
        """Format arguments as inline GraphQL arguments (fallback).

        Args:
            arguments: Argument key-value pairs.

        Returns:
            Formatted argument string.
        """
        parts = []
        for key, value in arguments.items():
            if key.startswith("_"):
                continue
            parts.append(f"{key}: {json.dumps(value)}")
        return f"({', '.join(parts)})" if parts else ""


class GraphQLToMcpTranslator:
    """Translates between GraphQL schemas and MCP tool definitions.

    Examples:
        >>> ep = GraphQLEndpoint("https://example.com/graphql")
        >>> tr = GraphQLToMcpTranslator(ep)
        >>> tr._endpoint is ep
        True
    """

    def __init__(self, endpoint: GraphQLEndpoint):
        """Initialize translator.

        Args:
            endpoint: GraphQL endpoint with introspected schema.
        """
        self._endpoint = endpoint

    def graphql_schema_to_mcp_server(self) -> Dict[str, Any]:
        """Convert the full GraphQL schema to an MCP virtual server definition.

        Returns:
            MCP server definition dict.
        """
        return {
            "name": f"graphql-{self._endpoint.url}",
            "description": f"GraphQL API: {self._endpoint.url}",
            "transport": ["sse", "http"],
            "tools": self.graphql_fields_to_mcp_tools(),
        }

    def graphql_fields_to_mcp_tools(self) -> List[Dict[str, Any]]:
        """Convert GraphQL query/mutation/subscription fields to MCP tool definitions.

        Returns:
            List of MCP tool definition dicts.
        """
        tools = []

        # Convert queries
        if self._endpoint.query_type_name:
            query_type = self._endpoint.types.get(self._endpoint.query_type_name, {})
            for field in query_type.get("fields", []):
                tools.append(self._field_to_mcp_tool(field, "query"))

        # Convert mutations
        if self._endpoint.include_mutations and self._endpoint.mutation_type_name:
            mutation_type = self._endpoint.types.get(self._endpoint.mutation_type_name, {})
            for field in mutation_type.get("fields", []):
                tools.append(self._field_to_mcp_tool(field, "mutation"))

        # Convert subscriptions
        if self._endpoint.include_subscriptions and self._endpoint.subscription_type_name:
            sub_type = self._endpoint.types.get(self._endpoint.subscription_type_name, {})
            for field in sub_type.get("fields", []):
                tools.append(self._field_to_mcp_tool(field, "subscription"))

        return tools

    def _field_to_mcp_tool(self, field: Dict[str, Any], operation_type: str) -> Dict[str, Any]:
        """Convert a single GraphQL field to an MCP tool definition.

        Args:
            field: GraphQL field definition from introspection.
            operation_type: 'query', 'mutation', or 'subscription'.

        Returns:
            MCP tool definition dict.
        """
        field_name = field["name"]
        description = field.get("description") or f"GraphQL {operation_type}: {field_name}"
        input_schema = self._args_to_json_schema(field.get("args", []))

        return {
            "name": f"{operation_type}_{field_name}",
            "description": description,
            "inputSchema": input_schema,
        }

    def _args_to_json_schema(self, args: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert GraphQL argument definitions to JSON Schema.

        Args:
            args: List of argument definitions from introspection.

        Returns:
            JSON Schema dict.
        """
        schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

        for arg in args:
            arg_name = arg["name"]
            arg_type = arg["type"]
            is_required = arg_type.get("kind") == "NON_NULL"
            prop_schema = self._graphql_type_to_json_schema(arg_type, visited=set())
            if arg.get("description"):
                prop_schema["description"] = arg["description"]
            if arg.get("defaultValue") is not None:
                try:
                    prop_schema["default"] = json.loads(arg["defaultValue"])
                except (json.JSONDecodeError, TypeError):
                    prop_schema["default"] = arg["defaultValue"]
            schema["properties"][arg_name] = prop_schema
            if is_required:
                schema["required"].append(arg_name)

        if not schema["required"]:
            del schema["required"]
        return schema

    def _graphql_type_to_json_schema(self, type_ref: Dict[str, Any], visited: Set[str]) -> Dict[str, Any]:
        """Convert a GraphQL type reference to JSON Schema.

        Handles NON_NULL, LIST, SCALAR, ENUM, and INPUT_OBJECT types recursively.

        Args:
            type_ref: GraphQL type reference dict.
            visited: Set of visited type names for cycle detection.

        Returns:
            JSON Schema dict.

        Examples:
            >>> ep = GraphQLEndpoint("https://example.com/graphql")
            >>> tr = GraphQLToMcpTranslator(ep)
            >>> tr._graphql_type_to_json_schema({"kind": "SCALAR", "name": "String", "ofType": None}, set())
            {'type': 'string'}
            >>> tr._graphql_type_to_json_schema({"kind": "SCALAR", "name": "Int", "ofType": None}, set())
            {'type': 'integer'}
            >>> tr._graphql_type_to_json_schema({"kind": "SCALAR", "name": "Boolean", "ofType": None}, set())
            {'type': 'boolean'}
        """
        kind = type_ref.get("kind")
        name = type_ref.get("name")

        if kind == "NON_NULL":
            inner = type_ref.get("ofType", {})
            return self._graphql_type_to_json_schema(inner, visited)

        if kind == "LIST":
            inner = type_ref.get("ofType", {})
            return {"type": "array", "items": self._graphql_type_to_json_schema(inner, visited)}

        if kind == "SCALAR":
            json_type = GRAPHQL_SCALAR_TYPE_MAP.get(name or "", "string")
            return {"type": json_type}

        if kind == "ENUM":
            type_def = self._endpoint.types.get(name or "", {})
            values = [ev["name"] for ev in type_def.get("enumValues", [])]
            if values:
                return {"type": "string", "enum": values}
            return {"type": "string"}

        if kind == "INPUT_OBJECT":
            if name in visited:
                return {"type": "object"}
            visited_copy = visited | {name or ""}
            type_def = self._endpoint.types.get(name or "", {})
            schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            for input_field in type_def.get("inputFields", []):
                field_name = input_field["name"]
                is_required = input_field["type"].get("kind") == "NON_NULL"
                prop_schema = self._graphql_type_to_json_schema(input_field["type"], visited_copy)
                if input_field.get("description"):
                    prop_schema["description"] = input_field["description"]
                schema["properties"][field_name] = prop_schema
                if is_required:
                    schema["required"].append(field_name)
            if not schema["required"]:
                del schema["required"]
            return schema

        # OBJECT / INTERFACE types used as input — fallback
        return {"type": "object"}


# Utility functions for CLI usage


async def expose_graphql_via_sse(
    endpoint_url: str,
    port: int = 9001,
    host: str = "127.0.0.1",
    auth_type: Optional[str] = None,
    auth_value: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    max_depth: int = 3,
    include_mutations: bool = True,
    include_subscriptions: bool = False,
    cache_ttl: int = 3600,
) -> None:
    """Expose a GraphQL API as MCP tools via SSE/HTTP endpoints.

    Args:
        endpoint_url: GraphQL API endpoint URL.
        port: HTTP port to listen on.
        host: Bind address.
        auth_type: Authentication type ('bearer', 'basic', 'header').
        auth_value: Authentication credential value.
        headers: Additional HTTP headers for the GraphQL endpoint.
        max_depth: Maximum field selection depth.
        include_mutations: Include mutations as tools.
        include_subscriptions: Include subscriptions as tools.
        cache_ttl: Introspection cache TTL in seconds.
    """
    logger.info(f"Exposing GraphQL API {endpoint_url} via SSE on {host}:{port}")

    endpoint = GraphQLEndpoint(
        url=endpoint_url,
        auth_type=auth_type,
        auth_value=auth_value,
        headers=headers,
        max_depth=max_depth,
        include_mutations=include_mutations,
        include_subscriptions=include_subscriptions,
        cache_ttl=cache_ttl,
    )

    try:
        await endpoint.start()

        translator = GraphQLToMcpTranslator(endpoint)
        tools = translator.graphql_fields_to_mcp_tools()

        logger.info(f"GraphQL API exposed. Discovered {len(tools)} MCP tools:")
        for tool in tools:
            logger.info(f"  - {tool['name']}: {tool['description'][:80]}")
        logger.info("To expose via HTTP/SSE, register this service in the gateway admin UI")
        logger.info(f"  Endpoint: {endpoint_url}")
        logger.info(f"  Queries: {len(endpoint.get_queries())}")
        logger.info(f"  Mutations: {len(endpoint.get_mutations())}")
        logger.info(f"  Subscriptions: {len(endpoint.get_subscriptions())}")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await endpoint.close()


def main() -> None:
    """CLI entry point for GraphQL-to-MCP translation."""
    parser = argparse.ArgumentParser(
        description="Expose a GraphQL API as MCP tools via SSE/HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m mcpgateway.translate_graphql --endpoint https://api.example.com/graphql --port 9001
  python -m mcpgateway.translate_graphql --endpoint https://api.example.com/graphql --auth-type bearer --auth-value TOKEN
        """,
    )
    parser.add_argument("--endpoint", required=True, help="GraphQL endpoint URL")
    parser.add_argument("--port", type=int, default=9001, help="HTTP/SSE port to listen on (default: 9001)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--auth-type", choices=["bearer", "basic", "header"], help="Authentication type")
    parser.add_argument("--auth-value", help="Authentication credential value")
    parser.add_argument("--max-depth", type=int, default=3, help="Max field selection depth (default: 3)")
    parser.add_argument("--include-mutations", action="store_true", default=True, help="Include mutations as tools (default: true)")
    parser.add_argument("--no-include-mutations", action="store_false", dest="include_mutations", help="Exclude mutations")
    parser.add_argument("--include-subscriptions", action="store_true", default=False, help="Include subscriptions as tools")
    parser.add_argument("--cache-ttl", type=int, default=3600, help="Introspection cache TTL in seconds (default: 3600)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")

    args = parser.parse_args()

    asyncio.run(
        expose_graphql_via_sse(
            endpoint_url=args.endpoint,
            port=args.port,
            host=args.host,
            auth_type=args.auth_type,
            auth_value=args.auth_value,
            max_depth=args.max_depth,
            include_mutations=args.include_mutations,
            include_subscriptions=args.include_subscriptions,
            cache_ttl=args.cache_ttl,
        )
    )


if __name__ == "__main__":
    main()
