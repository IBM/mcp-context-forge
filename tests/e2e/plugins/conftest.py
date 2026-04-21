# -*- coding: utf-8 -*-
"""Reusable fixtures and helpers for gateway-executed CPEX plugin E2E tests.

This harness targets real CPEX hook execution through ContextForge's live MCP
gateway path, with reusable helpers for:
- [`prompt_pre_fetch`](mcpgateway/plugins/framework/hooks/prompts.py:47)
- [`prompt_post_fetch`](mcpgateway/plugins/framework/hooks/prompts.py:48)
- [`tool_pre_invoke`](mcpgateway/plugins/framework/hooks/tools.py:40)
- [`tool_post_invoke`](mcpgateway/plugins/framework/hooks/tools.py:41)
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Generator
import logging
import os
import time
import uuid

import httpx
import pytest

from tests.e2e.helpers.mcp_test_helpers import BASE_URL, skip_no_gateway

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-11-25"
E2E_PLUGIN_PREFIX = "e2e-plugin"
COMPOSE_TEST_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")
# Generic defaults - can be overridden by individual test files
DEFAULT_TEST_TOOL = os.getenv("E2E_PLUGIN_TOOL_NAME", "fast-time-get-system-time")
DEFAULT_TEST_PROMPT_TEMPLATE = os.getenv(
    "E2E_PLUGIN_PROMPT_TEMPLATE",
    "User input: {{ user_input }}\nSecondary input: {{ secondary_input }}",
)

pytestmark = [pytest.mark.e2e, skip_no_gateway]


def _make_admin_jwt() -> str:
    """Authenticate the bootstrapped platform admin and return a live session JWT."""
    for candidate in (BASE_URL.rstrip("/"), "http://localhost:8080", "http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:4444"):
        try:
            with httpx.Client(base_url=candidate, timeout=20.0, verify=False) as client:
                response = client.post(
                    "/auth/login",
                    json={
                        "email": "admin@example.com",
                        "password": "changeme",  # pragma: allowlist secret
                    },
                )
                if response.status_code == 200:
                    return response.json()["access_token"]
        except Exception:
            continue
    raise AssertionError("Failed to obtain admin session JWT via /auth/login on the live ContextForge instance")


def _api_headers(token: str) -> dict[str, str]:
    """Build JSON API headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _mcp_headers(token: str, *, session_id: str | None = None) -> dict[str, str]:
    """Build MCP JSON-RPC headers."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> Any:
    """Send a JSON API request and return the parsed body."""
    response = client.request(method, path, **kwargs)
    assert response.status_code in expected, f"{method} {path} expected {expected}, got {response.status_code}: {response.text}"
    return response.json() if response.content else None


def _mcp_post(
    client: httpx.Client,
    *,
    server_id: str,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    request_id: int = 1,
) -> httpx.Response:
    """Send a direct server-scoped MCP request."""
    return client.post(
        f"/servers/{server_id}/mcp/",
        headers=_mcp_headers(token, session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )


def _extract_result(response: httpx.Response) -> dict[str, Any]:
    """Extract the JSON-RPC result payload from a successful response."""
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


def _initialize_session(client: httpx.Client, *, server_id: str, token: str) -> str | None:
    """Initialize an MCP session and return its session id when present."""
    response = _mcp_post(
        client,
        server_id=server_id,
        token=token,
        method="initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "cpex-plugin-e2e", "version": "1.0.0"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    return response.headers.get("mcp-session-id")


def _extract_text_content(result: dict[str, Any]) -> str:
    """Extract concatenated text content from an MCP result-like payload."""
    content = result.get("content", [])
    text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
    return "\n".join(part for part in text_parts if part)


def _extract_prompt_text(result: dict[str, Any]) -> str:
    """Extract concatenated prompt message text from a prompts/get result."""
    messages = result.get("messages", [])
    text_parts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
    return "\n".join(text_parts)




def _extract_admin_collection(payload: Any) -> list[dict[str, Any]]:
    """Normalize admin paginated/list responses into a plain list."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _wait_for_tool_sync(client: httpx.Client, *, timeout_seconds: int = 30) -> list[dict[str, Any]]:
    """Poll the admin tool catalog until the configured test tool is available."""
    deadline = time.time() + timeout_seconds
    last_tools: list[dict[str, Any]] = []
    while time.time() < deadline:
        tools_payload = _request_json(client, "GET", "/tools", expected=(200,))
        tools = _extract_admin_collection(tools_payload)
        if any(tool.get("name") == DEFAULT_TEST_TOOL for tool in tools):
            return tools
        last_tools = tools
        time.sleep(1)
    raise AssertionError(
        f"Timed out waiting for tool sync for expected tool {DEFAULT_TEST_TOOL!r}. "
        f"Last tools payload: {last_tools}"
    )


