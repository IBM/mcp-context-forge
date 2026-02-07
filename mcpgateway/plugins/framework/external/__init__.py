# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/external/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

External plugin which connects to a remote server.
Module that contains plugin client/server code to serve external plugins.

This package supports two transport mechanisms:
- MCP (Model Context Protocol): HTTP/SSE-based transport (default)
- gRPC: Binary protocol for higher performance

Usage:
    MCP Transport:
        ```yaml
        plugins:
          - name: "MyPlugin"
            kind: "external"
            mcp:
              proto: "STREAMABLEHTTP"
              url: "http://localhost:8000/mcp"
        ```

    gRPC Transport:
        ```yaml
        plugins:
          - name: "MyPlugin"
            kind: "external"
            grpc:
              target: "localhost:50051"
        ```
"""

# MCP transport exports (always available)
from mcpgateway.plugins.framework.external.mcp.client import ExternalHookRef, ExternalPlugin

__all__ = ["ExternalPlugin", "ExternalHookRef"]

# gRPC transport exports (optional - requires grpc extras)
try:
    from mcpgateway.plugins.framework.external.grpc import GrpcExternalPlugin  # noqa: E402, F401

    __all__.extend(["GrpcExternalPlugin"])
except ImportError:
    # grpc extras not installed
    pass
