# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/mcp/entities/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Pydantic models for MCP plugins.
This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import Field, RootModel

# First-Party
from mcpgateway.models import PromptResult
from mcpgateway.plugins.framework.models import PluginPayload, PluginResult


class HookType(str, Enum):
    """MCP Forge Gateway hook points.

    Attributes:
        prompt_pre_fetch: The prompt pre hook.
        prompt_post_fetch: The prompt post hook.
        tool_pre_invoke: The tool pre invoke hook.
        tool_post_invoke: The tool post invoke hook.
        resource_pre_fetch: The resource pre fetch hook.
        resource_post_fetch: The resource post fetch hook.

    Examples:
        >>> HookType.PROMPT_PRE_FETCH
        <HookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>
        >>> HookType.PROMPT_PRE_FETCH.value
        'prompt_pre_fetch'
        >>> HookType('prompt_post_fetch')
        <HookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>
        >>> list(HookType)  # doctest: +ELLIPSIS
        [<HookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>, <HookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>, <HookType.TOOL_PRE_INVOKE: 'tool_pre_invoke'>, <HookType.TOOL_POST_INVOKE: 'tool_post_invoke'>, ...]
    """

    PROMPT_PRE_FETCH = "prompt_pre_fetch"
    PROMPT_POST_FETCH = "prompt_post_fetch"
    TOOL_PRE_INVOKE = "tool_pre_invoke"
    TOOL_POST_INVOKE = "tool_post_invoke"
    RESOURCE_PRE_FETCH = "resource_pre_fetch"
    RESOURCE_POST_FETCH = "resource_post_fetch"


class PromptPrehookPayload(PluginPayload):
    """A prompt payload for a prompt prehook.

    Attributes:
        prompt_id (str): The ID of the prompt template.
        args (dic[str,str]): The prompt template arguments.

    Examples:
        >>> payload = PromptPrehookPayload(prompt_id="123", args={"user": "alice"})
        >>> payload.prompt_id
        '123'
        >>> payload.args
        {'user': 'alice'}
        >>> payload2 = PromptPrehookPayload(prompt_id="empty")
        >>> payload2.args
        {}
        >>> p = PromptPrehookPayload(prompt_id="123", args={"name": "Bob", "time": "morning"})
        >>> p.prompt_id
        '123'
        >>> p.args["name"]
        'Bob'
    """

    prompt_id: str
    args: Optional[dict[str, str]] = Field(default_factory=dict)


class PromptPosthookPayload(PluginPayload):
    """A prompt payload for a prompt posthook.

    Attributes:
        prompt_id (str): The prompt ID.
        result (PromptResult): The prompt after its template is rendered.

     Examples:
        >>> from mcpgateway.models import PromptResult, Message, TextContent
        >>> msg = Message(role="user", content=TextContent(type="text", text="Hello World"))
        >>> result = PromptResult(messages=[msg])
        >>> payload = PromptPosthookPayload(prompt_id="123", result=result)
        >>> payload.prompt_id
        '123'
        >>> payload.result.messages[0].content.text
        'Hello World'
        >>> from mcpgateway.models import PromptResult, Message, TextContent
        >>> msg = Message(role="assistant", content=TextContent(type="text", text="Test output"))
        >>> r = PromptResult(messages=[msg])
        >>> p = PromptPosthookPayload(prompt_id="123", result=r)
        >>> p.prompt_id
        '123'
    """

    prompt_id: str
    result: PromptResult


PromptPrehookResult = PluginResult[PromptPrehookPayload]
PromptPosthookResult = PluginResult[PromptPosthookPayload]


class HttpHeaderPayload(RootModel[dict[str, str]]):
    """An HTTP dictionary of headers used in the pre/post HTTP forwarding hooks."""

    def __iter__(self):
        """Custom iterator function to override root attribute.

        Returns:
            A custom iterator for header dictionary.
        """
        return iter(self.root)

    def __getitem__(self, item: str) -> str:
        """Custom getitem function to override root attribute.

        Args:
            item: The http header key.

        Returns:
            A custom accesser for the header dictionary.
        """
        return self.root[item]

    def __setitem__(self, key: str, value: str) -> None:
        """Custom setitem function to override root attribute.

        Args:
            key: The http header key.
            value: The http header value to be set.
        """
        self.root[key] = value

    def __len__(self):
        """Custom len function to override root attribute.

        Returns:
            The len of the header dictionary.
        """
        return len(self.root)


HttpHeaderPayloadResult = PluginResult[HttpHeaderPayload]


class ToolPreInvokePayload(PluginPayload):
    """A tool payload for a tool pre-invoke hook.

    Args:
        name: The tool name.
        args: The tool arguments for invocation.
        headers: The http pass through headers.

    Examples:
        >>> payload = ToolPreInvokePayload(name="test_tool", args={"input": "data"})
        >>> payload.name
        'test_tool'
        >>> payload.args
        {'input': 'data'}
        >>> payload2 = ToolPreInvokePayload(name="empty")
        >>> payload2.args
        {}
        >>> p = ToolPreInvokePayload(name="calculator", args={"operation": "add", "a": 5, "b": 3})
        >>> p.name
        'calculator'
        >>> p.args["operation"]
        'add'

    """

    name: str
    args: Optional[dict[str, Any]] = Field(default_factory=dict)
    headers: Optional[HttpHeaderPayload] = None


class ToolPostInvokePayload(PluginPayload):
    """A tool payload for a tool post-invoke hook.

    Args:
        name: The tool name.
        result: The tool invocation result.

    Examples:
        >>> payload = ToolPostInvokePayload(name="calculator", result={"result": 8, "status": "success"})
        >>> payload.name
        'calculator'
        >>> payload.result
        {'result': 8, 'status': 'success'}
        >>> p = ToolPostInvokePayload(name="analyzer", result={"confidence": 0.95, "sentiment": "positive"})
        >>> p.name
        'analyzer'
        >>> p.result["confidence"]
        0.95
    """

    name: str
    result: Any


ToolPreInvokeResult = PluginResult[ToolPreInvokePayload]
ToolPostInvokeResult = PluginResult[ToolPostInvokePayload]


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


class ResourcePostFetchPayload(PluginPayload):
    """A resource payload for a resource post-fetch hook.

    Attributes:
        uri: The resource URI.
        content: The fetched resource content.

    Examples:
        >>> from mcpgateway.models import ResourceContent
        >>> content = ResourceContent(type="resource", id="res-1", uri="file:///data.txt",
        ...     text="Hello World")
        >>> payload = ResourcePostFetchPayload(uri="file:///data.txt", content=content)
        >>> payload.uri
        'file:///data.txt'
        >>> payload.content.text
        'Hello World'
        >>> from mcpgateway.models import ResourceContent
    >>> resource_content = ResourceContent(type="resource", id="res-2", uri="test://resource", text="Test data")
        >>> p = ResourcePostFetchPayload(uri="test://resource", content=resource_content)
        >>> p.uri
        'test://resource'
    """

    uri: str
    content: Any


ResourcePreFetchResult = PluginResult[ResourcePreFetchPayload]
ResourcePostFetchResult = PluginResult[ResourcePostFetchPayload]
