# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_llmchat_endpoints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

Integration Tests for LLM Chat API Router

This test suite covers:
1. Multi-Worker Coordination Tests
2. Redis Failure Scenarios
3. Chat History Persistence Tests

All tests use mocked dependencies (Redis, LLM providers, MCP clients) to ensure
isolation from external services.
"""

import json
import pytest
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4


# ==================== FIXTURES ====================

@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.delete = AsyncMock(return_value=True)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.rpush = AsyncMock(return_value=1)
    redis_mock.lrange = AsyncMock(return_value=[])
    redis_mock.ltrim = AsyncMock(return_value=True)
    redis_mock.llen = AsyncMock(return_value=0)
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.fixture
def mock_mcp_client():
    """Mock MCP Client"""
    client = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_tools = AsyncMock(return_value=[])
    client.call_tool = AsyncMock(return_value={"result": "test"})
    client.is_connected = True
    return client


@pytest.fixture
def mock_agent():
    """Mock LangGraph Agent"""
    agent = AsyncMock()

    async def mock_astream_events(messages, version):
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": Mock(content="Test ")}
        }
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": Mock(content="response")}
        }

    async def mock_ainvoke(messages):
        return {"messages": [Mock(content="Test response")]}

    agent.astream_events = mock_astream_events
    agent.ainvoke = mock_ainvoke
    return agent


# ==================== HELPER FUNCTIONS ====================

def create_connect_payload(user_id: str, model: str = "test-model") -> Dict[str, Any]:
    """Helper to create connect request payload.

    Note: Models must be configured via Admin UI -> LLM Settings.
    The model parameter should match a model_id from the gateway.
    """
    return {
        "user_id": user_id,
        "server": {
            "url": "http://test-mcp-server.com/mcp",
            "transport": "streamable_http",
            "auth_token": "test-token"
        },
        "llm": {
            "model": model,
            "temperature": 0.7,
        },
        "streaming": False
    }


def create_chat_payload(user_id: str, message: str, streaming: bool = False) -> Dict[str, Any]:
    """Helper to create chat request payload"""
    return {
        "user_id": user_id,
        "message": message,
        "streaming": streaming
    }


# ==================== MULTI-WORKER COORDINATION TESTS ====================

class TestMultiWorkerCoordination:
    """Tests for multi-worker coordination scenarios"""

    @pytest.mark.asyncio
    async def test_session_handoff_between_workers(self, mock_redis):
        """Test session handoff when different workers handle requests"""
        from mcpgateway.routers.llmchat_router import set_active_session, _active_key

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "user123"
            mock_service = AsyncMock()

            await set_active_session(user_id, mock_service)

            mock_redis.set.assert_called()
            call_args = mock_redis.set.call_args[0]
            assert _active_key(user_id) in str(call_args)

            with patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-2'):
                mock_redis.get = AsyncMock(return_value='worker-1')
                owner_result = await mock_redis.get(_active_key(user_id))
                assert owner_result == 'worker-1'


    @pytest.mark.asyncio
    async def test_distributed_lock_acquisition_and_release(self, mock_redis):
        """Test distributed lock mechanism for session initialization"""
        from mcpgateway.routers.llmchat_router import _try_acquire_lock, _release_lock_safe

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "user123"

            mock_redis.set = AsyncMock(return_value=True)
            acquired = await _try_acquire_lock(user_id)
            assert acquired is True

            mock_redis.set.assert_called()

            mock_redis.get = AsyncMock(return_value='worker-1')
            await _release_lock_safe(user_id)
            mock_redis.delete.assert_called()


    @pytest.mark.asyncio
    async def test_session_ttl_expiration_and_renewal(self, mock_redis):
        """Test session TTL expiration and automatic renewal"""
        from mcpgateway.routers.llmchat_router import get_active_session

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            # Import locally to avoid affecting other tests
            from mcpgateway.routers import llmchat_router as router_module

            user_id = "user123"
            mock_service = AsyncMock()

            # Temporarily add to sessions
            original_sessions = router_module.active_sessions.copy()
            router_module.active_sessions[user_id] = mock_service

            try:
                mock_redis.get = AsyncMock(return_value='worker-1')
                mock_redis.expire = AsyncMock(return_value=True)

                session = await get_active_session(user_id)

                assert session is not None
                assert session == mock_service
                mock_redis.expire.assert_called()
            finally:
                # Restore original state
                router_module.active_sessions.clear()
                router_module.active_sessions.update(original_sessions)


# ==================== REDIS FAILURE SCENARIOS ====================

class TestRedisFailureScenarios:
    """Tests for Redis failure and fallback scenarios"""

    @pytest.mark.asyncio
    async def test_graceful_degradation_redis_unavailable(self):
        """Test graceful degradation when Redis is unavailable"""
        from mcpgateway.routers.llmchat_router import (
            set_user_config, get_user_config, set_active_session, get_active_session
        )
        from mcpgateway.services.mcp_client_chat_service import (
            MCPClientConfig, MCPServerConfig, LLMConfig, OllamaConfig
        )

        with patch('mcpgateway.routers.llmchat_router.redis_client', None):

            user_id = "test_user_" + str(uuid4())
            config = MCPClientConfig(
                mcp_server=MCPServerConfig(url="http://test.com/mcp"),
                llm=LLMConfig(provider="ollama", config=OllamaConfig(model="llama2"))
            )

            await set_user_config(user_id, config)
            retrieved_config = await get_user_config(user_id)
            assert retrieved_config == config

            mock_service = AsyncMock()
            await set_active_session(user_id, mock_service)
            session = await get_active_session(user_id)
            assert session == mock_service

            # Cleanup
            from mcpgateway.routers import llmchat_router as router_module
            if user_id in router_module.user_configs:
                del router_module.user_configs[user_id]
            if user_id in router_module.active_sessions:
                del router_module.active_sessions[user_id]


    @pytest.mark.asyncio
    async def test_redis_connection_loss_during_active_session(self, mock_redis):
        """Test handling of Redis connection loss during an active session"""
        from mcpgateway.routers.llmchat_router import get_active_session
        from mcpgateway.routers import llmchat_router as router_module

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "test_user_" + str(uuid4())
            mock_service = AsyncMock()

            original_sessions = router_module.active_sessions.copy()
            router_module.active_sessions[user_id] = mock_service

            try:
                mock_redis.get = AsyncMock(return_value='worker-1')
                mock_redis.expire = AsyncMock(side_effect=ConnectionError("Redis connection lost"))

                session = await get_active_session(user_id)
                assert session == mock_service
            finally:
                router_module.active_sessions.clear()
                router_module.active_sessions.update(original_sessions)


# ==================== CHAT HISTORY PERSISTENCE TESTS ====================

class TestChatHistoryPersistence:
    """Tests for chat history persistence and management"""

    @pytest.mark.asyncio
    async def test_history_with_redis(self, mock_redis):
        """Test chat history with Redis backend"""
        from mcpgateway.services.mcp_client_chat_service import ChatHistoryManager

        user_id = "test_user_" + str(uuid4())

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]

        # Mock Redis to return JSON data
        mock_redis.get = AsyncMock(return_value=json.dumps(messages))

        history_manager = ChatHistoryManager(redis_client=mock_redis, max_messages=100)

        history = await history_manager.get_history(user_id)

        mock_redis.get.assert_called()
        assert len(history) == 2
        assert history[0]["content"] == "Hello"
        assert history[1]["content"] == "Hi there!"


    @pytest.mark.asyncio
    async def test_message_ordering_in_memory(self):
        """Test message ordering with in-memory storage"""
        from mcpgateway.services.mcp_client_chat_service import ChatHistoryManager

        user_id = "test_user_" + str(uuid4())
        history_manager = ChatHistoryManager(redis_client=None)

        for i in range(5):
            await history_manager.append_message(user_id, "user", f"Message {i}")

        history = await history_manager.get_history(user_id)
        assert len(history) == 5
        for i, msg in enumerate(history):
            assert msg["content"] == f"Message {i}"

        # Cleanup
        await history_manager.clear_history(user_id)


    @pytest.mark.asyncio
    async def test_history_size_limits(self):
        """Test chat history size limits and automatic trimming"""
        from mcpgateway.services.mcp_client_chat_service import ChatHistoryManager

        user_id = "test_user_" + str(uuid4())
        max_messages = 10
        history_manager = ChatHistoryManager(redis_client=None, max_messages=max_messages)

        for i in range(15):
            await history_manager.append_message(user_id, "user", f"Message {i}")

        history = await history_manager.get_history(user_id)
        assert len(history) <= max_messages

        # Cleanup
        await history_manager.clear_history(user_id)


    @pytest.mark.asyncio
    async def test_clear_history(self, mock_redis):
        """Test clear history operation"""
        from mcpgateway.services.mcp_client_chat_service import ChatHistoryManager

        user_id = "test_user_" + str(uuid4())

        history_manager = ChatHistoryManager(redis_client=mock_redis)

        mock_redis.delete = AsyncMock(return_value=True)
        await history_manager.clear_history(user_id)

        mock_redis.delete.assert_called()


# ==================== CONFIGURATION TESTS ====================

class TestConfigurationManagement:
    """Tests for configuration management"""

    @pytest.mark.asyncio
    async def test_config_storage_and_retrieval(self):
        """Test storing and retrieving user configuration"""
        from mcpgateway.routers.llmchat_router import set_user_config, get_user_config
        from mcpgateway.services.mcp_client_chat_service import (
            MCPClientConfig, MCPServerConfig, LLMConfig, OllamaConfig
        )

        with patch('mcpgateway.routers.llmchat_router.redis_client', None):
            user_id = "test_user_" + str(uuid4())
            config = MCPClientConfig(
                mcp_server=MCPServerConfig(url="http://test.com/mcp"),
                llm=LLMConfig(provider="ollama", config=OllamaConfig(model="llama2"))
            )

            await set_user_config(user_id, config)
            retrieved = await get_user_config(user_id)

            assert retrieved == config

            # Cleanup
            from mcpgateway.routers import llmchat_router as router_module
            if user_id in router_module.user_configs:
                del router_module.user_configs[user_id]


    @pytest.mark.asyncio
    async def test_config_with_redis(self, mock_redis):
        """Test configuration storage with Redis"""
        from mcpgateway.routers.llmchat_router import set_user_config
        from mcpgateway.services.mcp_client_chat_service import (
            MCPClientConfig, MCPServerConfig, LLMConfig, OllamaConfig
        )

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis):
            user_id = "test_user_" + str(uuid4())
            config = MCPClientConfig(
                mcp_server=MCPServerConfig(url="http://test.com/mcp"),
                llm=LLMConfig(provider="ollama", config=OllamaConfig(model="llama2"))
            )

            mock_redis.set = AsyncMock(return_value=True)
            await set_user_config(user_id, config)

            mock_redis.set.assert_called()


# ==================== LOCK MECHANISM TESTS ====================

class TestLockMechanism:
    """Tests for distributed lock mechanism"""

    @pytest.mark.asyncio
    async def test_lock_acquisition(self, mock_redis):
        """Test successful lock acquisition"""
        from mcpgateway.routers.llmchat_router import _try_acquire_lock

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "test_user_" + str(uuid4())

            mock_redis.set = AsyncMock(return_value=True)
            acquired = await _try_acquire_lock(user_id)

            assert acquired is True
            mock_redis.set.assert_called()


    @pytest.mark.asyncio
    async def test_lock_failure(self, mock_redis):
        """Test failed lock acquisition"""
        from mcpgateway.routers.llmchat_router import _try_acquire_lock

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "test_user_" + str(uuid4())

            mock_redis.set = AsyncMock(return_value=False)
            acquired = await _try_acquire_lock(user_id)

            assert acquired is False


    @pytest.mark.asyncio
    async def test_lock_release(self, mock_redis):
        """Test lock release"""
        from mcpgateway.routers.llmchat_router import _release_lock_safe

        with patch('mcpgateway.routers.llmchat_router.redis_client', mock_redis), \
             patch('mcpgateway.routers.llmchat_router.WORKER_ID', 'worker-1'):

            user_id = "test_user_" + str(uuid4())

            mock_redis.get = AsyncMock(return_value='worker-1')
            mock_redis.delete = AsyncMock(return_value=True)

            await _release_lock_safe(user_id)

            mock_redis.delete.assert_called()
