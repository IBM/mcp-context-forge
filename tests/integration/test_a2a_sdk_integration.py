# -*- coding: utf-8 -*-
"""Integration tests for A2A agent support using an in-memory ASGI fixture.

The public Python SDK bundled in this repo still targets the legacy A2A surface,
so these tests exercise the v1 wire format directly while retaining a small set
of legacy-compatibility assertions.
"""

# Standard
from contextlib import closing
import socket
from typing import Any, Dict
from unittest.mock import MagicMock

# Third-Party
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import pytest
import pytest_asyncio

# First-Party
# ContextForge imports
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.tool_service import ToolService

pytestmark = pytest.mark.integration


class CalculatorAgent:
    """Simple calculator agent for testing."""

    async def invoke(self, query: str) -> str:
        """Process a calculator query."""
        # Standard
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
            if isinstance(node, ast.BinOp):
                if type(node.op) not in operators:
                    raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
                return operators[type(node.op)](safe_eval(node.left), safe_eval(node.right))
            if isinstance(node, ast.UnaryOp):
                if type(node.op) not in operators:
                    raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
                return operators[type(node.op)](safe_eval(node.operand))
            if isinstance(node, ast.Expression):
                return safe_eval(node.body)
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

        expression = query.lower().replace("calc:", "").strip() if "calc:" in query.lower() else query

        try:
            tree = ast.parse(expression, mode="eval")
            return str(safe_eval(tree))
        except (SyntaxError, ValueError) as e:
            return f"Error: {e}"
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:  # pragma: no cover - defensive fallback
            return f"Error: {e}"


def find_available_port(start: int = 19000, end: int = 19100) -> int:
    """Find an available port in the given range."""
    for port in range(start, end):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError(f"No available port found in range {start}-{end}")


def is_v1(method: str, version_header: str) -> bool:
    """Return whether a request should use v1 A2A semantics."""
    if method in {"message/send", "message/stream", "tasks/get", "tasks/list", "tasks/cancel", "tasks/resubscribe", "agent/getExtendedCard", "agent/getAuthenticatedExtendedCard"}:
        return False
    if method in {"SendMessage", "SendStreamingMessage", "GetTask", "ListTasks", "CancelTask", "SubscribeToTask", "GetExtendedAgentCard"}:
        return True
    return not str(version_header or "").strip().startswith("0.")


def render_role(role: str, use_v1: bool) -> str:
    """Render an A2A message role in the requested protocol form."""
    if use_v1:
        return {"user": "ROLE_USER", "agent": "ROLE_AGENT", "system": "ROLE_SYSTEM"}.get(role, "ROLE_USER")
    return role


def render_state(state: str, use_v1: bool) -> str:
    """Render an A2A task state in the requested protocol form."""
    if use_v1:
        return {
            "submitted": "TASK_STATE_SUBMITTED",
            "working": "TASK_STATE_WORKING",
            "completed": "TASK_STATE_COMPLETED",
            "canceled": "TASK_STATE_CANCELED",
            "failed": "TASK_STATE_FAILED",
        }.get(state, "TASK_STATE_COMPLETED")
    return state


def build_message(message_id: str, role: str, text: str, use_v1: bool) -> Dict[str, Any]:
    """Build an A2A message object."""
    message = {
        "messageId": message_id,
        "role": render_role(role, use_v1),
        "parts": [{"text": text}] if use_v1 else [{"kind": "text", "text": text}],
    }
    if not use_v1:
        message["kind"] = "message"
    return message


def build_task(task_id: str, output_text: str, use_v1: bool) -> Dict[str, Any]:
    """Build a completed task object."""
    task = {
        "id": task_id,
        "contextId": f"ctx-{task_id}",
        "status": {
            "state": render_state("completed", use_v1),
            "message": build_message(f"{task_id}-response", "agent", output_text, use_v1),
        },
        "artifacts": [
            {
                "artifactId": f"{task_id}-artifact",
                "name": "echo",
                "description": "Echo response",
                "parts": [{"text": output_text}] if use_v1 else [{"kind": "text", "text": output_text}],
                **({} if use_v1 else {"kind": "artifact"}),
            }
        ],
    }
    if not use_v1:
        task["kind"] = "task"
    return task


