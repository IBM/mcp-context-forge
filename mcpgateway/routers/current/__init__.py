# -*- coding: utf-8 -*-
"""MCP Gateway Current Routers - Current API version router imports.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

Provides access to routers and utilities for the current API version.
"""

from mcpgateway.routers.oauth_router import oauth_router
from mcpgateway.routers.reverse_proxy import reverse_proxy_router
from mcpgateway.routers.v1.a2a import a2a_router
from mcpgateway.routers.v1.export_import import export_import_router
from mcpgateway.routers.v1.gateway import gateway_router
from mcpgateway.routers.v1.metrics import metrics_router
from mcpgateway.routers.v1.prompts import prompt_router
from mcpgateway.routers.v1.protocol import protocol_router, initialize, handle_notification
from mcpgateway.routers.v1.resources import resource_router
from mcpgateway.routers.v1.root import root_router
from mcpgateway.routers.v1.servers import server_router
from mcpgateway.routers.v1.tag import tag_router
from mcpgateway.routers.v1.tool import tool_router
from mcpgateway.routers.v1.utility import utility_router, handle_rpc, websocket_endpoint
from mcpgateway.routers.well_known import well_known_router
from mcpgateway.version import router as version_router


_ = protocol_router
_ = resource_router
_ = root_router
_ = tool_router
_ = export_import_router
_ = prompt_router
_ = gateway_router
_ = utility_router
_ = server_router
_ = metrics_router
_ = tag_router
_ = a2a_router
_ = well_known_router
_ = oauth_router
_ = reverse_proxy_router
_ = version_router
_ = initialize
_ = handle_notification
_ = handle_rpc
_ = websocket_endpoint
