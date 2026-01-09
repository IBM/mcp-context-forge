# -*- coding: utf-8 -*-
"""Test plugin with configurable behavior."""

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginContext, PluginResult


class ConfigurablePlugin(Plugin):
    """Plugin with behavior controlled by config.

    This plugin's behavior changes based on configuration, useful for testing
    config merging and override functionality.
    """

    # Class-level tracking
    invocations = []

    def __init__(self, config):
        """Initialize configurable plugin."""
        super().__init__(config)
        plugin_config = config.config if config.config else {}
        self.action = plugin_config.get("action", "log")
        self.threshold = plugin_config.get("threshold", 100)
        self.message = plugin_config.get("message", "default")
        self.nested_config = plugin_config.get("nested", {})

    @classmethod
    def reset(cls):
        """Reset invocation tracking."""
        cls.invocations = []

    async def tool_pre_invoke(self, payload, context: PluginContext):
        """Execute configurable action on tool pre-invoke."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "tool_pre_invoke",
            "action": self.action,
            "threshold": self.threshold,
            "message": self.message,
            "nested": self.nested_config,
            "payload": payload
        })

        if self.action == "modify":
            modified = payload.model_copy(deep=True)
            if hasattr(modified, "args") and modified.args:
                modified.args["action"] = self.action
                modified.args["message"] = self.message
            return PluginResult(modified_payload=modified)

        return PluginResult()

    async def tool_post_invoke(self, payload, context: PluginContext):
        """Execute configurable action on tool post-invoke."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "tool_post_invoke",
            "action": self.action,
            "threshold": self.threshold,
            "message": self.message,
            "nested": self.nested_config
        })
        return PluginResult()
