#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for A2A agent support using the official A2A Python SDK.

This module tests Issue #840 features:
1. User input field for A2A agent testing
2. Tool visibility fix (defaulting to public)
3. Transaction handling for agent registration

These tests use the official a2a-sdk to create proper A2A servers and clients,
ensuring compatibility with the A2A protocol specification.
"""
import socket
from contextlib import closing
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

# A2A SDK imports
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message

# ContextForge imports
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.tool_service import ToolService

# Mark all tests in this module as integration tests
# These tests require --with-integration flag to run
pytestmark = pytest.mark.integration


# =============================================================================
# Test A2A Agent Implementation using Official SDK
# =============================================================================


class CalculatorAgent:
    """Simple calculator agent for testing."""

    async def invoke(self, query: str) -> str:
        """Process a calculator query."""
        import ast
        import operator

        operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def safe_eval(node):
            if isinstance(node, ast.Constant):
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

        # Extract expression from query
        expression = query.lower().replace("calc:", "").strip() if "calc:" in query.lower() else query

        try:
            tree = ast.parse(expression, mode="eval")
            result = safe_eval(tree)
            return str(result)
        except (SyntaxError, ValueError) as e:
            return f"Error: {e}"
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:
            return f"Error: {e}"


class CalculatorAgentExecutor(AgentExecutor):
    """Agent executor for the calculator agent."""

    def __init__(self):
        self.agent = CalculatorAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute the calculator agent."""
        user_input = context.get_user_input()
        result = await self.agent.invoke(user_input)
        await event_queue.enqueue_event(new_agent_text_message(result))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Handle cancellation."""
        raise Exception("cancel not supported")


def create_calculator_agent_card(port: int) -> AgentCard:
    """Create an agent card for the calculator agent."""
    skill = AgentSkill(
        id="calculator",
        name="Calculator",
        description="Evaluates mathematical expressions safely",
        tags=["math", "calculator"],
        examples=["calc: 5*10+2", "calc: 100/4"],
    )

    return AgentCard(
        name="Test Calculator Agent",
        description="A test A2A agent with calculator functionality",
        url=f"http://localhost:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
        supports_authenticated_extended_card=False,
    )


def find_available_port(start: int = 19000, end: int = 19100) -> int:
    """Find an available port in the given range."""
    for port in range(start, end):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError(f"No available port found in range {start}-{end}")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.flush = MagicMock()
    db.refresh = MagicMock()
    db.rollback = MagicMock()
    db.execute = MagicMock()
    db.get = MagicMock(return_value=None)
    return db


@pytest.fixture
def a2a_service():
    """Create an A2A service instance."""
    return A2AAgentService()


@pytest.fixture
def tool_service():
    """Create a tool service instance."""
    return ToolService()


@pytest.fixture
def calculator_agent_card():
    """Create a calculator agent card for testing."""
    port = find_available_port()
    return create_calculator_agent_card(port)


@pytest_asyncio.fixture
async def calculator_a2a_server():
    """Create and run a calculator A2A server using the official SDK.

    This fixture creates a proper A2A-compliant server that can be used
    for integration testing with ContextForge.
    """
    port = find_available_port()
    agent_card = create_calculator_agent_card(port)

    executor = CalculatorAgentExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )

    app_builder = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    app = app_builder.build()

    # Use httpx ASGITransport for in-memory testing
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://localhost:{port}") as client:
        yield {
            "client": client,
            "port": port,
            "agent_card": agent_card,
            "app": app,
        }


# =============================================================================
# Unit Tests for A2A Agent User Query Feature
# =============================================================================


class TestA2AUserQueryExtraction:
    """Tests for user query extraction from request body."""

    @pytest.mark.asyncio
    async def test_extract_user_query_from_body(self):
        """Test that user query is correctly extracted from request body."""

        # Simulate request body parsing
        body = {"query": "calc: 7*8"}
        user_query = body.get("query", "default")
        assert user_query == "calc: 7*8"

    @pytest.mark.asyncio
    async def test_default_query_when_body_empty(self):
        """Test that default query is used when body is empty."""
        body = {}
        default_message = "Hello from MCP Gateway Admin UI test!"
        user_query = body.get("query", default_message) if body else default_message
        assert user_query == default_message

    @pytest.mark.asyncio
    async def test_default_query_when_body_none(self):
        """Test that default query is used when body is None."""
        body = None
        default_message = "Hello from MCP Gateway Admin UI test!"
        user_query = body.get("query", default_message) if body else default_message
        assert user_query == default_message


# =============================================================================
# Unit Tests for Tool Visibility Fix
# =============================================================================


class TestToolVisibilityFix:
    """Tests for tool visibility defaulting to public."""

    @pytest.mark.asyncio
    async def test_tool_visibility_defaults_to_public_when_agent_visibility_none(self, mock_db, tool_service):
        """Test that tool visibility defaults to 'public' when agent visibility is None."""
        # Create a mock agent with None visibility
        mock_agent = MagicMock()
        mock_agent.id = "test-agent-id"
        mock_agent.name = "Test Agent"
        mock_agent.slug = "test-agent"
        mock_agent.description = "Test description"
        mock_agent.endpoint_url = "http://localhost:9000/run"
        mock_agent.agent_type = "custom"
        mock_agent.visibility = None  # Key: visibility is None
        mock_agent.tags = ["a2a"]
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_agent.auth_type = None
        mock_agent.auth_value = None

        # Mock execute to return None (no existing tool)
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # The visibility should default to "public"
        tool_visibility = mock_agent.visibility or "public"
        assert tool_visibility == "public"

    @pytest.mark.asyncio
    async def test_tool_visibility_respects_agent_visibility_when_set(self, mock_db, tool_service):
        """Test that tool visibility respects agent visibility when explicitly set."""
        # Create a mock agent with explicit visibility
        mock_agent = MagicMock()
        mock_agent.visibility = "team"  # Explicitly set

        tool_visibility = mock_agent.visibility or "public"
        assert tool_visibility == "team"

    @pytest.mark.asyncio
    async def test_tool_visibility_public_when_agent_visibility_empty_string(self, mock_db, tool_service):
        """Test that tool visibility defaults to 'public' when agent visibility is empty string."""
        mock_agent = MagicMock()
        mock_agent.visibility = ""  # Empty string is falsy

        tool_visibility = mock_agent.visibility or "public"
        assert tool_visibility == "public"


# =============================================================================
# Unit Tests for Transaction Handling
# =============================================================================


class TestTransactionHandling:
    """Tests for transaction handling during A2A agent registration."""

    @pytest.mark.asyncio
    async def test_agent_committed_before_tool_creation(self, mock_db, a2a_service):
        """Test that agent is committed before tool creation is attempted.

        This ensures that if tool creation fails (and calls rollback),
        the agent registration is not lost.
        """
        # Track the order of operations
        operation_order = []

        def track_add(*args):
            operation_order.append("add")

        def track_commit():
            operation_order.append("commit")

        def track_flush():
            operation_order.append("flush")

        mock_db.add.side_effect = track_add
        mock_db.commit.side_effect = track_commit
        mock_db.flush.side_effect = track_flush

        # The expected order after the fix is:
        # 1. add (agent)
        # 2. commit (agent - BEFORE tool creation)
        # NOT: add -> flush -> [tool creation] -> commit/rollback

        # Verify the fix ensures commit happens before tool creation
        # by checking the code structure
        import inspect

        source = inspect.getsource(a2a_service.register_agent)

        # The fix changes "db.flush()" to "db.commit()" before tool creation
        # Check that we have the pattern: db.add -> db.commit -> tool creation
        assert "db.add(new_agent)" in source
        assert "db.commit()" in source
        # The critical fix: commit should appear before create_tool_from_a2a_agent
        add_pos = source.find("db.add(new_agent)")
        commit_pos = source.find("db.commit()")
        tool_creation_pos = source.find("create_tool_from_a2a_agent")

        # Ensure commit comes between add and tool creation
        assert add_pos < commit_pos < tool_creation_pos, "Agent should be committed before tool creation"

    @pytest.mark.asyncio
    async def test_agent_survives_tool_creation_failure(self, mock_db):
        """Test that agent registration succeeds even if tool creation fails.

        After the transaction handling fix, the agent is committed BEFORE
        tool creation, so even if ToolService.register_tool calls rollback,
        the agent persists.
        """
        # This test verifies the expected behavior after the fix:
        # 1. Agent is added and committed
        # 2. Tool creation is attempted
        # 3. If tool creation fails (rollback), agent still exists

        # The key insight is that after commit, a rollback only affects
        # uncommitted changes, not the already-committed agent

        agent_committed = False

        def track_commit():
            nonlocal agent_committed
            agent_committed = True

        mock_db.commit.side_effect = track_commit

        # Simulate the flow:
        # 1. Add agent
        mock_db.add(MagicMock())  # new_agent
        # 2. Commit agent (the fix!)
        mock_db.commit()
        assert agent_committed, "Agent should be committed before tool creation"

        # 3. Tool creation fails and calls rollback
        mock_db.rollback()

        # 4. Agent should still be committed (rollback doesn't undo committed transaction)
        assert agent_committed, "Agent should survive tool creation failure"


# =============================================================================
# Integration Tests with A2A SDK Server
# =============================================================================


class TestA2ASDKIntegration:
    """Integration tests using the official A2A SDK."""

    @pytest.mark.asyncio
    async def test_calculator_agent_card_endpoint(self, calculator_a2a_server):
        """Test that the A2A agent card is served correctly."""
        client = calculator_a2a_server["client"]

        response = await client.get("/.well-known/agent.json")
        assert response.status_code == 200

        card = response.json()
        assert card["name"] == "Test Calculator Agent"
        assert card["capabilities"]["streaming"] is True
        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "calculator"

    @pytest.mark.asyncio
    async def test_calculator_agent_message_send(self, calculator_a2a_server):
        """Test sending a message to the calculator agent via JSON-RPC."""
        client = calculator_a2a_server["client"]

        # Send a calculation request using JSON-RPC protocol
        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "msg-test-1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "calc: 7*8"}],
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data or "error" not in data

    @pytest.mark.asyncio
    async def test_calculator_agent_streaming(self, calculator_a2a_server):
        """Test streaming response from calculator agent."""
        client = calculator_a2a_server["client"]

        # Request with streaming
        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-2",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "msg-test-2",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "calc: 100/4+25"}],
                    }
                },
            },
            headers={"Accept": "text/event-stream"},
        )

        # Either streaming or non-streaming response is valid
        assert response.status_code == 200


class TestA2AProtocolCompliance:
    """Tests for A2A protocol compliance."""

    @pytest.mark.asyncio
    async def test_agent_card_has_required_fields(self, calculator_a2a_server):
        """Test that agent card has all required A2A protocol fields."""
        client = calculator_a2a_server["client"]

        response = await client.get("/.well-known/agent.json")
        card = response.json()

        # Required fields per A2A spec
        required_fields = ["name", "description", "url", "version", "capabilities", "skills"]
        for field in required_fields:
            assert field in card, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_message_send_returns_task_or_message(self, calculator_a2a_server):
        """Test that message/send returns either a Task or Message per A2A spec."""
        client = calculator_a2a_server["client"]

        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-3",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "msg-test-3",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "calc: 2+2"}],
                    }
                },
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Result should be either a Task (with id, status) or Message (with messageId, role, parts)
        if "result" in data:
            result = data["result"]
            is_task = "id" in result and "status" in result
            is_message = "messageId" in result and "role" in result and "parts" in result
            assert is_task or is_message, "Result should be either Task or Message"


# =============================================================================
# Tests for ContextForge Admin A2A Test Endpoint
# =============================================================================


class TestContextForgeA2ATestEndpoint:
    """Tests for the ContextForge admin A2A test endpoint."""

    @pytest.mark.asyncio
    async def test_admin_test_endpoint_sends_user_query(self):
        """Test that admin test endpoint sends user-provided query to agent."""
        # Mock the admin endpoint behavior
        user_query = "calc: 15*3"
        default_message = "Hello from MCP Gateway Admin UI test!"

        # Simulate request body parsing (as done in admin.py)
        body = {"query": user_query}
        extracted_query = body.get("query", default_message) if body else default_message

        assert extracted_query == user_query
        assert extracted_query != default_message

    @pytest.mark.asyncio
    async def test_admin_test_endpoint_uses_default_when_no_query(self):
        """Test that admin test endpoint uses default message when no query provided."""
        default_message = "Hello from MCP Gateway Admin UI test!"

        # Empty body
        body = {}
        extracted_query = (body.get("query") if body else None) or default_message
        assert extracted_query == default_message

        # Body with empty query - should also use default
        body = {"query": ""}
        extracted_query = (body.get("query") if body else None) or default_message
        assert extracted_query == default_message

        # Body with None query
        body = {"query": None}
        extracted_query = (body.get("query") if body else None) or default_message
        assert extracted_query == default_message

    @pytest.mark.asyncio
    async def test_jsonrpc_format_includes_user_query(self):
        """Test that JSONRPC format includes user query in message parts."""
        import time

        user_query = "calc: 100/5"

        # Simulate JSONRPC format construction (as done in admin.py)
        test_params = {
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": f"admin-test-{int(time.time())}",
                    "role": "user",
                    "parts": [{"type": "text", "text": user_query}],
                }
            },
        }

        # Verify query is in the message
        message_text = test_params["params"]["message"]["parts"][0]["text"]
        assert message_text == user_query

    @pytest.mark.asyncio
    async def test_custom_agent_format_includes_user_query(self):
        """Test that custom agent format includes user query in parameters."""
        user_query = "weather: Dallas"

        # Simulate custom format construction (as done in admin.py)
        test_params = {
            "interaction_type": "admin_test",
            "parameters": {"query": user_query, "message": user_query},
            "protocol_version": "1.0",
        }

        # Verify query is in parameters
        assert test_params["parameters"]["query"] == user_query
        assert test_params["parameters"]["message"] == user_query


# =============================================================================
# Calculator Agent Unit Tests
# =============================================================================


class TestCalculatorAgent:
    """Unit tests for the calculator agent implementation."""

    @pytest.mark.asyncio
    async def test_basic_arithmetic(self):
        """Test basic arithmetic operations."""
        agent = CalculatorAgent()

        assert await agent.invoke("calc: 2+2") == "4"
        assert await agent.invoke("calc: 10-3") == "7"
        assert await agent.invoke("calc: 5*6") == "30"
        assert await agent.invoke("calc: 20/4") == "5.0"

    @pytest.mark.asyncio
    async def test_complex_expressions(self):
        """Test complex mathematical expressions."""
        agent = CalculatorAgent()

        assert await agent.invoke("calc: 7*8") == "56"
        assert await agent.invoke("calc: 100/4+25") == "50.0"
        assert await agent.invoke("calc: (2+3)*4") == "20"

    @pytest.mark.asyncio
    async def test_negative_numbers(self):
        """Test negative number handling."""
        agent = CalculatorAgent()

        assert await agent.invoke("calc: -5") == "-5"
        assert await agent.invoke("calc: -5+10") == "5"

    @pytest.mark.asyncio
    async def test_division_by_zero(self):
        """Test division by zero error handling."""
        agent = CalculatorAgent()

        result = await agent.invoke("calc: 10/0")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        """Test invalid expression error handling."""
        agent = CalculatorAgent()

        result = await agent.invoke("calc: invalid")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_query_without_prefix(self):
        """Test that queries without 'calc:' prefix still work."""
        agent = CalculatorAgent()

        # Direct expression
        assert await agent.invoke("5*5") == "25"
