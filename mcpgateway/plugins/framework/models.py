# -*- coding: utf-8 -*-
"""Pydantic models for plugins.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from enum import Enum
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel, PrivateAttr


class HookType(str, Enum):
    """MCP Forge Gateway hook points.

    Attributes:
        prompt_pre_fetch: The prompt pre hook.
        prompt_post_fetch: The prompt post hook.
        tool_pre_invoke: The tool pre invoke hook.
        tool_post_invoke: The tool post invoke hook.

    Examples:
        >>> HookType.PROMPT_PRE_FETCH
        <HookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>
        >>> HookType.PROMPT_PRE_FETCH.value
        'prompt_pre_fetch'
        >>> HookType('prompt_post_fetch')
        <HookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>
        >>> list(HookType)
        [<HookType.PROMPT_PRE_FETCH: 'prompt_pre_fetch'>, <HookType.PROMPT_POST_FETCH: 'prompt_post_fetch'>, <HookType.TOOL_PRE_INVOKE: 'tool_pre_invoke'>, <HookType.TOOL_POST_INVOKE: 'tool_post_invoke'>]
    """

    PROMPT_PRE_FETCH = "prompt_pre_fetch"
    PROMPT_POST_FETCH = "prompt_post_fetch"
    TOOL_PRE_INVOKE = "tool_pre_invoke"
    TOOL_POST_INVOKE = "tool_post_invoke"


class PluginMode(str, Enum):
    """Plugin modes of operation.

    Attributes:
       enforce: enforces the plugin result.
       permissive: audits the result.
       disabled: plugin disabled.

    Examples:
        >>> PluginMode.ENFORCE
        <PluginMode.ENFORCE: 'enforce'>
        >>> PluginMode.PERMISSIVE.value
        'permissive'
        >>> PluginMode('disabled')
        <PluginMode.DISABLED: 'disabled'>
        >>> 'enforce' in [m.value for m in PluginMode]
        True
    """

    ENFORCE = "enforce"
    PERMISSIVE = "permissive"
    DISABLED = "disabled"


class ToolTemplate(BaseModel):
    """Tool Template.

    Attributes:
        tool_name (str): the name of the tool.
        fields (Optional[list[str]]): the tool fields that are affected.
        result (bool): analyze tool output if true.

    Examples:
        >>> tool = ToolTemplate(tool_name="my_tool")
        >>> tool.tool_name
        'my_tool'
        >>> tool.result
        False
        >>> tool2 = ToolTemplate(tool_name="analyzer", fields=["input", "params"], result=True)
        >>> tool2.fields
        ['input', 'params']
        >>> tool2.result
        True
    """

    tool_name: str
    fields: Optional[list[str]] = None
    result: bool = False


class PromptTemplate(BaseModel):
    """Prompt Template.

    Attributes:
        prompt_name (str): the name of the prompt.
        fields (Optional[list[str]]): the prompt fields that are affected.
        result (bool): analyze tool output if true.

    Examples:
        >>> prompt = PromptTemplate(prompt_name="greeting")
        >>> prompt.prompt_name
        'greeting'
        >>> prompt.result
        False
        >>> prompt2 = PromptTemplate(prompt_name="question", fields=["context"], result=True)
        >>> prompt2.fields
        ['context']
    """

    prompt_name: str
    fields: Optional[list[str]] = None
    result: bool = False


class PluginCondition(BaseModel):
    """Conditions for when plugin should execute.

    Attributes:
        server_ids (Optional[set[str]]): set of server ids.
        tenant_ids (Optional[set[str]]): set of tenant ids.
        tools (Optional[set[str]]): set of tool names.
        prompts (Optional[set[str]]): set of prompt names.
        user_pattern (Optional[list[str]]): list of user patterns.
        content_types (Optional[list[str]]): list of content types.

    Examples:
        >>> cond = PluginCondition(server_ids={"server1", "server2"})
        >>> "server1" in cond.server_ids
        True
        >>> cond2 = PluginCondition(tools={"tool1"}, prompts={"prompt1"})
        >>> cond2.tools
        {'tool1'}
        >>> cond3 = PluginCondition(user_patterns=["admin", "root"])
        >>> len(cond3.user_patterns)
        2
    """

    server_ids: Optional[set[str]] = None
    tenant_ids: Optional[set[str]] = None
    tools: Optional[set[str]] = None
    prompts: Optional[set[str]] = None
    user_patterns: Optional[list[str]] = None
    content_types: Optional[list[str]] = None


class AppliedTo(BaseModel):
    """What tools/prompts and fields the plugin will be applied to.

    Attributes:
        tools (Optional[list[ToolTemplate]]): tools and fields to be applied.
        prompts (Optional[list[PromptTemplate]]): prompts and fields to be applied.
    """

    tools: Optional[list[ToolTemplate]] = None
    prompts: Optional[list[PromptTemplate]] = None


class PluginConfig(BaseModel):
    """A plugin configuration.

    Attributes:
        name (str): The unique name of the plugin.
        description (str): A description of the plugin.
        author (str): The author of the plugin.
        kind (str): The kind or type of plugin. Usually a fully qualified object type.
        namespace (str): The namespace where the plugin resides.
        version (str): version of the plugin.
        hooks (list[str]): a list of the hook points where the plugin will be called.
        tags (list[str]): a list of tags for making the plugin searchable.
        mode (bool): whether the plugin is active.
        priority (int): indicates the order in which the plugin is run. Lower = higher priority.
        conditions (Optional[list[PluginCondition]]): the conditions on which the plugin is run.
        applied_to (Optional[list[AppliedTo]]): the tools, fields, that the plugin is applied to.
        config (dict[str, Any]): the plugin specific configurations.
    """

    name: str
    description: str
    author: str
    kind: str
    namespace: Optional[str] = None
    version: str
    hooks: list[HookType]
    tags: list[str]
    mode: PluginMode = PluginMode.ENFORCE
    priority: int = 100  # Lower = higher priority
    conditions: Optional[list[PluginCondition]] = None  # When to apply
    applied_to: Optional[list[AppliedTo]] = None  # Fields to apply to.
    config: dict[str, Any] = {}


class PluginManifest(BaseModel):
    """Plugin manifest.

    Attributes:
        description (str): A description of the plugin.
        author (str): The author of the plugin.
        version (str): version of the plugin.
        tags (list[str]): a list of tags for making the plugin searchable.
        available_hooks (list[str]): a list of the hook points where the plugin is callable.
        default_config (dict[str, Any]): the default configurations.
    """

    description: str
    author: str
    version: str
    tags: list[str]
    available_hooks: list[str]
    default_config: dict[str, Any]


class PluginViolation(BaseModel):
    """A plugin violation, used to denote policy violations.

    Attributes:
        reason (str): the reason for the violation.
        description (str): a longer description of the violation.
        code (str): a violation code.
        details: (dict[str, Any]): additional violation details.
        _plugin_name (str): the plugin name, private attribute set by the plugin manager.

    Examples:
        >>> violation = PluginViolation(
        ...     reason="Invalid input",
        ...     description="The input contains prohibited content",
        ...     code="PROHIBITED_CONTENT",
        ...     details={"field": "message", "value": "test"}
        ... )
        >>> violation.reason
        'Invalid input'
        >>> violation.code
        'PROHIBITED_CONTENT'
        >>> violation.plugin_name = "content_filter"
        >>> violation.plugin_name
        'content_filter'
    """

    reason: str
    description: str
    code: str
    details: dict[str, Any]
    _plugin_name: str = PrivateAttr(default="")

    @property
    def plugin_name(self) -> str:
        """Getter for the plugin name attribute.

        Returns:
            The plugin name associated with the violation.
        """
        return self._plugin_name

    @plugin_name.setter
    def plugin_name(self, name: str) -> None:
        """Setter for the plugin_name attribute.

        Args:
            name: the plugin name.

        Raises:
            ValueError: if name is empty or not a string.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Name must be a non-empty string.")
        self._plugin_name = name


class PluginSettings(BaseModel):
    """Global plugin settings.

    Attributes:
        parallel_execution_within_band (bool): execute plugins with same priority in parallel.
        plugin_timeout (int):  timeout value for plugins operations.
        fail_on_plugin_error (bool): error when there is a plugin connectivity or ignore.
        enable_plugin_api (bool): enable or disable plugins globally.
        plugin_health_check_interval (int): health check interval check.
    """

    parallel_execution_within_band: bool = False
    plugin_timeout: int = 30
    fail_on_plugin_error: bool = False
    enable_plugin_api: bool = False
    plugin_health_check_interval: int = 60


class Config(BaseModel):
    """Configurations for plugins.

    Attributes:
        plugins: the list of plugins to enable.
        plugin_dirs: The directories in which to look for plugins.
        plugin_settings: global settings for plugins.
    """

    plugins: Optional[list[PluginConfig]] = []
    plugin_dirs: list[str] = []
    plugin_settings: PluginSettings
