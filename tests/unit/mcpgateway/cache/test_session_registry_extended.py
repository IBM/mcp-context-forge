# -*- coding: utf-8 -*-
"""Extended tests for session_registry.py to improve coverage.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This test suite focuses on uncovered code paths in session_registry.py
including import error handling, backend edge cases, and error scenarios.
"""

# Future
from __future__ import annotations

# Standard
import sys
from unittest.mock import patch, AsyncMock, Mock
import pytest
import asyncio

# First-Party
from mcpgateway.cache.session_registry import SessionRegistry


class TestImportErrors:
    """Test import error handling for optional dependencies."""

    def test_redis_import_error_flag(self):
        """Test REDIS_AVAILABLE flag when redis import fails."""
        with patch.dict(sys.modules, {'redis.asyncio': None}):
            import importlib
            import mcpgateway.cache.session_registry
            importlib.reload(mcpgateway.cache.session_registry)
            
            # Should set REDIS_AVAILABLE = False
            assert not mcpgateway.cache.session_registry.REDIS_AVAILABLE

    def test_sqlalchemy_import_error_flag(self):
        """Test SQLALCHEMY_AVAILABLE flag when sqlalchemy import fails."""
        with patch.dict(sys.modules, {'sqlalchemy': None}):
            import importlib
            import mcpgateway.cache.session_registry
            importlib.reload(mcpgateway.cache.session_registry)
            
            # Should set SQLALCHEMY_AVAILABLE = False
            assert not mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE


class TestNoneBackend:
    """Test 'none' backend functionality."""

    @pytest.mark.asyncio
    async def test_none_backend_initialization_logging(self, caplog):
        """Test that 'none' backend logs initialization message."""
        registry = SessionRegistry(backend="none")
        
        # Check that initialization message is logged
        assert "Session registry initialized with 'none' backend - session tracking disabled" in caplog.text

    @pytest.mark.asyncio
    async def test_none_backend_initialize_method(self):
        """Test 'none' backend initialize method does nothing."""
        registry = SessionRegistry(backend="none")
        
        # Should not raise any errors
        await registry.initialize()
        
        # No cleanup task should be created
        assert registry._cleanup_task is None


class TestRedisBackendErrors:
    """Test Redis backend error scenarios."""

    @pytest.mark.asyncio
    async def test_redis_add_session_error(self, monkeypatch, caplog):
        """Test Redis error during add_session."""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis connection error"))
        mock_redis.publish = AsyncMock()
        
        with patch('mcpgateway.cache.session_registry.REDIS_AVAILABLE', True):
            with patch('mcpgateway.cache.session_registry.Redis') as MockRedis:
                MockRedis.from_url.return_value = mock_redis
                
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                
                class DummyTransport:
                    async def disconnect(self):
                        pass
                    async def is_connected(self):
                        return True
                
                transport = DummyTransport()
                await registry.add_session("test_session", transport)
                
                # Should log the Redis error
                assert "Redis error adding session test_session: Redis connection error" in caplog.text

    @pytest.mark.asyncio
    async def test_redis_broadcast_error(self, monkeypatch, caplog):
        """Test Redis error during broadcast."""
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=Exception("Redis publish error"))
        
        with patch('mcpgateway.cache.session_registry.REDIS_AVAILABLE', True):
            with patch('mcpgateway.cache.session_registry.Redis') as MockRedis:
                MockRedis.from_url.return_value = mock_redis
                
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                
                await registry.broadcast("test_session", {"test": "message"})
                
                # Should log the Redis error
                assert "Redis error during broadcast: Redis publish error" in caplog.text


