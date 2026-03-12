"""
test_cli.py - Unit tests for CLI functionality

Tests policy command structure and basic functionality.
"""

import pytest
from unittest.mock import Mock, patch

from ..cli import PolicyEnginesCLI


@pytest.fixture
def mock_plugin():
    """Create a mock plugin."""
    plugin = Mock()
    plugin.list_policies = Mock(return_value=[])
    return plugin


class TestCLIInit:
    """Test CLI initialization."""

    def test_cli_initializes(self, mock_plugin):
        """Test CLI can be initialized."""
        with patch('plugins.policy_engine.cli.get_plugin', return_value=mock_plugin):
            cli = PolicyEnginesCLI()
            assert cli is not None
            assert cli.plugin is not None

    def test_cli_has_required_methods(self, mock_plugin):
        """Test CLI has required methods."""
        with patch('plugins.policy_engine.cli.get_plugin', return_value=mock_plugin):
            cli = PolicyEnginesCLI()
            
            # Check required methods exist
            assert hasattr(cli, 'scan')
            assert hasattr(cli, 'apply_policy')
            assert hasattr(cli, 'ask_waiver')
            assert hasattr(cli, 'list_policies')
            assert hasattr(cli, 'approve_waiver')


class TestCLIListPolicies:
    """Test list_policies method."""

    def test_list_policies_returns_list(self, mock_plugin):
        """Test list_policies returns a list."""
        mock_plugin.list_policies = Mock(return_value=[])
        
        with patch('plugins.policy_engine.cli.get_plugin', return_value=mock_plugin):
            cli = PolicyEnginesCLI()
            result = cli.list_policies()
            
            assert isinstance(result, list)

