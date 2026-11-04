# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/dataplane_publisher/dataplane_schema.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Schema definitions for the Control Plane and Data Plane contract.
See: https://github.com/contextforge-org/contextforge-data-plane/blob/main/crates/contextforge-data-plane-apis/src/user_store.rs
"""

# Standard
from typing import Any, TypedDict


class GatewayBaseConfig(TypedDict):
    """Connection fields shared by virtual-host backends."""

    name: str
    url: str
    mcp_protocol_version: str
    passthrough_headers: list[str]
    add_headers: dict[str, str]
    remove_headers: list[str]
    completion: dict[str, str]
    capabilities: dict[str, Any]


class BackendConfig(GatewayBaseConfig):
    """Backend configuration matching Rust BackendMCPGateway."""

    tool_schemas: dict[str, dict[str, Any]]


class ServiceRoute(TypedDict):
    """Published backend identity and upstream identifier."""

    backend_name: str
    upstream_name: str


class VirtualHostConfig(TypedDict):
    """Virtual host backends and resource routes."""

    backends: dict[str, BackendConfig]
    tools: dict[str, ServiceRoute]
    resources: dict[str, ServiceRoute]
    resource_templates: dict[str, ServiceRoute]
    prompts: dict[str, ServiceRoute]


class UserConfig(TypedDict):
    """User Config schema based on Dataplane User config store schema"""

    virtual_hosts: dict[str, VirtualHostConfig]
