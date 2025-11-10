# -*- coding: utf-8 -*-
"""Simple Token Authentication Plugin.

This plugin provides a simple token-based authentication system that completely
replaces the default JWT authentication in MCPContextForge.
"""

from plugins.examples.simple_token_auth.simple_token_auth import SimpleTokenAuthPlugin

__all__ = ["SimpleTokenAuthPlugin"]
