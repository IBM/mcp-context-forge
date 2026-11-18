# SPDX-License-Identifier: Apache-2.0
"""Gateway payload contracts adapted from CPEX 0.1.

Copyright 2025
Authors: Teryl Taylor, Mihai Criveti, Fred Araujo
"""

from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, RootModel

T = TypeVar("T")


class PluginMode(StrEnum):
    """Represent PluginMode at the gateway plugin boundary."""

    FIRE_AND_FORGET = "fire_and_forget"
    CONCURRENT = "concurrent"
    SEQUENTIAL = "sequential"
    TRANSFORM = "transform"
    AUDIT = "audit"
    DISABLED = "disabled"


class OnError(StrEnum):
    """Represent OnError at the gateway plugin boundary."""

    FAIL = "fail"
    IGNORE = "ignore"
    DISABLE = "disable"


class PluginErrorModel(BaseModel):
    """Represent PluginErrorModel at the gateway plugin boundary."""

    message: str
    plugin_name: str
    code: Optional[str] = ""
    details: Optional[dict[str, Any]] = Field(default_factory=dict)
    mcp_error_code: int = -32603


class PluginViolation(BaseModel):
    """Represent PluginViolation at the gateway plugin boundary."""

    reason: str
    description: str
    code: str
    details: Optional[dict[str, Any]] = Field(default_factory=dict)
    _plugin_name: str = PrivateAttr(default="")
    mcp_error_code: Optional[int] = None
    http_status_code: Optional[int] = None
    http_headers: Optional[dict[str, str]] = None

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


class UserContext(BaseModel):
    """Represent UserContext at the gateway plugin boundary."""

    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_admin: bool = False
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    team_id: Optional[str] = None
    teams: Optional[list[str]] = None
    department: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    auth_method: Optional[str] = None
    authenticated_at: Optional[datetime] = None
    service_account: Optional[str] = None
    delegation_chain: list[str] = Field(default_factory=list)


