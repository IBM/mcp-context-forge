"""MCP Gateway {{cookiecutter.plugin_name}} Plugin - {{cookiecutter.description}}.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: {{cookiecutter.author}}

"""

import importlib.metadata

# Package version
try:
    __version__ = importlib.metadata.version("{{ cookiecutter.plugin_slug }}")
except Exception:
    __version__ = "{{cookiecutter.version}}"

__author__ = "{{cookiecutter.author}}"
__copyright__ = "Copyright 2025"
__license__ = "Apache 2.0"
__description__ = "{{cookiecutter.description}}"
__url__ = "https://ibm.github.io/mcp-context-forge/"
__download_url__ = "https://github.com/IBM/mcp-context-forge"
__packages__ = ["{{ cookiecutter.plugin_slug }}"]
