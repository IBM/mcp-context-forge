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
import logging
import os
from pathlib import Path
from typing import Any, Generic, Optional, Self, TypeAlias, TypeVar

# Third-Party
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
    PrivateAttr,
    ValidationInfo,
)

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.plugins.framework.constants import (
    EXTERNAL_PLUGIN_TYPE,
    IGNORE_CONFIG_EXTERNAL,
    PYTHON_SUFFIX,
    SCRIPT,
    URL,
)

logger = logging.getLogger(__name__)
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
        post_priority (Optional[int]): Optional custom priority for post-hooks (enables wrapping behavior).
        conditions (Optional[list[PluginCondition]]): the conditions on which the plugin is run.
        applied_to (Optional[list[AppliedTo]]): the tools, fields, that the plugin is applied to.
        config (dict[str, Any]): the plugin specific configurations.
        mcp (Optional[MCPClientConfig]): Client-side MCP configuration (gateway connecting to plugin).
    """

    model_config = ConfigDict(use_enum_values=True)

    name: str
    description: Optional[str] = None
    author: Optional[str] = None
    kind: str
    namespace: Optional[str] = None
    version: Optional[str] = None
    hooks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    mode: PluginMode = PluginMode.ENFORCE
    priority: Optional[int] = 100  # Lower = higher priority
    post_priority: Optional[int] = None  # Optional custom priority for post-hooks
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
        auto_reverse_post_hooks (bool): automatically reverse plugin order on post-hooks for wrapping behavior.
        enable_plugin_routing (bool): enable resource-centric plugin routing configuration.
        rule_merge_strategy (str): strategy for merging matching rules - "most_specific" (default) or "merge_all".
    """

    parallel_execution_within_band: bool = False
    plugin_timeout: int = 30
    fail_on_plugin_error: bool = False
    enable_plugin_api: bool = False
    plugin_health_check_interval: int = 60
    auto_reverse_post_hooks: bool = False
    enable_plugin_routing: bool = False
    rule_merge_strategy: str = "most_specific"  # "most_specific" or "merge_all"


# ============================================================================
# PLUGIN ROUTING MODELS (Resource-Centric Configuration)
# ============================================================================


class EntityType(str, Enum):
    """Types of entities that can have plugins attached.

    Attributes:
        TOOL: MCP tool entity.
        PROMPT: MCP prompt entity.
        RESOURCE: MCP resource entity.
        AGENT: LLM agent entity.
        VIRTUAL_SERVER: Virtual server entity (composed from catalog items).
        MCP_SERVER: MCP server/gateway entity (external MCP server).

    Examples:
        >>> EntityType.TOOL
        <EntityType.TOOL: 'tool'>
        >>> EntityType.TOOL.value
        'tool'
        >>> EntityType('prompt')
        <EntityType.PROMPT: 'prompt'>
    """

    TOOL = "tool"
    PROMPT = "prompt"
    RESOURCE = "resource"
    AGENT = "agent"
    VIRTUAL_SERVER = "virtual_server"
    MCP_SERVER = "mcp_server"


class FieldSelection(BaseModel):
    """Field selection for scoping plugin execution to specific fields.

    Allows plugins to process only specific fields in payloads using JSONPath-like
    notation. Supports dot notation, array indexing, and wildcards.

    Attributes:
        fields: Shorthand for input_fields (pre-hook only).
        input_fields: Field paths to process on pre-hook (request).
        output_fields: Field paths to process on post-hook (response).

    Examples:
        >>> # Simple field selection
        >>> fs = FieldSelection(fields=["args.email", "args.phone"])
        >>> fs.fields
        ['args.email', 'args.phone']

        >>> # Different fields for input and output
        >>> fs2 = FieldSelection(
        ...     input_fields=["args.user_id"],
        ...     output_fields=["result.customer.ssn"]
        ... )
        >>> fs2.input_fields
        ['args.user_id']
        >>> fs2.output_fields
        ['result.customer.ssn']

        >>> # Array and wildcard support
        >>> fs3 = FieldSelection(fields=["args.customers[*].email"])
        >>> fs3.fields
        ['args.customers[*].email']
    """

    fields: Optional[list[str]] = None
    input_fields: Optional[list[str]] = None
    output_fields: Optional[list[str]] = None


