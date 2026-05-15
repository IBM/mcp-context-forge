# -*- coding: utf-8 -*-
"""Compatibility exports for the plugin framework package."""

from mcpgateway.plugins.framework.models import MCPServerConfig


class ExternalPluginServer:
    """Minimal compatibility stub for runtime import and test monkeypatching."""

    async def initialize(self) -> bool:
        """Initialize the external plugin server."""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Shut down the external plugin server."""
        raise NotImplementedError

    async def get_plugin_configs(self) -> list[dict]:
        """Return all plugin configurations."""
        raise NotImplementedError

    async def get_plugin_config(self, name: str) -> dict | None:
        """Return a single plugin configuration by name."""
        raise NotImplementedError

    async def invoke_hook(self, hook_type: str, plugin_name: str, payload: dict, context: dict) -> dict:
        """Invoke a plugin hook with the provided payload and context."""
        raise NotImplementedError

    def get_server_config(self) -> MCPServerConfig:
        """Return the server configuration for the plugin runtime."""
        raise NotImplementedError


__all__ = ["ExternalPluginServer", "MCPServerConfig"]
