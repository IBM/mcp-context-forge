# -*- coding: utf-8 -*-
"""Unit tests for ToolCallRegistry to improve coverage."""

# Standard
import asyncio
from uuid import uuid4

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.tool_call_registry import ToolCallRegistry


class TestToolCallRegistryCoverage:
    """Tests to improve coverage of ToolCallRegistry."""

    def test_register_and_get_tool_call(self):
        """Test basic register and get operations."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        tool_call_id = str(uuid4())
        session_id = "session-123"
        
        # Register
        registry.register_tool_call(tool_call_id, session_id)
        
        # Get
        result = registry.get_session_for_tool_call(tool_call_id)
        assert result == session_id
        
        # Get mapping count
        assert registry.get_mapping_count() == 1

    def test_unregister_tool_call(self):
        """Test unregister operation."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        tool_call_id = str(uuid4())
        session_id = "session-123"
        
        # Register
        registry.register_tool_call(tool_call_id, session_id)
        assert registry.get_mapping_count() == 1
        
        # Unregister
        registry.unregister_tool_call(tool_call_id)
        assert registry.get_mapping_count() == 0
        assert registry.get_session_for_tool_call(tool_call_id) is None

    def test_get_nonexistent_tool_call(self):
        """Test getting a tool call that doesn't exist."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        result = registry.get_session_for_tool_call("nonexistent")
        assert result is None

    def test_unregister_nonexistent_tool_call(self):
        """Test unregistering a tool call that doesn't exist."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        # Should not raise exception
        registry.unregister_tool_call("nonexistent")
        assert registry.get_mapping_count() == 0

    def test_register_duplicate_tool_call(self):
        """Test registering the same tool call twice."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        tool_call_id = str(uuid4())
        session_id_1 = "session-1"
        session_id_2 = "session-2"
        
        # Register first time
        registry.register_tool_call(tool_call_id, session_id_1)
        assert registry.get_session_for_tool_call(tool_call_id) == session_id_1
        
        # Register again with different session (should update)
        registry.register_tool_call(tool_call_id, session_id_2)
        assert registry.get_session_for_tool_call(tool_call_id) == session_id_2
        assert registry.get_mapping_count() == 1

    @pytest.mark.asyncio
    async def test_cleanup_stale_mappings(self):
        """Test cleanup of stale mappings."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        tool_call_id = str(uuid4())
        session_id = "session-123"
        
        # Register
        registry.register_tool_call(tool_call_id, session_id)
        assert registry.get_mapping_count() == 1
        
        # Manually set timestamp to very old value (more than 1 hour ago)
        registry._mappings[tool_call_id] = (session_id, 0.0)
        
        # Trigger cleanup
        await registry._cleanup_stale()
        
        # Verify mapping was cleaned up
        assert registry.get_mapping_count() == 0
        assert registry.get_session_for_tool_call(tool_call_id) is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_fresh_mappings(self):
        """Test that cleanup keeps fresh mappings."""
        import time
        
        registry = ToolCallRegistry(cleanup_interval=300)
        
        tool_call_id = str(uuid4())
        session_id = "session-123"
        
        # Register with current timestamp
        registry.register_tool_call(tool_call_id, session_id)
        assert registry.get_mapping_count() == 1
        
        # Trigger cleanup immediately (mapping is fresh)
        await registry._cleanup_stale()
        
        # Verify mapping still exists
        assert registry.get_mapping_count() == 1
        assert registry.get_session_for_tool_call(tool_call_id) == session_id

    @pytest.mark.asyncio
    async def test_cleanup_multiple_mappings(self):
        """Test cleanup with multiple mappings (some stale, some fresh)."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        # Register stale mapping (very old timestamp)
        stale_id = str(uuid4())
        registry.register_tool_call(stale_id, "session-stale")
        registry._mappings[stale_id] = ("session-stale", 0.0)
        
        # Register fresh mapping (current timestamp)
        fresh_id = str(uuid4())
        registry.register_tool_call(fresh_id, "session-fresh")
        
        assert registry.get_mapping_count() == 2
        
        # Trigger cleanup
        await registry._cleanup_stale()
        
        # Verify only stale mapping was removed
        assert registry.get_mapping_count() == 1
        assert registry.get_session_for_tool_call(stale_id) is None
        assert registry.get_session_for_tool_call(fresh_id) == "session-fresh"

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        """Test starting and shutting down the registry."""
        registry = ToolCallRegistry(cleanup_interval=0.1)
        
        # Start cleanup task
        await registry.start()
        assert registry._cleanup_task is not None
        assert not registry._cleanup_task.done()
        
        # Shutdown
        await registry.shutdown()
        assert registry._cleanup_task.done()
        assert registry.get_mapping_count() == 0

    @pytest.mark.asyncio
    async def test_cleanup_loop_runs_periodically(self):
        """Test that cleanup loop runs periodically."""
        registry = ToolCallRegistry(cleanup_interval=0.05)
        
        # Register a stale mapping
        tool_call_id = str(uuid4())
        registry.register_tool_call(tool_call_id, "session-123")
        registry._mappings[tool_call_id] = ("session-123", 0.0)  # Make it stale
        
        # Start cleanup task
        await registry.start()
        
        # Wait for cleanup to run
        await asyncio.sleep(0.15)
        
        # Verify mapping was cleaned up
        assert registry.get_session_for_tool_call(tool_call_id) is None
        
        # Shutdown
        await registry.shutdown()

    @pytest.mark.asyncio
    async def test_cleanup_loop_handles_exceptions(self):
        """Test that cleanup loop handles exceptions gracefully."""
        registry = ToolCallRegistry(cleanup_interval=0.05)
        
        # Start cleanup task
        await registry.start()
        
        # Corrupt the mappings to cause an exception
        registry._mappings["bad"] = ("session", "not-a-timestamp")  # type: ignore
        
        # Wait for cleanup to run (should handle exception)
        await asyncio.sleep(0.15)
        
        # Cleanup task should still be running
        assert registry._cleanup_task is not None
        assert not registry._cleanup_task.done()
        
        # Shutdown
        await registry.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_with_active_mappings(self):
        """Test shutdown clears all active mappings."""
        registry = ToolCallRegistry(cleanup_interval=300)
        
        # Register multiple mappings
        registry.register_tool_call(str(uuid4()), "session-1")
        registry.register_tool_call(str(uuid4()), "session-2")
        registry.register_tool_call(str(uuid4()), "session-3")
        assert registry.get_mapping_count() == 3
        
        # Shutdown
        await registry.shutdown()
        
        # Verify all mappings cleared
        assert registry.get_mapping_count() == 0

    @pytest.mark.asyncio
    async def test_start_when_already_started(self):
        """Test starting registry when cleanup task is already running."""
        registry = ToolCallRegistry(cleanup_interval=0.1)
        
        # Start first time
        await registry.start()
        first_task = registry._cleanup_task
        assert first_task is not None
        
        # Start again (should not create new task)
        await registry.start()
        assert registry._cleanup_task is first_task
        
        # Shutdown
        await registry.shutdown()