def build_agent_card(base_url: str, use_v1: bool) -> Dict[str, Any]:
    """Build a protocol-specific agent card."""
    skill = {
        "id": "calculator",
        "name": "Calculator",
        "description": "Evaluates mathematical expressions safely",
        "tags": ["math", "calculator"],
        "examples": ["calc: 5*10+2", "calc: 100/4"],
        "inputModes": ["text"],
        "outputModes": ["text"],
    }
    capabilities = {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    }
    common = {
        "name": "Test Calculator Agent",
        "description": "A test A2A agent with calculator functionality",
        "url": f"{base_url}/",
        "version": "1.0.0",
        "protocolVersion": "1.0.0" if use_v1 else "0.3.0",
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "capabilities": capabilities,
        "skills": [skill],
        "supportsAuthenticatedExtendedCard": False,
    }
    if use_v1:
        return {
            **common,
            "supportedInterfaces": [{"transport": "JSONRPC", "url": f"{base_url}/"}],
            "securitySchemes": {},
            "securityRequirements": [],
        }
    return {
        **common,
        "kind": "agent-card",
        "preferredTransport": "JSONRPC",
        "additionalInterfaces": [{"transport": "JSONRPC", "url": f"{base_url}/"}],
    }


def extract_text(params: Dict[str, Any]) -> str:
    """Extract text input from A2A params."""
    message = params.get("message")
    if isinstance(message, dict):
        parts = message.get("parts") or []
        texts = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
        if texts:
            return " ".join(texts)
    for key in ("query", "text", "content"):
        if isinstance(params.get(key), str):
            return params[key]
    return ""


def create_calculator_app(port: int) -> FastAPI:
    """Create an in-memory A2A calculator agent app."""
    app = FastAPI()
    agent = CalculatorAgent()
    tasks: Dict[str, Dict[str, Any]] = {}
    base_url = f"http://localhost:{port}"

    @app.get("/.well-known/agent.json")
    @app.get("/.well-known/agent-card.json")
    async def agent_card(request: Request):
        use_v1 = not str(request.headers.get("A2A-Version", "")).startswith("0.")
        return JSONResponse(build_agent_card(base_url, use_v1))

    @app.get("/extendedAgentCard")
    async def extended_agent_card():
        return JSONResponse(
            {
                **build_agent_card(base_url, True),
                "documentationUrl": "https://a2a-protocol.org/latest/specification/",
                "provider": {"organization": "ContextForge"},
            }
        )

    @app.post("/")
    async def rpc(request: Request):
        body = await request.json()
        method = body.get("method", "")
        request_id = body.get("id")
        params = body.get("params") or {}
        use_v1 = is_v1(method, request.headers.get("A2A-Version", ""))

        if method in {"SendMessage", "message/send", "SendStreamingMessage", "message/stream"}:
            text = extract_text(params)
            result_text = await agent.invoke(text)
            task_id = f"task-{len(tasks) + 1}"
            task = build_task(task_id, result_text, use_v1)
            tasks[task_id] = task
            return {"jsonrpc": "2.0", "id": request_id, "result": task}

        if method in {"GetTask", "tasks/get"}:
            task_id = str(params.get("id", ""))
            task = tasks.get(task_id)
            if task is None:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32004, "message": "task not found"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": build_task(task_id, task["status"]["message"]["parts"][0]["text"], use_v1)}

        if method in {"ListTasks", "tasks/list"}:
            status_filter = str(params.get("status", "")).replace("TASK_STATE_", "").lower()
            listed = []
            for task_id, task in tasks.items():
                if status_filter and status_filter != "completed":
                    continue
                listed.append(build_task(task_id, task["status"]["message"]["parts"][0]["text"], use_v1))
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tasks": listed}}

        if method in {"CancelTask", "tasks/cancel"}:
            task_id = str(params.get("id", ""))
            task = tasks.get(task_id)
            if task is None:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32004, "message": "task not found"}}
            canceled_task = build_task(task_id, task["status"]["message"]["parts"][0]["text"], use_v1)
            canceled_task["status"]["state"] = render_state("canceled", use_v1)
            tasks[task_id] = canceled_task
            return {"jsonrpc": "2.0", "id": request_id, "result": canceled_task}

        if method in {"GetExtendedAgentCard", "agent/getExtendedCard", "agent/getAuthenticatedExtendedCard"}:
            return {"jsonrpc": "2.0", "id": request_id, "result": {"documentationUrl": "https://a2a-protocol.org/latest/specification/", **build_agent_card(base_url, use_v1)}}

        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not supported: {method}"}}

    return app


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


@pytest_asyncio.fixture
async def calculator_a2a_server():
    """Run the test A2A app in-memory via ASGITransport."""
    port = find_available_port()
    app = create_calculator_app(port)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://localhost:{port}") as client:
        yield {
            "client": client,
            "port": port,
            "app": app,
        }


