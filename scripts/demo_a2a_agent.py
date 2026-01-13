#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo A2A Agent for Issue #840 Testing.

This script creates a simple A2A agent with calculator and weather tools,
runs it on an available port, and registers it with ContextForge.

Usage:
    uv run python scripts/demo_a2a_agent.py

The agent supports queries like:
    - "calc: 5*10+2"
    - "weather: Dallas"

Press Ctrl+C to stop the server and unregister the agent.
"""

import atexit
import os
import random
import signal
import socket
import sys
from contextlib import closing

import httpx
import jwt
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# ============================================================================
# A2A Agent Implementation (from Issue #840)
# ============================================================================


def calculator(expression: str) -> str:
    """Evaluate a math expression safely using ast module."""
    import ast
    import operator

    # Supported operators for safe evaluation
    operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def safe_eval(node):
        """Recursively evaluate an AST node safely."""
        if isinstance(node, ast.Constant):  # Python 3.8+
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Invalid constant type: {type(node.value)}")
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in operators:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            left = safe_eval(node.left)
            right = safe_eval(node.right)
            return operators[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in operators:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            operand = safe_eval(node.operand)
            return operators[type(node.op)](operand)
        elif isinstance(node, ast.Expression):
            return safe_eval(node.body)
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    try:
        # Parse the expression into an AST
        tree = ast.parse(expression, mode="eval")
        result = safe_eval(tree)
        return str(result)
    except (SyntaxError, ValueError) as e:
        return f"Error: {e}"
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error: {e}"


def weather(city: str) -> str:
    """Mock weather lookup tool."""
    conditions = ["sunny", "rainy", "cloudy", "stormy"]
    temp = random.randint(10, 35)
    return f"The weather in {city} is {random.choice(conditions)}, {temp}C"


class SimpleAgent:
    """Simple A2A agent that routes queries to tools."""

    def __init__(self, name: str = "Agent"):
        self.name = name
        self.tools = {
            "calculator": calculator,
            "weather": weather,
        }

    def run(self, query: str) -> str:
        """Process a query and route to appropriate tool."""
        if "calc:" in query.lower():
            expr = query.lower().replace("calc:", "").strip()
            return self.tools["calculator"](expr)
        elif "weather:" in query.lower():
            city = query.lower().replace("weather:", "").strip()
            return self.tools["weather"](city.title())
        else:
            return f"{self.name} received: {query}. Try 'calc: 5*10' or 'weather: Dallas'"


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(title="Demo A2A Agent", description="Calculator and Weather Agent for Issue #840")
agent = SimpleAgent("Demo-A2A-Agent")


class Parameters(BaseModel):
    """Parameters object containing the actual query."""

    query: str = ""
    message: str = ""


class A2ARequest(BaseModel):
    """Request model for A2A protocol format.

    ContextForge sends custom agents requests in this format:
    {
        "interaction_type": "admin_test",
        "parameters": {"query": "weather: Dallas", "message": "..."},
        "protocol_version": "1.0"
    }
    """

    interaction_type: str = ""
    parameters: Parameters | None = None
    protocol_version: str = ""
    # Also support direct query/message for simple testing
    query: str = ""
    message: str = ""


class Response(BaseModel):
    """Response model for agent results."""

    response: str


@app.post("/run")
def run_agent(req: A2ARequest) -> Response:
    """Execute a query against the agent.

    Supports both:
    - A2A protocol format: {"parameters": {"query": "..."}}
    - Simple format: {"query": "..."}
    """
    # Extract query from A2A protocol format (parameters.query)
    # or fall back to direct query/message fields
    query_text = ""
    if req.parameters:
        query_text = req.parameters.query or req.parameters.message
    if not query_text:
        query_text = req.query or req.message or "Hello"

    response = agent.run(query_text)
    return Response(response=response)


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": agent.name}


# ============================================================================
# ContextForge Registration
# ============================================================================

# Configuration from environment with fallbacks for local development
CONTEXTFORGE_URL = os.environ.get("CONTEXTFORGE_URL", "http://localhost:8000")
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "my-test-key")  # noqa: S105 - default for demo only
AGENT_ID = None


def create_jwt_token(username: str = "admin@example.com") -> str:
    """Create a JWT token for ContextForge authentication."""
    import datetime

    payload = {
        "sub": username,
        "email": username,
        "iat": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        "exp": int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).timestamp()),
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "teams": [],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def register_agent(port: int) -> str | None:
    """Register the A2A agent with ContextForge."""
    global AGENT_ID

    token = create_jwt_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    agent_data = {
        "agent": {
            "name": "Demo Calculator Agent",
            "description": "Demo A2A Agent with calculator and weather tools (Issue #840)",
            "endpoint_url": f"http://localhost:{port}/run",
            "agent_type": "custom",
            "protocol_version": "1.0",
            "capabilities": {"tools": ["calculator", "weather"]},
            "config": {},
            "tags": ["demo", "calculator", "weather", "issue-840"],
        },
        "visibility": "public",
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(f"{CONTEXTFORGE_URL}/a2a", headers=headers, json=agent_data)

            if response.status_code == 201:
                data = response.json()
                AGENT_ID = data.get("id")
                print(f"Registered A2A agent with ContextForge: {AGENT_ID}")
                print(f"  Name: {data.get('name')}")
                print(f"  Endpoint: {data.get('endpointUrl')}")
                return AGENT_ID
            else:
                print(f"Failed to register agent: {response.status_code}")
                print(f"  Response: {response.text}")
                return None
    except Exception as e:
        print(f"Error registering agent: {e}")
        return None


def unregister_agent():
    """Unregister the A2A agent from ContextForge."""
    if not AGENT_ID:
        return

    token = create_jwt_token()
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.Client(timeout=10) as client:
            response = client.delete(f"{CONTEXTFORGE_URL}/a2a/{AGENT_ID}", headers=headers)
            if response.status_code in (200, 204):
                print(f"Unregistered A2A agent: {AGENT_ID}")
            else:
                print(f"Failed to unregister agent: {response.status_code}")
    except Exception as e:
        print(f"Error unregistering agent: {e}")


def find_available_port(start: int = 9100, end: int = 9200) -> int:
    """Find an available port in the given range."""
    for port in range(start, end):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError(f"No available port found in range {start}-{end}")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Run the demo A2A agent."""
    # Find available port
    port = find_available_port()
    print(f"\n{'='*60}")
    print("Demo A2A Agent for Issue #840")
    print(f"{'='*60}")
    print(f"Starting agent on port {port}...")
    print("\nSupported queries:")
    print("  - calc: 5*10+2")
    print("  - weather: Dallas")
    print("\nPress Ctrl+C to stop\n")

    # Register cleanup handler
    atexit.register(unregister_agent)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        unregister_agent()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Register with ContextForge
    register_agent(port)

    # Start the server
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
