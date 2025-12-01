# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/models.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor, Mihai Criveti

Pydantic models for plugins.
This module implements the pydantic models associated with
the base plugin layer including configurations, and contexts.
"""

# Standard
from enum import Enum
import os
from pathlib import Path
from typing import Any, Generic, Optional, Self, TypeAlias, TypeVar

# Third-Party
from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator, PrivateAttr, ValidationInfo

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.plugins.framework.constants import EXTERNAL_PLUGIN_TYPE, IGNORE_CONFIG_EXTERNAL, PYTHON_SUFFIX, SCRIPT, URL

T = TypeVar("T")


class PluginMode(str, Enum):
    """Plugin modes of operation.

    Attributes:
       enforce: enforces the plugin result, and blocks execution when there is an error.
       enforce_ignore_error: enforces the plugin result, but allows execution when there is an error.
       permissive: audits the result.
       disabled: plugin disabled.

    Examples:
        >>> PluginMode.ENFORCE
        <PluginMode.ENFORCE: 'enforce'>
        >>> PluginMode.ENFORCE_IGNORE_ERROR
        <PluginMode.ENFORCE_IGNORE_ERROR: 'enforce_ignore_error'>
        >>> PluginMode.PERMISSIVE.value
        'permissive'
        >>> PluginMode('disabled')
        <PluginMode.DISABLED: 'disabled'>
        >>> 'enforce' in [m.value for m in PluginMode]
        True
    """

    ENFORCE = "enforce"
    ENFORCE_IGNORE_ERROR = "enforce_ignore_error"
    PERMISSIVE = "permissive"
    DISABLED = "disabled"


class BaseTemplate(BaseModel):
    """Base Template.The ToolTemplate, PromptTemplate and ResourceTemplate could be extended using this

    Attributes:
        context (Optional[list[str]]): specifies the keys of context to be extracted. The context could be global (shared between the plugins) or
        local (shared within the plugin). Example: global.key1.
        extensions (Optional[dict[str, Any]]): add custom keys for your specific plugin. Example - 'policy'
        key for opa plugin.

    Examples:
        >>> base = BaseTemplate(context=["global.key1.key2", "local.key1.key2"])
        >>> base.context
        ['global.key1.key2', 'local.key1.key2']
        >>> base = BaseTemplate(context=["global.key1.key2"], extensions={"policy" : "sample policy"})
        >>> base.extensions
        {'policy': 'sample policy'}
    """

    context: Optional[list[str]] = None
    extensions: Optional[dict[str, Any]] = None


class ToolTemplate(BaseTemplate):
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


class PromptTemplate(BaseTemplate):
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


class ResourceTemplate(BaseTemplate):
    """Resource Template.

    Attributes:
        resource_uri (str): the URI of the resource.
        fields (Optional[list[str]]): the resource fields that are affected.
        result (bool): analyze resource output if true.

    Examples:
        >>> resource = ResourceTemplate(resource_uri="file:///data.txt")
        >>> resource.resource_uri
        'file:///data.txt'
        >>> resource.result
        False
        >>> resource2 = ResourceTemplate(resource_uri="http://api/data", fields=["content"], result=True)
        >>> resource2.fields
        ['content']
    """

    resource_uri: str
    fields: Optional[list[str]] = None
    result: bool = False


class PluginCondition(BaseModel):
    """Conditions for when plugin should execute.

    Attributes:
        server_ids (Optional[set[str]]): set of server ids.
        tenant_ids (Optional[set[str]]): set of tenant ids.
        tools (Optional[set[str]]): set of tool names.
        prompts (Optional[set[str]]): set of prompt names.
        resources (Optional[set[str]]): set of resource URIs.
        agents (Optional[set[str]]): set of agent IDs.
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
    resources: Optional[set[str]] = None
    agents: Optional[set[str]] = None
    user_patterns: Optional[list[str]] = None
    content_types: Optional[list[str]] = None

    @field_serializer("server_ids", "tenant_ids", "tools", "prompts", "resources", "agents")
    def serialize_set(self, value: set[str] | None) -> list[str] | None:
        """Serialize set objects in PluginCondition for MCP.

        Args:
            value: a set of server ids, tenant ids, tools or prompts.

        Returns:
            The set as a serializable list.
        """
        if value:
            values = []
            for key in value:
                values.append(key)
            return values
        return None


