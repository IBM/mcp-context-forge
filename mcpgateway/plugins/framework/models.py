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
from typing import Any, Generic, Optional, Self, TypeAlias, TypeVar, Union

# Third-Party
from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator, PrivateAttr, ValidationInfo

# First-Party
from mcpgateway.common.models import TransportType
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.plugins.framework.constants import CMD, CWD, ENV, EXTERNAL_PLUGIN_TYPE, IGNORE_CONFIG_EXTERNAL, PYTHON_SUFFIX, SCRIPT, UDS, URL
from mcpgateway.plugins.framework.settings import get_settings

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
        s = get_settings()
        data: dict[str, Any] = {}

        if s.client_mtls_certfile:
            data["certfile"] = s.client_mtls_certfile
        if s.client_mtls_keyfile:
            data["keyfile"] = s.client_mtls_keyfile
        if s.client_mtls_ca_bundle:
            data["ca_bundle"] = s.client_mtls_ca_bundle
        if s.client_mtls_keyfile_password is not None:
            data["keyfile_password"] = s.client_mtls_keyfile_password
        if s.client_mtls_verify is not None:
            data["verify"] = s.client_mtls_verify
        if s.client_mtls_check_hostname is not None:
            data["check_hostname"] = s.client_mtls_check_hostname

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
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.server_ssl_keyfile:
            data["keyfile"] = s.server_ssl_keyfile
        if s.server_ssl_certfile:
            data["certfile"] = s.server_ssl_certfile
        if s.server_ssl_ca_certs:
            data["ca_bundle"] = s.server_ssl_ca_certs
        if s.server_ssl_keyfile_password is not None:
            data["keyfile_password"] = s.server_ssl_keyfile_password
        if s.server_ssl_cert_reqs is not None:
            data["ssl_cert_reqs"] = s.server_ssl_cert_reqs

        if not data:
            return None

        return cls(**data)


