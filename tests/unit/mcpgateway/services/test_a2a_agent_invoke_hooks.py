# -*- coding: utf-8 -*-
"""Unit tests for A2A agent invoke plugin hook integration.

Tests that the plugin hooks fired inside `invoke_agent()` receive the correct
payloads and that hook results are applied correctly.

Uses the same mocking pattern as `test_a2a_service.py` for DB and HTTP, with
additional mocking of `_get_plugin_manager` to control plugin hook behaviour.

Tests cover:
    - PRE_INVOKE fires with correct AgentPreInvokePayload (headers=request_headers)
    - PRE_INVOKE applies modified headers to prepared request
    - PRE_INVOKE applies modified parameters
    - PRE_INVOKE PluginViolationError is raised as A2AAgentError
    - POST_INVOKE fires (non-blocking)
    - POST_INVOKE errors are swallowed (logged)
    - No hooks when plugin_manager is None
    - GlobalContext has correct server_id and A2A_AGENT_METADATA
    - content_type is set in agent metadata when provided
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService


@pytest.fixture
def service():
    return A2AAgentService()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def sample_agent_id():
    return "agent-123"


@pytest.fixture
def sample_agent_name():
    return "test-agent"


@pytest.fixture
def mock_agent(sample_agent_id, sample_agent_name):
    agent = MagicMock()
    agent.id = sample_agent_id
    agent.name = sample_agent_name
    agent.enabled = True
    agent.endpoint_url = "http://localhost:9999/agent"
    agent.agent_type = "custom"
    agent.protocol_version = "1.0"
    agent.auth_type = None
    agent.auth_value = None
    agent.auth_query_params = None
    agent.team_id = "team-a"
    agent.owner_email = None
    agent.visibility = "public"
    agent.passthrough_headers = ["x-forwarded-for", "x-request-id", "x-forwarded-proto", "accept-language", "x-custom-header"]
    agent.oauth_config = None
    agent.tags = []
    agent.uaid = None
    agent.uaid_native_id = None
    return agent


def _make_plugin_manager(has_pre=True, has_post=True):
    pm = MagicMock()

    def _has_hooks(hook_type):
        # Third-Party
        from cpex.framework import AgentHookType

        if hook_type == AgentHookType.AGENT_PRE_INVOKE:
            return has_pre
        if hook_type == AgentHookType.AGENT_POST_INVOKE:
            return has_post
        return False

    pm.has_hooks_for = MagicMock(side_effect=_has_hooks)
    pm.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=None, retry_delay_ms=0), {}))
    return pm


class TestA2AInvokePreHook:
    """Tests for the AGENT_PRE_INVOKE hook in invoke_agent."""

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_request_headers_filtered_by_passthrough_whitelist(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """Only headers in agent.passthrough_headers reach plugins."""
        # Narrow whitelist to a subset of headers
        mock_agent.passthrough_headers = ["x-request-id", "x-tenant-id"]

        inbound_headers = {
            "x-tenant-id": "tenant-123",
            "x-request-id": "req-456",
            "user-agent": "Mozilla/5.0",
            "referer": "https://example.com",
            "authorization": "Bearer secret",
        }
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                request_headers=inbound_headers,
            )

        payload = pm.invoke_hook.await_args_list[0].kwargs["payload"]
        filtered = payload.headers.root
        assert "x-tenant-id" in filtered
        assert "x-request-id" in filtered
        assert "user-agent" not in filtered
        assert "referer" not in filtered
        assert "authorization" not in filtered

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_no_passthrough_headers_strips_all(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When agent.passthrough_headers is None, no headers reach plugins."""
        mock_agent.passthrough_headers = None

        inbound_headers = {"x-tenant-id": "tenant-123", "x-request-id": "req-456"}
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                request_headers=inbound_headers,
            )

        payload = pm.invoke_hook.await_args_list[0].kwargs["payload"]
        assert payload.headers.root == {}

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_pre_invoke_hook_receives_request_headers(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """PRE_INVOKE receives the inbound request_headers as AgentPreInvokePayload.headers."""
        # Third-Party
        from cpex.framework import AgentHookType, AgentPreInvokePayload

        inbound_headers = {"x-forwarded-for": "10.0.0.1", "x-request-id": "req-001"}
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                request_headers=inbound_headers,
            )

        first_call = pm.invoke_hook.await_args_list[0]
        assert first_call.args[0] == AgentHookType.AGENT_PRE_INVOKE
        payload = first_call.kwargs["payload"]
        assert isinstance(payload, AgentPreInvokePayload)
        assert payload.agent_id == mock_agent.id
        assert payload.headers is not None
        assert payload.headers.root == inbound_headers

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_pre_invoke_default_headers_when_no_request_headers(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When request_headers is None, PRE_INVOKE receives an empty dict."""
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                request_headers=None,
            )

        payload = pm.invoke_hook.await_args_list[0].kwargs["payload"]
        assert payload.headers.root == {}

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_pre_invoke_modified_headers_applied_to_prepared(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """Headers modified by the plugin are applied to the outbound prepared request headers."""
        # Third-Party
        from cpex.framework import HttpHeaderPayload

        pm = _make_plugin_manager()
        modified = SimpleNamespace(
            modified_payload=SimpleNamespace(
                parameters=None,
                headers=HttpHeaderPayload(root={"X-Custom": "value", "Authorization": "Bearer plugin-added"}),
            ),
            retry_delay_ms=0,
        )
        pm.invoke_hook = AsyncMock(return_value=(modified, {}))

        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                request_headers={"x-inbound": "original"},
            )

        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("X-Custom") == "value"
        assert headers.get("Authorization") == "Bearer plugin-added"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_pre_invoke_plugin_violation_error_propagated(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """PluginViolationError from PRE_INVOKE is raised as A2AAgentError."""
        # Third-Party
        from cpex.framework.errors import PluginViolationError

        pm = _make_plugin_manager()
        pm.invoke_hook = AsyncMock(side_effect=PluginViolationError(message="Access denied"))

        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            with pytest.raises(A2AAgentError, match="Plugin RBAC violation"):
                await service.invoke_agent(
                    mock_db,
                    mock_agent.name,
                    {"query": "hello"},
                )

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_pre_invoke_generic_error_propagated(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """Generic exception from PRE_INVOKE (not PluginViolationError) is raised as A2AAgentError."""
        pm = _make_plugin_manager()
        pm.invoke_hook = AsyncMock(side_effect=RuntimeError("plugin crashed"))

        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            with pytest.raises(A2AAgentError, match="Pre-invoke plugin error"):
                await service.invoke_agent(
                    mock_db,
                    mock_agent.name,
                    {"query": "hello"},
                )


class TestA2AInvokePostHook:
    """Tests for the AGENT_POST_INVOKE hook in invoke_agent."""

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_post_invoke_fires_after_successful_invocation(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """POST_INVOKE is called after a successful invocation."""
        # Third-Party
        from cpex.framework import AgentHookType

        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert pm.invoke_hook.await_count == 2
        post_call = pm.invoke_hook.await_args_list[1]
        assert post_call.args[0] == AgentHookType.AGENT_POST_INVOKE

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_post_invoke_error_does_not_fail_request(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """POST_INVOKE exceptions are swallowed — the request continues."""
        pm = _make_plugin_manager()
        call_count = 0

        async def _invoke_hook_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (SimpleNamespace(modified_payload=None), {})
            raise RuntimeError("post crash")

        pm.invoke_hook = AsyncMock(side_effect=_invoke_hook_side_effect)

        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            result = await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert result["result"] == "ok"


class TestA2AInvokeNoPluginManager:
    """Tests when plugin_manager is None or has no hooks."""

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_no_plugin_manager_skips_hooks(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When _get_plugin_manager returns None, no hooks fire but invocation succeeds."""
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            result = await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert result["result"] == "ok"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_no_pre_hook_registered_skips_pre_only(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When no PRE_INVOKE hooks are registered, only POST_INVOKE is fired."""
        # Third-Party
        from cpex.framework import AgentHookType

        pm = _make_plugin_manager(has_pre=False, has_post=True)
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert pm.invoke_hook.await_count == 1
        assert pm.invoke_hook.await_args.args[0] == AgentHookType.AGENT_POST_INVOKE

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_no_post_hook_registered_skips_post_only(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When no POST_INVOKE hooks are registered, only PRE_INVOKE is fired."""
        # Third-Party
        from cpex.framework import AgentHookType

        pm = _make_plugin_manager(has_pre=True, has_post=False)
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert pm.invoke_hook.await_count == 1
        assert pm.invoke_hook.await_args.args[0] == AgentHookType.AGENT_PRE_INVOKE


class TestA2AInvokeGlobalContext:
    """Tests for GlobalContext construction in invoke_agent."""

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_global_context_server_id(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """GlobalContext.server_id is set to the context_id when team_id is present."""
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        captured_context = {}

        async def _capture_plugin_manager(agent_context_id):
            pm.last_context_id = agent_context_id

            async def _invoke_hook(hook_type, payload, global_context=None, local_contexts=None, violations_as_exceptions=True):
                captured_context["global"] = global_context
                return (SimpleNamespace(modified_payload=None, retry_delay_ms=0), {})

            pm.invoke_hook = _invoke_hook
            return pm

        with patch.object(service, "_get_plugin_manager", _capture_plugin_manager), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        gc = captured_context["global"]
        assert gc is not None
        assert gc.server_id is not None
        assert "team-a" in gc.server_id
        assert mock_agent.name in gc.server_id

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_global_context_metadata_contains_agent(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """GlobalContext.metadata contains the A2A_AGENT_METADATA key."""
        # Third-Party
        # First-Party
        from mcpgateway.schemas import A2A_AGENT_METADATA

        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        captured_context = {}

        async def _invoke_hook(hook_type, payload, global_context=None, local_contexts=None, violations_as_exceptions=True):
            captured_context["global"] = global_context
            return (SimpleNamespace(modified_payload=None, retry_delay_ms=0), {})

        pm.invoke_hook = _invoke_hook

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        gc = captured_context["global"]
        assert gc is not None
        assert A2A_AGENT_METADATA in gc.metadata
        agent_meta = gc.metadata[A2A_AGENT_METADATA]
        assert agent_meta.id == mock_agent.id
        assert agent_meta.name == mock_agent.name

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_content_type_in_agent_metadata(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When content_type is provided, it is set in the agent metadata."""
        # First-Party
        from mcpgateway.schemas import A2A_AGENT_METADATA

        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        captured_context = {}

        async def _invoke_hook(hook_type, payload, global_context=None, local_contexts=None, violations_as_exceptions=True):
            captured_context["global"] = global_context
            return (SimpleNamespace(modified_payload=None, retry_delay_ms=0), {})

        pm.invoke_hook = _invoke_hook

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch("mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"):
            await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
                content_type="application/json",
            )

        gc = captured_context["global"]
        agent_meta = gc.metadata[A2A_AGENT_METADATA]
        assert agent_meta.content_type == "application/json"

    @patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service")
    @patch("mcpgateway.services.a2a_service.fresh_db_session")
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_metadata_build_error_swallowed(
        self,
        mock_get_for_update,
        mock_get_client,
        mock_fresh_db,
        mock_metrics_buffer_fn,
        service,
        mock_db,
        mock_agent,
    ):
        """When PydanticA2AAgent construction fails, the error is logged but invocation continues."""
        pm = _make_plugin_manager()
        mock_get_for_update.return_value = mock_agent
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"result": "ok"}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        mock_ts_db = MagicMock()
        mock_fresh_db.return_value.__enter__.return_value = mock_ts_db
        mock_fresh_db.return_value.__exit__.return_value = None
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer_fn.return_value = mock_metrics_buffer

        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id

        with patch.object(service, "_get_plugin_manager", AsyncMock(return_value=pm)), patch(
            "mcpgateway.services.a2a_service.get_correlation_id", return_value="test-req-id"
        ), patch("mcpgateway.schemas.PydanticA2AAgent", side_effect=ValueError("bad field")):
            result = await service.invoke_agent(
                mock_db,
                mock_agent.name,
                {"query": "hello"},
            )

        assert result["result"] == "ok"