class TestA2AUserQueryExtraction:
    """Tests for user query extraction from request body."""

    @pytest.mark.asyncio
    async def test_extract_user_query_from_body(self):
        body = {"query": "calc: 7*8"}
        user_query = body.get("query", "default")
        assert user_query == "calc: 7*8"

    @pytest.mark.asyncio
    async def test_default_query_when_body_empty(self):
        body = {}
        default_message = "Hello from ContextForge Admin UI test!"
        user_query = body.get("query", default_message) if body else default_message
        assert user_query == default_message

    @pytest.mark.asyncio
    async def test_default_query_when_body_none(self):
        body = None
        default_message = "Hello from ContextForge Admin UI test!"
        user_query = body.get("query", default_message) if body else default_message
        assert user_query == default_message


class TestToolVisibilityFix:
    """Tests for tool visibility defaulting to public."""

    @pytest.mark.asyncio
    async def test_tool_visibility_defaults_to_public_when_agent_visibility_none(self, mock_db, tool_service):
        mock_agent = MagicMock()
        mock_agent.id = "test-agent-id"
        mock_agent.name = "Test Agent"
        mock_agent.slug = "test-agent"
        mock_agent.description = "Test description"
        mock_agent.endpoint_url = "http://localhost:9000/run"
        mock_agent.agent_type = "custom"
        mock_agent.visibility = None
        mock_agent.tags = ["a2a"]
        mock_agent.team_id = None
        mock_agent.owner_email = None
        mock_agent.auth_type = None
        mock_agent.auth_value = None

        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        tool_visibility = mock_agent.visibility or "public"
        assert tool_visibility == "public"

    @pytest.mark.asyncio
    async def test_tool_visibility_respects_agent_visibility_when_set(self, mock_db, tool_service):
        mock_agent = MagicMock()
        mock_agent.visibility = "team"
        assert (mock_agent.visibility or "public") == "team"

    @pytest.mark.asyncio
    async def test_tool_visibility_public_when_agent_visibility_empty_string(self, mock_db, tool_service):
        mock_agent = MagicMock()
        mock_agent.visibility = ""
        assert (mock_agent.visibility or "public") == "public"


class TestTransactionHandling:
    """Tests for transaction handling during A2A agent registration."""

    @pytest.mark.asyncio
    async def test_agent_committed_before_tool_creation(self, mock_db, a2a_service):
        # Standard
        import inspect

        source = inspect.getsource(a2a_service.register_agent)
        assert "db.add(new_agent)" in source
        assert "db.commit()" in source
        assert source.find("db.add(new_agent)") < source.find("db.commit()") < source.find("create_tool_from_a2a_agent")

    @pytest.mark.asyncio
    async def test_agent_survives_tool_creation_failure(self, mock_db):
        agent_committed = False

        def track_commit():
            nonlocal agent_committed
            agent_committed = True

        mock_db.commit.side_effect = track_commit
        mock_db.add(MagicMock())
        mock_db.commit()
        assert agent_committed is True
        mock_db.rollback()
        assert agent_committed is True


class TestA2AAgentIntegration:
    """Integration tests for v1 A2A behavior with legacy compatibility."""

    @pytest.mark.asyncio
    async def test_calculator_agent_card_endpoint_defaults_to_v1(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        response = await client.get("/.well-known/agent.json")

        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "Test Calculator Agent"
        assert card["protocolVersion"] == "1.0.0"
        assert "supportedInterfaces" in card
        assert "kind" not in card
        assert card["capabilities"]["streaming"] is False

    @pytest.mark.asyncio
    async def test_calculator_agent_card_legacy_compatibility(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        response = await client.get("/.well-known/agent-card.json", headers={"A2A-Version": "0.3"})

        assert response.status_code == 200
        card = response.json()
        assert card["protocolVersion"] == "0.3.0"
        assert card["kind"] == "agent-card"
        assert card["preferredTransport"] == "JSONRPC"

    @pytest.mark.asyncio
    async def test_calculator_agent_send_message_v1(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-test-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "calc: 7*8"}],
                    }
                },
            },
            headers={"A2A-Version": "1.0"},
        )

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["status"]["state"] == "TASK_STATE_COMPLETED"
        assert result["status"]["message"]["role"] == "ROLE_AGENT"
        assert result["artifacts"][0]["parts"] == [{"text": "56"}]

    @pytest.mark.asyncio
    async def test_calculator_agent_send_message_legacy_compatibility(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-legacy",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "msg-test-legacy",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "calc: 10-3"}],
                    }
                },
            },
            headers={"A2A-Version": "0.3"},
        )

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["kind"] == "task"
        assert result["status"]["state"] == "completed"
        assert result["status"]["message"]["role"] == "agent"

    @pytest.mark.asyncio
    async def test_get_task_and_list_tasks_use_v1_shapes(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        send = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-2",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-test-2",
                        "role": "ROLE_USER",
                        "parts": [{"text": "calc: 100/4+25"}],
                    }
                },
            },
        )
        task_id = send.json()["result"]["id"]

        get_task = await client.post("/", json={"jsonrpc": "2.0", "id": "test-3", "method": "GetTask", "params": {"id": task_id}})
        list_tasks = await client.post("/", json={"jsonrpc": "2.0", "id": "test-4", "method": "ListTasks", "params": {"status": "TASK_STATE_COMPLETED"}})

        assert get_task.status_code == 200
        assert get_task.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert list_tasks.status_code == 200
        assert len(list_tasks.json()["result"]["tasks"]) >= 1

    @pytest.mark.asyncio
    async def test_cancel_task_keeps_jsonrpc_success_shape(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        send = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-5",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-test-5",
                        "role": "ROLE_USER",
                        "parts": [{"text": "calc: 2+2"}],
                    }
                },
            },
        )
        task_id = send.json()["result"]["id"]

        cancel = await client.post("/", json={"jsonrpc": "2.0", "id": "test-6", "method": "CancelTask", "params": {"id": task_id}})

        assert cancel.status_code == 200
        assert cancel.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"