@pytest.fixture(scope="session")
def plugin_test_config() -> dict[str, str]:
    """Environment contract for the live plugin E2E stack.

    When running against Docker (test-e2e-plugins-docker), these environment
    variables are set inside the container, not on the host. We use defaults
    that match the Docker configuration in docker-compose.plugin-e2e.yml.
    """
    plugin_name = os.getenv("E2E_PLUGIN_UNDER_TEST", "pii_filter")
    plugin_kind = os.getenv("E2E_PLUGIN_KIND", "cpex_pii_filter.pii_filter.PIIFilterPlugin")
    return {
        "plugin_name": plugin_name,
        "plugin_kind": plugin_kind,
        "plugins_enabled": os.getenv("PLUGINS_ENABLED", "true"),
        "plugins_config_file": os.getenv("PLUGINS_CONFIG_FILE", "tests/plugins/test_e2e_config.yaml"),
        "observability_enabled": os.getenv("OBSERVABILITY_ENABLED", "true"),
    }


@pytest.fixture(scope="module")
def admin_client() -> Generator[httpx.Client, None, None]:
    """Module-scoped admin client."""
    base_urls = [BASE_URL.rstrip("/")]
    if "http://localhost:8080" not in base_urls:
        base_urls.append("http://localhost:8080")
    if "http://127.0.0.1:8000" not in base_urls:
        base_urls.append("http://127.0.0.1:8000")
    if "http://localhost:8000" not in base_urls:
        base_urls.append("http://localhost:8000")
    if "http://127.0.0.1:4444" not in base_urls:
        base_urls.append("http://127.0.0.1:4444")

    token = _make_admin_jwt()
    last_error: str | None = None
    for candidate in base_urls:
        try:
            with httpx.Client(base_url=candidate, headers=_api_headers(token), timeout=20.0, verify=False, follow_redirects=True) as client:
                health_response = client.get("/health")
                if health_response.status_code != 200:
                    last_error = f"{candidate} returned {health_response.status_code} for /health"
                    continue

                auth_response = client.get("/teams/")
                if auth_response.status_code in (200, 403):
                    yield client
                    return

                # 401 means token is invalid - this is a critical error, not just wrong URL
                if auth_response.status_code == 401:
                    last_error = f"{candidate} auth probe returned 401 Unauthorized. Token may be invalid or expired. Response: {auth_response.text[:200]}"
                    # Don't continue trying other URLs if we have a token validation issue
                    break

                last_error = f"{candidate} auth probe returned {auth_response.status_code}: {auth_response.text[:200]}"
        except Exception as exc:
            last_error = f"{candidate} failed: {exc}"

    raise AssertionError(f"ContextForge admin client could not connect using session JWT. Last error: {last_error}")


