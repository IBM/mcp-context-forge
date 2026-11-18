# SPDX-License-Identifier: Apache-2.0
"""Read startup settings without importing the legacy SDK."""

from importlib import import_module
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpgateway.plugins.contracts import LEGACY_RUNTIME_AVAILABLE


class GatewayNativeSettings(BaseSettings):
    """Select the native plugin configuration."""

    native_config_file: str | None = None
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", extra="ignore")


class GatewayPluginSettings(GatewayNativeSettings):
    """Provide gateway startup settings for native CPEX."""

    enabled: bool = False
    config_file: str = "plugins/config.yaml"
    plugin_timeout: int = 30


def get_plugin_settings() -> Any:
    """Return settings for the installed runtime."""
    if LEGACY_RUNTIME_AVAILABLE:
        return import_module("cpex.framework.settings").settings
    return GatewayPluginSettings()
