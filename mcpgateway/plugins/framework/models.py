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
from pydantic import BaseModel


class HookType(str, Enum):
    """MCP Forge Gateway hook points.

    Attributes:
        prompt_pre_fetch: The prompt pre hook.
        prompt_post_fetch: The prompt post hook.
    """

    PROMPT_PRE_FETCH = "prompt_pre_fetch"
    PROMPT_POST_FETCH = "prompt_post_fetch"


class PluginMode(str, Enum):
    """Plugin modes of operation.

    Attributes:
       enforce: enforces the plugin result.
       permissive: audits the result.
       disabled: plugin disabled.
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
    """A plugin filter violation.

    Attributes:
        plugin_name (str): The name of the plugin.
        description (str): the violation in text.
        violation_code (str): a violation code.
        details: (dict[str, Any])
    """

    plugin_name: str
    description: str
    violation_code: str
    details: dict[str, Any]


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

    plugins: list[PluginConfig] = []
    plugin_dirs: list[str] = []
    plugin_settings: PluginSettings
