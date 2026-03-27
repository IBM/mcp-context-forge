"""
Unit tests for version_control_plugin.py

Tests the VersionControlPlugin class including:
- Plugin initialization
- tool_pre_invoke hook (blocking logic)
- Background polling
- Shutdown behavior
"""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock, call
from sqlalchemy import text

from mcpgateway.plugins.framework.models import PluginConfig, PluginContext, GlobalContext
from mcpgateway.plugins.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult

from plugins.version_control.version_control_plugin import VersionControlPlugin
from plugins.version_control.core.version_control_core import VersionControlDB, VersionControlCore, ServerVersion


class TestVersionControlPluginInit:
    """Test suite for VersionControlPlugin initialization"""
    
    def test_init_with_valid_config(self):
        """Test plugin initialization with valid configuration"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 60,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                
                assert plugin.enabled is True
                assert plugin.polling_interval == 60
                assert plugin.db_manager is not None
                assert plugin.vc_core is not None
                
    def test_init_disabled_when_missing_db_urls(self):
        """Test plugin is disabled when database URLs are missing"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 60
                # Missing main_db_url and vc_db_url
            }
        )
        
        plugin = VersionControlPlugin(config)
        
        assert plugin.enabled is False
        
    def test_init_with_custom_polling_interval(self):
        """Test plugin initialization with custom polling interval"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 120,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                
                assert plugin.polling_interval == 120


class TestVersionControlPluginInitialize:
    """Test suite for plugin initialization (async)"""
    
    @pytest.mark.asyncio
    async def test_initialize_performs_backfill(self):
        """Test that initialize performs initial server backfill"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 60,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                
                # Mock backfill_existing_servers
                with patch.object(plugin.vc_core, 'backfill_existing_servers', new_callable=AsyncMock) as mock_backfill:
                    mock_backfill.return_value = 3  # 3 servers backfilled
                    
                    await plugin.initialize()
                    
                    # Verify backfill was called
                    mock_backfill.assert_called_once_with(created_by="plugin")
                    
                    # Verify polling task was started
                    assert plugin._polling_task is not None
                    
                    # Clean up
                    plugin._shutdown_event.set()
                    if plugin._polling_task:
                        plugin._polling_task.cancel()
                        try:
                            await plugin._polling_task
                        except asyncio.CancelledError:
                            pass
                            
    @pytest.mark.asyncio
    async def test_initialize_disabled_plugin_does_nothing(self):
        """Test that disabled plugin doesn't perform initialization"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": False,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                plugin.enabled = False
                
                await plugin.initialize()
                
                # Verify no polling task was started
                assert plugin._polling_task is None


class TestVersionControlPluginToolPreInvoke:
    """Test suite for tool_pre_invoke hook - CRITICAL SECURITY TESTS"""
    
    @pytest.fixture
    def plugin_config(self):
        """Create a test plugin configuration"""
        return PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 60,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
    
    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager"""
        mock_db = MagicMock(spec=VersionControlDB)
        return mock_db
    
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_allows_active_server(self, plugin_config, mock_db_manager):
        """Test that active servers are allowed"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                # Mock database session to return active status
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_row = ('active', 1, 'test-server')
                mock_result.fetchone.return_value = mock_row
                mock_session.execute.return_value = mock_result
                
                plugin.db_manager.get_vc_session = MagicMock(return_value=mock_session)
                
                # Mock check_for_changes to return False (no changes)
                with patch.object(plugin.vc_core, 'check_for_changes', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = False
                    
                    # Create test payload and context
                    payload = ToolPreInvokePayload(name="test_tool", arguments={})
                    context = PluginContext(
                        global_context=GlobalContext(server_id=1, user_email="test@example.com")
                    )
                    
                    result = await plugin.tool_pre_invoke(payload, context)
                    
                    assert result.continue_processing is True
                    assert result.violation is None
                    assert result.metadata["version_control_check"] == "passed"
                    assert result.metadata["status"] == "active"
                    
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_blocks_deactivated_server(self, plugin_config):
        """Test that deactivated servers are blocked"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                # Mock database session to return deactivated status
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_row = ('deactivated', 1, 'test-server')
                mock_result.fetchone.return_value = mock_row
                mock_session.execute.return_value = mock_result
                
                plugin.db_manager.get_vc_session = MagicMock(return_value=mock_session)
                
                # Mock check_for_changes to return False
                with patch.object(plugin.vc_core, 'check_for_changes', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = False
                    
                    payload = ToolPreInvokePayload(name="test_tool", arguments={})
                    context = PluginContext(
                        global_context=GlobalContext(server_id=1, user_email="test@example.com")
                    )
                    
                    result = await plugin.tool_pre_invoke(payload, context)
                    
                    assert result.continue_processing is False
                    assert result.violation is not None
                    assert result.violation.code == "VERSION_CONTROL_DEACTIVATED"
                    assert "deactivated" in result.violation.description.lower()
                    
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_blocks_pending_changes(self, plugin_config):
        """Test that servers with pending changes are blocked"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                # Mock database session to return pending status
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_row = ('pending', 2, 'test-server')
                mock_result.fetchone.return_value = mock_row
                mock_session.execute.return_value = mock_result
                
                plugin.db_manager.get_vc_session = MagicMock(return_value=mock_session)
                
                # Mock check_for_changes to return False
                with patch.object(plugin.vc_core, 'check_for_changes', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = False
                    
                    payload = ToolPreInvokePayload(name="test_tool", arguments={})
                    context = PluginContext(
                        global_context=GlobalContext(server_id=1, user_email="test@example.com")
                    )
                    
                    result = await plugin.tool_pre_invoke(payload, context)
                    
                    assert result.continue_processing is False
                    assert result.violation is not None
                    assert result.violation.code == "VERSION_CONTROL_PENDING"
                    assert "pending changes" in result.violation.description.lower()
                    
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_detects_and_blocks_new_changes(self, plugin_config):
        """Test that newly detected changes create pending version and block"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                # First query returns active status
                mock_session = MagicMock()
                mock_result1 = MagicMock()
                mock_row1 = ('active', 1, 'test-server')
                mock_result1.fetchone.return_value = mock_row1
                
                # Second query returns pending status (after creating pending version)
                mock_result2 = MagicMock()
                mock_row2 = ('pending', 2, 'test-server')
                mock_result2.fetchone.return_value = mock_row2
                
                mock_session.execute.side_effect = [mock_result1, mock_result2]
                plugin.db_manager.get_vc_session = MagicMock(return_value=mock_session)
                
                # Mock check_for_changes to return True (changes detected)
                with patch.object(plugin.vc_core, 'check_for_changes', new_callable=AsyncMock) as mock_check:
                    mock_check.return_value = True
                    
                    # Mock create_pending_version
                    mock_pending_version = MagicMock()
                    mock_pending_version.version_number = 2
                    mock_pending_version.server_name = 'test-server'
                    
                    with patch.object(plugin.vc_core, 'create_pending_version', new_callable=AsyncMock) as mock_create:
                        mock_create.return_value = mock_pending_version
                        
                        payload = ToolPreInvokePayload(name="test_tool", arguments={})
                        context = PluginContext(
                            global_context=GlobalContext(server_id=1, user_email="test@example.com")
                        )
                        
                        result = await plugin.tool_pre_invoke(payload, context)
                        
                        # Verify pending version was created
                        mock_create.assert_called_once()
                        
                        # Verify call was blocked
                        assert result.continue_processing is False
                        assert result.violation is not None
                        assert result.violation.code == "VERSION_CONTROL_CHANGES_DETECTED"
                        
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_creates_initial_version_for_new_server(self, plugin_config):
        """Test that new servers get initial version created"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                # Mock database session to return no existing version
                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.fetchone.return_value = None  # No version exists
                mock_session.execute.return_value = mock_result
                
                plugin.db_manager.get_vc_session = MagicMock(return_value=mock_session)
                
                # Mock create_initial_version
                mock_initial_version = MagicMock()
                mock_initial_version.version_number = 1
                mock_initial_version.server_name = 'new-server'
                
                with patch.object(plugin.vc_core, 'create_initial_version', new_callable=AsyncMock) as mock_create:
                    mock_create.return_value = mock_initial_version
                    
                    payload = ToolPreInvokePayload(name="test_tool", arguments={})
                    context = PluginContext(
                        global_context=GlobalContext(server_id=999, user_email="test@example.com")
                    )
                    
                    result = await plugin.tool_pre_invoke(payload, context)
                    
                    # Verify initial version was created
                    mock_create.assert_called_once_with(999, created_by="tool_pre_hook")
                    
                    # Verify call was allowed
                    assert result.continue_processing is True
                    assert result.metadata["version_control_check"] == "new_server_backfilled"
                    
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_disabled_plugin_allows_all(self, plugin_config):
        """Test that disabled plugin allows all calls"""
        plugin_config.config["enabled"] = False
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                plugin.enabled = False
                
                payload = ToolPreInvokePayload(name="test_tool", arguments={})
                context = PluginContext(
                    global_context=GlobalContext(server_id=1, user_email="test@example.com")
                )
                
                result = await plugin.tool_pre_invoke(payload, context)
                
                assert result.continue_processing is True
                assert result.metadata["version_control_check"] == "disabled"
                
    @pytest.mark.asyncio
    async def test_tool_pre_invoke_no_server_id_allows_call(self, plugin_config):
        """Test that missing server_id allows call (fail open)"""
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(plugin_config)
                
                payload = ToolPreInvokePayload(name="test_tool", arguments={})
                context = PluginContext(
                    global_context=GlobalContext(server_id=None, user_email="test@example.com")
                )
                
                result = await plugin.tool_pre_invoke(payload, context)
                
                assert result.continue_processing is True
                assert result.metadata["version_control_check"] == "no_server_id"


class TestVersionControlPluginShutdown:
    """Test suite for plugin shutdown"""
    
    @pytest.mark.asyncio
    async def test_shutdown_cancels_polling_task(self):
        """Test that shutdown properly cancels polling task"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 60,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                
                # Create a mock polling task
                mock_task = AsyncMock()
                mock_task.cancel = MagicMock()
                plugin._polling_task = mock_task
                
                await plugin.shutdown()
                
                # Verify shutdown event was set
                assert plugin._shutdown_event.is_set()
                
                # Verify task was cancelled
                mock_task.cancel.assert_called_once()


class TestVersionControlPluginGetStatus:
    """Test suite for get_status method"""
    
    def test_get_status_returns_correct_info(self):
        """Test that get_status returns plugin status"""
        config = PluginConfig(
            name="VersionControl",
            kind="version_control",
            hooks=["tool_pre_invoke"],
            mode="enforce",
            priority=100,
            config={
                "enabled": True,
                "polling_interval": 120,
                "main_db_url": "sqlite:///test_main.db",
                "vc_db_url": "sqlite:///test_vc.db"
            }
        )
        
        with patch.object(VersionControlDB, 'create_database_if_not_exists'):
            with patch.object(VersionControlDB, 'create_tables'):
                plugin = VersionControlPlugin(config)
                
                status = plugin.get_status()
                
                assert status["enabled"] is True
                assert status["database_connected"] is True
                assert status["polling_interval"] == 120
                assert "description" in status

# Made with Bob
