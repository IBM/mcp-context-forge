# -*- coding: utf-8 -*-

"""Location: ./tests/unit/mcpgateway/plugins/fixtures/plugins/cross_hook_context.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Cross-hook context sharing test plugin.

This plugin demonstrates sharing context across different hook types:
- HTTP_PRE_REQUEST stores data
- HTTP_AUTH_CHECK_PERMISSION reads and verifies data
- TOOL_PRE_INVOKE reads and adds more data
- RESOURCE_PRE_FETCH reads and adds more data
- PROMPT_PRE_FETCH reads and adds more data
"""

import logging

from mcpgateway.plugins.framework import (
    HttpAuthCheckPermissionPayload,
    HttpAuthCheckPermissionResult,
    HttpPreRequestPayload,
    HttpPreRequestResult,
    Plugin,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger("cross_hook_context_plugin")
logger.setLevel(logging.INFO)  # Ensure INFO level logs are captured


class CrossHookContextPlugin(Plugin):
    """Plugin that demonstrates cross-hook context sharing.

    This plugin stores context in HTTP_PRE_REQUEST and verifies it's accessible
    in subsequent hooks like HTTP_AUTH_CHECK_PERMISSION, TOOL_PRE_INVOKE,
    RESOURCE_PRE_FETCH, and PROMPT_PRE_FETCH.
    """

    async def http_pre_request(
        self, payload: HttpPreRequestPayload, context: PluginContext
    ) -> HttpPreRequestResult:
        """Store initial context data in HTTP_PRE_REQUEST hook.

        Args:
            payload: The HTTP request payload.
            context: Plugin context for state storage.

        Returns:
            Result allowing processing to continue.
        """
        logger.info(
            f"🔍 [CrossHookContextPlugin] HTTP_PRE_REQUEST executed - "
            f"request_id={context.global_context.request_id}, "
            f"path={payload.path}, method={payload.method}"
        )

        # Store data in plugin-specific state
        context.state["http_timestamp"] = "2025-01-01T00:00:00Z"
        context.state["http_request_path"] = payload.path
        context.state["http_method"] = payload.method

        # Also store in global context to show it's shared
        context.global_context.state["shared_request_id"] = context.global_context.request_id

        return HttpPreRequestResult(continue_processing=True)

    async def http_auth_check_permission(
        self, payload: HttpAuthCheckPermissionPayload, context: PluginContext
    ) -> HttpAuthCheckPermissionResult:
        """Verify context from HTTP_PRE_REQUEST is accessible.

        Args:
            payload: The permission check payload.
            context: Plugin context that should contain data from HTTP_PRE_REQUEST.

        Returns:
            Result with permission decision.

        Raises:
            ValueError: If expected context data is missing.
        """
        logger.info(
            f"🔍 [CrossHookContextPlugin] HTTP_AUTH_CHECK_PERMISSION executed - "
            f"request_id={context.global_context.request_id}, "
            f"user_email={payload.user_email}"
        )

        # Verify we can read data stored in HTTP_PRE_REQUEST
        if "http_timestamp" not in context.state:
            raise ValueError("http_timestamp not found in context! Cross-hook sharing failed.")

        if "http_request_path" not in context.state:
            raise ValueError("http_request_path not found in context!")

        # Verify global context is shared
        if "shared_request_id" not in context.global_context.state:
            raise ValueError("shared_request_id not found in global context!")

        # Verify request_id consistency
        shared_request_id = context.global_context.state["shared_request_id"]
        if shared_request_id != context.global_context.request_id:
            raise ValueError(
                f"Request ID mismatch! shared_request_id={shared_request_id}, "
                f"global_context.request_id={context.global_context.request_id}"
            )

        logger.info(
            f"✅ [CrossHookContextPlugin] Request ID verified: {context.global_context.request_id}"
        )

        # Add permission-specific data
        context.state["permission_checked"] = True
        context.state["user_email"] = payload.user_email

        return HttpAuthCheckPermissionResult(continue_processing=True)

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        """Verify context from HTTP hooks is accessible in tool hooks.

        Args:
            payload: The tool invocation payload.
            context: Plugin context that should contain data from HTTP hooks.

        Returns:
            Result allowing tool invocation to continue.

        Raises:
            ValueError: If expected context data is missing.
        """
        logger.info(
            f"🔍 [CrossHookContextPlugin] TOOL_PRE_INVOKE executed - "
            f"request_id={context.global_context.request_id}, "
            f"tool_name={payload.name}"
        )

        # Verify we can read data from HTTP_PRE_REQUEST
        if "http_timestamp" not in context.state:
            raise ValueError("http_timestamp not found in tool hook! Cross-hook sharing failed.")

        # Verify we can read data from HTTP_AUTH_CHECK_PERMISSION
        if "permission_checked" not in context.state:
            raise ValueError("permission_checked not found in tool hook!")

        # Verify request_id consistency
        if "shared_request_id" in context.global_context.state:
            shared_request_id = context.global_context.state["shared_request_id"]
            if shared_request_id != context.global_context.request_id:
                raise ValueError(
                    f"Request ID mismatch in tool hook! shared_request_id={shared_request_id}, "
                    f"global_context.request_id={context.global_context.request_id}"
                )

        # Add tool-specific data
        context.state["tool_name"] = payload.name
        context.state["tool_invoked_at"] = "2025-01-01T00:01:00Z"

        return ToolPreInvokeResult(continue_processing=True)

    async def resource_pre_fetch(
        self, payload: ResourcePreFetchPayload, context: PluginContext
    ) -> ResourcePreFetchResult:
        """Verify context from HTTP hooks is accessible in resource hooks.

        Args:
            payload: The resource fetch payload.
            context: Plugin context that should contain data from HTTP hooks.

        Returns:
            Result allowing resource fetch to continue.

        Raises:
            ValueError: If expected context data is missing.
        """
        logger.info(
            f"🔍 [CrossHookContextPlugin] RESOURCE_PRE_FETCH executed - "
            f"request_id={context.global_context.request_id}, "
            f"resource_uri={payload.uri}"
        )

        # Verify we can read data from HTTP_PRE_REQUEST
        if "http_timestamp" not in context.state:
            raise ValueError("http_timestamp not found in resource hook! Cross-hook sharing failed.")

        # Verify global context is shared
        if "shared_request_id" not in context.global_context.state:
            raise ValueError("shared_request_id not found in resource hook!")

        # Verify request_id consistency
        shared_request_id = context.global_context.state["shared_request_id"]
        if shared_request_id != context.global_context.request_id:
            raise ValueError(
                f"Request ID mismatch in resource hook! shared_request_id={shared_request_id}, "
                f"global_context.request_id={context.global_context.request_id}"
            )

        # Add resource-specific data
        context.state["resource_uri"] = payload.uri
        context.state["resource_fetched_at"] = "2025-01-01T00:02:00Z"

        return ResourcePreFetchResult(continue_processing=True)

    async def prompt_pre_fetch(
        self, payload: PromptPrehookPayload, context: PluginContext
    ) -> PromptPrehookResult:
        """Verify context from HTTP hooks is accessible in prompt hooks.

        Args:
            payload: The prompt fetch payload.
            context: Plugin context that should contain data from HTTP hooks.

        Returns:
            Result allowing prompt fetch to continue.

        Raises:
            ValueError: If expected context data is missing.
        """
        logger.info(
            f"🔍 [CrossHookContextPlugin] PROMPT_PRE_FETCH executed - "
            f"request_id={context.global_context.request_id}, "
            f"prompt_id={payload.prompt_id}"
        )

        # Verify we can read data from HTTP_PRE_REQUEST
        if "http_timestamp" not in context.state:
            raise ValueError("http_timestamp not found in prompt hook! Cross-hook sharing failed.")

        # Verify global context is shared
        if "shared_request_id" not in context.global_context.state:
            raise ValueError("shared_request_id not found in prompt hook!")

        # Verify request_id consistency
        shared_request_id = context.global_context.state["shared_request_id"]
        if shared_request_id != context.global_context.request_id:
            raise ValueError(
                f"Request ID mismatch in prompt hook! shared_request_id={shared_request_id}, "
                f"global_context.request_id={context.global_context.request_id}"
            )

        # Add prompt-specific data
        context.state["prompt_id"] = payload.prompt_id
        context.state["prompt_fetched_at"] = "2025-01-01T00:03:00Z"

        return PromptPrehookResult(continue_processing=True)
