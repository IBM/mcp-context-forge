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
from mcpgateway.plugins.framework.models import Config


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
