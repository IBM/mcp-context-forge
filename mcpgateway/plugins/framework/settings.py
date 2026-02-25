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
import logging
import os
from typing import Any, Literal

# Third-Party
from pydantic import AliasChoices, Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _empty_string_to_none(value: Any) -> Any:
    """Treat empty optional env vars as unset (None).

    Shared validator for optional fields that may arrive as empty strings
    from the environment.  Used by ``@field_validator(..., mode="before")``
    across multiple lightweight settings classes.

    Args:
        value: The raw value from the environment variable.

    Returns:
        None if the value is an empty string, otherwise the original value.
    """
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class PluginsSettings(BaseSettings):
    """Plugin framework configuration.

    All settings can be overridden via environment variables with the PLUGINS_ prefix.
    For example: PLUGINS_ENABLED=true, PLUGINS_PLUGIN_TIMEOUT=60, PLUGINS_SKIP_SSL_VERIFY=true
    """

    enabled: bool = Field(default=False, description="Enable the plugin framework")
    default_hook_policy: Literal["allow", "deny"] = Field(
        default="allow",
        description=(
            "Default behavior for hooks without an explicit policy: 'allow' accepts all modifications"
            " (backwards compatible), 'deny' rejects all. Standard hooks always have explicit policies;"
            " this only affects custom hook types. Set to 'deny' for stricter production environments."
        ),
    )
    config_file: str = Field(default="plugins/config.yaml", description="Path to main plugins configuration file")
    plugin_timeout: int = Field(default=30, description="Plugin execution timeout in seconds")
    log_level: str = Field(default="INFO", description="Logging level for plugin framework components")
    skip_ssl_verify: bool = Field(
        default=False,
        description="Skip SSL certificate verification for plugin HTTP requests. WARNING: Only enable in dev environments with self-signed certificates.",
    )
    ssrf_protection_enabled: bool = Field(
        default=True,
        description=(
            "Enable SSRF protection for plugin endpoint URLs. Blocks private/reserved IP ranges"
            " (10.x, 172.16.x, 192.168.x, 127.x, 169.254.x). Disable for development or sidecar"
            " plugin configurations that use private IPs."
        ),
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
    client_mtls_keyfile_password: SecretStr | None = Field(default=None, description="Password for encrypted client private key")
    client_mtls_verify: bool | None = Field(default=None, description="Verify the upstream server certificate")
    client_mtls_check_hostname: bool | None = Field(default=None, description="Enable hostname verification")

    # MCP server SSL settings
    server_ssl_keyfile: str | None = Field(default=None, description="Path to PEM server private key")
    server_ssl_certfile: str | None = Field(default=None, description="Path to PEM server certificate")
    server_ssl_ca_certs: str | None = Field(default=None, description="Path to CA certificates for client verification")
    server_ssl_keyfile_password: SecretStr | None = Field(default=None, description="Password for encrypted server private key")
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
    grpc_client_mtls_keyfile_password: SecretStr | None = Field(default=None, description="Password for encrypted gRPC client private key")
    grpc_client_mtls_verify: bool | None = Field(default=None, description="Verify the gRPC upstream server certificate")

    # gRPC server SSL settings
    grpc_server_ssl_keyfile: str | None = Field(default=None, description="Path to PEM gRPC server private key")
    grpc_server_ssl_certfile: str | None = Field(default=None, description="Path to PEM gRPC server certificate")
    grpc_server_ssl_ca_certs: str | None = Field(default=None, description="Path to CA certificates for gRPC client verification")
    grpc_server_ssl_keyfile_password: SecretStr | None = Field(default=None, description="Password for encrypted gRPC server private key")
    grpc_server_ssl_client_auth: str | None = Field(default=None, description="gRPC client certificate requirement (none, optional, require)")

    # gRPC server settings
    grpc_server_host: str | None = Field(default=None, description="gRPC server host to bind to")
    grpc_server_port: int | None = Field(default=None, description="gRPC server port to bind to")
    grpc_server_uds: str | None = Field(default=None, description="Unix domain socket path for gRPC server")
    grpc_server_ssl_enabled: bool | None = Field(default=None, description="Enable SSL/TLS for the gRPC server")

    # Unix socket settings
    unix_socket_path: str | None = Field(default=None, description="Path to the Unix domain socket", validation_alias=AliasChoices("PLUGINS_UNIX_SOCKET_PATH", "UNIX_SOCKET_PATH"))

    @field_validator(
        "client_mtls_verify",
        "client_mtls_check_hostname",
        "server_ssl_cert_reqs",
        "server_port",
        "server_ssl_enabled",
        "grpc_client_mtls_verify",
        "grpc_server_port",
        "grpc_server_ssl_enabled",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        """Delegate to shared validator."""
        return _empty_string_to_none(value)

    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsEnabledSettings(BaseSettings):
    """Lightweight settings model for reading PLUGINS_ENABLED only."""

    enabled: bool = False
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsConfigPathSettings(BaseSettings):
    """Lightweight settings model for reading PLUGINS_CONFIG_PATH only."""

    config_path: str | None = None
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsStartupSettings(BaseSettings):
    """Lightweight settings for fields read during gateway startup.

    Reads only ``config_file`` and ``plugin_timeout`` so that malformed
    unrelated plugin env vars (e.g. ``PLUGINS_SERVER_PORT=abc``) do not
    prevent the gateway from booting.
    """

    config_file: str = Field(default="plugins/config.yaml")
    plugin_timeout: int = 30
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsPolicySettings(BaseSettings):
    """Lightweight settings model for reading default hook policy only."""

    default_hook_policy: Literal["allow", "deny"] = "allow"
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsSsrfSettings(BaseSettings):
    """Lightweight settings model for reading SSRF protection flag only."""

    ssrf_protection_enabled: bool = True
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsTransportSettings(BaseSettings):
    """Lightweight settings for transport type and Unix socket path."""

    transport: str | None = None
    unix_socket_path: str | None = Field(default=None, validation_alias=AliasChoices("UNIX_SOCKET_PATH", "PLUGINS_UNIX_SOCKET_PATH"))
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsClientMtlsSettings(BaseSettings):
    """Lightweight settings for MCP client mTLS configuration."""

    client_mtls_certfile: str | None = None
    client_mtls_keyfile: str | None = None
    client_mtls_ca_bundle: str | None = None
    client_mtls_keyfile_password: SecretStr | None = None
    client_mtls_verify: bool | None = None
    client_mtls_check_hostname: bool | None = None

    @field_validator("client_mtls_verify", "client_mtls_check_hostname", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        """Delegate to shared validator."""
        return _empty_string_to_none(value)

    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsMcpServerSettings(BaseSettings):
    """Lightweight settings for MCP server configuration."""

    server_ssl_keyfile: str | None = None
    server_ssl_certfile: str | None = None
    server_ssl_ca_certs: str | None = None
    server_ssl_keyfile_password: SecretStr | None = None
    server_ssl_cert_reqs: int | None = None
    server_host: str | None = None
    server_port: int | None = None
    server_uds: str | None = None
    server_ssl_enabled: bool | None = None

    @field_validator("server_ssl_cert_reqs", "server_port", "server_ssl_enabled", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        """Delegate to shared validator."""
        return _empty_string_to_none(value)

    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsGrpcClientMtlsSettings(BaseSettings):
    """Lightweight settings for gRPC client mTLS configuration."""

    grpc_client_mtls_certfile: str | None = None
    grpc_client_mtls_keyfile: str | None = None
    grpc_client_mtls_ca_bundle: str | None = None
    grpc_client_mtls_keyfile_password: SecretStr | None = None
    grpc_client_mtls_verify: bool | None = None

    @field_validator("grpc_client_mtls_verify", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        """Delegate to shared validator."""
        return _empty_string_to_none(value)

    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsHttpClientSettings(BaseSettings):
    """Lightweight settings for HTTP client (httpx) configuration."""

    skip_ssl_verify: bool = False
    httpx_max_connections: int = 200
    httpx_max_keepalive_connections: int = 100
    httpx_keepalive_expiry: float = 30.0
    httpx_connect_timeout: float = 5.0
    httpx_read_timeout: float = 120.0
    httpx_write_timeout: float = 30.0
    httpx_pool_timeout: float = 10.0
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsCliSettings(BaseSettings):
    """Lightweight settings for mcpplugins CLI configuration."""

    cli_completion: bool = False
    cli_markup_mode: Literal["markdown", "rich", "disabled"] | None = None
    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


class PluginsGrpcServerSettings(BaseSettings):
    """Lightweight settings for gRPC server configuration."""

    grpc_server_ssl_keyfile: str | None = None
    grpc_server_ssl_certfile: str | None = None
    grpc_server_ssl_ca_certs: str | None = None
    grpc_server_ssl_keyfile_password: SecretStr | None = None
    grpc_server_ssl_client_auth: str | None = None
    grpc_server_host: str | None = None
    grpc_server_port: int | None = None
    grpc_server_uds: str | None = None
    grpc_server_ssl_enabled: bool | None = None

    @field_validator("grpc_server_port", "grpc_server_ssl_enabled", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        """Delegate to shared validator."""
        return _empty_string_to_none(value)

    model_config = SettingsConfigDict(env_prefix="PLUGINS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> PluginsSettings:
    """Get cached plugins settings instance.

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
    return PluginsSettings()


@lru_cache()
def get_enabled_settings() -> PluginsEnabledSettings:
    """Get cached lightweight enabled flag settings instance.

    Returns:
        PluginsEnabledSettings: A cached instance.
    """
    return PluginsEnabledSettings()


@lru_cache()
def get_startup_settings() -> PluginsStartupSettings:
    """Get cached lightweight startup settings (config_file, plugin_timeout).

    Returns:
        PluginsStartupSettings: A cached instance.
    """
    return PluginsStartupSettings()


@lru_cache()
def get_config_path_settings() -> PluginsConfigPathSettings:
    """Get cached lightweight config-path settings instance.

    Returns:
        PluginsConfigPathSettings: A cached instance.
    """
    return PluginsConfigPathSettings()


@lru_cache()
def get_policy_settings() -> PluginsPolicySettings:
    """Get cached lightweight policy settings instance.

    Returns:
        PluginsPolicySettings: A cached instance.
    """
    return PluginsPolicySettings()


@lru_cache()
def get_ssrf_settings() -> PluginsSsrfSettings:
    """Get cached lightweight SSRF protection settings instance.

    Returns:
        PluginsSsrfSettings: A cached instance.
    """
    return PluginsSsrfSettings()


@lru_cache()
def get_transport_settings() -> PluginsTransportSettings:
    """Get cached lightweight transport settings instance.

    Returns:
        PluginsTransportSettings: A cached instance.
    """
    return PluginsTransportSettings()


@lru_cache()
def get_client_mtls_settings() -> PluginsClientMtlsSettings:
    """Get cached lightweight MCP client mTLS settings instance.

    Returns:
        PluginsClientMtlsSettings: A cached instance.
    """
    return PluginsClientMtlsSettings()


@lru_cache()
def get_mcp_server_settings() -> PluginsMcpServerSettings:
    """Get cached lightweight MCP server settings instance.

    Returns:
        PluginsMcpServerSettings: A cached instance.
    """
    return PluginsMcpServerSettings()


@lru_cache()
def get_grpc_client_mtls_settings() -> PluginsGrpcClientMtlsSettings:
    """Get cached lightweight gRPC client mTLS settings instance.

    Returns:
        PluginsGrpcClientMtlsSettings: A cached instance.
    """
    return PluginsGrpcClientMtlsSettings()


@lru_cache()
def get_http_client_settings() -> PluginsHttpClientSettings:
    """Get cached lightweight HTTP client settings instance.

    Returns:
        PluginsHttpClientSettings: A cached instance.
    """
    return PluginsHttpClientSettings()


@lru_cache()
def get_cli_settings() -> PluginsCliSettings:
    """Get cached lightweight CLI settings instance.

    Returns:
        PluginsCliSettings: A cached instance.
    """
    return PluginsCliSettings()


@lru_cache()
def get_grpc_server_settings() -> PluginsGrpcServerSettings:
    """Get cached lightweight gRPC server settings instance.

    Returns:
        PluginsGrpcServerSettings: A cached instance.
    """
    return PluginsGrpcServerSettings()


class LazySettingsWrapper:
    """Lazily initialize plugins settings singleton on getattr."""

    @staticmethod
    def _parse_bool(value: str) -> bool:
        """Parse common truthy string values.

        Args:
            value: The string value to parse.

        Returns:
            True if the value represents a truthy string.
        """
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @property
    def enabled(self) -> bool:
        """Access plugin enabled flag with env override support.

        Returns:
            True if plugin framework is enabled.
        """
        env_flag = os.getenv("PLUGINS_ENABLED")
        if env_flag is not None:
            return self._parse_bool(env_flag)
        return get_enabled_settings().enabled

    @property
    def config_file(self) -> str:
        """Access config_file without validating full plugin settings.

        Returns:
            The plugin configuration file path.
        """
        return get_startup_settings().config_file

    @property
    def plugin_timeout(self) -> int:
        """Access plugin_timeout without validating full plugin settings.

        Returns:
            The plugin execution timeout in seconds.
        """
        return get_startup_settings().plugin_timeout

    @property
    def config_path(self) -> str | None:
        """Access PLUGINS_CONFIG_PATH without validating full plugin settings.

        Returns:
            The config path or None if unset.
        """
        return get_config_path_settings().config_path

    @property
    def default_hook_policy(self) -> Literal["allow", "deny"]:
        """Access default hook policy without validating full plugin settings.

        Returns:
            The default hook policy string.
        """
        return get_policy_settings().default_hook_policy

    @property
    def ssrf_protection_enabled(self) -> bool:
        """Access SSRF protection flag without validating full plugin settings.

        Returns:
            True if SSRF protection is enabled.
        """
        return get_ssrf_settings().ssrf_protection_enabled

    @property
    def transport(self) -> str | None:
        """Access transport type without validating full plugin settings.

        Returns:
            The transport type or None if unset.
        """
        return get_transport_settings().transport

    @property
    def unix_socket_path(self) -> str | None:
        """Access Unix socket path without validating full plugin settings.

        Returns:
            The Unix socket path or None if unset.
        """
        return get_transport_settings().unix_socket_path

    @property
    def cli_completion(self) -> bool:
        """Access CLI completion flag without validating full plugin settings.

        Returns:
            True if CLI completion is enabled.
        """
        return get_cli_settings().cli_completion

    @property
    def cli_markup_mode(self) -> Literal["markdown", "rich", "disabled"] | None:
        """Access CLI markup mode without validating full plugin settings.

        Returns:
            The CLI markup mode or None if unset.
        """
        return get_cli_settings().cli_markup_mode

    @staticmethod
    def cache_clear() -> None:
        """Clear the cached settings instance so the next access re-reads from env."""
        get_settings.cache_clear()
        get_enabled_settings.cache_clear()
        get_startup_settings.cache_clear()
        get_config_path_settings.cache_clear()
        get_policy_settings.cache_clear()
        get_ssrf_settings.cache_clear()
        get_transport_settings.cache_clear()
        get_client_mtls_settings.cache_clear()
        get_mcp_server_settings.cache_clear()
        get_http_client_settings.cache_clear()
        get_cli_settings.cache_clear()
        get_grpc_client_mtls_settings.cache_clear()
        get_grpc_server_settings.cache_clear()

    def __getattr__(self, key: str) -> Any:
        """Get the real settings object and forward to it

        Args:
            key: The key to fetch from settings

        Returns:
            Any: The value of the attribute on the settings
        """

        return getattr(get_settings(), key)


settings = LazySettingsWrapper()
