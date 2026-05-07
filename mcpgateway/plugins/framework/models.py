# -*- coding: utf-8 -*-
"""Compatibility models for the plugin framework package."""

# Third-Party
from pydantic import BaseModel


class MCPServerTLSConfig(BaseModel):
    """TLS configuration for an external MCP plugin server."""

    certfile: str | None = None
    keyfile: str | None = None
    ca_bundle: str | None = None
    keyfile_password: str | None = None
    ssl_cert_reqs: int = 0


class MCPServerConfig(BaseModel):
    """Server configuration for an external MCP plugin server."""

    host: str = "127.0.0.1"
    port: int = 8000
    uds: str | None = None
    tls: MCPServerTLSConfig | None = None