@pytest.fixture(scope="module")
def plugin_team(admin_client: httpx.Client) -> Generator[dict[str, Any], None, None]:
    """Create a dedicated team for plugin E2E resources."""
    team = _request_json(
        admin_client,
        "POST",
        "/teams/",
        json={
            "name": f"{E2E_PLUGIN_PREFIX}-team-{uuid.uuid4().hex[:8]}",
            "description": "CPEX plugin E2E team",
            "visibility": "private",
        },
    )
    yield team
    with suppress(Exception):
        admin_client.delete(f"/teams/{team['id']}")


@pytest.fixture(scope="module")
def plugin_user(admin_client: httpx.Client, plugin_team: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Create a dedicated test user and API token for plugin E2E flows."""
    email = f"{E2E_PLUGIN_PREFIX}-{uuid.uuid4().hex[:8]}@test.com"
    password = "SecureTestPass123!"  # pragma: allowlist secret
    create_response = admin_client.post(
        "/auth/email/admin/users",
        json={
            "email": email,
            "password": password,
            "full_name": "Plugin E2E User",
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
    )
    assert create_response.status_code in (200, 201, 409), create_response.text

    add_member_response = admin_client.post(
        f"/teams/{plugin_team['id']}/members",
        json={"email": email, "role": "member"},
    )
    assert add_member_response.status_code in (200, 201, 400, 409), add_member_response.text

    login_response = admin_client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    assert login_response.status_code == 200, login_response.text
    user_jwt = login_response.json()["access_token"]

    with httpx.Client(base_url=BASE_URL, headers=_api_headers(user_jwt), timeout=20.0, verify=False) as user_client:
        token_payload = _request_json(
            user_client,
            "POST",
            "/tokens",
            json={
                "name": f"{E2E_PLUGIN_PREFIX}-token-{uuid.uuid4().hex[:8]}",
                "expires_in_days": 1,
                "team_id": plugin_team["id"],
            },
        )

    access_token = token_payload["access_token"]
    token_obj = token_payload.get("token", token_payload)

    yield {
        "email": email,
        "team_id": plugin_team["id"],
        "access_token": access_token,
        "token_id": token_obj.get("id") or token_obj.get("token_id"),
    }

    if token_obj.get("id") or token_obj.get("token_id"):
        with suppress(Exception):
            admin_client.delete(f"/tokens/admin/{token_obj.get('id') or token_obj.get('token_id')}")
    with suppress(Exception):
        admin_client.delete(f"/teams/{plugin_team['id']}/members/{email}")
    with suppress(Exception):
        admin_client.delete(f"/auth/email/admin/users/{email}")


@pytest.fixture(scope="module")
def plugin_server(admin_client: httpx.Client, plugin_team: dict[str, Any], request: pytest.FixtureRequest) -> Generator[dict[str, Any], None, None]:
    """Create a virtual server bound to a self-provisioned REST tool and team prompt.

    This fixture can be customized via indirect parametrization:

    Example:
        @pytest.mark.parametrize("plugin_server", [
            {
                "tool": {"url": "https://api.example.com/endpoint"},
                "prompt": {"template": "Custom: {{ input }}"}
            }
        ], indirect=True)
        def test_with_custom_server(plugin_server):
            ...
    """
    # Allow tests to override via pytest.mark.parametrize or fixture params
    params = getattr(request, "param", {}) if hasattr(request, "param") else {}
    tool_config = params.get("tool", {})
    prompt_config = params.get("prompt", {})

    # Tool configuration with defaults
    tool_name = tool_config.get("name", f"{E2E_PLUGIN_PREFIX}-tool-{uuid.uuid4().hex[:8]}")
    tool_url = tool_config.get("url", "https://postman-echo.com/post")
    tool_description = tool_config.get("description", "Self-provisioned REST echo tool for plugin E2E validation")
    tool_schema = tool_config.get("inputSchema", {
        "type": "object",
        "properties": {
            "user_input": {"type": "string"},
            "secondary_input": {"type": "string"},
            "timezone": {"type": "string"},
        },
        "additionalProperties": True,
    })

    tool = _request_json(
        admin_client,
        "POST",
        "/tools/",
        json={
            "tool": {
                "name": tool_name,
                "description": tool_description,
                "integration_type": "REST",
                "request_type": "POST",
                "url": tool_url,
                "headers": {"Content-Type": "application/json"},
                "inputSchema": tool_schema,
            },
            "team_id": plugin_team["id"],
            "visibility": "team",
        },
    )

    # Prompt configuration with defaults
    prompt_name = prompt_config.get("name", f"{E2E_PLUGIN_PREFIX}-prompt-{uuid.uuid4().hex[:8]}")
    prompt_template = prompt_config.get("template", DEFAULT_TEST_PROMPT_TEMPLATE)
    prompt_description = prompt_config.get("description", "CPEX plugin E2E prompt")
    prompt_arguments = prompt_config.get("arguments", [
        {"name": "user_input", "description": "Primary user input"},
        {"name": "secondary_input", "description": "Secondary user input"},
    ])

    prompt = _request_json(
        admin_client,
        "POST",
        "/prompts",
        json={
            "prompt": {
                "name": prompt_name,
                "template": prompt_template,
                "description": prompt_description,
                "arguments": prompt_arguments,
            },
            "visibility": "team",
            "team_id": plugin_team["id"],
        },
    )

    server = _request_json(
        admin_client,
        "POST",
        "/servers",
        json={
            "server": {
                "name": f"{E2E_PLUGIN_PREFIX}-server-{uuid.uuid4().hex[:8]}",
                "description": "CPEX plugin E2E server",
                "associated_tools": [tool["id"]],
                "associated_resources": [],
                "associated_prompts": [prompt["id"]],
            },
            "team_id": plugin_team["id"],
            "visibility": "team",
        },
    )

    yield {
        "id": server["id"],
        "name": server["name"],
        "tool_id": tool["id"],
        "tool_name": tool["name"],
        "prompt_id": prompt["id"],
        "prompt_name": prompt["name"],
        "team_id": plugin_team["id"],
    }

    # No cleanup - test database will be reset between test runs
    # Cleanup causes race condition with async metrics buffer service


@pytest.fixture(scope="module")
def plugin_harness(plugin_server: dict[str, Any], plugin_user: dict[str, Any], plugin_test_config: dict[str, str]) -> dict[str, Any]:
    """Bundle reusable helpers and state for gateway-driven plugin E2E tests."""
    return {
        "server_id": plugin_server["id"],
        "server_name": plugin_server["name"],
        "tool_name": plugin_server["tool_name"],
        "prompt_id": plugin_server["prompt_id"],
        "prompt_name": plugin_server["prompt_name"],
        "team_id": plugin_user["team_id"],
        "token": plugin_user["access_token"],
        "plugin_name": plugin_test_config["plugin_name"],
        "plugin_kind": plugin_test_config["plugin_kind"],
        "plugins_enabled": plugin_test_config["plugins_enabled"],
        "plugins_config_file": plugin_test_config["plugins_config_file"],
        "observability_enabled": plugin_test_config["observability_enabled"],
    }


@pytest.fixture
def invoke_tool() -> Any:
    """Return a callable that invokes a tool through the live MCP gateway path."""

    def _invoke(
        harness: dict[str, Any],
        *,
        arguments: dict[str, Any] | None = None,
        request_id: int = 2,
    ) -> dict[str, Any]:
        with httpx.Client(base_url=BASE_URL, timeout=20.0, verify=False) as client:
            session_id = _initialize_session(client, server_id=harness["server_id"], token=harness["token"])
            response = _mcp_post(
                client,
                server_id=harness["server_id"],
                token=harness["token"],
                session_id=session_id,
                method="tools/call",
                params={
                    "name": harness["tool_name"],
                    "arguments": {
                        "user_input": (arguments or {}).get("user_input", ""),
                        "secondary_input": (arguments or {}).get("secondary_input", ""),
                        "timezone": (arguments or {}).get("timezone", "UTC"),
                    },
                },
                request_id=request_id,
            )
            payload = response.json()
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "payload": payload,
                "result": payload.get("result"),
                "error": payload.get("error"),
            }

    return _invoke


@pytest.fixture
def invoke_prompt() -> Any:
    """Return a callable that invokes a prompt through the live MCP gateway path."""

    def _invoke(
        harness: dict[str, Any],
        *,
        arguments: dict[str, str] | None = None,
        request_id: int = 3,
    ) -> dict[str, Any]:
        with httpx.Client(base_url=BASE_URL, timeout=20.0, verify=False) as client:
            session_id = _initialize_session(client, server_id=harness["server_id"], token=harness["token"])
            response = _mcp_post(
                client,
                server_id=harness["server_id"],
                token=harness["token"],
                session_id=session_id,
                method="prompts/get",
                params={"name": harness["prompt_name"], "arguments": arguments or {}},
                request_id=request_id,
            )
            payload = response.json()
            return {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "payload": payload,
                "result": payload.get("result"),
                "error": payload.get("error"),
            }

    return _invoke


@pytest.fixture
def plugin_assertions() -> dict[str, Any]:
    """Return common generic assertion helpers for plugin E2E tests."""
    return {
        "extract_tool_text": _extract_text_content,
        "extract_prompt_text": _extract_prompt_text,
    }


@pytest.fixture
def plugin_config_factory(admin_client: httpx.Client, plugin_team: dict[str, Any]) -> Callable:
    """Factory for creating plugin configurations dynamically.

    This allows tests to specify plugin settings without hardcoding them in conftest.
    Each plugin test file can define its own plugin configuration.

    Example:
        def test_my_plugin(plugin_config_factory):
            config = plugin_config_factory(
                plugin_name="my_plugin",
                plugin_kind="my_module.MyPlugin",
                hooks=["tool_pre_invoke"],
                config={"setting": "value"}
            )
    """
    def _factory(
        plugin_name: str,
        plugin_kind: str,
        hooks: list[str],
        config: dict[str, Any],
        mode: str = "enforce",
        priority: int = 100,
    ) -> dict[str, Any]:
        """
        Create a plugin configuration for E2E testing.

        Args:
            plugin_name: Plugin identifier
            plugin_kind: Python import path (e.g., "cpex_pii_filter.PIIFilterPlugin")
            hooks: List of hook names (e.g., ["tool_pre_invoke", "tool_post_invoke"])
            config: Plugin-specific configuration dict
            mode: "enforce" | "permissive" | "disabled"
            priority: Plugin execution priority (default: 100)

        Returns:
            Dict with plugin metadata for test assertions

        Note:
            This currently returns metadata only. In the future, this could
            POST to /admin/plugins or update PLUGINS_CONFIG_FILE dynamically.
            For now, plugins must be pre-configured in the live gateway via
            PLUGINS_CONFIG_FILE environment variable.
        """
        return {
            "plugin_name": plugin_name,
            "plugin_kind": plugin_kind,
            "hooks": hooks,
            "config": config,
            "mode": mode,
            "priority": priority,
            "team_id": plugin_team["id"],
        }
    return _factory



@pytest.fixture
def query_observability_traces(admin_client: httpx.Client) -> Callable:
    """Query observability traces to verify plugin execution.

    Returns a function that queries traces by various criteria.

    Example:
        traces = query_observability_traces(
            resource_type="tool",
            resource_name="my-tool",
            limit=10
        )
        assert len(traces) > 0
        assert any("plugin" in trace.get("name", "").lower() for trace in traces)
    """
    def _query(
        resource_type: str | None = None,
        resource_name: str | None = None,
        span_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query observability traces and filter by span attributes.

        Note: The /observability/traces API doesn't support resource_type/resource_name
        filtering directly. We fetch traces and filter client-side by examining spans.

        Args:
            resource_type: Filter by resource type (tool, prompt, resource)
            resource_name: Filter by resource name
            span_name: Filter by span name (e.g., "plugin_execution")
            limit: Maximum number of traces to return

        Returns:
            List of trace dictionaries that contain matching spans
        """
        try:
            # Fetch traces from API (no resource filtering at API level)
            response = admin_client.get("/observability/traces", params={"limit": limit * 2})
            if response.status_code == 200:
                data = response.json()
                # Handle both list and dict responses
                if isinstance(data, list):
                    all_traces = data
                elif isinstance(data, dict):
                    all_traces = data.get("traces", data.get("data", []))
                else:
                    return []

                # Client-side filtering by span attributes
                filtered_traces = []
                for trace in all_traces:
                    # Get spans from trace (may be nested in different structures)
                    spans = trace.get("spans", [])
                    if not spans and "data" in trace:
                        spans = trace["data"].get("spans", [])

                    # Check if any span matches our filters
                    has_match = False
                    for span in spans:
                        if not isinstance(span, dict):
                            continue

                        # Check resource_type filter
                        if resource_type and span.get("resource_type") != resource_type:
                            continue

                        # Check resource_name filter
                        if resource_name and span.get("resource_name") != resource_name:
                            continue

                        # Check span_name filter
                        if span_name and span_name.lower() not in span.get("name", "").lower():
                            continue

                        # All filters passed
                        has_match = True
                        break

                    if has_match:
                        filtered_traces.append(trace)
                        if len(filtered_traces) >= limit:
                            break

                return filtered_traces

            elif response.status_code == 403:
                logger.warning(
                    "Observability API returned 403 Forbidden. "
                    "Admin user may lack 'admin.system_config' permission. "
                    "Response: %s", response.text
                )
                return []
            elif response.status_code == 404:
                logger.warning(
                    "Observability API endpoint not found (404). "
                    "OBSERVABILITY_ENABLED may be false or endpoint not registered."
                )
                return []
            else:
                logger.warning(
                    "Observability API returned unexpected status %d: %s",
                    response.status_code, response.text
                )
                return []
        except Exception as e:
            logger.warning("Failed to query observability traces: %s", e)
            return []

    return _query


@pytest.fixture
def verify_plugin_execution(query_observability_traces: Callable) -> Callable:
    """Verify that a plugin actually executed by checking observability traces.

    Returns a function that checks for plugin-related spans in traces.

    Example:
        executed = verify_plugin_execution(
            resource_name="my-tool",
            plugin_name="pii_filter"
        )
        assert executed, "Plugin did not execute"
    """
    def _verify(
        resource_name: str,
        resource_type: str = "tool",
        plugin_name: str | None = None,
        hook_type: str | None = None,
    ) -> bool:
        """Verify plugin execution via observability traces.

        Args:
            resource_name: Name of the resource (tool/prompt) that was invoked
            resource_type: Type of resource (tool, prompt, resource)
            plugin_name: Optional plugin name to verify
            hook_type: Optional hook type (pre_invoke, post_invoke, etc.)

        Returns:
            True if plugin execution was found in traces
        """
        traces = query_observability_traces(
            resource_type=resource_type,
            resource_name=resource_name,
            limit=50
        )

        if not traces:
            return False

        # Look for plugin-related spans
        for trace in traces:
            spans = trace.get("spans", [])
            for span in spans:
                span_name = span.get("name", "").lower()
                attributes = span.get("attributes", {})

                # Check for plugin execution indicators
                if "plugin" in span_name:
                    if plugin_name and plugin_name.lower() not in span_name:
                        continue
                    if hook_type and hook_type.lower() not in span_name:
                        continue
                    return True

                # Check attributes for plugin info
                if attributes.get("plugin_name") or attributes.get("hook_type"):
                    if plugin_name and attributes.get("plugin_name") != plugin_name:
                        continue
                    if hook_type and attributes.get("hook_type") != hook_type:
                        continue
                    return True

        return False

    return _verify
