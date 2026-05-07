# -*- coding: utf-8 -*-
"""Compatibility settings for the plugin framework package."""

from types import SimpleNamespace
import os


def get_transport_settings() -> SimpleNamespace:
    """Return transport settings expected by the external MCP runtime."""
    return SimpleNamespace(transport=os.getenv("PLUGINS_TRANSPORT"))