class MCPServerConfig(BaseModel):
    """Server-side MCP configuration (plugin running as server).

    Attributes:
        host (str): Server host to bind to.
        port (int): Server port to bind to.
        uds (Optional[str]): Unix domain socket path for streamable HTTP.
        tls (Optional[MCPServerTLSConfig]): Server-side TLS configuration.
    """

    host: str = Field(default="127.0.0.1", description="Server host to bind to")
    port: int = Field(default=8000, description="Server port to bind to")
    uds: Optional[str] = Field(default=None, description="Unix domain socket path for streamable HTTP")
    tls: Optional[MCPServerTLSConfig] = Field(default=None, description="Server-side TLS configuration")

    @field_validator("uds", mode="after")
    @classmethod
    def validate_uds(cls, uds: str | None) -> str | None:
        """Validate the Unix domain socket path for security.

        Args:
            uds: Unix domain socket path.

        Returns:
            The validated canonical uds path or None if none is set.

        Raises:
            ValueError: if uds is empty, not absolute, or parent directory is invalid.
        """
        if uds is None:
            return uds
        if not isinstance(uds, str) or not uds.strip():
            raise ValueError("MCP server uds must be a non-empty string.")

        uds_path = Path(uds).expanduser().resolve()
        if not uds_path.is_absolute():
            raise ValueError(f"MCP server uds path must be absolute: {uds}")

        parent_dir = uds_path.parent
        if not parent_dir.is_dir():
            raise ValueError(f"MCP server uds parent directory does not exist: {parent_dir}")

        # Check parent directory permissions for security
        try:
            parent_mode = parent_dir.stat().st_mode
            # Warn if parent directory is world-writable (o+w = 0o002)
            if parent_mode & 0o002:
                logging.getLogger(__name__).warning(
                    "MCP server uds parent directory %s is world-writable. This may allow unauthorized socket hijacking. Consider using a directory with restricted permissions (e.g., 0o700).",
                    parent_dir,
                )
        except OSError:
            pass  # Best effort - continue if we can't check permissions

        return str(uds_path)

    @model_validator(mode="after")
    def validate_uds_tls(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure TLS is not configured when using a Unix domain socket.

        Returns:
            Self after validation.

        Raises:
            ValueError: if tls is set with uds.
        """
        if self.uds and self.tls:
            raise ValueError("TLS configuration is not supported for Unix domain sockets.")
        return self

    @classmethod
    def from_env(cls) -> Optional["MCPServerConfig"]:
        """Construct server configuration from PLUGINS_SERVER_* environment variables.

        Returns:
            MCPServerConfig instance or None if no environment variables are set.
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.server_host:
            data["host"] = s.server_host
        if s.server_port is not None:
            data["port"] = s.server_port
        if s.server_uds:
            data["uds"] = s.server_uds

        # Check if SSL/TLS is enabled
        if s.server_ssl_enabled:
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
        cmd (Optional[list[str]]): Command + args used to start a STDIO MCP server. Only valid for STDIO type.
        env (Optional[dict[str, str]]): Environment overrides for STDIO server process.
        cwd (Optional[str]): Working directory for STDIO server process.
        uds (Optional[str]): Unix domain socket path for streamable HTTP.
        tls (Optional[MCPClientTLSConfig]): Client-side TLS configuration for mTLS.
    """

    proto: TransportType
    url: Optional[str] = None
    script: Optional[str] = None
    cmd: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    cwd: Optional[str] = None
    uds: Optional[str] = None
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
            ValueError: if the script doesn't exist or isn't executable when required.

        Returns:
            The validated string or None if none is set.
        """
        if script:
            file_path = Path(script).expanduser()
            # Allow relative paths; they are resolved at runtime (optionally using cwd).
            if file_path.is_absolute():
                if not file_path.is_file():
                    raise ValueError(f"MCP server script {script} does not exist.")
                # Allow Python (.py) and shell scripts (.sh). Other files must be executable.
                if file_path.suffix not in {PYTHON_SUFFIX, ".sh"} and not os.access(file_path, os.X_OK):
                    raise ValueError(f"MCP server script {script} must be executable.")
        return script

    @field_validator(CMD, mode="after")
    @classmethod
    def validate_cmd(cls, cmd: list[str] | None) -> list[str] | None:
        """Validate an MCP stdio command.

        Args:
            cmd: the command to be validated.

        Raises:
            ValueError: if cmd is empty or contains empty values.

        Returns:
            The validated command list or None if none is set.
        """
        if cmd is None:
            return cmd
        if not isinstance(cmd, list) or not cmd:
            raise ValueError("MCP stdio cmd must be a non-empty list.")
        if not all(isinstance(part, str) and part.strip() for part in cmd):
            raise ValueError("MCP stdio cmd entries must be non-empty strings.")
        return cmd

    @field_validator(ENV, mode="after")
    @classmethod
    def validate_env(cls, env: dict[str, str] | None) -> dict[str, str] | None:
        """Validate environment overrides for MCP stdio.

        Args:
            env: Environment overrides to set for the stdio plugin process.

        Returns:
            The validated environment dict or None if none is set.

        Raises:
            ValueError: if keys/values are invalid or the dict is empty.
        """
        if env is None:
            return env
        if not isinstance(env, dict) or not env:
            raise ValueError("MCP stdio env must be a non-empty dict.")
        for key, value in env.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("MCP stdio env keys must be non-empty strings.")
            if not isinstance(value, str):
                raise ValueError("MCP stdio env values must be strings.")
        return env

    @field_validator(CWD, mode="after")
    @classmethod
    def validate_cwd(cls, cwd: str | None) -> str | None:
        """Validate the working directory for MCP stdio.

        Args:
            cwd: Working directory for the stdio plugin process.

        Returns:
            The validated canonical cwd path or None if none is set.

        Raises:
            ValueError: if cwd does not exist or is not a directory.
        """
        if not cwd:
            return cwd
        cwd_path = Path(cwd).expanduser().resolve()
        if not cwd_path.is_dir():
            raise ValueError(f"MCP stdio cwd {cwd} does not exist or is not a directory.")
        return str(cwd_path)

    @field_validator(UDS, mode="after")
    @classmethod
    def validate_uds(cls, uds: str | None) -> str | None:
        """Validate a Unix domain socket path for streamable HTTP.

        Args:
            uds: Unix domain socket path.

        Returns:
            The validated canonical uds path or None if none is set.

        Raises:
            ValueError: if uds is empty, not absolute, or parent directory is invalid.
        """
        if uds is None:
            return uds
        if not isinstance(uds, str) or not uds.strip():
            raise ValueError("MCP client uds must be a non-empty string.")

        uds_path = Path(uds).expanduser().resolve()
        if not uds_path.is_absolute():
            raise ValueError(f"MCP client uds path must be absolute: {uds}")

        parent_dir = uds_path.parent
        if not parent_dir.is_dir():
            raise ValueError(f"MCP client uds parent directory does not exist: {parent_dir}")

        # Check parent directory permissions for security
        try:
            parent_mode = parent_dir.stat().st_mode
            # Warn if parent directory is world-writable (o+w = 0o002)
            if parent_mode & 0o002:
                logging.getLogger(__name__).warning(
                    "MCP client uds parent directory %s is world-writable. This may allow unauthorized socket hijacking. Consider using a directory with restricted permissions (e.g., 0o700).",
                    parent_dir,
                )
        except OSError:
            pass  # Best effort - continue if we can't check permissions

        return str(uds_path)

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
        if self.uds and self.tls:
            raise ValueError("TLS configuration is not supported for Unix domain sockets.")
        return self

    @model_validator(mode="after")
    def validate_transport_fields(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure transport-specific fields are only used with matching transports.

        Returns:
            Self after validation.

        Raises:
            ValueError: if fields are incompatible with the selected transport.
        """
        if self.proto == TransportType.STDIO and self.url:
            raise ValueError("URL is only valid for HTTP/SSE transports")
        if self.proto != TransportType.STDIO and (self.script or self.cmd or self.env or self.cwd):
            raise ValueError("script/cmd/env/cwd are only valid for STDIO transport")
        if self.proto != TransportType.STREAMABLEHTTP and self.uds:
            raise ValueError("uds is only valid for STREAMABLEHTTP transport")
        return self


class GRPCClientTLSConfig(MCPTransportTLSConfigBase):
    """Client-side gRPC TLS configuration (gateway connecting to plugin).

    Attributes:
        verify (bool): Whether to verify the remote server certificate.
    """

    verify: bool = Field(default=True, description="Verify the upstream server certificate")

    @classmethod
    def from_env(cls) -> Optional["GRPCClientTLSConfig"]:
        """Construct gRPC client TLS configuration from PLUGINS_GRPC_CLIENT_* environment variables.

        Returns:
            GRPCClientTLSConfig instance or None if no environment variables are set.
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.grpc_client_mtls_certfile:
            data["certfile"] = s.grpc_client_mtls_certfile
        if s.grpc_client_mtls_keyfile:
            data["keyfile"] = s.grpc_client_mtls_keyfile
        if s.grpc_client_mtls_ca_bundle:
            data["ca_bundle"] = s.grpc_client_mtls_ca_bundle
        if s.grpc_client_mtls_keyfile_password is not None:
            data["keyfile_password"] = s.grpc_client_mtls_keyfile_password
        if s.grpc_client_mtls_verify is not None:
            data["verify"] = s.grpc_client_mtls_verify

        if not data:
            return None

        return cls(**data)


class GRPCServerTLSConfig(MCPTransportTLSConfigBase):
    """Server-side gRPC TLS configuration (plugin accepting gateway connections).

    Attributes:
        client_auth (str): Client certificate requirement ('none', 'optional', 'require').
    """

    client_auth: str = Field(default="require", description="Client certificate requirement (none, optional, require)")

    @field_validator("client_auth", mode="after")
    @classmethod
    def validate_client_auth(cls, value: str) -> str:
        """Validate client_auth value.

        Args:
            value: Client auth requirement string.

        Returns:
            Validated client auth string.

        Raises:
            ValueError: If client_auth is not a valid value.
        """
        valid_values = {"none", "optional", "require"}
        if value.lower() not in valid_values:
            raise ValueError(f"client_auth must be one of {valid_values}, got '{value}'")
        return value.lower()

    @classmethod
    def from_env(cls) -> Optional["GRPCServerTLSConfig"]:
        """Construct gRPC server TLS configuration from PLUGINS_GRPC_SERVER_SSL_* environment variables.

        Returns:
            GRPCServerTLSConfig instance or None if no environment variables are set.
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.grpc_server_ssl_keyfile:
            data["keyfile"] = s.grpc_server_ssl_keyfile
        if s.grpc_server_ssl_certfile:
            data["certfile"] = s.grpc_server_ssl_certfile
        if s.grpc_server_ssl_ca_certs:
            data["ca_bundle"] = s.grpc_server_ssl_ca_certs
        if s.grpc_server_ssl_keyfile_password is not None:
            data["keyfile_password"] = s.grpc_server_ssl_keyfile_password
        if s.grpc_server_ssl_client_auth:
            data["client_auth"] = s.grpc_server_ssl_client_auth

        if not data:
            return None

        return cls(**data)


class GRPCClientConfig(BaseModel):
    """Client-side gRPC configuration (gateway connecting to external plugin).

    Attributes:
        target (Optional[str]): The gRPC target address in host:port format.
        uds (Optional[str]): Unix domain socket path (alternative to target).
        tls (Optional[GRPCClientTLSConfig]): Client-side TLS configuration for mTLS.

    Examples:
        >>> # TCP connection
        >>> config = GRPCClientConfig(target="localhost:50051")
        >>> config.get_target()
        'localhost:50051'
        >>> # Unix domain socket connection (path is resolved to canonical form)
        >>> config = GRPCClientConfig(uds="/tmp/grpc-plugin.sock")  # doctest: +SKIP
        >>> config.get_target()  # doctest: +SKIP
        'unix:///tmp/grpc-plugin.sock'
    """

    target: Optional[str] = Field(default=None, description="gRPC target address (host:port)")
    uds: Optional[str] = Field(default=None, description="Unix domain socket path")
    tls: Optional[GRPCClientTLSConfig] = None

    @field_validator("target", mode="after")
    @classmethod
    def validate_target(cls, target: str | None) -> str | None:
        """Validate gRPC target address format.

        Args:
            target: The target address to validate.

        Returns:
            The validated target address.

        Raises:
            ValueError: If target is not in host:port format.
        """
        if target is None:
            return target
        if not target:
            raise ValueError("gRPC target address cannot be empty")
        # Basic validation - should contain host and port
        if ":" not in target:
            raise ValueError(f"gRPC target must be in host:port format, got '{target}'")
        return target

    @field_validator("uds", mode="after")
    @classmethod
    def validate_uds(cls, uds: str | None) -> str | None:
        """Validate Unix domain socket path for gRPC.

        Args:
            uds: Unix domain socket path.

        Returns:
            The validated canonical uds path or None if none is set.

        Raises:
            ValueError: if uds is empty, not absolute, or parent directory is invalid.
        """
        if uds is None:
            return uds
        if not isinstance(uds, str) or not uds.strip():
            raise ValueError("gRPC client uds must be a non-empty string.")

        uds_path = Path(uds).expanduser().resolve()
        if not uds_path.is_absolute():
            raise ValueError(f"gRPC client uds path must be absolute: {uds}")

        parent_dir = uds_path.parent
        if not parent_dir.is_dir():
            raise ValueError(f"gRPC client uds parent directory does not exist: {parent_dir}")

        # Check parent directory permissions for security
        try:
            parent_mode = parent_dir.stat().st_mode
            if parent_mode & 0o002:
                logging.getLogger(__name__).warning(
                    "gRPC client uds parent directory %s is world-writable. Consider using a directory with restricted permissions.",
                    parent_dir,
                )
        except OSError:
            pass

        return str(uds_path)

    @model_validator(mode="after")
    def validate_target_or_uds(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure exactly one of target or uds is configured.

        Returns:
            Self after validation.

        Raises:
            ValueError: If neither or both target and uds are set.
        """
        has_target = self.target is not None
        has_uds = self.uds is not None

        if not has_target and not has_uds:
            raise ValueError("gRPC client must have either 'target' or 'uds' configured")
        if has_target and has_uds:
            raise ValueError("gRPC client cannot have both 'target' and 'uds' configured")
        if has_uds and self.tls:
            raise ValueError("TLS configuration is not supported for Unix domain sockets")
        return self

    def get_target(self) -> str:
        """Get the gRPC target string for channel creation.

        Returns:
            str: The target string, either host:port or unix:///path format.
        """
        if self.uds:
            return f"unix://{self.uds}"
        return self.target or ""


class GRPCServerConfig(BaseModel):
    """Server-side gRPC configuration (plugin running as gRPC server).

    Attributes:
        host (str): Server host to bind to.
        port (int): Server port to bind to.
        uds (Optional[str]): Unix domain socket path (alternative to host:port).
        tls (Optional[GRPCServerTLSConfig]): Server-side TLS configuration.

    Examples:
        >>> # TCP binding
        >>> config = GRPCServerConfig(host="0.0.0.0", port=50051)
        >>> config.get_bind_address()
        '0.0.0.0:50051'
        >>> # Unix domain socket binding (path is resolved to canonical form)
        >>> config = GRPCServerConfig(uds="/tmp/grpc-plugin.sock")  # doctest: +SKIP
        >>> config.get_bind_address()  # doctest: +SKIP
        'unix:///tmp/grpc-plugin.sock'
    """

    host: str = Field(default="127.0.0.1", description="Server host to bind to")
    port: int = Field(default=50051, description="Server port to bind to")
    uds: Optional[str] = Field(default=None, description="Unix domain socket path")
    tls: Optional[GRPCServerTLSConfig] = Field(default=None, description="Server-side TLS configuration")

    @field_validator("uds", mode="after")
    @classmethod
    def validate_uds(cls, uds: str | None) -> str | None:
        """Validate Unix domain socket path for gRPC server.

        Args:
            uds: Unix domain socket path.

        Returns:
            The validated canonical uds path or None if none is set.

        Raises:
            ValueError: if uds is empty, not absolute, or parent directory is invalid.
        """
        if uds is None:
            return uds
        if not isinstance(uds, str) or not uds.strip():
            raise ValueError("gRPC server uds must be a non-empty string.")

        uds_path = Path(uds).expanduser().resolve()
        if not uds_path.is_absolute():
            raise ValueError(f"gRPC server uds path must be absolute: {uds}")

        parent_dir = uds_path.parent
        if not parent_dir.is_dir():
            raise ValueError(f"gRPC server uds parent directory does not exist: {parent_dir}")

        # Check parent directory permissions for security
        try:
            parent_mode = parent_dir.stat().st_mode
            if parent_mode & 0o002:
                logging.getLogger(__name__).warning(
                    "gRPC server uds parent directory %s is world-writable. Consider using a directory with restricted permissions.",
                    parent_dir,
                )
        except OSError:
            pass

        return str(uds_path)

    @model_validator(mode="after")
    def validate_uds_tls(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Ensure TLS is not configured when using a Unix domain socket.

        Returns:
            Self after validation.

        Raises:
            ValueError: if tls is set with uds.
        """
        if self.uds and self.tls:
            raise ValueError("TLS configuration is not supported for Unix domain sockets")
        return self

    def get_bind_address(self) -> str:
        """Get the gRPC bind address string.

        Returns:
            str: The bind address, either host:port or unix:///path format.
        """
        if self.uds:
            return f"unix://{self.uds}"
        return f"{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> Optional["GRPCServerConfig"]:
        """Construct gRPC server configuration from PLUGINS_GRPC_SERVER_* environment variables.

        Returns:
            GRPCServerConfig instance or None if no environment variables are set.
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.grpc_server_host:
            data["host"] = s.grpc_server_host
        if s.grpc_server_port is not None:
            data["port"] = s.grpc_server_port
        if s.grpc_server_uds:
            data["uds"] = s.grpc_server_uds

        # Check if SSL/TLS is enabled
        if s.grpc_server_ssl_enabled:
            tls_config = GRPCServerTLSConfig.from_env()
            if tls_config:
                data["tls"] = tls_config

        if not data:
            return None

        return cls(**data)


class UnixSocketClientConfig(BaseModel):
    """Client-side Unix socket configuration (gateway connecting to external plugin).

    Attributes:
        path (str): Path to the Unix domain socket file.
        reconnect_attempts (int): Number of reconnection attempts on failure.
        reconnect_delay (float): Base delay between reconnection attempts (with exponential backoff).
        timeout (float): Timeout for read operations in seconds.

    Examples:
        >>> config = UnixSocketClientConfig(path="/tmp/plugin.sock")
        >>> config.path
        '/tmp/plugin.sock'
        >>> config.reconnect_attempts
        3
    """

    path: str = Field(..., description="Path to the Unix domain socket")
    reconnect_attempts: int = Field(default=3, description="Number of reconnection attempts")
    reconnect_delay: float = Field(default=0.1, description="Base delay between reconnection attempts (seconds)")
    timeout: float = Field(default=30.0, description="Read timeout in seconds")

    @field_validator("path", mode="after")
    @classmethod
    def validate_path(cls, path: str) -> str:
        """Validate Unix socket path.

        Args:
            path: The socket path to validate.

        Returns:
            The validated path.

        Raises:
            ValueError: If path is empty or invalid.
        """
        if not path:
            raise ValueError("Unix socket path cannot be empty")
        if not path.startswith("/"):
            raise ValueError(f"Unix socket path must be absolute, got '{path}'")
        return path


class UnixSocketServerConfig(BaseModel):
    """Server-side Unix socket configuration (plugin running as Unix socket server).

    Attributes:
        path (str): Path to the Unix domain socket file.

    Examples:
        >>> config = UnixSocketServerConfig(path="/tmp/plugin.sock")
        >>> config.path
        '/tmp/plugin.sock'
    """

    path: str = Field(default="/tmp/mcpgateway-plugins.sock", description="Path to the Unix domain socket")  # nosec B108 - configurable default

    @classmethod
    def from_env(cls) -> Optional["UnixSocketServerConfig"]:
        """Construct Unix socket server configuration from environment variables.

        Returns:
            UnixSocketServerConfig instance or None if no environment variables are set.
        """
        s = get_settings()
        data: dict[str, Any] = {}

        if s.unix_socket_path:
            data["path"] = s.unix_socket_path

        if not data:
            return None

        return cls(**data)


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
        grpc (Optional[GRPCClientConfig]): Client-side gRPC configuration (gateway connecting to plugin).
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
    grpc: Optional[GRPCClientConfig] = None
    unix_socket: Optional[UnixSocketClientConfig] = None

    @model_validator(mode="after")
    def check_url_or_script_filled(self) -> Self:  # pylint: disable=bad-classmethod-argument
        """Checks to see that at least one of url or script are set depending on MCP server configuration.

        Raises:
            ValueError: if the script/cmd attribute is not defined with STDIO set, or the URL not defined with HTTP transports.

        Returns:
            The model after validation.
        """
        if not self.mcp:
            return self
        if self.mcp.proto == TransportType.STDIO and not (self.mcp.script or self.mcp.cmd):
            raise ValueError(f"Plugin {self.name} has transport type set to STDIO but no script/cmd value")
        if self.mcp.proto == TransportType.STDIO and self.mcp.script and self.mcp.cmd:
            raise ValueError(f"Plugin {self.name} must set either script or cmd for STDIO, not both")
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

        # External plugins must have exactly one transport configured (mcp, grpc, or unix_socket)
        if self.kind == EXTERNAL_PLUGIN_TYPE:
            has_mcp = self.mcp is not None
            has_grpc = self.grpc is not None
            has_unix = self.unix_socket is not None
            transport_count = sum([has_mcp, has_grpc, has_unix])

            if transport_count == 0:
                raise ValueError(f"External plugin {self.name} must have 'mcp', 'grpc', or 'unix_socket' section configured")
            if transport_count > 1:
                raise ValueError(f"External plugin {self.name} can only have one transport configured (mcp, grpc, or unix_socket)")

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
        include_user_info (bool): if enabled user info is injected in plugin context
    """

    parallel_execution_within_band: bool = False
    plugin_timeout: int = 30
    fail_on_plugin_error: bool = False
    enable_plugin_api: bool = False
    plugin_health_check_interval: int = 60
    include_user_info: bool = False


class Config(BaseModel):
    """Configurations for plugins.

    Attributes:
        plugins (Optional[list[PluginConfig]]): the list of plugins to enable.
        plugin_dirs (list[str]): The directories in which to look for plugins.
        plugin_settings (PluginSettings): global settings for plugins.
        server_settings (Optional[MCPServerConfig]): Server-side MCP configuration (when plugins run as server).
        grpc_server_settings (Optional[GRPCServerConfig]): Server-side gRPC configuration (when plugins run as gRPC server).
        unix_socket_server_settings (Optional[UnixSocketServerConfig]): Server-side Unix socket configuration.
    """

    plugins: Optional[list[PluginConfig]] = []
    plugin_dirs: list[str] = []
    plugin_settings: PluginSettings
    server_settings: Optional[MCPServerConfig] = None
    grpc_server_settings: Optional[GRPCServerConfig] = None
    unix_socket_server_settings: Optional[UnixSocketServerConfig] = None


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
    user: Optional[Union[str, dict[str, Any]]] = None
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
