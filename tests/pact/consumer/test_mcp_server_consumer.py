# -*- coding: utf-8 -*-
"""Consumer contract tests: Gateway calling MCP servers.

These tests define what the Gateway expects from upstream MCP servers.
Each test generates a pact file capturing the expected interaction contract.
The pact files are written to the ``pacts/`` directory and can later be
verified against real MCP server implementations.
"""

import json

import httpx
import pytest

from pact import Pact
from pact import match as m


@pytest.mark.pact
class TestMCPServerToolsContract:
    """Contract tests for MCP server tools/list and tools/call interactions."""

    def test_tools_list(self, pact_dir):
        """Gateway expects MCP server to return a tools list via JSON-RPC."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a tools/list request")
            .given("MCP server is running with tools")
            .with_request("POST", "/")
            .with_body(
                json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1}),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(1),
                    "result": {
                        "tools": m.each_like(
                            {
                                "name": m.string("example-tool"),
                                "description": m.string("An example tool"),
                                "inputSchema": m.like(
                                    {
                                        "type": "object",
                                        "properties": m.like({}),
                                    }
                                ),
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["jsonrpc"] == "2.0"
            assert "result" in body
            assert "tools" in body["result"]

        pact.write_file(pact_dir, overwrite=True)

    def test_tools_call(self, pact_dir):
        """Gateway expects MCP server to execute a tool and return results."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a tools/call request")
            .given("MCP server has tool 'weather' registered")
            .with_request("POST", "/")
            .with_body(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "id": 2,
                        "params": {
                            "name": "weather",
                            "arguments": {"city": "NYC"},
                        },
                    }
                ),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(2),
                    "result": {
                        "content": m.each_like(
                            {
                                "type": m.string("text"),
                                "text": m.string("Weather data for NYC"),
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "weather", "arguments": {"city": "NYC"}},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["jsonrpc"] == "2.0"
            assert "result" in body
            assert len(body["result"]["content"]) >= 1

        pact.write_file(pact_dir, overwrite=True)


@pytest.mark.pact
class TestMCPServerResourcesContract:
    """Contract tests for MCP server resources/list and resources/read."""

    def test_resources_list(self, pact_dir):
        """Gateway expects MCP server to return a resources list."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a resources/list request")
            .given("MCP server has resources available")
            .with_request("POST", "/")
            .with_body(
                json.dumps({"jsonrpc": "2.0", "method": "resources/list", "id": 3}),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(3),
                    "result": {
                        "resources": m.each_like(
                            {
                                "uri": m.string("file:///example.txt"),
                                "name": m.string("example.txt"),
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={"jsonrpc": "2.0", "method": "resources/list", "id": 3},
            )
            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert "resources" in body["result"]

        pact.write_file(pact_dir, overwrite=True)

    def test_resources_read(self, pact_dir):
        """Gateway expects MCP server to return resource content."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a resources/read request")
            .given("MCP server has resource 'file:///example.txt'")
            .with_request("POST", "/")
            .with_body(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "resources/read",
                        "id": 4,
                        "params": {"uri": "file:///example.txt"},
                    }
                ),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(4),
                    "result": {
                        "contents": m.each_like(
                            {
                                "uri": m.string("file:///example.txt"),
                                "text": m.string("Example file content"),
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/read",
                    "id": 4,
                    "params": {"uri": "file:///example.txt"},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert len(body["result"]["contents"]) >= 1

        pact.write_file(pact_dir, overwrite=True)


@pytest.mark.pact
class TestMCPServerPromptsContract:
    """Contract tests for MCP server prompts/list and prompts/get."""

    def test_prompts_list(self, pact_dir):
        """Gateway expects MCP server to return a prompts list."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a prompts/list request")
            .given("MCP server has prompts available")
            .with_request("POST", "/")
            .with_body(
                json.dumps({"jsonrpc": "2.0", "method": "prompts/list", "id": 5}),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(5),
                    "result": {
                        "prompts": m.each_like(
                            {
                                "name": m.string("summarize"),
                                "description": m.string("Summarize the given text"),
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={"jsonrpc": "2.0", "method": "prompts/list", "id": 5},
            )
            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert "prompts" in body["result"]

        pact.write_file(pact_dir, overwrite=True)

    def test_prompts_get(self, pact_dir):
        """Gateway expects MCP server to return prompt details with messages."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("a prompts/get request")
            .given("MCP server has prompt 'summarize'")
            .with_request("POST", "/")
            .with_body(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "prompts/get",
                        "id": 6,
                        "params": {
                            "name": "summarize",
                            "arguments": {"text": "Hello world"},
                        },
                    }
                ),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(6),
                    "result": {
                        "messages": m.each_like(
                            {
                                "role": m.string("user"),
                                "content": {
                                    "type": m.string("text"),
                                    "text": m.string("Please summarize: Hello world"),
                                },
                            },
                            min=1,
                        ),
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "prompts/get",
                    "id": 6,
                    "params": {"name": "summarize", "arguments": {"text": "Hello world"}},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert len(body["result"]["messages"]) >= 1

        pact.write_file(pact_dir, overwrite=True)


@pytest.mark.pact
class TestMCPServerInitializeContract:
    """Contract tests for MCP server initialize handshake."""

    def test_initialize(self, pact_dir):
        """Gateway expects MCP server to respond to initialize with capabilities."""
        pact = Pact("mcp-gateway", "mcp-server").with_specification("V4")

        (
            pact.upon_receiving("an initialize request")
            .given("MCP server is ready")
            .with_request("POST", "/")
            .with_body(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "id": 0,
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "mcp-gateway", "version": "1.0.0"},
                        },
                    }
                ),
                content_type="application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": m.string("2.0"),
                    "id": m.integer(0),
                    "result": {
                        "protocolVersion": m.string("2025-11-25"),
                        "capabilities": m.like({}),
                        "serverInfo": {
                            "name": m.string("example-server"),
                            "version": m.string("1.0.0"),
                        },
                    },
                },
                content_type="application/json",
            )
        )

        with pact.serve() as srv:
            response = httpx.post(
                f"{srv.url}/",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": 0,
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-gateway", "version": "1.0.0"},
                    },
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert "result" in body
            assert "protocolVersion" in body["result"]
            assert "serverInfo" in body["result"]

        pact.write_file(pact_dir, overwrite=True)