class TestDatabaseBackendErrors:
    """Test database backend error scenarios."""

    @pytest.mark.asyncio 
    async def test_database_add_session_error(self, monkeypatch, caplog):
        """Test database error during add_session."""
        def mock_get_db():
            mock_session = Mock()
            mock_session.add = Mock(side_effect=Exception("Database connection error"))
            mock_session.rollback = Mock()
            mock_session.close = Mock()
            yield mock_session
        
        with patch('mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE', True):
            with patch('mcpgateway.cache.session_registry.get_db', mock_get_db):
                with patch('asyncio.to_thread') as mock_to_thread:
                    # Simulate the database error being raised from the thread
                    mock_to_thread.side_effect = Exception("Database connection error")
                    
                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
                    
                    class DummyTransport:
                        async def disconnect(self):
                            pass
                        async def is_connected(self):
                            return True
                    
                    transport = DummyTransport()
                    await registry.add_session("test_session", transport)
                    
                    # Should log the database error
                    assert "Database error adding session test_session: Database connection error" in caplog.text

    @pytest.mark.asyncio
    async def test_database_broadcast_error(self, monkeypatch, caplog):
        """Test database error during broadcast."""
        def mock_get_db():
            mock_session = Mock()
            mock_session.add = Mock(side_effect=Exception("Database broadcast error"))
            mock_session.rollback = Mock()
            mock_session.close = Mock()
            yield mock_session
        
        with patch('mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE', True):
            with patch('mcpgateway.cache.session_registry.get_db', mock_get_db):
                with patch('asyncio.to_thread') as mock_to_thread:
                    # Simulate the database error being raised from the thread
                    mock_to_thread.side_effect = Exception("Database broadcast error")
                    
                    registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
                    
                    await registry.broadcast("test_session", {"test": "message"})
                    
                    # Should log the database error
                    assert "Database error during broadcast: Database broadcast error" in caplog.text


class TestInitializationAndShutdown:
    """Test initialization and shutdown methods."""

    @pytest.mark.asyncio
    async def test_memory_backend_initialization_logging(self, caplog):
        """Test memory backend initialization creates cleanup task."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()
        
        try:
            # Should log initialization
            assert "Initializing session registry with backend: memory" in caplog.text
            assert "Memory cleanup task started" in caplog.text
            
            # Should have created cleanup task
            assert registry._cleanup_task is not None
            assert not registry._cleanup_task.done()
            
        finally:
            await registry.shutdown()

    @pytest.mark.asyncio
    async def test_database_backend_initialization_logging(self, caplog):
        """Test database backend initialization creates cleanup task."""
        with patch('mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE', True):
            registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
            await registry.initialize()
            
            try:
                # Should log initialization 
                assert "Initializing session registry with backend: database" in caplog.text
                assert "Database cleanup task started" in caplog.text
                
                # Should have created cleanup task
                assert registry._cleanup_task is not None
                assert not registry._cleanup_task.done()
                
            finally:
                await registry.shutdown()

    @pytest.mark.asyncio
    async def test_redis_initialization_subscribe(self, monkeypatch):
        """Test Redis backend initialization subscribes to events."""
        mock_redis = AsyncMock()
        mock_pubsub = AsyncMock()
        mock_redis.pubsub = Mock(return_value=mock_pubsub)  # Use Mock for sync method
        
        with patch('mcpgateway.cache.session_registry.REDIS_AVAILABLE', True):
            with patch('mcpgateway.cache.session_registry.Redis') as MockRedis:
                MockRedis.from_url.return_value = mock_redis
                
                registry = SessionRegistry(backend="redis", redis_url="redis://localhost")
                await registry.initialize()
                
                try:
                    # Should have subscribed to events channel
                    mock_pubsub.subscribe.assert_called_once_with("mcp_session_events")
                    
                finally:
                    await registry.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_cleanup_task(self):
        """Test shutdown properly cancels cleanup tasks."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()
        
        original_task = registry._cleanup_task
        assert not original_task.cancelled()
        
        await registry.shutdown()
        
        # Task should be cancelled
        assert original_task.cancelled()

    @pytest.mark.asyncio
    async def test_shutdown_handles_already_cancelled_task(self):
        """Test shutdown handles already cancelled cleanup task."""
        registry = SessionRegistry(backend="memory")
        await registry.initialize()
        
        # Cancel task before shutdown
        registry._cleanup_task.cancel()
        
        # Shutdown should not raise error
        await registry.shutdown()