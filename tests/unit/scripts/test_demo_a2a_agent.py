# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Location: ./tests/unit/scripts/test_demo_a2a_agent.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for scripts/demo_a2a_agent.py request parsing and agent logic.

Uses the FastAPI TestClient to exercise the /run endpoint's multi-format
request parsing (JSONRPC, A2A protocol, simple, nested message parts)
and the calculator/weather tool routing.
"""

import json

import pytest
from fastapi.testclient import TestClient

from scripts.demo_a2a_agent import SimpleAgent, app, calculator

# ---------------------------------------------------------------------------
# TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Return a TestClient for the demo agent FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# /run endpoint — format parsing
# ---------------------------------------------------------------------------


class TestRunEndpointFormats:
    """Test the /run endpoint handles all supported request formats."""

    def test_simple_query_format(self, client):
        """Simple {"query": "..."} format extracts correctly."""
        resp = client.post("/run", json={"query": "calc: 2+3"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "5"

    def test_simple_message_format(self, client):
        """Simple {"message": "..."} format extracts correctly."""
        resp = client.post("/run", json={"message": "calc: 10*2"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "20"

    def test_a2a_protocol_format_query(self, client):
        """A2A protocol {"parameters": {"query": "..."}} format."""
        resp = client.post("/run", json={"parameters": {"query": "calc: 7+3"}})
        assert resp.status_code == 200
        assert resp.json()["response"] == "10"

    def test_a2a_protocol_format_message(self, client):
        """A2A protocol {"parameters": {"message": "..."}} format."""
        resp = client.post("/run", json={"parameters": {"message": "calc: 9-4"}})
        assert resp.status_code == 200
        assert resp.json()["response"] == "5"

    def test_jsonrpc_simple_query(self, client):
        """JSONRPC format with simple query param."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"query": "calc: 6*7"},
            "id": 1,
        }
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        assert resp.json()["response"] == "42"

    def test_jsonrpc_simple_message(self, client):
        """JSONRPC format with simple message string param."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"message": "calc: 100/4"},
            "id": 1,
        }
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        assert resp.json()["response"] == "25.0"

    def test_jsonrpc_nested_message_parts(self, client):
        """JSONRPC with nested message.parts (Admin UI test button format)."""
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "test-1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "calc: 3+3"}],
                }
            },
            "id": 1,
        }
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        assert resp.json()["response"] == "6"

    def test_jsonrpc_nested_message_no_text_part(self, client):
        """JSONRPC with nested message but no text part falls back to default."""
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "test-2",
                    "role": "user",
                    "parts": [{"kind": "image", "url": "http://example.com/img.png"}],
                }
            },
            "id": 1,
        }
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        # Falls back to "Hello" default
        assert "received: Hello" in resp.json()["response"]

    def test_empty_body_returns_default(self, client):
        """Empty JSON object falls back to default Hello."""
        resp = client.post("/run", json={})
        assert resp.status_code == 200
        assert "received: Hello" in resp.json()["response"]

    def test_invalid_json_returns_error(self, client):
        """Non-JSON body returns an error response."""
        resp = client.post("/run", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        assert "invalid JSON" in resp.json()["response"]

    def test_a2a_protocol_with_interaction_type(self, client):
        """Full A2A protocol payload with interaction_type and protocol_version."""
        payload = {
            "interaction_type": "admin_test",
            "parameters": {"query": "weather: Dallas"},
            "protocol_version": "1.0",
        }
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        assert "Dallas" in resp.json()["response"]

    def test_jsonrpc_empty_params(self, client):
        """JSONRPC with empty params falls back to default."""
        payload = {"jsonrpc": "2.0", "method": "test", "params": {}, "id": 1}
        resp = client.post("/run", json=payload)
        assert resp.status_code == 200
        assert "received: Hello" in resp.json()["response"]


# ---------------------------------------------------------------------------
# Calculator tool
# ---------------------------------------------------------------------------


class TestCalculator:
    """Test the calculator function directly."""

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("2+3", "5"),
            ("10*5", "50"),
            ("100/4", "25.0"),
            ("10-3", "7"),
            ("-5", "-5"),
        ],
    )
    def test_basic_operations(self, expr, expected):
        assert calculator(expr) == expected

    def test_division_by_zero(self):
        assert calculator("1/0") == "Error: Division by zero"

    def test_invalid_expression(self):
        result = calculator("not_math")
        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# SimpleAgent routing
# ---------------------------------------------------------------------------


class TestSimpleAgent:
    """Test SimpleAgent query routing."""

    def setup_method(self):
        self.agent = SimpleAgent("TestAgent")

    def test_calc_routing(self):
        result = self.agent.run("calc: 2+2")
        assert result == "4"

    def test_weather_routing(self):
        result = self.agent.run("weather: London")
        assert "London" in result

    def test_unknown_query(self):
        result = self.agent.run("hello world")
        assert "TestAgent received: hello world" in result
        assert "calc:" in result.lower() or "weather:" in result.lower()


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_status(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "agent" in data