class PluginAttachment(BaseModel):
    """Plugin attachment configuration for resource-centric routing.

    Represents HOW a plugin is attached to an entity (tool/prompt/resource/agent).
    The plugin definition (PluginConfig) declares WHAT the plugin is.

    Attributes:
        name: Plugin name (references PluginConfig.name).
        priority: Execution priority (lower = runs first).
        post_priority: Optional custom priority for post-hooks (enables wrapping behavior).
        hooks: Override plugin's declared hooks (use specific hooks only).
        when: Runtime condition (transferred from rule, not set in config).
        apply_to: Field selection for scoping to specific fields.
        override: If True, replace inherited config instead of merging.
        mode: Override plugin's default execution mode.
        config: Plugin-specific configuration overrides/extensions.
        instance_key: Unique instance identifier (name:config_hash), set during resolution.

    Examples:
        >>> # Basic attachment
        >>> pa = PluginAttachment(name="pii_filter", priority=10)
        >>> pa.name
        'pii_filter'
        >>> pa.priority
        10

        >>> # With field selection
        >>> pa3 = PluginAttachment(
        ...     name="pii_filter",
        ...     priority=10,
        ...     apply_to=FieldSelection(fields=["args.email"])
        ... )
        >>> pa3.apply_to.fields
        ['args.email']

        >>> # With hooks override
        >>> pa4 = PluginAttachment(
        ...     name="security_check",
        ...     priority=5,
        ...     hooks=["tool_pre_invoke", "tool_post_invoke"]
        ... )
        >>> len(pa4.hooks)
        2

        >>> # With post-hook priority for wrapping
        >>> pa5 = PluginAttachment(
        ...     name="transaction",
        ...     priority=10,
        ...     post_priority=30
        ... )
        >>> pa5.post_priority
        30
    """

    model_config = ConfigDict(use_enum_values=True)

    name: str
    priority: Optional[int] = None  # If None, assigned based on list position
    post_priority: Optional[int] = None
    hooks: Optional[list[str]] = None
    when: Optional[str] = None  # Transferred from rule, not set in config
    apply_to: Optional[FieldSelection] = None
    override: bool = False
    mode: Optional[PluginMode] = None
    config: dict[str, Any] = Field(default_factory=dict)
    instance_key: Optional[str] = None  # Unique instance key (name:config_hash), set during resolution

    @model_validator(mode="after")
    def warn_when_in_config(self) -> Self:
        """Warn if 'when' is set directly on plugin attachment in config.

        The 'when' field should be defined at the rule level, not on individual plugins.
        The resolver transfers the rule's 'when' to plugins during resolution.

        Returns:
            The validated attachment.
        """
        if self.when:
            logger.warning(
                f"Plugin attachment '{self.name}' has 'when' clause set directly. "
                f"This is not recommended - define 'when' at the rule level instead. "
                f"The resolver will transfer rule 'when' clauses to plugins automatically."
            )
        return self


