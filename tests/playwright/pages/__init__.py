# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Page objects for Playwright tests.
"""

from .base_page import BasePage
from .login_page import LoginPage
from .admin_page import AdminPage
from .agents_page import AgentsPage
from .gateways_page import GatewaysPage
from .team_page import TeamPage
from .tokens_page import TokensPage
from .tools_page import ToolsPage
from .metrics_page import MetricsPage
from .resources_page import ResourcesPage
from .prompts_page import PromptsPage
from .servers_page import ServersPage
from .version_page import VersionPage
from .mcp_registry_page import MCPRegistryPage
from .runtime_page import RuntimePage

__all__ = [
    "BasePage",
    "LoginPage",
    "AdminPage",
    "AgentsPage",
    "GatewaysPage",
    "TeamPage",
    "TokensPage",
    "ToolsPage",
    "MetricsPage",
    "ResourcesPage",
    "PromptsPage",
    "ServersPage",
    "VersionPage",
    "MCPRegistryPage",
    "RuntimePage",
]
