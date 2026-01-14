# -*- coding: utf-8 -*-
"""Test plugin that tracks invocations for testing."""

from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginContext, PluginResult


class TrackerPlugin(Plugin):
    """Plugin that tracks hook invocations for testing.

    This plugin records when it's called and can optionally modify payloads.
    """

    # Class-level tracking for test verification
    invocations = []

    def __init__(self, config):
        """Initialize tracker plugin."""
        super().__init__(config)
        plugin_config = config.config if config.config else {}
        self.modify_payload = plugin_config.get("modify_payload", False)
        self.modification_value = plugin_config.get("modification_value", "modified")

    @classmethod
    def reset(cls):
        """Reset invocation tracking."""
        cls.invocations = []

    async def tool_pre_invoke(self, payload, context: PluginContext):
        """Track tool pre-invoke hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "tool_pre_invoke",
            "payload": payload,
            "config": self.config
        })

        if self.modify_payload:
            # Modify payload for testing
            modified = payload.model_copy(deep=True)
            if hasattr(modified, "args") and modified.args:
                modified.args["modified_by"] = self.modification_value
            return PluginResult(modified_payload=modified)

        return PluginResult()

    async def tool_post_invoke(self, payload, context: PluginContext):
        """Track tool post-invoke hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "tool_post_invoke",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def prompt_pre_fetch(self, payload, context: PluginContext):
        """Track prompt pre-fetch hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "prompt_pre_fetch",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def resource_pre_fetch(self, payload, context: PluginContext):
        """Track resource pre-fetch hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "resource_pre_fetch",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def http_pre_request(self, payload, context: PluginContext):
        """Track HTTP pre-request hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "http_pre_request",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def http_post_request(self, payload, context: PluginContext):
        """Track HTTP post-request hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "http_post_request",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def http_auth_resolve_user(self, payload, context: PluginContext):
        """Track HTTP auth resolve user hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "http_auth_resolve_user",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()

    async def http_auth_check_permission(self, payload, context: PluginContext):
        """Track HTTP auth check permission hook."""
        self.invocations.append({
            "plugin": self.name,
            "hook": "http_auth_check_permission",
            "payload": payload,
            "config": self.config
        })
        return PluginResult()
