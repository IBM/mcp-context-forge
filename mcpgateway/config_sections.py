# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/config_sections.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared settings contracts for gateway and standalone entry points.
"""

# Standard
from typing import Any, Callable, Literal

# Third-Party
from pydantic import AliasChoices, Field, field_validator, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class EnvironmentSettings(BaseSettings):
    """Load validated configuration from environment variables and .env files."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")


class ListenerEnvironmentSettings(EnvironmentSettings):
    """Normalize canonical and legacy listener aliases within each settings source."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[Any, ...]:
        """Normalize listener aliases within each source before merging sources.

        Args:
            settings_cls: Settings model being initialized.
            init_settings: Explicit constructor configuration.
            env_settings: Process environment configuration.
            dotenv_settings: Environment file configuration.
            file_secret_settings: File secret configuration.

        Returns:
            Sources in descending priority, with listener aliases normalized.
        """
        del cls, settings_cls

        def normalize(source: PydanticBaseSettingsSource) -> Callable[[], dict[str, Any]]:
            """Wrap one source with canonical listener keys."""

            def read() -> dict[str, Any]:
                """Read one source and normalize listener keys."""
                values = source()
                for canonical, legacy in (("HOST", "MCG_HOST"), ("PORT", "MCG_PORT")):
                    for alias in (canonical, legacy, canonical.lower()):
                        if alias in values:
                            value = values[alias]
                            for key in (canonical, legacy, canonical.lower()):
                                values.pop(key, None)
                            values[canonical.lower()] = value
                            break
                return values

            return read

        return tuple(normalize(source) for source in (init_settings, env_settings, dotenv_settings, file_secret_settings))


class ListenerHostSettings(ListenerEnvironmentSettings):
    """Resolve the listener host independently of unused port configuration."""

    host: str = Field(default="127.0.0.1", min_length=1, validation_alias=AliasChoices("host", "HOST", "MCG_HOST"), description="Nonempty listener bind address (HOST; legacy alias MCG_HOST).")


class ListenerPortSettings(ListenerEnvironmentSettings):
    """Resolve a configured TCP port independently of unused host configuration."""

    port: PositiveInt = Field(default=4444, ge=1, le=65535, validation_alias=AliasChoices("port", "PORT", "MCG_PORT"), description="Listener TCP port (PORT; legacy alias MCG_PORT).")


class ListenerSettings(ListenerHostSettings, ListenerPortSettings):
    """Configure gateway listener addresses through shared field contracts."""


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingSettings(EnvironmentSettings):
    """Configure gateway logging with case-insensitive levels."""

    log_level: LogLevel = Field(default="ERROR", description="Log verbosity selected by LOG_LEVEL.")

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """
        Normalize and validate the log level value.

        Ensures that the input string matches one of the allowed log levels,
        case-insensitively. The value is uppercased before validation so that
        "debug", "Debug", etc. are all accepted as "DEBUG".

        Args:
            v (str): The log level string provided via configuration or environment.

        Returns:
            str: The validated and normalized (uppercase) log level.

        Raises:
            ValueError: If the provided value is not one of
                {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}.
        """
        del cls
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_up = v.upper()
        if v_up not in allowed:
            raise ValueError(f"Invalid log_level: {v}")
        return v_up


class DatabaseSettings(LoggingSettings):
    """Configure database connections and standalone readiness probes."""

    database_url: str = Field(
        default="sqlite:///./mcp.db",
        description="Database connection URL. Supports SQLite and PostgreSQL, including options for a custom search_path.",
    )
    db_wait_max_tries: int = Field(default=30, description="Database readiness attempts (DB_WAIT_MAX_TRIES).")
    db_wait_interval: float = Field(default=2, description="Initial database readiness retry delay in seconds (DB_WAIT_INTERVAL).")
    db_connect_timeout: int = Field(default=2, description="Database readiness connection timeout in seconds (DB_CONNECT_TIMEOUT).")
    db_max_backoff_seconds: float = Field(default=30, description="Database retry backoff cap in seconds (DB_MAX_BACKOFF_SECONDS).")
    sqlalchemy_echo: bool = Field(default=False, description="Emit SQLAlchemy statement logs (SQLALCHEMY_ECHO).")

    @field_validator("sqlalchemy_echo", mode="before")
    @classmethod
    def parse_sqlalchemy_echo(cls, value: Any) -> Any:
        """Preserve legacy string parsing and explicit boolean values.

        Args:
            value: Configured SQL logging value.

        Returns:
            True for legacy truthy strings, otherwise False for strings or the original value.
        """
        del cls
        return value.lower() in {"true", "1", "yes"} if isinstance(value, str) else value


class RedisSettings(EnvironmentSettings):
    """Configure Redis connections and retry intervals."""

    redis_url: str | None = Field(default="redis://localhost:6379/0", description="Redis connection URL (REDIS_URL).")
    redis_max_retries: int = Field(default=30, description="Redis readiness attempts (REDIS_MAX_RETRIES).")
    redis_retry_interval_ms: int = Field(default=2000, description="Initial Redis retry delay in milliseconds (REDIS_RETRY_INTERVAL_MS).")
    redis_max_backoff_seconds: float = Field(default=30, description="Redis retry backoff cap in seconds (REDIS_MAX_BACKOFF_SECONDS).")


class RedisReadinessSettings(RedisSettings, LoggingSettings):
    """Preserve the Redis readiness command's INFO logging default."""

    log_level: LogLevel = Field(default="INFO", description="Log verbosity selected by LOG_LEVEL.")