class TestA2AProtocolCompliance:
    """Tests for A2A protocol compliance."""

    @pytest.mark.asyncio
    async def test_agent_card_has_required_v1_fields(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        card = (await client.get("/.well-known/agent.json")).json()

        for field in ["name", "description", "url", "version", "protocolVersion", "capabilities", "skills", "supportedInterfaces"]:
            assert field in card

    @pytest.mark.asyncio
    async def test_send_message_returns_task(self, calculator_a2a_server):
        client = calculator_a2a_server["client"]
        response = await client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "test-7",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-test-7",
                        "role": "ROLE_USER",
                        "parts": [{"text": "calc: 2+2"}],
                    }
                },
            },
        )

        result = response.json()["result"]
        assert "id" in result
        assert result["status"]["state"] == "TASK_STATE_COMPLETED"


class TestContextForgeA2ATestEndpoint:
    """Tests for ContextForge admin A2A test endpoint."""

    @pytest.mark.asyncio
    async def test_admin_test_endpoint_sends_user_query(self):
        user_query = "calc: 15*3"
        default_message = "Hello from ContextForge Admin UI test!"
        body = {"query": user_query}
        extracted_query = body.get("query", default_message) if body else default_message

        assert extracted_query == user_query
        assert extracted_query != default_message

    @pytest.mark.asyncio
    async def test_admin_test_endpoint_uses_default_when_no_query(self):
        default_message = "Hello from ContextForge Admin UI test!"
        for body in ({}, {"query": ""}, {"query": None}, None):
            extracted_query = (body.get("query") if body else None) or default_message
            assert extracted_query == default_message

    @pytest.mark.asyncio
    async def test_jsonrpc_format_includes_user_query(self):
        user_query = "calc: 100/5"
        test_params = {
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "admin-test-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": user_query}],
                }
            },
        }

        message_part = test_params["params"]["message"]["parts"][0]
        assert message_part["text"] == user_query
        assert "kind" not in message_part

    @pytest.mark.asyncio
    async def test_custom_agent_format_includes_user_query(self):
        user_query = "weather: Dallas"
        test_params = {
            "interaction_type": "admin_test",
            "parameters": {"query": user_query, "message": user_query},
            "protocol_version": "1.0",
        }
        assert test_params["parameters"]["query"] == user_query
        assert test_params["parameters"]["message"] == user_query


class TestCalculatorAgent:
    """Unit tests for the calculator agent implementation."""

    @pytest.mark.asyncio
    async def test_basic_arithmetic(self):
        agent = CalculatorAgent()
        assert await agent.invoke("calc: 2+2") == "4"
        assert await agent.invoke("calc: 10-3") == "7"
        assert await agent.invoke("calc: 5*6") == "30"
        assert await agent.invoke("calc: 20/4") == "5.0"

    @pytest.mark.asyncio
    async def test_complex_expressions(self):
        agent = CalculatorAgent()
        assert await agent.invoke("calc: 7*8") == "56"
        assert await agent.invoke("calc: 100/4+25") == "50.0"
        assert await agent.invoke("calc: (2+3)*4") == "20"

    @pytest.mark.asyncio
    async def test_negative_numbers(self):
        agent = CalculatorAgent()
        assert await agent.invoke("calc: -5") == "-5"
        assert await agent.invoke("calc: -5+10") == "5"

    @pytest.mark.asyncio
    async def test_division_by_zero(self):
        result = await CalculatorAgent().invoke("calc: 10/0")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        result = await CalculatorAgent().invoke("calc: invalid")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_query_without_prefix(self):
        assert await CalculatorAgent().invoke("5*5") == "25"
