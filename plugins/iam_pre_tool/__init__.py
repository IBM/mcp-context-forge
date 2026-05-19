# -*- coding: utf-8 -*-
"""IAM Pre-Tool Plugin.

This plugin handles IAM requirements for MCP servers including:
- Token acquisition (OAuth2 client credentials)
- Token exchange
- Credential injection into HTTP requests
"""

# First-Party
from plugins.iam_pre_tool.iam_pre_tool import IamPreToolPlugin

__all__ = ["IamPreToolPlugin"]
