# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/loader/config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti

Configuration loader implementation.
This module loads configurations for plugins.
"""

# Standard
import os

# Third-Party
import jinja2
import yaml

# First-Party
from mcpgateway.plugins.framework.models import Config, PluginSettings


class ConfigLoader:
    """A configuration loader.

    Examples:
        >>> import tempfile
        >>> import os
        >>> from mcpgateway.plugins.framework.models import PluginSettings
        >>> # Create a temporary config file
        >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        ...     _ = f.write(\"\"\"
        ... plugin_settings:
        ...   enable_plugin_api: true
        ...   plugin_timeout: 30
        ... plugin_dirs: ['/path/to/plugins']
        ... \"\"\")
        ...     temp_path = f.name
        >>> try:
        ...     config = ConfigLoader.load_config(temp_path, use_jinja=False)
        ...     config.plugin_settings.enable_plugin_api
        ... finally:
        ...     os.unlink(temp_path)
        True
    """

    @staticmethod
    def load_config(config: str, use_jinja: bool = True) -> Config:
        """Load the plugin configuration from a file path.

        Args:
            config: the configuration path.
            use_jinja: use jinja to replace env variables if true.

        Returns:
            The plugin configuration object.

        Examples:
            >>> import tempfile
            >>> import os
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            ...     _ = f.write(\"\"\"
            ... plugin_settings:
            ...   plugin_timeout: 60
            ...   enable_plugin_api: false
            ... plugin_dirs: []
            ... \"\"\")
            ...     temp_path = f.name
            >>> try:
            ...     cfg = ConfigLoader.load_config(temp_path, use_jinja=False)
            ...     cfg.plugin_settings.plugin_timeout
            ... finally:
            ...     os.unlink(temp_path)
            60
        """
        try:
            with open(os.path.normpath(config), "r", encoding="utf-8") as file:
                template = file.read()
                if use_jinja:
                    jinja_env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=True)
                    rendered_template = jinja_env.from_string(template).render(env=os.environ)
                else:
                    rendered_template = template
                config_data = yaml.safe_load(rendered_template) or {}
            return Config(**config_data)
        except FileNotFoundError:
            # Graceful fallback for tests and minimal environments without plugin config
            return Config(plugins=[], plugin_dirs=[], plugin_settings=PluginSettings())
