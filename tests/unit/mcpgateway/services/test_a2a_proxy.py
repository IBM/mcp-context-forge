# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_proxy.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for the A2A JSON-RPC transparent proxy.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentNotFoundError, A2AAgentService


@pytest.fixture
def service():
    return A2AAgentService()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def sample_agent_name():
    return "proxy-test-agent"


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.id = "agent-proxy-001"
    agent.name = "proxy-test-agent"
    agent.enabled = True
    agent.endpoint_url = "http://localhost:9999/a2a"
    agent.agent_type = "custom"
    agent.protocol_version = "1.0"
    agent.auth_type = None
    agent.auth_value = None
    agent.auth_query_params = None
    return agent


@pytest.fixture
def mock_response_200():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"jsonrpc":"2.0","result":{"ok":true},"id":1}'
    resp.json.return_value = {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}
    return resp


class TestProxyA2ARequest:

    # ── Happy path tests ──

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_valid_tasks_send(self, mock_get_for_update, mock_get_http_client,
                                           service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            result = await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1})
        assert result["result"]["ok"] is True

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_valid_tasks_get(self, mock_get_for_update, mock_get_http_client,
                                          service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            result = await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "tasks/get", "params": {"id": "t1"}, "id": 2})
        assert result["id"] == 1

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_v1_send_message(self, mock_get_for_update, mock_get_http_client,
                                          service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            result = await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "SendMessage", "params": {}, "id": 3})
        assert result["id"] == 1

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_auto_adds_jsonrpc(self, mock_get_for_update, mock_get_http_client,
                                            service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"method": "message/send", "params": {}, "id": 1})
        forwarded = mock_get_http_client.return_value.post.call_args[1]["json"]
        assert forwarded["jsonrpc"] == "2.0"

    # ── Validation / rejection tests ──

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_rejects_invalid_method(self, mock_get_for_update, service, mock_db, mock_agent):
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            with pytest.raises(A2AAgentError, match="Unknown A2A method"):
                await service.proxy_a2a_request(mock_db, mock_agent.name,
                    {"jsonrpc": "2.0", "method": "invalid/method", "id": 1})

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_rejects_missing_method(self, mock_get_for_update, service, mock_db, mock_agent):
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            with pytest.raises(A2AAgentError, match="requires a 'method' field"):
                await service.proxy_a2a_request(mock_db, mock_agent.name,
                    {"jsonrpc": "2.0", "params": {}, "id": 1})

    @pytest.mark.asyncio
    async def test_proxy_rejects_non_dict(self, service, mock_db):
        with pytest.raises(A2AAgentError, match="requires a JSON-RPC body"):
            await service.proxy_a2a_request(mock_db, "test", "not-a-dict")  # type: ignore

    # ── Agent resolution tests ──

    @pytest.mark.asyncio
    async def test_proxy_agent_not_found(self, service, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(A2AAgentNotFoundError, match="not found"):
            await service.proxy_a2a_request(mock_db, "no-such-agent",
                {"jsonrpc": "2.0", "method": "message/send", "id": 1})

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_agent_disabled(self, mock_get_for_update, service, mock_db, mock_agent):
        mock_agent.enabled = False
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            with pytest.raises(A2AAgentError, match="disabled"):
                await service.proxy_a2a_request(mock_db, mock_agent.name,
                    {"jsonrpc": "2.0", "method": "message/send", "id": 1})

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_access_denied(self, mock_get_for_update, service, mock_db, mock_agent):
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=False):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            with pytest.raises(A2AAgentNotFoundError):
                await service.proxy_a2a_request(mock_db, mock_agent.name,
                    {"jsonrpc": "2.0", "method": "message/send", "id": 1})

    # ── Header / auth / hop counter tests ──

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_stamps_hop_counter(self, mock_get_for_update, mock_get_http_client,
                                             service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "message/send", "id": 1}, hop_count=1)
        headers = mock_get_http_client.return_value.post.call_args[1]["headers"]
        assert "X-Contextforge-UAID-Hop" in headers

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_forwards_bearer_token(self, mock_get_for_update, mock_get_http_client,
                                                service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "message/send", "id": 1},
                bearer_token="test.jwt.token")
        headers = mock_get_http_client.return_value.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test.jwt.token"

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    @patch("mcpgateway.utils.services_auth.decode_auth")
    async def test_proxy_forwards_bearer_auth(self, mock_decode_auth, mock_get_for_update,
                                               mock_get_http_client, service, mock_db, mock_agent, mock_response_200):
        mock_agent.auth_type = "bearer"
        mock_agent.auth_value = "encrypted"
        mock_decode_auth.return_value = "decrypted-token"
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "message/send", "id": 1})
        headers = mock_get_http_client.return_value.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer decrypted-token"

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_a2a_version_header(self, mock_get_for_update, mock_get_http_client,
                                              service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "message/send", "id": 1})
        headers = mock_get_http_client.return_value.post.call_args[1]["headers"]
        assert headers["A2A-Version"] == "1.0"

    # ── Error handling tests ──

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_downstream_http_error(self, mock_get_for_update, mock_get_http_client,
                                                service, mock_db, mock_agent):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "boom"
        mock_get_http_client.return_value.post.return_value = mock_response
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            with pytest.raises(A2AAgentError, match="returned HTTP 500"):
                await service.proxy_a2a_request(mock_db, mock_agent.name,
                    {"jsonrpc": "2.0", "method": "message/send", "id": 1})

    # ── Agent card method tests ──

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    @patch("mcpgateway.services.a2a_service.get_for_update")
    async def test_proxy_agent_card_methods(self, mock_get_for_update, mock_get_http_client,
                                              service, mock_db, mock_agent, mock_response_200):
        mock_get_http_client.return_value.post.return_value = mock_response_200
        mock_get_for_update.return_value = mock_agent
        with patch.object(service, "_check_agent_access", return_value=True):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_agent.id
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "agent/getCard", "id": 1})
            await service.proxy_a2a_request(mock_db, mock_agent.name,
                {"jsonrpc": "2.0", "method": "GetAgentCard", "id": 2})
        assert mock_get_http_client.return_value.post.call_count == 2