class TransportSettings(EnvironmentSettings):
    """Configure standalone transport request headers."""

    forge_content_type: str = Field(default="application/json", description="Transport request content type (FORGE_CONTENT_TYPE).")


class ClientAuthSettings(EnvironmentSettings):
    """Configure credentials used by gateway CLI clients."""

    mcpgateway_bearer_token: SecretStr | None = Field(default=None, description="Bearer token used by CLI clients (MCPGATEWAY_BEARER_TOKEN).")


class ReverseProxySettings(EnvironmentSettings):
    """Configure the standalone reverse proxy client."""

    reverse_proxy_gateway: str | None = Field(default=None, description="Gateway URL used by the reverse proxy (REVERSE_PROXY_GATEWAY).")
    reverse_proxy_token: SecretStr | None = Field(default=None, description="Bearer token used by the reverse proxy (REVERSE_PROXY_TOKEN).")


class SSLCacheSettings(EnvironmentSettings):
    """Configure SSL context cache limits without gateway initialization."""

    ssl_context_cache_max_size: int = Field(default=100, description="Maximum cached SSL contexts (SSL_CONTEXT_CACHE_MAX_SIZE).")
    ssl_context_cache_ttl: int | None = Field(default=None, description="SSL context lifetime in seconds; empty means unlimited (SSL_CONTEXT_CACHE_TTL).")

    @field_validator("ssl_context_cache_ttl", mode="before")
    @classmethod
    def empty_ttl(cls, value: Any) -> Any:
        """Interpret an empty TTL as unlimited caching.

        Args:
            value: Configured TTL value.

        Returns:
            None for empty values, otherwise the configured value.
        """
        del cls
        return None if isinstance(value, str) and not value.strip() else value


class BuilderSettings(EnvironmentSettings):
    """Configure deployment artifact generation."""

    mcp_deploy_dir: str = Field(default="./deploy", description="Deployment artifact directory (MCP_DEPLOY_DIR).")
    mcp_debug: str = Field(default="", description="Nonempty value enables builder diagnostics (MCP_DEBUG).")


