# -*- coding: utf-8 -*-
"""Plugin loader implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

This module implements the plugin loader.
"""

# Standard
import logging
from typing import cast, Type

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig
from mcpgateway.plugins.framework.utils import import_module, parse_class_name

logger = logging.getLogger(__name__)


class PluginLoader(object):
    """A plugin loader object for loading and instantiating plugins."""

    def __init__(self) -> None:
        """Initialize the plugin loader."""
        self._plugin_types: dict[str, Type[Plugin]] = {}

    def __get_plugin_type(self, kind: str) -> Type[Plugin]:
        try:
            (mod_name, cls_name) = parse_class_name(kind)
            module = import_module(mod_name)
            class_ = getattr(module, cls_name)
            return cast(Type[Plugin], class_)
        except Exception:
            logger.exception("Unable to instantiate class '%s'", kind)
            raise

    def __register_plugin_type(self, kind: str) -> None:
        if kind not in self._plugin_types:
            plugin_type = self.__get_plugin_type(kind)
            self._plugin_types[kind] = plugin_type

    async def load_and_instantiate_plugin(self, config: PluginConfig) -> Plugin | None:
        """Load and instantiate a plugin, given a configuration.

        Args:
            config: A plugin configuration.

        Returns:
            A plugin instance.
        """
        if config.kind not in self._plugin_types:
            self.__register_plugin_type(config.kind)
        plugin_type = self._plugin_types[config.kind]
        if plugin_type:
            return plugin_type(config)
        return None
