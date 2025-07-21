# -*- coding: utf-8 -*-
"""MCP Gateway Configuration.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

This module defines configuration settings for the MCP Gateway using Pydantic.
It loads configuration from environment variables with sensible defaults.

Environment variables:
- APP_NAME: Gateway name (default: "MCP_Gateway")
- HOST: Host to bind to (default: "127.0.0.1")
- PORT: Port to listen on (default: 4444)
- DATABASE_URL: SQLite database URL (default: "sqlite:///./mcp.db")
- BASIC_AUTH_USER: Admin username (default: "admin")
- BASIC_AUTH_PASSWORD: Admin password (default: "changeme")
- LOG_LEVEL: Logging level (default: "INFO")
- SKIP_SSL_VERIFY: Disable SSL verification (default: False)
- AUTH_REQUIRED: Require authentication (default: True)
- TRANSPORT_TYPE: Transport mechanisms (default: "all")
- FEDERATION_ENABLED: Enable gateway federation (default: True)
- FEDERATION_DISCOVERY: Enable auto-discovery (default: False)
- FEDERATION_PEERS: List of peer gateway URLs (default: [])
- RESOURCE_CACHE_SIZE: Max cached resources (default: 1000)
- RESOURCE_CACHE_TTL: Cache TTL in seconds (default: 3600)
- TOOL_TIMEOUT: Tool invocation timeout (default: 60)
- PROMPT_CACHE_SIZE: Max cached prompts (default: 100)
- HEALTH_CHECK_INTERVAL: Gateway health check interval (default: 60)

Examples:
    >>> from mcpgateway.config import Settings
    >>> s = Settings(basic_auth_user='admin', basic_auth_password='secret')
    >>> s.api_key
    'admin:secret'
    >>> s2 = Settings(transport_type='http')
    >>> s2.validate_transport()  # no error
    >>> s3 = Settings(transport_type='invalid')
    >>> try:
    ...     s3.validate_transport()
    ... except ValueError as e:
    ...     print('error')
    error
    >>> s4 = Settings(database_url='sqlite:///./test.db')
    >>> isinstance(s4.database_settings, dict)
    True
"""

# Standard
from functools import lru_cache
from importlib.resources import files
import json
import logging
from pathlib import Path
import re
from typing import Annotated, Any, ClassVar, Dict, List, Optional, Set, Union