class ToolOpsSettings(EnvironmentSettings):
    """Configure ToolOps providers with typed credentials and legacy token aliases."""

    llm_provider: str = Field(default="", description="ToolOps provider name (LLM_PROVIDER).")
    openai_api_key: SecretStr = Field(default=SecretStr(""), description="OpenAI provider credential (OPENAI_API_KEY).")
    openai_base_url: str = Field(default="", description="OpenAI provider base URL (OPENAI_BASE_URL).")
    openai_model: str = Field(default="", description="OpenAI model identifier (OPENAI_MODEL).")
    openai_max_retries: int = Field(default=2, description="OpenAI request retry limit (OPENAI_MAX_RETRIES).")
    openai_max_toekns: int = Field(default=600, description="OpenAI token limit; retains the legacy OPENAI_MAX_TOEKNS environment name.")
    azure_openai_api_key: SecretStr = Field(default=SecretStr(""), description="Azure OpenAI provider credential (AZURE_OPENAI_API_KEY).")
    azure_openai_endpoint: str = Field(default="", description="Azure OpenAI endpoint URL (AZURE_OPENAI_ENDPOINT).")
    azure_openai_api_version: str = Field(default="", description="Azure OpenAI API version (AZURE_OPENAI_API_VERSION).")
    azure_openai_deployment: str = Field(default="", description="Azure OpenAI deployment name (AZURE_OPENAI_DEPLOYMENT).")
    azure_openai_model: str = Field(default="", description="Azure OpenAI model identifier (AZURE_OPENAI_MODEL).")
    azure_openai_max_retries: int = Field(default=2, description="Azure OpenAI request retry limit (AZURE_OPENAI_MAX_RETRIES).")
    azure_openai_max_toekns: int = Field(default=600, description="Azure token limit; retains the legacy AZURE_OPENAI_MAX_TOEKNS environment name.")
    anthropic_api_key: SecretStr = Field(default=SecretStr(""), description="Anthropic provider credential (ANTHROPIC_API_KEY).")
    anthropic_model: str = Field(default="", description="Anthropic model identifier (ANTHROPIC_MODEL).")
    anthropic_max_tokens: int = Field(default=4096, description="Anthropic response token limit (ANTHROPIC_MAX_TOKENS).")
    anthropic_max_retries: int = Field(default=2, description="Anthropic request retry limit (ANTHROPIC_MAX_RETRIES).")
    aws_bedrock_model_id: str = Field(default="", description="Bedrock model identifier (AWS_BEDROCK_MODEL_ID).")
    aws_bedrock_region: str = Field(default="", description="Bedrock region name (AWS_BEDROCK_REGION).")
    aws_bedrock_max_tokens: int = Field(default=4096, description="Bedrock response token limit (AWS_BEDROCK_MAX_TOKENS).")
    aws_access_key_id: SecretStr = Field(default=SecretStr(""), description="AWS access credential identifier (AWS_ACCESS_KEY_ID).")
    aws_secret_access_key: SecretStr = Field(default=SecretStr(""), description="AWS secret access credential (AWS_SECRET_ACCESS_KEY).")
    aws_session_token: SecretStr = Field(default=SecretStr(""), description="AWS temporary session token (AWS_SESSION_TOKEN).")
    ollama_model: str = Field(default="", description="Ollama model identifier (OLLAMA_MODEL).")
    ollama_base_url: str = Field(default="", description="Ollama endpoint URL (OLLAMA_BASE_URL).")
    watsonx_apikey: SecretStr = Field(default=SecretStr(""), description="Watsonx provider credential (WATSONX_APIKEY).")
    watsonx_url: str = Field(default="", description="Watsonx service URL (WATSONX_URL).")
    watsonx_model_id: str = Field(default="", description="Watsonx model identifier (WATSONX_MODEL_ID).")
    watsonx_project_id: str = Field(default="", description="Watsonx project identifier (WATSONX_PROJECT_ID).")
    watsonx_max_new_tokens: int = Field(default=1000, description="Watsonx response token limit (WATSONX_MAX_NEW_TOKENS).")
    watsonx_decoding_method: str = Field(default="greedy", description="Watsonx decoding method (WATSONX_DECODING_METHOD).")
