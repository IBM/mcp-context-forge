# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pm_mcp_server/src/pm_mcp_server/resource_store.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

In-memory resource registry exposed via FastMCP resources.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass
class Resource:
    mime_type: str
    content: bytes


class ResourceStore:
    """Simple namespaced in-memory resource store."""

    def __init__(self) -> None:
        self._registry: dict[str, Resource] = {}

    def add(self, content: bytes, mime_type: str, prefix: str = "resource") -> str:
        resource_id = f"resource://{prefix}/{uuid.uuid4().hex}"
        self._registry[resource_id] = Resource(mime_type=mime_type, content=content)
        return resource_id

    def get(self, resource_id: str) -> tuple[str, bytes]:
        resource = self._registry[resource_id]
        return resource.mime_type, resource.content

    def list_ids(self) -> dict[str, str]:
        return {resource_id: res.mime_type for resource_id, res in self._registry.items()}


GLOBAL_RESOURCE_STORE = ResourceStore()
