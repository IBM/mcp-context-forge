# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/settings.py

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Plugin framework configuration.

Self-contained settings for the plugin framework, eliminating the
dependency on mcpgateway.config.settings.
"""

# Standard
from functools import lru_cache
import os
from typing import Any, Literal

# Third-Party
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PluginsSettings(BaseSettings):
    """Plugin framework configuration.

    All settings can be overridden via environment variables with the PLUGINS_ prefix.
    For example: PLUGINS_ENABLED=true, PLUGINS_PLUGIN_TIMEOUT=60, PLUGINS_SKIP_SSL_VERIFY=true
    """

    enabled: bool = Field(default=False, description="Enable the plugin framework")
    config_file: str = Field(default="plugins/config.yaml", description="Path to main plugins configuration file", validation_alias=AliasChoices("PLUGIN_CONFIG_FILE", "PLUGINS_CONFIG_FILE"))
    plugin_timeout: int = Field(default=30, description="Plugin execution timeout in seconds")
    log_level: str = Field(default="INFO", description="Logging level for plugin framework components")
    skip_ssl_verify: bool = Field(
        default=False,
        description="Skip SSL certificate verification for plugin HTTP requests. WARNING: Only enable in dev environments with self-signed certificates.",
    )

    # HTTP client settings
    httpx_max_connections: int = Field(default=200, description="Maximum total concurrent HTTP connections for plugin requests")
    httpx_max_keepalive_connections: int = Field(default=100, description="Maximum idle keepalive connections to retain (typically 50%% of max_connections)")
    httpx_keepalive_expiry: float = Field(default=30.0, description="Seconds before idle keepalive connections are closed")
    httpx_connect_timeout: float = Field(default=5.0, description="Timeout in seconds for establishing new connections (5s for LAN, increase for WAN)")
    httpx_read_timeout: float = Field(default=120.0, description="Timeout in seconds for reading response data (set high for slow MCP tool calls)")
    httpx_write_timeout: float = Field(default=30.0, description="Timeout in seconds for writing request data")
    httpx_pool_timeout: float = Field(default=10.0, description="Timeout in seconds waiting for a connection from the pool (fail fast on exhaustion)")

    # CLI settings
    cli_completion: bool = Field(default=False, description="Enable shell auto-completion for the mcpplugins CLI")
    cli_markup_mode: Literal["markdown", "rich", "disabled"] | None = Field(default=None, description="Markup renderer for CLI output (rich, markdown, or disabled)")

    # MCP client mTLS settings
    client_mtls_certfile: str | None = Field(default=None, description="Path to PEM client certificate for mTLS")
    client_mtls_keyfile: str | None = Field(default=None, description="Path to PEM client private key for mTLS")
    client_mtls_ca_bundle: str | None = Field(default=None, description="Path to CA bundle for client certificate verification")
    client_mtls_keyfile_password: str | None = Field(default=None, description="Password for encrypted client private key")
    client_mtls_verify: bool | None = Field(default=None, description="Verify the upstream server certificate")
    client_mtls_check_hostname: bool | None = Field(default=None, description="Enable hostname verification")

    # MCP server SSL settings
    server_ssl_keyfile: str | None = Field(default=None, description="Path to PEM server private key")
    server_ssl_certfile: str | None = Field(default=None, description="Path to PEM server certificate")
    server_ssl_ca_certs: str | None = Field(default=None, description="Path to CA certificates for client verification")
    server_ssl_keyfile_password: str | None = Field(default=None, description="Password for encrypted server private key")
    server_ssl_cert_reqs: int | None = Field(default=None, description="Client certificate requirement (0=NONE, 1=OPTIONAL, 2=REQUIRED)")

    # MCP server settings
    server_host: str | None = Field(default=None, description="MCP server host to bind to")
    server_port: int | None = Field(default=None, description="MCP server port to bind to")
    server_uds: str | None = Field(default=None, description="Unix domain socket path for MCP streamable HTTP")
    server_ssl_enabled: bool | None = Field(default=None, description="Enable SSL/TLS for the MCP server")

    # MCP runtime settings
    config_path: str | None = Field(default=None, description="Path to plugin configuration file for external servers")
    transport: str | None = Field(default=None, description="Transport type for external MCP server (http, stdio)")

    # gRPC client mTLS settings
    grpc_client_mtls_certfile: str | None = Field(default=None, description="Path to PEM client certificate for gRPC mTLS")
    grpc_client_mtls_keyfile: str | None = Field(default=None, description="Path to PEM client private key for gRPC mTLS")
    grpc_client_mtls_ca_bundle: str | None = Field(default=None, description="Path to CA bundle for gRPC client verification")
    grpc_client_mtls_keyfile_password: str | None = Field(default=None, description="Password for encrypted gRPC client private key")
    grpc_client_mtls_verify: bool | None = Field(default=None, description="Verify the gRPC upstream server certificate")

    # gRPC server SSL settings
    grpc_server_ssl_keyfile: str | None = Field(default=None, description="Path to PEM gRPC server private key")
    grpc_server_ssl_certfile: str | None = Field(default=None, description="Path to PEM gRPC server certificate")
    grpc_server_ssl_ca_certs: str | None = Field(default=None, description="Path to CA certificates for gRPC client verification")
    grpc_server_ssl_keyfile_password: str | None = Field(default=None, description="Password for encrypted gRPC server private key")
    grpc_server_ssl_client_auth: str | None = Field(default=None, description="gRPC client certificate requirement (none, optional, require)")

    # gRPC server settings
    grpc_server_host: str | None = Field(default=None, description="gRPC server host to bind to")
    grpc_server_port: int | None = Field(default=None, description="gRPC server port to bind to")
    grpc_server_uds: str | None = Field(default=None, description="Unix domain socket path for gRPC server")
    grpc_server_ssl_enabled: bool | None = Field(default=None, description="Enable SSL/TLS for the gRPC server")

    # Unix socket settings
    unix_socket_path: str | None = Field(default=None, description="Path to the Unix domain socket", validation_alias=AliasChoices("UNIX_SOCKET_PATH", "PLUGINS_UNIX_SOCKET_PATH"))

    model_config = SettingsConfigDict(env_prefix="PLUGINS_")


@lru_cache()
def get_settings(**kwargs: Any) -> PluginsSettings:
    """Get cached plugins settings instance.

    Args:
        **kwargs: Keyword arguments to pass to the PluginsSettings setup.

    Returns:
        PluginsSettings: A cached instance of the PluginsSettings class.

    Examples:
        >>> settings = get_settings()
        >>> isinstance(settings, PluginsSettings)
        True
        >>> # Second call returns the same cached instance
        >>> settings2 = get_settings()
        >>> settings is settings2
        True
    """
    # Instantiate a fresh Pydantic PluginsSettings object,
    # loading from env vars or .env exactly once.
    return PluginsSettings(**kwargs)


class LazySettingsWrapper:
    """Lazily initialize plugins settings singleton on getattr with override support."""

    @property
    def enabled(self) -> bool:
        """Access plugin enabled flag with env override support.

        Returns:
            True if plugin framework is enabled.
        """
        env_flag = os.getenv("PLUGINS_ENABLED")
        if env_flag is not None:
            return env_flag.strip().lower() in {"1", "true", "yes", "on"}
        return get_settings().enabled

    @staticmethod
    def cache_clear() -> None:
        """Clear the cached settings instance so the next access re-reads from env."""
        get_settings.cache_clear()

    def __getattr__(self, key: str) -> Any:
        """Get the real settings object and forward to it

        Args:
            key: The key to fetch from settings

        Returns:
            Any: The value of the attribute on the settings
        """

        return getattr(get_settings(), key)


settings = LazySettingsWrapper()