class GlobalContext(BaseModel):
    """Represent GlobalContext at the gateway plugin boundary."""

    request_id: str
    user: Optional[Union[str, dict[str, Any]]] = None
    user_context: Optional[UserContext] = None
    tenant_id: Optional[str] = None
    server_id: Optional[str] = None
    content_type: Optional[str] = None
    state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginContext(BaseModel):
    """Represent PluginContext at the gateway plugin boundary."""

    state: dict[str, Any] = Field(default_factory=dict)
    global_context: GlobalContext
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginPayload(BaseModel):
    """Represent PluginPayload at the gateway plugin boundary."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class HttpHeaderPayload(RootModel[dict[str, str]], PluginPayload):
    """Represent HttpHeaderPayload at the gateway plugin boundary."""

    def __iter__(self) -> Any:
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
        """Mutation helper — operates on the underlying dict.

        .. warning::
           Because ``PluginPayload`` is frozen, this should only be used
           on freshly-created copies (e.g. inside ``model_copy``).  The
           executor deep-copies payloads before handing them to plugins,
           so in-place writes on the copy are safe.

        Args:
            key: The http header key.
            value: The http header value to be set.
        """
        self.root[key] = value

    def __len__(self) -> int:
        """Custom len function to override root attribute.

        Returns:
            The len of the header dictionary.
        """
        return len(self.root)


class HttpHookType(str, Enum):
    """Represent HttpHookType at the gateway plugin boundary."""

    HTTP_PRE_REQUEST = "http_pre_request"
    HTTP_POST_REQUEST = "http_post_request"
    HTTP_AUTH_RESOLVE_USER = "http_auth_resolve_user"
    HTTP_AUTH_CHECK_PERMISSION = "http_auth_check_permission"


class HttpPreRequestPayload(PluginPayload):
    """Represent HttpPreRequestPayload at the gateway plugin boundary."""

    path: str
    method: str
    client_host: str | None = None
    client_port: int | None = None
    headers: HttpHeaderPayload


class HttpPostRequestPayload(HttpPreRequestPayload):
    """Represent HttpPostRequestPayload at the gateway plugin boundary."""

    response_headers: HttpHeaderPayload | None = None
    status_code: int | None = None


class HttpAuthResolveUserPayload(PluginPayload):
    """Represent HttpAuthResolveUserPayload at the gateway plugin boundary."""

    credentials: dict[str, Any] | None = None
    headers: HttpHeaderPayload
    client_host: str | None = None
    client_port: int | None = None


class HttpAuthCheckPermissionPayload(PluginPayload):
    """Represent HttpAuthCheckPermissionPayload at the gateway plugin boundary."""

    user_email: str
    permission: str
    resource_type: str | None = None
    team_id: str | None = None
    is_admin: bool = False
    auth_method: str | None = None
    client_host: str | None = None
    user_agent: str | None = None


class HttpAuthCheckPermissionResultPayload(PluginPayload):
    """Represent HttpAuthCheckPermissionResultPayload at the gateway plugin boundary."""

    granted: bool
    reason: str | None = None


class ToolHookType(str, Enum):
    """Represent ToolHookType at the gateway plugin boundary."""

    TOOL_PRE_INVOKE = "tool_pre_invoke"
    TOOL_POST_INVOKE = "tool_post_invoke"


class ToolPreInvokePayload(PluginPayload):
    """Represent ToolPreInvokePayload at the gateway plugin boundary."""

    name: str
    args: Optional[dict[str, Any]] = Field(default_factory=dict)
    headers: Optional[HttpHeaderPayload] = None


class ToolPostInvokePayload(PluginPayload):
    """Represent ToolPostInvokePayload at the gateway plugin boundary."""

    name: str
    result: Any


class PromptHookType(str, Enum):
    """Represent PromptHookType at the gateway plugin boundary."""

    PROMPT_PRE_FETCH = "prompt_pre_fetch"
    PROMPT_POST_FETCH = "prompt_post_fetch"


class PromptPrehookPayload(PluginPayload):
    """Represent PromptPrehookPayload at the gateway plugin boundary."""

    prompt_id: str
    args: Optional[dict[str, str]] = Field(default_factory=dict)


class PromptPosthookPayload(PluginPayload):
    """Represent PromptPosthookPayload at the gateway plugin boundary."""

    prompt_id: str
    result: Any


class ResourceHookType(str, Enum):
    """Represent ResourceHookType at the gateway plugin boundary."""

    RESOURCE_PRE_FETCH = "resource_pre_fetch"
    RESOURCE_POST_FETCH = "resource_post_fetch"


class ResourcePreFetchPayload(PluginPayload):
    """Represent ResourcePreFetchPayload at the gateway plugin boundary."""

    uri: str
    metadata: Optional[dict[str, Any]] = Field(default_factory=dict)


class ResourcePostFetchPayload(PluginPayload):
    """Represent ResourcePostFetchPayload at the gateway plugin boundary."""

    uri: str
    content: Any


class AgentHookType(str, Enum):
    """Represent AgentHookType at the gateway plugin boundary."""

    AGENT_PRE_INVOKE = "agent_pre_invoke"
    AGENT_POST_INVOKE = "agent_post_invoke"


class AgentPreInvokePayload(PluginPayload):
    """Represent AgentPreInvokePayload at the gateway plugin boundary."""

    agent_id: str
    messages: List[Any]
    tools: Optional[List[str]] = None
    headers: Optional[HttpHeaderPayload] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AgentPostInvokePayload(PluginPayload):
    """Represent AgentPostInvokePayload at the gateway plugin boundary."""

    agent_id: str
    messages: List[Any]
    tool_calls: Optional[List[Dict[str, Any]]] = None


class RequestExtension(BaseModel):
    """Represent RequestExtension at the gateway plugin boundary."""

    model_config = ConfigDict(frozen=True)
    environment: str | None = Field(default=None, description="Execution environment (production, staging, dev).")
    request_id: str | None = Field(default=None, description="Request correlation ID.")
    timestamp: str | None = Field(default=None, description="ISO timestamp of the request.")
    trace_id: str | None = Field(default=None, description="Distributed tracing ID (OpenTelemetry).")
    span_id: str | None = Field(default=None, description="Distributed tracing span ID.")


PluginContextTable = dict[str, PluginContext]


class PluginResult(BaseModel, Generic[T]):
    """Return gateway hook payloads and control decisions."""

    continue_processing: bool = True
    modified_payload: T | None = None
    violation: PluginViolation | None = None
    metadata: dict[str, Any] | None = Field(default_factory=dict)
    retry_delay_ms: int = 0
    executions: list[Any] = Field(default_factory=list)