class PluginHookRule(BaseModel):
    """Plugin hook rule for declarative, flat rule-based routing.

    Defines WHEN and WHERE plugins should be attached using exact matches,
    tag-based matching, and complex expressions. Replaces hierarchical cascading.

    Attributes:
        entities: Entity types this rule applies to (tools, prompts, resources, agents).
                 If None, applies to HTTP-level hooks (before entity resolution).
        name: Exact entity name match(es) - fast path with hash lookup.
              Can be single string or list of strings.
        tags: Tag-based matching - fast path with set intersection.
        hooks: Hook type filter(s) - applies only to specific hooks.
               Examples: ["tool_pre_invoke", "tool_post_invoke"], ["http_pre_request"]
        when: Complex policy expression - flexible path with expression evaluation.
        server_name: Server name filter(s) - applies only to entities on these servers.
        server_id: Server ID filter(s) - applies only to entities on these servers.
        gateway_id: Gateway ID filter(s) - applies only to entities on these gateways.
        priority: Rule priority (lower = runs first). Default: list order.
        reverse_order_on_post: If True, reverse plugin order for post-hooks (wrapping).
        plugins: Plugins to attach when rule matches.
        metadata: Rule metadata for governance, auditing, documentation.

    Examples:
        >>> # Simple tag-based rule
        >>> rule = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     tags=["customer", "pii"],
        ...     plugins=[
        ...         PluginAttachment(name="pii_filter", priority=10),
        ...         PluginAttachment(name="audit_logger", priority=20)
        ...     ]
        ... )
        >>> rule.tags
        ['customer', 'pii']
        >>> len(rule.plugins)
        2

        >>> # Exact name match
        >>> rule2 = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     name="process_payment",
        ...     plugins=[PluginAttachment(name="fraud_detector", priority=5)]
        ... )
        >>> rule2.name
        'process_payment'

        >>> # Multiple names
        >>> rule3 = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     name=["create_user", "update_user", "delete_user"],
        ...     reverse_order_on_post=True,
        ...     plugins=[PluginAttachment(name="user_validator", priority=10)]
        ... )
        >>> len(rule3.name)
        3

        >>> # Complex expression
        >>> rule4 = PluginHookRule(
        ...     entities=[EntityType.RESOURCE],
        ...     when="payload.uri.endswith('.env') or payload.uri.endswith('.secrets')",
        ...     plugins=[PluginAttachment(name="secret_redactor", priority=1)]
        ... )
        >>> rule4.when
        "payload.uri.endswith('.env') or payload.uri.endswith('.secrets')"

        >>> # HTTP-level rule (no entities)
        >>> rule5 = PluginHookRule(
        ...     when="payload.method == 'POST'",
        ...     plugins=[PluginAttachment(name="rate_limiter", priority=10)]
        ... )
        >>> rule5.entities is None
        True

        >>> # Server filtering
        >>> rule6 = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     server_name="production-api",
        ...     tags=["pii"],
        ...     plugins=[PluginAttachment(name="pii_filter", priority=10)]
        ... )
        >>> rule6.server_name
        'production-api'

        >>> # With metadata
        >>> rule7 = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     tags=["customer"],
        ...     plugins=[PluginAttachment(name="audit_logger", priority=10)],
        ...     metadata={"reason": "GDPR compliance", "ticket": "SEC-1234"}
        ... )
        >>> rule7.metadata['reason']
        'GDPR compliance'

        >>> # Hook type filtering
        >>> rule8 = PluginHookRule(
        ...     entities=[EntityType.TOOL],
        ...     hooks=["tool_pre_invoke"],
        ...     tags=["customer"],
        ...     plugins=[PluginAttachment(name="pre_validator", priority=10)]
        ... )
        >>> rule8.hooks
        ['tool_pre_invoke']

        >>> # HTTP-level with hook filter
        >>> rule9 = PluginHookRule(
        ...     hooks=["http_pre_request"],
        ...     plugins=[PluginAttachment(name="auth_checker", priority=5)]
        ... )
        >>> rule9.hooks
        ['http_pre_request']
        >>> rule9.entities is None
        True
    """

    model_config = ConfigDict(use_enum_values=True)
    entities: Optional[list[EntityType]] = None  # None = HTTP-level
    name: Optional[str | list[str]] = None  # Exact match (fast path)
    tags: Optional[list[str]] = None  # Tag match (fast path)
    hooks: Optional[list[str]] = None  # Hook type filter (e.g., ["tool_pre_invoke"])
    when: Optional[str] = None  # Expression (flexible path)
    server_name: Optional[str | list[str]] = None  # Server filter
    server_id: Optional[str | list[str]] = None  # Server ID filter
    gateway_id: Optional[str | list[str]] = None  # Gateway filter
    priority: Optional[int] = None  # Rule priority (lower = first)
    reverse_order_on_post: bool = False  # Reverse plugin order for post-hooks
    plugins: list[PluginAttachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        """Validate the plugin hook rule has valid configuration.

        Checks:
        1. Plugins list is not empty
        2. At least one matching criterion is specified (name, tags, when, or entities)
        3. 'when' expression has valid syntax (if specified)

        Returns:
            The validated rule.

        Raises:
            ValueError: If validation fails.
        """
        # Check plugins list is not empty
        if not self.plugins:
            raise ValueError("PluginHookRule must have at least one plugin in the 'plugins' list")

        # Global rules support: Allow rules with no matching criteria
        # Empty rules (no filters) will match ALL entities and hooks globally
        # This enables baseline/default plugin configurations
        #
        # Note: The rule matching logic in rule_resolver.py handles empty rules correctly:
        # - If all filters are None/empty, all checks are skipped and the rule matches everything
        # - This allows creating "global" or "default" rules that apply universally

        # Entity-level rules CAN match all entities of a type (catch-all rules are valid)
        # e.g., entities: [tool] without other criteria applies to ALL tools
        # This allows baseline plugins; more specific rules can override via priority

        # Validate 'when' expression syntax if present
        if self.when:
            try:
                # Import here to avoid circular dependency
                # First-Party
                from mcpgateway.plugins.framework.routing.evaluator import PolicyEvaluator

                evaluator = PolicyEvaluator()
                # Try to parse the expression (validates syntax, doesn't evaluate)
                evaluator._parse_expression(self.when)
            except SyntaxError as e:
                raise ValueError(f"Invalid 'when' expression syntax: {self.when}. Error: {e}") from e
            except Exception as e:
                raise ValueError(f"Failed to validate 'when' expression: {self.when}. Error: {e}") from e

        # Assign default priorities to plugins based on list position
        # This enables implicit priority through order
        for i, plugin in enumerate(self.plugins):
            if plugin.priority is None:
                # Assign priority based on position (0, 1, 2, ...)
                plugin.priority = i

        return self


class ConfigMetadata(BaseModel):
    """Top-level configuration metadata.

    Used for config-wide attributes like tenant_id, environment, region.
    Especially useful when using separate config files per tenant.

    Attributes:
        tenant_id: Tenant identifier.
        environment: Environment (production, staging, development).
        region: Cloud region or datacenter.
        custom: Additional custom metadata.

    Examples:
        >>> metadata = ConfigMetadata(
        ...     tenant_id="tenant-acme",
        ...     environment="production",
        ...     region="us-east-1"
        ... )
        >>> metadata.tenant_id
        'tenant-acme'
        >>> metadata.environment
        'production'
    """

    tenant_id: Optional[str] = None
    environment: Optional[str] = None
    region: Optional[str] = None
    custom: dict[str, Any] = Field(default_factory=dict)


class PluginWithHookInfo(BaseModel):
    """Plugin information enriched with hook phase details.

    Used for UI display to show which hooks are pre/post for a given entity type.

    Attributes:
        name: Plugin name
        description: Plugin description
        pre_hooks: List of pre-phase hooks (e.g., tool_pre_invoke)
        post_hooks: List of post-phase hooks (e.g., tool_post_invoke)
        all_hooks: All hooks for the entity type

    Examples:
        >>> info = PluginWithHookInfo(
        ...     name="TestPlugin",
        ...     pre_hooks=["tool_pre_invoke"],
        ...     post_hooks=["tool_post_invoke"],
        ...     all_hooks=["tool_pre_invoke", "tool_post_invoke"]
        ... )
        >>> info.name
        'TestPlugin'
        >>> len(info.pre_hooks)
        1
    """

    name: str
    description: Optional[str] = None
    pre_hooks: list[str] = Field(default_factory=list)
    post_hooks: list[str] = Field(default_factory=list)
    all_hooks: list[str] = Field(default_factory=list)


class Config(BaseModel):
    """Configurations for plugins.

    Attributes:
        plugins (Optional[list[PluginConfig]]): the list of plugins to enable.
        plugin_dirs (list[str]): The directories in which to look for plugins.
        plugin_settings (PluginSettings): global settings for plugins.
        server_settings (Optional[MCPServerConfig]): Server-side MCP configuration (when plugins run as server).
        metadata (Optional[ConfigMetadata]): Config-wide metadata (tenant_id, environment, region, etc.).
        routes (list[PluginHookRule]): Flat rule-based plugin routing (NEW declarative approach).
    """

    model_config = ConfigDict(use_enum_values=True)

    plugins: Optional[list[PluginConfig]] = []
    plugin_dirs: list[str] = []
    plugin_settings: PluginSettings = Field(default_factory=PluginSettings)
    server_settings: Optional[MCPServerConfig] = None
    # Config-wide metadata
    metadata: Optional[ConfigMetadata] = None
    # NEW: Flat rule-based plugin routing (declarative approach)
    routes: list[PluginHookRule] = Field(default_factory=list)


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
            entity_type (Optional[str]): entity type for resource-centric routing (e.g., "tool", "prompt", "resource").
            entity_id (Optional[str]): unique entity ID for resource-centric routing (e.g., database ID).
            entity_name (Optional[str]): entity name for resource-centric routing (e.g., "my_tool").
            attachment_config (Optional[PluginAttachment]): The plugin attachment configuration for the current plugin execution.
                Contains priority, field selection (apply_to), conditional execution (when), and plugin-specific config overrides.
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
        >>> c2 = GlobalContext(request_id="123", entity_type="tool", entity_id="tool-123", entity_name="my_tool")
        >>> c2.entity_type
        'tool'
        >>> c2.entity_id
        'tool-123'
        >>> c2.entity_name
        'my_tool'
        >>> # With attachment config for field selection
        >>> from mcpgateway.plugins.framework.models import PluginAttachment, FieldSelection
        >>> attachment = PluginAttachment(name="pii_filter", priority=10, apply_to=FieldSelection(fields=["args.email"]))
        >>> c3 = GlobalContext(request_id="456", attachment_config=attachment)
        >>> c3.attachment_config.name
        'pii_filter'
        >>> c3.attachment_config.apply_to.fields
        ['args.email']
    """

    request_id: str
    user: Optional[str] = None
    tenant_id: Optional[str] = None
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    gateway_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    attachment_config: Optional["PluginAttachment"] = None
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