class AppliedTo(BaseModel):
    """What tools/prompts/resources and fields the plugin will be applied to.

    Attributes:
        tools (Optional[list[ToolTemplate]]): tools and fields to be applied.
        prompts (Optional[list[PromptTemplate]]): prompts and fields to be applied.
        resources (Optional[list[ResourceTemplate]]): resources and fields to be applied.
        global_context (Optional[list[str]]): keys in the context to be applied on globally
        local_context(Optional[list[str]]): keys in the context to be applied on locally
    """

    tools: Optional[list[ToolTemplate]] = None
    prompts: Optional[list[PromptTemplate]] = None
    resources: Optional[list[ResourceTemplate]] = None


class MCPTransportTLSConfigBase(BaseModel):
    """Base TLS configuration with common fields for both client and server.

    Attributes:
        certfile (Optional[str]): Path to the PEM-encoded certificate file.
        keyfile (Optional[str]): Path to the PEM-encoded private key file.
        ca_bundle (Optional[str]): Path to a CA bundle file for verification.
        keyfile_password (Optional[str]): Optional password for encrypted private key.
    """

    certfile: Optional[str] = Field(default=None, description="Path to PEM certificate file")
    keyfile: Optional[str] = Field(default=None, description="Path to PEM private key file")
    ca_bundle: Optional[str] = Field(default=None, description="Path to CA bundle for verification")
    keyfile_password: Optional[str] = Field(default=None, description="Password for encrypted private key")

    @field_validator("ca_bundle", "certfile", "keyfile", mode="after")
    @classmethod
    def validate_path(cls, value: Optional[str]) -> Optional[str]:
        """Expand and validate file paths supplied in TLS configuration.

        Args:
            value: File path to validate.

        Returns:
            Expanded file path or None if not provided.

        Raises:
            ValueError: If file path does not exist.
        """

        if not value:
            return value
        expanded = Path(value).expanduser()
        if not expanded.is_file():
            raise ValueError(f"TLS file path does not exist: {value}")
        return str(expanded)

    @model_validator(mode="after")
    def validate_cert_key(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure certificate and key options are consistent.

        Returns:
            Self after validation.

        Raises:
            ValueError: If keyfile is specified without certfile.
        """

        if self.keyfile and not self.certfile:
            raise ValueError("keyfile requires certfile to be specified")
        return self

    @staticmethod
    def _parse_bool(value: Optional[str]) -> Optional[bool]:
        """Convert a string environment value to boolean.

        Args:
            value: String value to parse as boolean.

        Returns:
            Boolean value or None if value is None.

        Raises:
            ValueError: If value is not a valid boolean string.
        """

        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value}")


class MCPClientTLSConfig(MCPTransportTLSConfigBase):
    """Client-side TLS configuration (gateway connecting to plugin).

    Attributes:
        verify (bool): Whether to verify the remote server certificate.
        check_hostname (bool): Enable hostname verification when verify is true.
    """

    verify: bool = Field(default=True, description="Verify the upstream server certificate")
    check_hostname: bool = Field(default=True, description="Enable hostname verification")

    @classmethod
    def from_env(cls) -> Optional["MCPClientTLSConfig"]:
        """Construct client TLS configuration from PLUGINS_CLIENT_* environment variables.

        Returns:
            MCPClientTLSConfig instance or None if no environment variables are set.
        """

        env = os.environ
        data: dict[str, Any] = {}

        if env.get("PLUGINS_CLIENT_MTLS_CERTFILE"):
            data["certfile"] = env["PLUGINS_CLIENT_MTLS_CERTFILE"]
        if env.get("PLUGINS_CLIENT_MTLS_KEYFILE"):
            data["keyfile"] = env["PLUGINS_CLIENT_MTLS_KEYFILE"]
        if env.get("PLUGINS_CLIENT_MTLS_CA_BUNDLE"):
            data["ca_bundle"] = env["PLUGINS_CLIENT_MTLS_CA_BUNDLE"]
        if env.get("PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD") is not None:
            data["keyfile_password"] = env["PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD"]

        verify_val = cls._parse_bool(env.get("PLUGINS_CLIENT_MTLS_VERIFY"))
        if verify_val is not None:
            data["verify"] = verify_val

        check_hostname_val = cls._parse_bool(env.get("PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME"))
        if check_hostname_val is not None:
            data["check_hostname"] = check_hostname_val

        if not data:
            return None

        return cls(**data)


class MCPServerTLSConfig(MCPTransportTLSConfigBase):
    """Server-side TLS configuration (plugin accepting gateway connections).

    Attributes:
        ssl_cert_reqs (int): Client certificate requirement (0=NONE, 1=OPTIONAL, 2=REQUIRED).
    """

    ssl_cert_reqs: int = Field(default=2, description="Client certificate requirement (0=NONE, 1=OPTIONAL, 2=REQUIRED)")

    @classmethod
    def from_env(cls) -> Optional["MCPServerTLSConfig"]:
        """Construct server TLS configuration from PLUGINS_SERVER_SSL_* environment variables.

        Returns:
            MCPServerTLSConfig instance or None if no environment variables are set.

        Raises:
            ValueError: If PLUGINS_SERVER_SSL_CERT_REQS is not a valid integer.
        """

        env = os.environ
        data: dict[str, Any] = {}

        if env.get("PLUGINS_SERVER_SSL_KEYFILE"):
            data["keyfile"] = env["PLUGINS_SERVER_SSL_KEYFILE"]
        if env.get("PLUGINS_SERVER_SSL_CERTFILE"):
            data["certfile"] = env["PLUGINS_SERVER_SSL_CERTFILE"]
        if env.get("PLUGINS_SERVER_SSL_CA_CERTS"):
            data["ca_bundle"] = env["PLUGINS_SERVER_SSL_CA_CERTS"]
        if env.get("PLUGINS_SERVER_SSL_KEYFILE_PASSWORD") is not None:
            data["keyfile_password"] = env["PLUGINS_SERVER_SSL_KEYFILE_PASSWORD"]

        if env.get("PLUGINS_SERVER_SSL_CERT_REQS"):
            try:
                data["ssl_cert_reqs"] = int(env["PLUGINS_SERVER_SSL_CERT_REQS"])
            except ValueError:
                raise ValueError(f"Invalid PLUGINS_SERVER_SSL_CERT_REQS: {env['PLUGINS_SERVER_SSL_CERT_REQS']}")

        if not data:
            return None

        return cls(**data)


class MCPServerConfig(BaseModel):
    """Server-side MCP configuration (plugin running as server).

    Attributes:
        host (str): Server host to bind to.
        port (int): Server port to bind to.
        tls (Optional[MCPServerTLSConfig]): Server-side TLS configuration.
    """

    host: str = Field(default="127.0.0.1", description="Server host to bind to")
    port: int = Field(default=8000, description="Server port to bind to")
    tls: Optional[MCPServerTLSConfig] = Field(default=None, description="Server-side TLS configuration")

    @staticmethod
    def _parse_bool(value: Optional[str]) -> Optional[bool]:
        """Convert a string environment value to boolean.

        Args:
            value: String value to parse as boolean.

        Returns:
            Boolean value or None if value is None.

        Raises:
            ValueError: If value is not a valid boolean string.
        """

        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {value}")

    @classmethod
    def from_env(cls) -> Optional["MCPServerConfig"]:
        """Construct server configuration from PLUGINS_SERVER_* environment variables.

        Returns:
            MCPServerConfig instance or None if no environment variables are set.

        Raises:
            ValueError: If PLUGINS_SERVER_PORT is not a valid integer.
        """

        env = os.environ
        data: dict[str, Any] = {}

        if env.get("PLUGINS_SERVER_HOST"):
            data["host"] = env["PLUGINS_SERVER_HOST"]
        if env.get("PLUGINS_SERVER_PORT"):
            try:
                data["port"] = int(env["PLUGINS_SERVER_PORT"])
            except ValueError:
                raise ValueError(f"Invalid PLUGINS_SERVER_PORT: {env['PLUGINS_SERVER_PORT']}")

        # Check if SSL/TLS is enabled
        ssl_enabled = cls._parse_bool(env.get("PLUGINS_SERVER_SSL_ENABLED"))
        if ssl_enabled:
            # Load TLS configuration
            tls_config = MCPServerTLSConfig.from_env()
            if tls_config:
                data["tls"] = tls_config

        if not data:
            return None

        return cls(**data)


class MCPClientConfig(BaseModel):
    """Client-side MCP configuration (gateway connecting to external plugin).

    Attributes:
        proto (TransportType): The MCP transport type. Can be SSE, STDIO, or STREAMABLEHTTP
        url (Optional[str]): An MCP URL. Only valid when MCP transport type is SSE or STREAMABLEHTTP.
        script (Optional[str]): The path and name to the STDIO script that runs the plugin server. Only valid for STDIO type.
        tls (Optional[MCPClientTLSConfig]): Client-side TLS configuration for mTLS.
    """

    proto: TransportType
    url: Optional[str] = None
    script: Optional[str] = None
    tls: Optional[MCPClientTLSConfig] = None

    @field_validator(URL, mode="after")
    @classmethod
    def validate_url(cls, url: str | None) -> str | None:
        """Validate a MCP url for streamable HTTP connections.

        Args:
            url: the url to be validated.

        Raises:
            ValueError: if the URL fails validation.

        Returns:
            The validated URL or None if none is set.
        """
        if url:
            result = SecurityValidator.validate_url(url)
            return result
        return url

    @field_validator(SCRIPT, mode="after")
    @classmethod
    def validate_script(cls, script: str | None) -> str | None:
        """Validate an MCP stdio script.

        Args:
            script: the script to be validated.

        Raises:
            ValueError: if the script doesn't exist or doesn't have a valid suffix.

        Returns:
            The validated string or None if none is set.
        """
        if script:
            file_path = Path(script)
            if not file_path.is_file():
                raise ValueError(f"MCP server script {script} does not exist.")
            # Allow both Python (.py) and shell scripts (.sh)
            allowed_suffixes = {PYTHON_SUFFIX, ".sh"}
            if file_path.suffix not in allowed_suffixes:
                raise ValueError(f"MCP server script {script} must have a .py or .sh suffix.")
        return script

    @model_validator(mode="after")
    def validate_tls_usage(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure TLS configuration is only used with HTTP-based transports.

        Returns:
            Self after validation.

        Raises:
            ValueError: If TLS configuration is used with non-HTTP transports.
        """

        if self.tls and self.proto not in (TransportType.SSE, TransportType.STREAMABLEHTTP):
            raise ValueError("TLS configuration is only valid for HTTP/SSE transports")
        return self


class PluginConfig(BaseModel):
    """A plugin configuration.

    Attributes:
        name (str): The unique name of the plugin.
        description (str): A description of the plugin.
        author (str): The author of the plugin.
        kind (str): The kind or type of plugin. Usually a fully qualified object type.
        namespace (str): The namespace where the plugin resides.
        version (str): version of the plugin.
        hooks (list[str]): a list of the hook points where the plugin will be called. Default: [].
        tags (list[str]): a list of tags for making the plugin searchable.
        mode (bool): whether the plugin is active.
        priority (int): indicates the order in which the plugin is run. Lower = higher priority. Default: 100.
        conditions (Optional[list[PluginCondition]]): the conditions on which the plugin is run.
        applied_to (Optional[list[AppliedTo]]): the tools, fields, that the plugin is applied to.
        config (dict[str, Any]): the plugin specific configurations.
        mcp (Optional[MCPClientConfig]): Client-side MCP configuration (gateway connecting to plugin).
    """

    name: str
    description: Optional[str] = None
    author: Optional[str] = None
    kind: str
    namespace: Optional[str] = None
    version: Optional[str] = None
    hooks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    mode: PluginMode = PluginMode.ENFORCE
    priority: int = 100  # Lower = higher priority
    conditions: list[PluginCondition] = Field(default_factory=list)  # When to apply
    applied_to: Optional[AppliedTo] = None  # Fields to apply to.
    config: Optional[dict[str, Any]] = None
    mcp: Optional[MCPClientConfig] = None

    @model_validator(mode="after")
    def check_url_or_script_filled(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Checks to see that at least one of url or script are set depending on MCP server configuration.

        Raises:
            ValueError: if the script attribute is not defined with STDIO set, or the URL not defined with HTTP transports.

        Returns:
            The model after validation.
        """
        if not self.mcp:
            return self
        if self.mcp.proto == TransportType.STDIO and not self.mcp.script:
            raise ValueError(f"Plugin {self.name} has transport type set to SSE but no script value")
        if self.mcp.proto in (TransportType.STREAMABLEHTTP, TransportType.SSE) and not self.mcp.url:
            raise ValueError(f"Plugin {self.name} has transport type set to StreamableHTTP but no url value")
        if self.mcp.proto not in (TransportType.SSE, TransportType.STREAMABLEHTTP, TransportType.STDIO):
            raise ValueError(f"Plugin {self.name} must set transport type to either SSE or STREAMABLEHTTP or STDIO")
        return self

    @model_validator(mode="after")
    def check_config_and_external(self, info: ValidationInfo) -> Self:  # pylint: disable=bad-classmethod-argument
        """Checks to see that a plugin's 'config' section is not defined if the kind is 'external'. This is because developers cannot override items in the plugin config section for external plugins.

        Args:
            info: the contextual information passed into the pydantic model during model validation. Used to determine validation sequence.

        Raises:
            ValueError: if the script attribute is not defined with STDIO set, or the URL not defined with HTTP transports.

        Returns:
            The model after validation.
        """
        ignore_config_external = False
        if info and info.context and IGNORE_CONFIG_EXTERNAL in info.context:
            ignore_config_external = info.context[IGNORE_CONFIG_EXTERNAL]

        if not ignore_config_external and self.config and self.kind == EXTERNAL_PLUGIN_TYPE:
            raise ValueError(f"""Cannot have {self.name} plugin defined as 'external' with 'config' set.""" """ 'config' section settings can only be set on the plugin server.""")

        if self.kind == EXTERNAL_PLUGIN_TYPE and not self.mcp:
            raise ValueError(f"Must set 'mcp' section for external plugin {self.name}")

        return self


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


class PluginErrorModel(BaseModel):
    """A plugin error, used to denote exceptions/errors inside external plugins.

    Attributes:
        message (str): the reason for the error.
        code (str): an error code.
        details: (dict[str, Any]): additional error details.
        plugin_name (str): the plugin name.
        mcp_error_code ([int]): The MCP error code passed back to the client. Defaults to Internal Error.
    """

    message: str
    plugin_name: str
    code: Optional[str] = ""
    details: Optional[dict[str, Any]] = Field(default_factory=dict)
    mcp_error_code: int = -32603


class PluginViolation(BaseModel):
    """A plugin violation, used to denote policy violations.

    Attributes:
        reason (str): the reason for the violation.
        description (str): a longer description of the violation.
        code (str): a violation code.
        details: (dict[str, Any]): additional violation details.
        _plugin_name (str): the plugin name, private attribute set by the plugin manager.
        mcp_error_code(Optional[int]): A valid mcp error code which will be sent back to the client if plugin enabled.

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
    details: Optional[dict[str, Any]] = Field(default_factory=dict)
    _plugin_name: str = PrivateAttr(default="")
    mcp_error_code: Optional[int] = None

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
        plugins (Optional[list[PluginConfig]]): the list of plugins to enable.
        plugin_dirs (list[str]): The directories in which to look for plugins.
        plugin_settings (PluginSettings): global settings for plugins.
        server_settings (Optional[MCPServerConfig]): Server-side MCP configuration (when plugins run as server).
    """

    plugins: Optional[list[PluginConfig]] = []
    plugin_dirs: list[str] = []
    plugin_settings: PluginSettings
    server_settings: Optional[MCPServerConfig] = None


class PluginResult(BaseModel, Generic[T]):
    """A result of the plugin hook processing. The actual type is dependent on the hook.

    Attributes:
            continue_processing (bool): Whether to stop processing.
            modified_payload (Optional[Any]): The modified payload if the plugin is a transformer.
            violation (Optional[PluginViolation]): violation object.
            metadata (Optional[dict[str, Any]]): additional metadata.

     Examples:
        >>> result = PluginResult()
        >>> result.continue_processing
        True
        >>> result.metadata
        {}
        >>> from mcpgateway.plugins.framework import PluginViolation
        >>> violation = PluginViolation(
        ...     reason="Test", description="Test desc", code="TEST", details={}
        ... )
        >>> result2 = PluginResult(continue_processing=False, violation=violation)
        >>> result2.continue_processing
        False
        >>> result2.violation.code
        'TEST'
        >>> r = PluginResult(metadata={"key": "value"})
        >>> r.metadata["key"]
        'value'
        >>> r2 = PluginResult(continue_processing=False)
        >>> r2.continue_processing
        False
    """

    continue_processing: bool = True
    modified_payload: Optional[T] = None
    violation: Optional[PluginViolation] = None
    metadata: Optional[dict[str, Any]] = Field(default_factory=dict)


class GlobalContext(BaseModel):
    """The global context, which shared across all plugins.

    Attributes:
            request_id (str): ID of the HTTP request.
            user (str): user ID associated with the request.
            tenant_id (str): tenant ID.
            server_id (str): server ID.
            metadata (Optional[dict[str,Any]]): a global shared metadata across plugins (Read-only from plugin's perspective).
            state (Optional[dict[str,Any]]): a global shared state across plugins.

    Examples:
        >>> ctx = GlobalContext(request_id="req-123")
        >>> ctx.request_id
        'req-123'
        >>> ctx.user is None
        True
        >>> ctx2 = GlobalContext(request_id="req-456", user="alice", tenant_id="tenant1")
        >>> ctx2.user
        'alice'
        >>> ctx2.tenant_id
        'tenant1'
        >>> c = GlobalContext(request_id="123", server_id="srv1")
        >>> c.request_id
        '123'
        >>> c.server_id
        'srv1'
    """

    request_id: str
    user: Optional[str] = None
    tenant_id: Optional[str] = None
    server_id: Optional[str] = None
    state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginContext(BaseModel):
    """The plugin's context, which lasts a request lifecycle.

    Attributes:
       state:  the inmemory state of the request.
       global_context: the context that is shared across plugins.
       metadata: plugin meta data.

    Examples:
        >>> gctx = GlobalContext(request_id="req-123")
        >>> ctx = PluginContext(global_context=gctx)
        >>> ctx.global_context.request_id
        'req-123'
        >>> ctx.global_context.user is None
        True
        >>> ctx.state["somekey"] = "some value"
        >>> ctx.state["somekey"]
        'some value'
    """

    state: dict[str, Any] = Field(default_factory=dict)
    global_context: GlobalContext
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get value from shared state.

        Args:
            key: The key to access the shared state.
            default: A default value if one doesn't exist.

        Returns:
            The state value.
        """
        return self.state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        """Set value in shared state.

        Args:
            key: the key to add to the state.
            value: the value to add to the state.
        """
        self.state[key] = value

    async def cleanup(self) -> None:
        """Cleanup context resources."""
        self.state.clear()
        self.metadata.clear()

    def is_empty(self) -> bool:
        """Check whether the state and metadata objects are empty.

        Returns:
            True if the context state and metadata are empty.
        """
        return not (self.state or self.metadata or self.global_context.state)


PluginContextTable = dict[str, PluginContext]

PluginPayload: TypeAlias = BaseModel
