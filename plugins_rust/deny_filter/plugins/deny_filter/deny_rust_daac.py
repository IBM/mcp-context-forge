# -*- coding: utf-8 -*-
"""Location: ./plugins/deny_filter/deny_rust_daac.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo, Dmitry Zakharov

Simple example plugin for searching and replacing text.
This module loads configurations for plugins.
"""

# First-Party
from deny_filter import DenyListDaac

# Third-Party
from mcpgateway.plugins.framework import PluginConfig
from mcpgateway.services.logging_service import LoggingService

from plugins.deny_filter.deny import DenyListConfig
from plugins.deny_filter.deny_rust import DenyListPluginRust

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class DenyListPluginRustDaac(DenyListPluginRust):
    """Example deny list plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the deny list plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._dconfig = DenyListConfig.model_validate(self._config.config)
        self._deny_list: DenyListDaac = DenyListDaac(self._dconfig.words)