# Third-Party
from fastapi import HTTPException
import jq
from jsonpath_ng.ext import parse
from jsonpath_ng.jsonpath import JSONPath
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    MCP Gateway configuration settings.

    Examples:
        >>> from mcpgateway.config import Settings
        >>> s = Settings(basic_auth_user='admin', basic_auth_password='secret')
        >>> s.api_key
        'admin:secret'
        >>> s2 = Settings(transport_type='http')
        >>> s2.validate_transport()  # no error
        >>> s3 = Settings(transport_type='invalid')
        >>> try:
        ...     s3.validate_transport()
        ... except ValueError as e:
        ...     print('error')
        error
        >>> s4 = Settings(database_url='sqlite:///./test.db')
        >>> isinstance(s4.database_settings, dict)
        True
    """

    # Basic Settings
    app_name: str = "MCP_Gateway"
    host: str = "127.0.0.1"
    port: int = 4444
    database_url: str = "sqlite:///./mcp.db"
    templates_dir: Path = Path("mcpgateway/templates")
    # Absolute paths resolved at import-time (still override-able via env vars)
    templates_dir: Path = files("mcpgateway") / "templates"
    static_dir: Path = files("mcpgateway") / "static"
    app_root_path: str = ""

    # Protocol
    protocol_version: str = "2025-03-26"

    # Authentication
    basic_auth_user: str = "admin"
    basic_auth_password: str = "changeme"
    jwt_secret_key: str = "my-test-key"
    jwt_algorithm: str = "HS256"
    auth_required: bool = True
    token_expiry: int = 10080  # minutes

    #  Encryption key phrase for auth storage
    auth_encryption_secret: str = "my-test-salt"

    # UI/Admin Feature Flags
    mcpgateway_ui_enabled: bool = False
    mcpgateway_admin_api_enabled: bool = False

    # Security
    skip_ssl_verify: bool = False
    cors_enabled: bool = True

    # For allowed_origins, strip '' to ensure we're passing on valid JSON via env
    # Tell pydantic *not* to touch this env var - our validator will.
    allowed_origins: Annotated[Set[str], NoDecode] = {
        "http://localhost",
        "http://localhost:4444",
    }

    # Max retries for HTTP requests
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0  # seconds
    retry_max_delay: int = 60  # seconds
    retry_jitter_max: float = 0.5  # fraction of base delay

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, v):
        """Parse allowed origins from environment variable or config value.

        Handles multiple input formats for the allowed_origins field:
        - JSON array string: '["http://localhost", "http://example.com"]'
        - Comma-separated string: "http://localhost, http://example.com"
        - Already parsed set/list

        Automatically strips whitespace and removes outer quotes if present.

        Args:
            v: The input value to parse. Can be a string (JSON or CSV), set, list, or other iterable.

        Returns:
            Set[str]: A set of allowed origin strings.

        Examples:
            >>> sorted(Settings._parse_allowed_origins('["https://a.com", "https://b.com"]'))
            ['https://a.com', 'https://b.com']
            >>> sorted(Settings._parse_allowed_origins("https://x.com , https://y.com"))
            ['https://x.com', 'https://y.com']
            >>> Settings._parse_allowed_origins('""')
            set()
            >>> Settings._parse_allowed_origins('"https://single.com"')
            {'https://single.com'}
            >>> sorted(Settings._parse_allowed_origins(['http://a.com', 'http://b.com']))
            ['http://a.com', 'http://b.com']
            >>> Settings._parse_allowed_origins({'http://existing.com'})
            {'http://existing.com'}
        """
        if isinstance(v, str):
            v = v.strip()
            if v[:1] in "\"'" and v[-1:] == v[:1]:  # strip 1 outer quote pair
                v = v[1:-1]
            try:
                parsed = set(json.loads(v))
            except json.JSONDecodeError:
                parsed = {s.strip() for s in v.split(",") if s.strip()}
            return parsed
        return set(v)

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text
    log_file: Optional[Path] = None

    # Transport
    transport_type: str = "all"  # http, ws, sse, all
    websocket_ping_interval: int = 30  # seconds
    sse_retry_timeout: int = 5000  # milliseconds

    # Federation
    federation_enabled: bool = True
    federation_discovery: bool = False

    # For federation_peers strip out quotes to ensure we're passing valid JSON via env
    federation_peers: Annotated[List[str], NoDecode] = []

    @field_validator("federation_peers", mode="before")
    @classmethod
    def _parse_federation_peers(cls, v):
        """Parse federation peer URLs from environment variable or config value.

        Handles multiple input formats for the federation_peers field:
        - JSON array string: '["https://gw1.com", "https://gw2.com"]'
        - Comma-separated string: "https://gw1.com, https://gw2.com"
        - Already parsed list

        Automatically strips whitespace and removes outer quotes if present.
        Order is preserved when parsing.

        Args:
            v: The input value to parse. Can be a string (JSON or CSV), list, or other iterable.

        Returns:
            List[str]: A list of federation peer URLs.

        Examples:
            >>> Settings._parse_federation_peers('["https://gw1", "https://gw2"]')
            ['https://gw1', 'https://gw2']
            >>> Settings._parse_federation_peers("https://gw3, https://gw4")
            ['https://gw3', 'https://gw4']
            >>> Settings._parse_federation_peers('""')
            []
            >>> Settings._parse_federation_peers('"https://single-peer.com"')
            ['https://single-peer.com']
            >>> Settings._parse_federation_peers(['http://p1.com', 'http://p2.com'])
            ['http://p1.com', 'http://p2.com']
            >>> Settings._parse_federation_peers([])
            []
        """
        if isinstance(v, str):
            v = v.strip()
            if v[:1] in "\"'" and v[-1:] == v[:1]:
                v = v[1:-1]
            try:
                peers = json.loads(v)
            except json.JSONDecodeError:
                peers = [s.strip() for s in v.split(",") if s.strip()]
            return peers
        return list(v)

    federation_timeout: int = 30  # seconds
    federation_sync_interval: int = 300  # seconds

    # Resources
    resource_cache_size: int = 1000
    resource_cache_ttl: int = 3600  # seconds
    max_resource_size: int = 10 * 1024 * 1024  # 10MB
    allowed_mime_types: Set[str] = {
        "text/plain",
        "text/markdown",
        "text/html",
        "application/json",
        "application/xml",
        "image/png",
        "image/jpeg",
        "image/gif",
    }

    # Tools
    tool_timeout: int = 60  # seconds
    max_tool_retries: int = 3
    tool_rate_limit: int = 100  # requests per minute
    tool_concurrent_limit: int = 10

    # Prompts
    prompt_cache_size: int = 100
    max_prompt_size: int = 100 * 1024  # 100KB
    prompt_render_timeout: int = 10  # seconds

    # Health Checks
    health_check_interval: int = 60  # seconds
    health_check_timeout: int = 10  # seconds
    unhealthy_threshold: int = 5  # after this many failures, mark as Offline

    filelock_name: str = "gateway_service_leader.lock"

    # Default Roots
    default_roots: List[str] = []

    # Database
    db_pool_size: int = 200
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_max_retries: int = 3
    db_retry_interval_ms: int = 2000

    # Cache
    cache_type: str = "database"  # memory or redis or database
    redis_url: Optional[str] = "redis://localhost:6379/0"
    cache_prefix: str = "mcpgw:"
    session_ttl: int = 3600
    message_ttl: int = 600
    redis_max_retries: int = 3
    redis_retry_interval_ms: int = 2000

    # streamable http transport
    use_stateful_sessions: bool = False  # Set to False to use stateless sessions without event store
    json_response_enabled: bool = True  # Enable JSON responses instead of SSE streams

    # Development
    dev_mode: bool = False
    reload: bool = False
    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    gateway_tool_name_separator: str = "-"
    valid_slug_separator_regexp: ClassVar[str] = r"^(-{1,2}|[_.])$"

    @field_validator("gateway_tool_name_separator")
    @classmethod
    def must_be_allowed_sep(cls, v: str) -> str:
        """Validate the gateway tool name separator.

        Args:
            v: The separator value to validate.

        Returns:
            The validated separator, defaults to '-' if invalid.
        """
        if not re.fullmatch(cls.valid_slug_separator_regexp, v):
            logger.warning(
                f"Invalid gateway_tool_name_separator '{v}'. Must be '-', '--', '_' or '.'. Defaulting to '-'.",
                stacklevel=2,
            )
            return "-"
        return v

    @property
    def api_key(self) -> str:
        """
        Generate API key from auth credentials.

        Returns:
            str: API key string in the format "username:password".

        Examples:
            >>> from mcpgateway.config import Settings
            >>> settings = Settings(basic_auth_user="admin", basic_auth_password="secret")
            >>> settings.api_key
            'admin:secret'
            >>> settings = Settings(basic_auth_user="user123", basic_auth_password="pass456")
            >>> settings.api_key
            'user123:pass456'
        """
        return f"{self.basic_auth_user}:{self.basic_auth_password}"

    @property
    def supports_http(self) -> bool:
        """Check if HTTP transport is enabled.

        Returns:
            bool: True if HTTP transport is enabled, False otherwise.

        Examples:
            >>> settings = Settings(transport_type="http")
            >>> settings.supports_http
            True
            >>> settings = Settings(transport_type="all")
            >>> settings.supports_http
            True
            >>> settings = Settings(transport_type="ws")
            >>> settings.supports_http
            False
        """
        return self.transport_type in ["http", "all"]

    @property
    def supports_websocket(self) -> bool:
        """Check if WebSocket transport is enabled.

        Returns:
            bool: True if WebSocket transport is enabled, False otherwise.

        Examples:
            >>> settings = Settings(transport_type="ws")
            >>> settings.supports_websocket
            True
            >>> settings = Settings(transport_type="all")
            >>> settings.supports_websocket
            True
            >>> settings = Settings(transport_type="http")
            >>> settings.supports_websocket
            False
        """
        return self.transport_type in ["ws", "all"]

    @property
    def supports_sse(self) -> bool:
        """Check if SSE transport is enabled.

        Returns:
            bool: True if SSE transport is enabled, False otherwise.

        Examples:
            >>> settings = Settings(transport_type="sse")
            >>> settings.supports_sse
            True
            >>> settings = Settings(transport_type="all")
            >>> settings.supports_sse
            True
            >>> settings = Settings(transport_type="http")
            >>> settings.supports_sse
            False
        """
        return self.transport_type in ["sse", "all"]

    @property
    def database_settings(self) -> dict:
        """
        Get SQLAlchemy database settings.

        Returns:
            dict: Dictionary containing SQLAlchemy database configuration options.

        Examples:
            >>> from mcpgateway.config import Settings
            >>> s = Settings(database_url='sqlite:///./test.db')
            >>> isinstance(s.database_settings, dict)
            True
        """
        return {
            "pool_size": self.db_pool_size,
            "max_overflow": self.db_max_overflow,
            "pool_timeout": self.db_pool_timeout,
            "pool_recycle": self.db_pool_recycle,
            "connect_args": {"check_same_thread": False} if self.database_url.startswith("sqlite") else {},
        }

    @property
    def cors_settings(self) -> dict:
        """Get CORS settings.

        Returns:
            dict: Dictionary containing CORS configuration options.
        """
        return (
            {
                "allow_origins": list(self.allowed_origins),
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            }
            if self.cors_enabled
            else {}
        )

    def validate_transport(self) -> None:
        """
        Validate transport configuration.

        Raises:
            ValueError: If the transport type is not one of the valid options.

        Examples:
            >>> from mcpgateway.config import Settings
            >>> s = Settings(transport_type='http')
            >>> s.validate_transport()  # no error
            >>> s2 = Settings(transport_type='invalid')
            >>> try:
            ...     s2.validate_transport()
            ... except ValueError as e:
            ...     print('error')
            error
        """
        valid_types = {"http", "ws", "sse", "all"}
        if self.transport_type not in valid_types:
            raise ValueError(f"Invalid transport type. Must be one of: {valid_types}")

    def validate_database(self) -> None:
        """Validate database configuration.

        Examples:
            >>> from mcpgateway.config import Settings
            >>> s = Settings(database_url='sqlite:///./test.db')
            >>> s.validate_database()  # Should create the directory if it does not exist
        """
        if self.database_url.startswith("sqlite"):
            db_path = Path(self.database_url.replace("sqlite:///", ""))
            db_dir = db_path.parent
            if not db_dir.exists():
                db_dir.mkdir(parents=True)

    # Validation patterns for safe display (configurable)
    validation_dangerous_html_pattern: str = (
        r"<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\b|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>"
    )

    validation_dangerous_js_pattern: str = r"javascript:|vbscript:|on\w+\s*=|data:.*script"
    validation_allowed_url_schemes: List[str] = ["http://", "https://", "ws://", "wss://"]

    # Character validation patterns
    validation_name_pattern: str = r"^[a-zA-Z0-9_.\-\s]+$"  # Allow spaces for names
    validation_identifier_pattern: str = r"^[a-zA-Z0-9_\-\.]+$"  # No spaces for IDs
    validation_safe_uri_pattern: str = r"^[a-zA-Z0-9_\-.:/?=&%]+$"
    validation_unsafe_uri_pattern: str = r'[<>"\'\\]'
    validation_tool_name_pattern: str = r"^[a-zA-Z][a-zA-Z0-9._-]*$"  # MCP tool naming

    # MCP-compliant size limits (configurable via env)
    validation_max_name_length: int = 255
    validation_max_description_length: int = 4096
    validation_max_template_length: int = 65536  # 64KB
    validation_max_content_length: int = 1048576  # 1MB
    validation_max_json_depth: int = 10
    validation_max_url_length: int = 2048
    validation_max_rpc_param_size: int = 262144  # 256KB

    # Allowed MIME types
    validation_allowed_mime_types: List[str] = [
        "text/plain",
        "text/html",
        "text/css",
        "text/markdown",
        "text/javascript",
        "application/json",
        "application/xml",
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/svg+xml",
        "application/octet-stream",
    ]

    # Rate limiting
    validation_max_requests_per_minute: int = 60


def extract_using_jq(data, jq_filter=""):
    """
    Extracts data from a given input (string, dict, or list) using a jq filter string.

    Args:
        data (str, dict, list): The input JSON data. Can be a string, dict, or list.
        jq_filter (str): The jq filter string to extract the desired data.

    Returns:
        The result of applying the jq filter to the input data.

    Examples:
        >>> extract_using_jq('{"a": 1, "b": 2}', '.a')
        [1]
        >>> extract_using_jq({'a': 1, 'b': 2}, '.b')
        [2]
        >>> extract_using_jq('[{"a": 1}, {"a": 2}]', '.[].a')
        [1, 2]
        >>> extract_using_jq('not a json', '.a')
        ['Invalid JSON string provided.']
        >>> extract_using_jq({'a': 1}, '')
        {'a': 1}
    """
    if jq_filter == "":
        return data
    if isinstance(data, str):
        # If the input is a string, parse it as JSON
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return ["Invalid JSON string provided."]

    elif not isinstance(data, (dict, list)):
        # If the input is not a string, dict, or list, raise an error
        return ["Input data must be a JSON string, dictionary, or list."]

    # Apply the jq filter to the data
    try:
        # Pylint can't introspect C-extension modules, so it doesn't know that jq really does export an all() function.
        # pylint: disable=c-extension-no-member
        result = jq.all(jq_filter, data)  # Use `jq.all` to get all matches (returns a list)
        if result == [None]:
            result = "Error applying jsonpath filter"
    except Exception as e:
        message = "Error applying jsonpath filter: " + str(e)
        return message

    return result


def jsonpath_modifier(data: Any, jsonpath: str = "$[*]", mappings: Optional[Dict[str, str]] = None) -> Union[List, Dict]:
    """
    Applies the given JSONPath expression and mappings to the data.
    Only return data that is required by the user dynamically.

    Args:
        data: The JSON data to query.
        jsonpath: The JSONPath expression to apply.
        mappings: Optional dictionary of mappings where keys are new field names
                  and values are JSONPath expressions.

    Returns:
        Union[List, Dict]: A list (or mapped list) or a Dict of extracted data.

    Raises:
        HTTPException: If there's an error parsing or executing the JSONPath expressions.

    Examples:
        >>> jsonpath_modifier({'a': 1, 'b': 2}, '$.a')
        [1]
        >>> jsonpath_modifier([{'a': 1}, {'a': 2}], '$[*].a')
        [1, 2]
        >>> jsonpath_modifier({'a': {'b': 2}}, '$.a.b')
        [2]
        >>> jsonpath_modifier({'a': 1}, '$.b')
        []
    """
    if not jsonpath:
        jsonpath = "$[*]"

    try:
        main_expr: JSONPath = parse(jsonpath)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid main JSONPath expression: {e}")

    try:
        main_matches = main_expr.find(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error executing main JSONPath: {e}")

    results = [match.value for match in main_matches]

    if mappings:
        mapped_results = []
        for item in results:
            mapped_item = {}
            for new_key, mapping_expr_str in mappings.items():
                try:
                    mapping_expr = parse(mapping_expr_str)
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid mapping JSONPath for key '{new_key}': {e}")
                try:
                    mapping_matches = mapping_expr.find(item)
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Error executing mapping JSONPath for key '{new_key}': {e}")
                if not mapping_matches:
                    mapped_item[new_key] = None
                elif len(mapping_matches) == 1:
                    mapped_item[new_key] = mapping_matches[0].value
                else:
                    mapped_item[new_key] = [m.value for m in mapping_matches]
            mapped_results.append(mapped_item)
        results = mapped_results

    if len(results) == 1 and isinstance(results[0], dict):
        return results[0]
    return results


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: A cached instance of the Settings class.
    """
    # Instantiate a fresh Pydantic Settings object,
    # loading from env vars or .env exactly once.
    cfg = Settings()
    # Validate that transport_type is correct; will
    # raise if mis-configured.
    cfg.validate_transport()
    # Ensure sqlite DB directories exist if needed.
    cfg.validate_database()
    # Return the one-and-only Settings instance (cached).
    return cfg


# Create settings instance
settings = get_settings()
