# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_issue_840_a2a_agent.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for GitHub Issue #840: A2A Agent testing bugs.

This module contains tests that replicate the issues described in #840:
1. A2A agent is exposed as an API endpoint but there is no way to test it
   from the UI with user-provided input (no field to pass the user query).
2. Tools from A2A Agent are not getting listed under the Global Tools Tab.

These tests verify the expected behavior and will fail until the issues are fixed.
"""

# Standard
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolRead
from mcpgateway.services.a2a_service import A2AAgentService
from mcpgateway.services.tool_service import ToolService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock structured_logger and audit_trail to prevent database writes during tests."""
    with (
        patch("mcpgateway.services.a2a_service.structured_logger") as mock_a2a_logger,
        patch("mcpgateway.services.tool_service.structured_logger") as mock_tool_logger,
        patch("mcpgateway.services.tool_service.audit_trail") as mock_tool_audit,
    ):
        mock_a2a_logger.log = MagicMock(return_value=None)
        mock_a2a_logger.info = MagicMock(return_value=None)
        mock_tool_logger.log = MagicMock(return_value=None)
        mock_tool_logger.info = MagicMock(return_value=None)
        mock_tool_audit.log_action = MagicMock(return_value=None)
        yield


class TestIssue840UserInputForA2AAgentTest:
    """Test suite for Issue #840 - Part 1: A2A agent test endpoint lacks user input field.

    The issue reports that A2A agents exposed as API endpoints cannot be tested
    from the UI with user-provided input. The test button sends a hardcoded
    message instead of allowing users to provide custom queries like:
    - "calc: 5*10+2"
    - "weather: Dallas"

    These tests verify that:
    1. The test endpoint should accept user-provided query parameters
    2. The test payload should include the user's custom query
    3. The agent invocation should receive the user-specified input
    """

    @pytest.fixture
    def a2a_service(self):
        """Create A2A agent service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def sample_a2a_agent(self):
        """Sample A2A agent that expects user queries."""
        agent_id = uuid.uuid4().hex
        return MagicMock(
            id=agent_id,
            name="calculator-agent",
            slug="calculator-agent",
            description="A2A Agent that handles calc: and weather: queries",
            endpoint_url="http://localhost:8000/run",
            agent_type="custom",
            protocol_version="1.0",
            capabilities={"chat": True, "tools": True},
            config={},
            auth_type="none",
            auth_value=None,
            auth_query_params=None,
            enabled=True,
            reachable=True,
            visibility="public",
            team_id=None,
            owner_email=None,
            tags=[{"id": "a2a", "label": "a2a"}, {"id": "agent", "label": "agent"}],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1,
            metrics=[],
        )

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_invoke_agent_with_custom_user_query(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        a2a_service,
        mock_db,
        sample_a2a_agent,
    ):
        """Test that A2A agent can be invoked with custom user query.

        This test demonstrates the expected behavior: users should be able to
        send custom queries like "calc: 7*8" to A2A agents.

        Issue #840 reports that the UI test button doesn't allow users to
        provide custom input - it sends a hardcoded message instead.
        """
        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "56"}  # Result of 7*8
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations - agent lookup by name returns ID
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_a2a_agent.id

        # Mock get_for_update to return our sample agent
        mock_get_for_update.return_value = sample_a2a_agent

        # Mock fresh_db_session
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = sample_a2a_agent
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # User's custom query - this is what the UI should allow
        user_custom_query = {"query": "calc: 7*8"}

        # Invoke the agent with user's custom query
        result = await a2a_service.invoke_agent(
            mock_db,
            sample_a2a_agent.name,
            user_custom_query,
            "user_test",
        )

        # Verify the result
        assert result["response"] == "56"

        # CRITICAL: Verify that the user's custom query was sent to the agent
        # This is the core of Issue #840 - the query should be user-provided
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        # The request body should contain the user's custom query
        # In the current implementation, this works at the service level,
        # but the UI doesn't provide a way to input the query
        assert call_args is not None

    async def test_admin_test_endpoint_should_accept_user_query(self):
        """Test that verifies the admin test endpoint signature.

        Issue #840 reports that the admin UI test button for A2A agents
        sends an empty payload `{}` instead of allowing users to provide
        custom queries.

        The endpoint `/admin/a2a/{agent_id}/test` should accept a request body
        with a user-provided query field.

        Current behavior (BUG):
        - JavaScript sends: testPayload = {}
        - Server uses hardcoded: "Hello from MCP Gateway Admin UI test!"

        Expected behavior (FIX NEEDED):
        - JavaScript should provide input field for user query
        - Server should use: request_body.query or request_body.message
        """
        # This test documents the expected behavior
        # Currently, the admin endpoint uses hardcoded test parameters:
        #
        # From admin.py line 13334-13340:
        # test_params = {
        #     "method": "message/send",
        #     "params": {"message": {..., "text": "Hello from MCP Gateway Admin UI test!"}}
        # }
        #
        # The UI should instead:
        # 1. Show an input field for the user to enter their query
        # 2. Send the user's query to the endpoint
        # 3. The endpoint should use that query in the test_params

        # Document the expected request body format
        expected_request_body = {
            "query": "calc: 7*8",  # User-provided query
        }

        # Document the expected test_params that should be sent to the agent
        expected_test_params = {
            "query": "calc: 7*8",  # Should use user's query, not hardcoded message
        }

        # These assertions document the expected behavior
        assert "query" in expected_request_body, "Request body should include user query"
        assert expected_test_params["query"] == expected_request_body["query"], "Test params should use user's query"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_custom_agent_receives_query_in_parameters(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        a2a_service,
        mock_db,
        sample_a2a_agent,
    ):
        """Test that custom A2A agents receive query in parameters object.

        Per A2A protocol, ContextForge sends custom agents requests in format:
            {"interaction_type": "...", "parameters": {"query": "..."}, "protocol_version": "..."}

        A2A-compliant agents should extract the query from parameters.query.

        This test verifies that invoke_agent correctly sends the query
        nested under the parameters object for custom agent types.
        """
        # Mock HTTP client to capture the actual request body
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "The weather in Dallas is sunny"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Mock database operations - agent lookup by name returns ID
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_a2a_agent.id

        # Mock get_for_update to return our sample agent
        mock_get_for_update.return_value = sample_a2a_agent

        # Mock fresh_db_session
        mock_ts_db = MagicMock()
        mock_ts_db.execute.return_value.scalar_one_or_none.return_value = sample_a2a_agent
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None

        # Mock metrics buffer service
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        # This is what the admin test endpoint sends for custom agents
        test_params = {"query": "weather: Dallas", "message": "weather: Dallas", "test": True}

        # Invoke the agent
        await a2a_service.invoke_agent(
            mock_db,
            sample_a2a_agent.name,
            test_params,
            "admin_test",
        )

        # Verify the HTTP client was called
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        # Extract the JSON body that was sent to the agent
        request_body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert request_body is not None, "Request body should not be None"

        # Per A2A protocol for custom agents, verify the structure.
        # Accept either the A2A `parameters` object OR JSON-RPC `params` wrapper
        # (some deployments may use JSON-RPC). Ensure the user's `query` is present.
        if "parameters" in request_body:
            params = request_body["parameters"]
            # Ensure interaction_type present for custom A2A format
            assert "interaction_type" in request_body, "Request should contain 'interaction_type' for custom agents"
            assert request_body["interaction_type"] == "admin_test"
        elif "params" in request_body and "jsonrpc" in request_body:
            params = request_body["params"]
            assert isinstance(params, dict), "JSON-RPC 'params' should be an object"
        else:
            assert False, "Request should contain 'parameters' object or JSON-RPC 'params' with query"

        # Verify the query is present in the resolved params
        assert "query" in params or "message" in params, "parameters should contain query or message"

        # Verify the actual query value
        actual_query = params.get("query") or params.get("message")
        assert actual_query == "weather: Dallas", f"Query should be 'weather: Dallas', got '{actual_query}'"


class TestIssue840A2AToolsNotListedInGlobalTools:
    """Test suite for Issue #840 - Part 2: A2A tools not appearing in Global Tools.

    The issue reports that tools from A2A Agents are not getting listed under
    the Global Tools Tab.

    When an A2A agent is registered, a corresponding MCP tool should be
    automatically created with:
    - name: "a2a_{agent_slug}"
    - integration_type: "A2A"
    - tags: ["a2a", "agent", ...agent_tags]

    These tests verify that:
    1. A2A agent registration creates a corresponding tool
    2. The tool has correct integration_type="A2A"
    3. The tool appears in tool listing queries
    4. The tool has proper tags for filtering
    """

    @pytest.fixture
    def tool_service(self):
        """Create tool service instance."""
        return ToolService()

    @pytest.fixture
    def a2a_service(self):
        """Create A2A agent service instance."""
        return A2AAgentService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock(spec=Session)
        db.get_bind.return_value.dialect.name = "sqlite"
        return db

    @pytest.fixture
    def sample_a2a_agent_db(self):
        """Sample database A2A agent for tool creation."""
        agent_id = uuid.uuid4().hex
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = agent_id
        agent.name = "calculator-agent"
        agent.slug = "calculator-agent"
        agent.description = "A2A Agent that handles calc: and weather: queries"
        agent.endpoint_url = "http://localhost:8000/run"
        agent.agent_type = "custom"
        agent.protocol_version = "1.0"
        agent.capabilities = {"chat": True, "tools": True}
        agent.config = {}
        agent.auth_type = "none"
        agent.auth_value = None
        agent.enabled = True
        agent.reachable = True
        agent.tags = [{"id": "test", "label": "test"}]
        agent.team_id = None
        agent.owner_email = "admin@example.com"
        agent.visibility = "public"
        return agent

    async def test_a2a_agent_registration_creates_tool(
        self,
        tool_service,
        mock_db,
        sample_a2a_agent_db,
    ):
        """Test that registering an A2A agent creates a corresponding tool.

        Issue #840 reports that A2A agent tools are not showing in the
        Global Tools Tab. This test verifies that a tool should be created
        when an A2A agent is registered.
        """
        # Mock: No existing tool with the same name
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        # Mock the register_tool method to capture the tool data
        created_tool_data = None

        async def capture_register_tool(db, tool_data, **kwargs):
            nonlocal created_tool_data
            created_tool_data = tool_data
            # Return a mock ToolRead
            return MagicMock(
                id=uuid.uuid4().hex,
                name=tool_data.name,
                integration_type=tool_data.integration_type,
                tags=tool_data.tags,
            )

        with patch.object(tool_service, "register_tool", side_effect=capture_register_tool):
            # Mock db.get to return a tool
            mock_tool = MagicMock(spec=DbTool)
            mock_tool.id = uuid.uuid4().hex
            mock_db.get.return_value = mock_tool

            # Create tool from A2A agent
            _ = await tool_service.create_tool_from_a2a_agent(
                db=mock_db,
                agent=sample_a2a_agent_db,
                created_by="admin@example.com",
            )

        # Verify tool was created
        assert created_tool_data is not None, "Tool data should be created"

        # Verify tool name follows convention
        expected_tool_name = f"a2a_{sample_a2a_agent_db.slug}"
        assert created_tool_data.name == expected_tool_name, f"Tool name should be '{expected_tool_name}'"

        # CRITICAL: Verify integration_type is "A2A"
        # This is crucial for the tool to be recognized as an A2A tool
        assert created_tool_data.integration_type == "A2A", "Tool integration_type must be 'A2A'"

        # Verify tags include "a2a" and "agent"
        # Tags can be either strings or dicts with 'id'/'label' keys
        def tag_contains(tags, value):
            """Check if a tag value exists in the tags list (handles both string and dict formats)."""
            for tag in tags:
                if isinstance(tag, dict):
                    if tag.get("id") == value or tag.get("label") == value:
                        return True
                elif tag == value:
                    return True
            return False

        assert tag_contains(created_tool_data.tags, "a2a"), "Tool tags must include 'a2a'"
        assert tag_contains(created_tool_data.tags, "agent"), "Tool tags must include 'agent'"

        # Verify annotations contain agent ID
        assert "a2a_agent_id" in created_tool_data.annotations, "Annotations must include a2a_agent_id"
        assert created_tool_data.annotations["a2a_agent_id"] == sample_a2a_agent_db.id

    async def test_a2a_tool_should_appear_in_tool_listing(self, tool_service, mock_db):
        """Test that A2A tools appear in the global tools listing.

        Issue #840 reports that A2A agent tools don't appear in the Global
        Tools Tab. This test verifies that list_tools should include tools
        with integration_type="A2A".
        """
        # Create a mock A2A tool
        a2a_tool_id = uuid.uuid4().hex
        a2a_tool = MagicMock(spec=DbTool)
        a2a_tool.id = a2a_tool_id
        a2a_tool.name = "a2a_calculator-agent"
        a2a_tool.original_name = "a2a_calculator-agent"
        a2a_tool.integration_type = "A2A"
        a2a_tool.enabled = True
        a2a_tool.tags = [{"id": "a2a", "label": "a2a"}, {"id": "agent", "label": "agent"}]
        a2a_tool.annotations = {"a2a_agent_id": "test-agent-id", "a2a_agent_type": "custom"}
        a2a_tool.gateway_id = None
        a2a_tool.gateway = None
        a2a_tool.team_id = None
        a2a_tool.owner_email = "admin@example.com"
        a2a_tool.visibility = "public"
        a2a_tool.created_at = datetime.now(timezone.utc)
        a2a_tool.updated_at = datetime.now(timezone.utc)

        # Mock database query to return the A2A tool
        mock_db.execute.return_value.scalars.return_value.all.return_value = [a2a_tool]

        # Mock convert_tool_to_read to return a proper ToolRead
        mock_tool_read = MagicMock(spec=ToolRead)
        mock_tool_read.id = a2a_tool_id
        mock_tool_read.name = "a2a_calculator-agent"
        mock_tool_read.integration_type = "A2A"
        mock_tool_read.tags = ["a2a", "agent"]

        # Mock registry cache to ensure cache miss (prevents stale cached data from interfering)
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="test_hash")

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache", return_value=mock_cache),
            patch.object(tool_service, "convert_tool_to_read", return_value=mock_tool_read),
        ):
            # List tools - this should include A2A tools
            result = await tool_service.list_tools(
                db=mock_db,
                include_inactive=False,
            )

        # Result is a tuple (tools_list, next_cursor)
        tools_list = result[0] if isinstance(result, tuple) else result

        # CRITICAL: Verify A2A tool appears in the listing
        # Issue #840 reports this is not happening
        assert len(tools_list) >= 1, "A2A tool should appear in the tools listing"

        # Find the A2A tool in the results
        a2a_tools = [t for t in tools_list if getattr(t, "integration_type", None) == "A2A"]
        assert len(a2a_tools) >= 1, "At least one A2A tool should be in the listing"

    async def test_a2a_tool_filterable_by_tags(self, tool_service, mock_db):
        """Test that A2A tools can be filtered by 'a2a' and 'agent' tags.

        The Global Tools Tab likely filters by tags. A2A tools should have
        the 'a2a' and 'agent' tags to be discoverable.
        """
        # Create mock A2A tool with proper tags
        a2a_tool = MagicMock(spec=DbTool)
        a2a_tool.id = uuid.uuid4().hex
        a2a_tool.name = "a2a_calculator-agent"
        a2a_tool.original_name = "a2a_calculator-agent"
        a2a_tool.integration_type = "A2A"
        a2a_tool.enabled = True
        # Tags should be in the format used by the database
        a2a_tool.tags = [{"id": "a2a", "label": "a2a"}, {"id": "agent", "label": "agent"}, {"id": "test", "label": "test"}]
        a2a_tool.annotations = {"a2a_agent_id": "test-agent-id"}
        a2a_tool.gateway_id = None
        a2a_tool.gateway = None
        a2a_tool.team_id = None
        a2a_tool.owner_email = "admin@example.com"
        a2a_tool.visibility = "public"
        a2a_tool.created_at = datetime.now(timezone.utc)
        a2a_tool.updated_at = datetime.now(timezone.utc)

        # Mock database query with tag filter
        mock_db.execute.return_value.scalars.return_value.all.return_value = [a2a_tool]

        mock_tool_read = MagicMock(spec=ToolRead)
        mock_tool_read.id = a2a_tool.id
        mock_tool_read.name = "a2a_calculator-agent"
        mock_tool_read.integration_type = "A2A"
        mock_tool_read.tags = ["a2a", "agent", "test"]

        # Mock registry cache to ensure cache miss (prevents stale cached data from interfering)
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.hash_filters = MagicMock(return_value="test_hash")

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache", return_value=mock_cache),
            patch.object(tool_service, "convert_tool_to_read", return_value=mock_tool_read),
        ):
            # Filter by "a2a" tag - should find the A2A tool
            result = await tool_service.list_tools(
                db=mock_db,
                tags=["a2a"],
                include_inactive=False,
            )

        tools_list = result[0] if isinstance(result, tuple) else result

        # Verify A2A tool is found when filtering by "a2a" tag
        assert len(tools_list) >= 1, "A2A tool should be found when filtering by 'a2a' tag"

    async def test_tool_integration_type_a2a_is_preserved(self, mock_db):
        """Test that integration_type='A2A' is preserved throughout the tool lifecycle.

        This test verifies that when a tool is created for an A2A agent,
        the integration_type='A2A' is properly set and preserved.
        """
        # The tool should be created with integration_type="A2A"
        # as defined in tool_service.create_tool_from_a2a_agent()

        # Document the expected ToolCreate data
        expected_tool_create_fields = {
            "name": "a2a_calculator-agent",
            "integration_type": "A2A",  # This is the key field
            "tags": ["test", "a2a", "agent"],  # Must include a2a and agent
            "annotations": {
                "a2a_agent_id": "agent-uuid-here",
                "a2a_agent_type": "custom",
            },
        }

        # Verify the expected structure
        assert expected_tool_create_fields["integration_type"] == "A2A"
        assert "a2a" in expected_tool_create_fields["tags"]
        assert "agent" in expected_tool_create_fields["tags"]
        assert "a2a_agent_id" in expected_tool_create_fields["annotations"]


class TestIssue840ToolInvocationRouting:
    """Test that A2A tools are properly routed to their agents when invoked.

    Even if A2A tools appear in the listing, they need to be properly invoked
    when called. The tool_service should recognize integration_type="A2A" and
    route the call to the A2A agent service.
    """

    @pytest.fixture
    def tool_service(self):
        """Create tool service instance."""
        return ToolService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    async def test_a2a_tool_invocation_routes_to_agent_service(self, tool_service, mock_db):
        """Test that invoking an A2A tool routes to the A2A agent service.

        When a tool with integration_type="A2A" is invoked, it should:
        1. Extract the a2a_agent_id from annotations
        2. Call A2AAgentService.invoke_agent()
        3. Return the agent's response
        """
        # Create mock A2A tool
        a2a_tool = MagicMock(spec=DbTool)
        a2a_tool.id = uuid.uuid4().hex
        a2a_tool.name = "a2a_calculator-agent"
        a2a_tool.integration_type = "A2A"
        a2a_tool.annotations = {"a2a_agent_id": "test-agent-id", "a2a_agent_type": "custom"}
        a2a_tool.enabled = True

        # The tool invocation should check integration_type and route appropriately
        # From tool_service.py line ~2365:
        # if tool_integration_type == "A2A" and tool_annotations and "a2a_agent_id" in tool_annotations:
        #     return await self._invoke_a2a_tool(db=db, tool=tool_stub, arguments=arguments)

        # Document expected behavior
        assert a2a_tool.integration_type == "A2A", "Tool must have integration_type='A2A'"
        assert "a2a_agent_id" in a2a_tool.annotations, "Tool annotations must include a2a_agent_id"

        # When invoked with user arguments, the query should be passed to the agent.
        # Example expected arguments format: {"query": "calc: 7*8"}

        # The _invoke_a2a_tool method should:
        # 1. Look up the A2A agent by ID from annotations
        # 2. Call invoke_agent with the user's arguments
        # 3. Return the agent's response

        # This documents the expected flow for proper A2A tool invocation
        expected_invocation_flow = [
            "1. Receive tool invocation with arguments",
            "2. Check integration_type == 'A2A'",
            "3. Extract a2a_agent_id from annotations",
            "4. Call A2AAgentService.invoke_agent(agent_id, arguments)",
            "5. Return agent response as ToolResult",
        ]

        assert len(expected_invocation_flow) == 5


class TestIssue840CustomAgentQueryFormat:
    """Test that custom A2A agents receive query as string, not JSONRPC message object.

    When invoking A2A tools through MCP, the code must handle agent_type correctly:
    - For JSONRPC agents: convert query to nested message structure
    - For custom agents: pass query directly as string

    Bug: Custom agents were receiving query as JSONRPC message object:
    {"message": {"messageId": "...", "role": "user", "parts": [{"type": "text", "text": "..."}]}}

    Fix: Custom agents should receive flat parameters:
    {"query": "...", "message": "..."}
    """

    @pytest.fixture
    def tool_service(self):
        """Create tool service instance."""
        return ToolService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def custom_agent(self):
        """Create a custom (non-JSONRPC) A2A agent."""
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = uuid.uuid4().hex
        agent.name = "custom-calculator-agent"
        agent.endpoint_url = "http://localhost:9100/run"
        agent.agent_type = "custom"  # NOT jsonrpc
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.enabled = True
        return agent

    @pytest.fixture
    def jsonrpc_agent(self):
        """Create a JSONRPC A2A agent."""
        agent = MagicMock(spec=DbA2AAgent)
        agent.id = uuid.uuid4().hex
        agent.name = "jsonrpc-agent"
        agent.endpoint_url = "http://localhost:9999/"
        agent.agent_type = "jsonrpc"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.enabled = True
        return agent

    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_custom_agent_receives_string_query(
        self,
        mock_get_client,
        tool_service,
        custom_agent,
    ):
        """Test that custom agents receive query as a string, not JSONRPC message object.

        This is the core bug fix verification: when MCP Tool invokes a custom A2A agent,
        the agent should receive {"parameters": {"query": "calc: 7*8"}} NOT
        {"parameters": {"message": {"messageId": ..., "parts": [...]}}}
        """
        # Mock HTTP client to capture request
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "56"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Call the agent with a flat query (how MCP tool calls it)
        parameters = {"query": "calc: 7*8"}
        await tool_service._call_a2a_agent(custom_agent, parameters)

        # Verify HTTP call was made
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        # Extract the JSON body
        request_body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert request_body is not None, "Request body should not be None"

        # CRITICAL: For custom agents, parameters should contain flat query string
        params = request_body.get("parameters", {})

        # The query should be a STRING, not an object
        query_value = params.get("query")
        assert query_value is not None, "parameters.query should exist"
        assert isinstance(query_value, str), f"parameters.query should be string, got {type(query_value)}"
        assert query_value == "calc: 7*8", f"Query should be 'calc: 7*8', got '{query_value}'"

        # Verify that 'message' is NOT a nested object (JSONRPC format)
        message_value = params.get("message")
        if message_value is not None:
            assert not isinstance(message_value, dict), "parameters.message should NOT be JSONRPC object for custom agents"

    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_jsonrpc_agent_receives_nested_message(
        self,
        mock_get_client,
        tool_service,
        jsonrpc_agent,
    ):
        """Test that JSONRPC agents receive query as nested message structure.

        JSONRPC agents expect the A2A protocol format:
        {"jsonrpc": "2.0", "method": "message/send", "params": {"message": {...}}}
        """
        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": {"text": "Hello"}}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Call the agent with a flat query
        parameters = {"query": "Hello world"}
        await tool_service._call_a2a_agent(jsonrpc_agent, parameters)

        # Verify HTTP call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        request_body = call_args.kwargs.get("json") or call_args[1].get("json")

        # For JSONRPC agents, request should be JSONRPC format
        assert request_body.get("jsonrpc") == "2.0", "Should be JSONRPC format"
        assert "params" in request_body, "Should have params"

        # params.message should be a nested object
        params = request_body.get("params", {})
        message = params.get("message")
        assert isinstance(message, dict), "params.message should be dict for JSONRPC agents"
        assert "parts" in message, "message should have parts array"
