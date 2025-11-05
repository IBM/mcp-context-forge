# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/hooks/resources.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for resource hooks.
"""

# Standard
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import Field

# First-Party
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class ResourceHookType(str, Enum):
    """MCP Forge Gateway resource hook points.

    Attributes:
        resource_pre_fetch: The resource pre fetch hook.
        resource_post_fetch: The resource post fetch hook.

    Examples:
        >>> ResourceHookType.RESOURCE_PRE_FETCH
        <ResourceHookType.RESOURCE_PRE_FETCH: 'resource_pre_fetch'>
        >>> ResourceHookType.RESOURCE_PRE_FETCH.value
        'resource_pre_fetch'
        >>> ResourceHookType('resource_post_fetch')
        <ResourceHookType.RESOURCE_POST_FETCH: 'resource_post_fetch'>
        >>> list(ResourceHookType)
        [<ResourceHookType.RESOURCE_PRE_FETCH: 'resource_pre_fetch'>, <ResourceHookType.RESOURCE_POST_FETCH: 'resource_post_fetch'>]
    """

    RESOURCE_PRE_FETCH = "resource_pre_fetch"
    RESOURCE_POST_FETCH = "resource_post_fetch"


class ResourcePreFetchPayload(PluginPayload):
    """A resource payload for a resource pre-fetch hook.

    Attributes:
            uri: The resource URI.
            metadata: Optional metadata for the resource request.

    Examples:
        >>> payload = ResourcePreFetchPayload(uri="file:///data.txt")
        >>> payload.uri
        'file:///data.txt'
        >>> payload2 = ResourcePreFetchPayload(uri="http://api/data", metadata={"Accept": "application/json"})
        >>> payload2.metadata
        {'Accept': 'application/json'}
        >>> p = ResourcePreFetchPayload(uri="file:///docs/readme.md", metadata={"version": "1.0"})
        >>> p.uri
        'file:///docs/readme.md'
        >>> p.metadata["version"]
        '1.0'
    """

    uri: str
    metadata: Optional[dict[str, Any]] = Field(default_factory=dict)

    def model_dump_pb(self):
        """Convert to protobuf ResourcePreFetchPayload message.

        Returns:
            resources_pb2.ResourcePreFetchPayload: Protobuf message.
        """
        # Third-Party
        from google.protobuf import json_format, struct_pb2

        # First-Party
        from mcpgateway.plugins.framework.generated import resources_pb2

        # Convert metadata dict to Struct
        metadata_struct = struct_pb2.Struct()
        if self.metadata:
            json_format.ParseDict(self.metadata, metadata_struct)

        return resources_pb2.ResourcePreFetchPayload(
            uri=self.uri,
            metadata=metadata_struct,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "ResourcePreFetchPayload":
        """Create from protobuf ResourcePreFetchPayload message.

        Args:
            proto: resources_pb2.ResourcePreFetchPayload protobuf message.

        Returns:
            ResourcePreFetchPayload: Pydantic model instance.
        """
        # Third-Party
        from google.protobuf import json_format

        # Convert Struct to dict
        metadata = {}
        if proto.HasField("metadata"):
            metadata = json_format.MessageToDict(proto.metadata)

        return cls(
            uri=proto.uri,
            metadata=metadata,
        )


class ResourcePostFetchPayload(PluginPayload):
    """A resource payload for a resource post-fetch hook.

    Attributes:
        uri: The resource URI.
        content: The fetched resource content.

    Examples:
        >>> from mcpgateway.common.models import ResourceContent
        >>> content = ResourceContent(type="resource", id="res-1", uri="file:///data.txt",
        ...     text="Hello World")
        >>> payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)
        >>> payload.uri
        'file:///data.txt'
        >>> payload.content.text
        'Hello World'
        >>> from mcpgateway.common.models import ResourceContent
    >>> resource_content = ResourceContent(type="resource", id="res-2", uri="test://resource", text="Test data")
        >>> p = ResourcePostFetchPayload(uri="test://resource", content=resource_content)
        >>> p.uri
        'test://resource'
    """

    uri: str
    content: Any

    def model_dump_pb(self):
        """Convert to protobuf ResourcePostFetchPayload message.

        Returns:
            resources_pb2.ResourcePostFetchPayload: Protobuf message.
        """
        # Third-Party
        from google.protobuf import json_format, struct_pb2

        # First-Party
        from mcpgateway.plugins.framework.generated import resources_pb2

        # Convert content to Struct
        content_struct = struct_pb2.Struct()
        if self.content is not None:
            if isinstance(self.content, dict):
                json_format.ParseDict(self.content, content_struct)
            elif hasattr(self.content, "model_dump"):
                # Handle Pydantic models like ResourceContent
                content_dict = self.content.model_dump(mode="json")
                json_format.ParseDict(content_dict, content_struct)
            else:
                # For other types, wrap in a dict
                json_format.ParseDict({"value": self.content}, content_struct)

        return resources_pb2.ResourcePostFetchPayload(
            uri=self.uri,
            content=content_struct,
        )

    @classmethod
    def model_validate_pb(cls, proto) -> "ResourcePostFetchPayload":
        """Create from protobuf ResourcePostFetchPayload message.

        Args:
            proto: resources_pb2.ResourcePostFetchPayload protobuf message.

        Returns:
            ResourcePostFetchPayload: Pydantic model instance.
        """
        # Third-Party
        from google.protobuf import json_format

        # Convert Struct to dict/value
        content = None
        if proto.HasField("content"):
            content_dict = json_format.MessageToDict(proto.content)
            # If it was wrapped with "value" key, unwrap it
            if len(content_dict) == 1 and "value" in content_dict:
                content = content_dict["value"]
            else:
                content = content_dict

        return cls(
            uri=proto.uri,
            content=content,
        )


ResourcePreFetchResult = PluginResult[ResourcePreFetchPayload]
ResourcePostFetchResult = PluginResult[ResourcePostFetchPayload]


def _register_resource_hooks() -> None:
    """Register resource hooks in the global registry.

    This is called lazily to avoid circular import issues.
    """
    # Import here to avoid circular dependency at module load time
    # First-Party
    from mcpgateway.plugins.framework.hooks.registry import get_hook_registry  # pylint: disable=import-outside-toplevel

    registry = get_hook_registry()

    # Only register if not already registered (idempotent)
    if not registry.is_registered(ResourceHookType.RESOURCE_PRE_FETCH):
        registry.register_hook(ResourceHookType.RESOURCE_PRE_FETCH, ResourcePreFetchPayload, ResourcePreFetchResult)
        registry.register_hook(ResourceHookType.RESOURCE_POST_FETCH, ResourcePostFetchPayload, ResourcePostFetchResult)


_register_resource_hooks()
