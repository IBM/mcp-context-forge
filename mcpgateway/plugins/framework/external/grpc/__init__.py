# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/grpc/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

gRPC transport for external plugins.

This package provides gRPC-based communication between the MCP Gateway and
external plugin servers. It offers a faster binary protocol alternative to
the MCP/HTTP transport while maintaining the same plugin semantics.

Usage:
    Client (Gateway side):
        Configure a plugin with the `grpc:` section instead of `mcp:`:

        ```yaml
        plugins:
          - name: "MyPlugin"
            kind: "external"
            hooks: ["tool_pre_invoke"]
            grpc:
              target: "localhost:50051"
              tls:
                verify: true
                ca_bundle: /path/to/ca.pem
        ```

    Server (Plugin side):
        Run the gRPC server to expose your plugins:

        ```bash
        python -m mcpgateway.plugins.framework.external.grpc.server.runtime \\
            --config plugins/config.yaml \\
            --port 50051
        ```

Exports:
    GrpcExternalPlugin: Client-side plugin that connects to gRPC server.
    GrpcPluginServicer: Server-side gRPC servicer.
    GrpcHealthServicer: Health check servicer.
    create_client_credentials: Helper to create gRPC client TLS credentials.
    create_server_credentials: Helper to create gRPC server TLS credentials.

Note:
    gRPC plugins use the existing ExternalHookRef from the MCP transport since
    both transports share the same invoke_hook() interface.
"""

from mcpgateway.plugins.framework.external.grpc.client import GrpcExternalPlugin
from mcpgateway.plugins.framework.external.grpc.tls_utils import create_client_credentials, create_server_credentials

__all__ = [
    "GrpcExternalPlugin",
    "create_client_credentials",
    "create_server_credentials",
]

# Server exports are imported lazily to avoid circular imports
# Import here after client to ensure proper initialization order
from mcpgateway.plugins.framework.external.grpc.server import GrpcHealthServicer, GrpcPluginServicer  # noqa: E402, F401

__all__.extend(["GrpcPluginServicer", "GrpcHealthServicer"])
