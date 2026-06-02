"""Location: ./plugins/apiconnect_fam/fam/endpoints.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

IBM API Connect Federated API Management API Endpoint Constants.
"""


class FAMEndpoints:
    """IBM API Connect Federated API Management Asset Catalog and Engine API endpoint constants."""

    # Ingress API v1 - Authentication
    TOKEN = "/api/ingress/v1/token"

    # Asset Catalog API v1 - Servers
    SERVERS_BASE = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers"
    SERVER_BY_ID = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}"

    # Asset Catalog API v1 - Tools
    TOOLS_BASE = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}/mcp-tools"
    TOOL_BY_ID = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}/mcp-tools/{tool_id}"
    TOOLS_BULK_CREATE = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}/mcp-tools/bulk/create"
    TOOLS_BULK_UPDATE = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}/mcp-tools/bulk/update"
    TOOLS_BULK_DELETE = "/api/assetcatalog/v1/runtimes/{runtime_id}/mcp-servers/{server_id}/mcp-tools/bulk/delete"

    # Asset Catalog API v2 - Runtimes
    RUNTIMES = "/api/assetcatalog/v2/runtimes"
    RUNTIME_TYPES = "/api/assetcatalog/v2/runtimes/types"

    # Engine API v2 - Heartbeat
    HEARTBEAT = "/api/engine/v2/runtimes/heartbeat"

    # Engine API v3 - Metrics
    METRICS = "/api/engine/v3/runtimes/{runtime_id}/metrics"
