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
    """A plugin loader object for loading and instantiating plugins.

    Examples:
        >>> loader = PluginLoader()
        >>> isinstance(loader._plugin_types, dict)
        True
        >>> len(loader._plugin_types)
        0
    """

    def __init__(self) -> None:
        """Initialize the plugin loader.

        Examples:
            >>> loader = PluginLoader()
            >>> loader._plugin_types
            {}
        """
        self._plugin_types: dict[str, Type[Plugin]] = {}

    def __get_plugin_type(self, kind: str) -> Type[Plugin]:
        """Import a plugin type from a python module.

        Args:
            kind: The fully-qualified type of the plugin to be registered.

        Raises:
            Exception: if unable to import a module.

        Returns:
            A plugin type.
        """
        try:
            (mod_name, cls_name) = parse_class_name(kind)
            module = import_module(mod_name)
            class_ = getattr(module, cls_name)
            return cast(Type[Plugin], class_)
        except Exception:
            logger.exception("Unable to import plugin type '%s'", kind)
            raise

    def __register_plugin_type(self, kind: str) -> None:
        """Register a plugin type.

        Args:
            kind: The fully-qualified type of the plugin to be registered.
        """
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

    async def shutdown(self) -> None:
        """Shutdown and cleanup plugin loader."""
        if self._plugin_types:
            self._plugin_types.clear()
