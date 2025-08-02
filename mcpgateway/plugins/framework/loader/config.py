# -*- coding: utf-8 -*-
"""Configuration loader implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

This module loads configurations for plugins.
"""

# Standard
import os

# Third-Party
import jinja2
import yaml

# First-Party
from mcpgateway.plugins.framework.models import Config, PluginConfig, PluginManifest


class ConfigLoader:
    """A configuration loader."""

    @staticmethod
    def load_config(config: str, use_jinja: bool = True) -> Config:
        """Load the plugin configuration from a file path.

        Args:
            config: the configuration path.
            use_jinja: use jinja to replace env variables if true.

        Returns:
            The plugin configuration object.
        """
        with open(os.path.normpath(config), "r", encoding="utf-8") as file:
            template = file.read()
            if use_jinja:
                jinja_env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=True)
                rendered_template = jinja_env.from_string(template).render(env=os.environ)
            else:
                rendered_template = template
            config_data = yaml.safe_load(rendered_template)
        return Config(**config_data)

    @staticmethod
    def dump_config(path: str, config: Config) -> None:
        """Dump plugin configuration to a file.

        Args:
            path: configuration file path
            config: the plugin configuration path
        """
        with open(os.path.normpath(path), "w", encoding="utf-8") as file:
            yaml.safe_dump(config.model_dump(exclude_none=True), file)

    @staticmethod
    def load_plugin_config(config: str) -> PluginConfig:
        """Load a plugin configuration from a file path.

        This function autoescapes curly brackets in the 'instruction'
        and 'examples' keys under the config attribute.

        Args:
            config: the plugin configuration path

        Returns:
            The plugin configuration object
        """
        with open(os.path.normpath(config), "r", encoding="utf8") as file:
            template = file.read()
            jinja_env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=True)
            rendered_template = jinja_env.from_string(template).render(env=os.environ)
            config_data = yaml.safe_load(rendered_template)
        return PluginConfig(**config_data)

    @staticmethod
    def load_plugin_manifest(manifest: str) -> PluginManifest:
        """Load a plugin manifest from a file path.

        Args:
            manifest: the plugin manifest path

        Returns:
            The plugin manifest object
        """
        with open(os.path.normpath(manifest), "r", encoding="utf8") as file:
            template = file.read()
            jinja_env = jinja2.Environment(loader=jinja2.BaseLoader(), autoescape=True)
            rendered_template = jinja_env.from_string(template).render(env=os.environ)
            config_data = yaml.safe_load(rendered_template)
        return PluginManifest(**config_data)
