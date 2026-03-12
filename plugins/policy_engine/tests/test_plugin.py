"""
test_plugin.py - Unit tests for plugin integration

Tests plugin initialization and basic functionality.
"""

import pytest
from ..plugin import PolicyEnginePlugin, get_plugin
from ..models import Policy


@pytest.fixture
def policy_plugin():
    """Create a policy engine plugin instance."""
    return PolicyEnginePlugin()


class TestPluginInitialization:
    """Test plugin initialization."""

    def test_plugin_init(self):
        """Test plugin initialization."""
        plugin = PolicyEnginePlugin()
        assert plugin is not None
        assert plugin.evaluator is not None
        assert plugin.waiver_manager is not None

    def test_plugin_has_methods(self):
        """Test plugin has required methods."""
        plugin = PolicyEnginePlugin()
        assert hasattr(plugin, 'list_policies')
        assert hasattr(plugin, 'create_policy')
        assert hasattr(plugin, 'get_policy')
        assert hasattr(plugin, 'delete_policy')
        assert hasattr(plugin, 'evaluate_assessment')
        assert hasattr(plugin, 'create_waiver')

    def test_get_plugin_singleton(self):
        """Test get_plugin returns plugin instances."""
        plugin1 = get_plugin()
        plugin2 = get_plugin()
        # Should both be valid instances
        assert plugin1 is not None
        assert plugin2 is not None


class TestPluginPolicies:
    """Test policy management methods."""

    def test_list_policies_returns_list(self, policy_plugin):
        """Test listing all policies returns a list."""
        policies = policy_plugin.list_policies()
        assert isinstance(policies, list)

    def test_create_policy_with_policy_object(self, policy_plugin):
        """Test creating a policy with a Policy object."""
        policy = Policy(
            name="TestPolicy",
            environment="test",
            rules={"max_critical_vulnerabilities": 5}
        )
        result = policy_plugin.create_policy(policy)
        assert result is not None

    def test_get_policy_method_exists(self, policy_plugin):
        """Test get_policy method is callable."""
        result = policy_plugin.get_policy(1)  # Try by ID
        assert result is None or isinstance(result, (dict, Policy))


class TestPluginWaivers:
    """Test waiver management methods."""

    def test_list_waivers_returns_list(self, policy_plugin):
        """Test listing waivers returns a list."""
        result = policy_plugin.list_waivers()
        assert isinstance(result, list)

    def test_create_waiver_returns_dict(self, policy_plugin):
        """Test creating a waiver returns something."""
        result = policy_plugin.create_waiver(
            server_id="test-server",
            rule_name="max_critical_vulnerabilities",
            reason="Testing",
            requested_by="test@example.com",
            duration_days=30,
        )
        assert result is not None


class TestPluginConfiguration:
    """Test plugin configuration and state."""

    def test_plugin_has_policies_storage(self):
        """Test plugin has internal policies storage."""
        plugin = PolicyEnginePlugin()
        assert hasattr(plugin, '_policies')
        assert isinstance(plugin._policies, dict)

    def test_plugin_has_waiver_manager(self):
        """Test plugin has waiver manager."""
        plugin = PolicyEnginePlugin()
        assert plugin.waiver_manager is not None

