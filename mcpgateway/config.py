# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

MCP Gateway Configuration.
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
- DOCS_ALLOW_BASIC_AUTH: Allow basic auth for docs (default: False)
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
import os
from pathlib import Path
import re
from typing import Annotated, Any, ClassVar, Dict, List, Optional, Set, Union

# Third-Party
from fastapi import HTTPException
import jq
from jsonpath_ng.ext import parse
from jsonpath_ng.jsonpath import JSONPath
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Only configure basic logging if no handlers exist yet
# This prevents conflicts with LoggingService while ensuring config logging works
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

logger = logging.getLogger(__name__)


def _normalize_env_list_vars() -> None:
    """Normalize list-typed env vars to valid JSON arrays.

    Ensures env values parse cleanly when providers expect JSON for complex types.
    If a value is empty or CSV, convert to a JSON array string.
    """
    keys = [
        "SSO_TRUSTED_DOMAINS",
        "SSO_AUTO_ADMIN_DOMAINS",
        "SSO_GITHUB_ADMIN_ORGS",
        "SSO_GOOGLE_ADMIN_DOMAINS",
    ]
    for key in keys:
        raw = os.environ.get(key)
        if raw is None:
            continue
        s = raw.strip()
        if not s:
            os.environ[key] = "[]"
            continue
        if s.startswith("["):
            # Already JSON-like, keep as is
            try:
                json.loads(s)
                continue
            except Exception:
                pass  # nosec B110 - Intentionally continue with CSV parsing if JSON parsing fails
        # Convert CSV to JSON array
        items = [item.strip() for item in s.split(",") if item.strip()]
        os.environ[key] = json.dumps(items)


_normalize_env_list_vars()


# Default content type for outgoing requests to Forge
FORGE_CONTENT_TYPE = os.getenv("FORGE_CONTENT_TYPE", "application/json")


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
        >>> s5 = Settings()
        >>> s5.app_name
        'MCP_Gateway'
        >>> s5.host in ('0.0.0.0', '127.0.0.1')  # Default can be either
        True
        >>> s5.port
        4444
        >>> s5.auth_required
        True
        >>> isinstance(s5.allowed_origins, set)
        True
    """

    # Basic Settings
    app_name: str = "MCP_Gateway"
    host: str = "127.0.0.1"
    port: int = 4444
    docs_allow_basic_auth: bool = False  # Allow basic auth for docs
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
    jwt_algorithm: str = "HS256"
    jwt_secret_key: str = "my-test-key"
    jwt_public_key_path: str = ""
    jwt_private_key_path: str = ""
    jwt_audience: str = "mcpgateway-api"
    jwt_issuer: str = "mcpgateway"
    jwt_audience_verification: bool = True
    auth_required: bool = True
    token_expiry: int = 10080  # minutes

    require_token_expiration: bool = Field(default=False, description="Require all JWT tokens to have expiration claims")  # Default to flexible mode for backward compatibility

    # SSO Configuration
    sso_enabled: bool = Field(default=False, description="Enable Single Sign-On authentication")
    sso_github_enabled: bool = Field(default=False, description="Enable GitHub OAuth authentication")
    sso_github_client_id: Optional[str] = Field(default=None, description="GitHub OAuth client ID")
    sso_github_client_secret: Optional[str] = Field(default=None, description="GitHub OAuth client secret")

    sso_google_enabled: bool = Field(default=False, description="Enable Google OAuth authentication")
    sso_google_client_id: Optional[str] = Field(default=None, description="Google OAuth client ID")
    sso_google_client_secret: Optional[str] = Field(default=None, description="Google OAuth client secret")

    sso_ibm_verify_enabled: bool = Field(default=False, description="Enable IBM Security Verify OIDC authentication")
    sso_ibm_verify_client_id: Optional[str] = Field(default=None, description="IBM Security Verify client ID")
    sso_ibm_verify_client_secret: Optional[str] = Field(default=None, description="IBM Security Verify client secret")
    sso_ibm_verify_issuer: Optional[str] = Field(default=None, description="IBM Security Verify OIDC issuer URL")

    sso_okta_enabled: bool = Field(default=False, description="Enable Okta OIDC authentication")
    sso_okta_client_id: Optional[str] = Field(default=None, description="Okta client ID")
    sso_okta_client_secret: Optional[str] = Field(default=None, description="Okta client secret")
    sso_okta_issuer: Optional[str] = Field(default=None, description="Okta issuer URL")

    # SSO Settings
    sso_auto_create_users: bool = Field(default=True, description="Automatically create users from SSO providers")
    sso_trusted_domains: Annotated[list[str], NoDecode()] = Field(default_factory=list, description="Trusted email domains (CSV or JSON list)")
    sso_preserve_admin_auth: bool = Field(default=True, description="Preserve local admin authentication when SSO is enabled")

    # SSO Admin Assignment Settings
    sso_auto_admin_domains: Annotated[list[str], NoDecode()] = Field(default_factory=list, description="Admin domains (CSV or JSON list)")
    sso_github_admin_orgs: Annotated[list[str], NoDecode()] = Field(default_factory=list, description="GitHub orgs granting admin (CSV/JSON)")
    sso_google_admin_domains: Annotated[list[str], NoDecode()] = Field(default_factory=list, description="Google admin domains (CSV/JSON)")
    sso_require_admin_approval: bool = Field(default=False, description="Require admin approval for new SSO registrations")

    # MCP Client Authentication
    mcp_client_auth_enabled: bool = Field(default=True, description="Enable JWT authentication for MCP client operations")
    trust_proxy_auth: bool = Field(
        default=False,
        description="Trust proxy authentication headers (required when mcp_client_auth_enabled=false)",
    )
    proxy_user_header: str = Field(default="X-Authenticated-User", description="Header containing authenticated username from proxy")

    #  Encryption key phrase for auth storage
    auth_encryption_secret: str = "my-test-salt"

    # OAuth Configuration
    oauth_request_timeout: int = Field(default=30, description="OAuth request timeout in seconds")
    oauth_max_retries: int = Field(default=3, description="Maximum retries for OAuth token requests")

    # Email-Based Authentication
    email_auth_enabled: bool = Field(default=True, description="Enable email-based authentication")
    platform_admin_email: str = Field(default="admin@example.com", description="Platform administrator email address")
    platform_admin_password: str = Field(default="changeme", description="Platform administrator password")
    platform_admin_full_name: str = Field(default="Platform Administrator", description="Platform administrator full name")

    # Argon2id Password Hashing Configuration
    argon2id_time_cost: int = Field(default=3, description="Argon2id time cost (number of iterations)")
    argon2id_memory_cost: int = Field(default=65536, description="Argon2id memory cost in KiB")
    argon2id_parallelism: int = Field(default=1, description="Argon2id parallelism (number of threads)")

    # Password Policy Configuration
    password_min_length: int = Field(default=8, description="Minimum password length")
    password_require_uppercase: bool = Field(default=False, description="Require uppercase letters in passwords")
    password_require_lowercase: bool = Field(default=False, description="Require lowercase letters in passwords")
    password_require_numbers: bool = Field(default=False, description="Require numbers in passwords")
    password_require_special: bool = Field(default=False, description="Require special characters in passwords")

    # Account Security Configuration
    max_failed_login_attempts: int = Field(default=5, description="Maximum failed login attempts before account lockout")
    account_lockout_duration_minutes: int = Field(default=30, description="Account lockout duration in minutes")

    # Personal Teams Configuration
    auto_create_personal_teams: bool = Field(default=True, description="Enable automatic personal team creation for new users")
    personal_team_prefix: str = Field(default="personal", description="Personal team naming prefix")
    max_teams_per_user: int = Field(default=50, description="Maximum number of teams a user can belong to")
    max_members_per_team: int = Field(default=100, description="Maximum number of members per team")
    invitation_expiry_days: int = Field(default=7, description="Number of days before team invitations expire")
    require_email_verification_for_invites: bool = Field(default=True, description="Require email verification for team invitations")

    # UI/Admin Feature Flags
    mcpgateway_ui_enabled: bool = False
    mcpgateway_admin_api_enabled: bool = False
    mcpgateway_bulk_import_enabled: bool = True
    mcpgateway_bulk_import_max_tools: int = 200
    mcpgateway_bulk_import_rate_limit: int = 10

    # UI Tool Test Configuration
    mcpgateway_ui_tool_test_timeout: int = Field(default=60000, description="Tool test timeout in milliseconds for the admin UI")

    # A2A (Agent-to-Agent) Feature Flags
    mcpgateway_a2a_enabled: bool = True
    mcpgateway_a2a_max_agents: int = 100
    mcpgateway_a2a_default_timeout: int = 30
    mcpgateway_a2a_max_retries: int = 3
    mcpgateway_a2a_metrics_enabled: bool = True

    # Security
    skip_ssl_verify: bool = False
    cors_enabled: bool = True

    # Environment
    environment: str = Field(default="development", env="ENVIRONMENT")

    # Domain configuration
    app_domain: str = Field(default="localhost", env="APP_DOMAIN")

    # Security settings
    secure_cookies: bool = Field(default=True, env="SECURE_COOKIES")
    cookie_samesite: str = Field(default="lax", env="COOKIE_SAMESITE")

    # CORS settings
    cors_allow_credentials: bool = Field(default=True, env="CORS_ALLOW_CREDENTIALS")

    # Security Headers Configuration
    security_headers_enabled: bool = Field(default=True, env="SECURITY_HEADERS_ENABLED")
    x_frame_options: str = Field(default="DENY", env="X_FRAME_OPTIONS")
    x_content_type_options_enabled: bool = Field(default=True, env="X_CONTENT_TYPE_OPTIONS_ENABLED")
    x_xss_protection_enabled: bool = Field(default=True, env="X_XSS_PROTECTION_ENABLED")
    x_download_options_enabled: bool = Field(default=True, env="X_DOWNLOAD_OPTIONS_ENABLED")
    hsts_enabled: bool = Field(default=True, env="HSTS_ENABLED")
    hsts_max_age: int = Field(default=31536000, env="HSTS_MAX_AGE")  # 1 year
    hsts_include_subdomains: bool = Field(default=True, env="HSTS_INCLUDE_SUBDOMAINS")
    remove_server_headers: bool = Field(default=True, env="REMOVE_SERVER_HEADERS")

    # For allowed_origins, strip '' to ensure we're passing on valid JSON via env
    # Tell pydantic *not* to touch this env var - our validator will.
    allowed_origins: Annotated[Set[str], NoDecode] = {
        "http://localhost",
        "http://localhost:4444",
    }

    # Security validation thresholds
    min_secret_length: int = 32
    min_password_length: int = 12
    require_strong_secrets: bool = False  # Default to False for backward compatibility, will be enforced in 0.8.0

    @field_validator("jwt_secret_key", "auth_encryption_secret")
    @classmethod
    def validate_secrets(cls, v: str, info) -> str:
        """Validate secret keys meet security requirements.

        Args:
            v: The secret key value to validate.
            info: ValidationInfo containing field metadata.

        Returns:
            str: The validated secret key value.
        """
        field_name = info.field_name

        # Check for default/weak secrets
        weak_secrets = ["my-test-key", "my-test-salt", "changeme", "secret", "password"]  # nosec B105 - list of weak defaults to check against
        if v.lower() in weak_secrets:
            logger.warning(f"🔓 SECURITY WARNING - {field_name}: Default/weak secret detected! Please set a strong, unique value for production.")

        # Check minimum length
        if len(v) < 32:  # Using hardcoded value since we can't access instance attributes
            logger.warning(f"⚠️  SECURITY WARNING - {field_name}: Secret should be at least 32 characters long. Current length: {len(v)}")

        # Check entropy (basic check for randomness)
        if len(set(v)) < 10:  # Less than 10 unique characters
            logger.warning(f"🔑 SECURITY WARNING - {field_name}: Secret has low entropy. Consider using a more random value.")

        return v

    @field_validator("basic_auth_password")
    @classmethod
    def validate_admin_password(cls, v: str) -> str:
        """Validate admin password meets security requirements.

        Args:
            v: The admin password value to validate.

        Returns:
            str: The validated admin password value.
        """
        if v == "changeme":  # nosec B105 - checking for default value
            logger.warning("🔓 SECURITY WARNING: Default admin password detected! Please change the BASIC_AUTH_PASSWORD immediately.")

        if len(v) < 12:  # Using hardcoded value
            logger.warning(f"⚠️  SECURITY WARNING: Admin password should be at least 12 characters long. Current length: {len(v)}")

        # Check password complexity
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', v))

        complexity_score = sum([has_upper, has_lower, has_digit, has_special])
        if complexity_score < 3:
            logger.warning("🔐 SECURITY WARNING: Admin password has low complexity. Should contain at least 3 of: uppercase, lowercase, digits, special characters")

        return v

    @field_validator("allowed_origins")
    @classmethod
    def validate_cors_origins(cls, v: set) -> set:
        """Validate CORS allowed origins.

        Args:
            v: The set of allowed origins to validate.

        Returns:
            set: The validated set of allowed origins.
        """
        if not v:
            return v

        dangerous_origins = ["*", "null", ""]
        for origin in v:
            if origin in dangerous_origins:
                logger.warning(f"🌐 SECURITY WARNING: Dangerous CORS origin '{origin}' detected. Consider specifying explicit origins instead of wildcards.")

            # Validate URL format
            if not origin.startswith(("http://", "https://")) and origin not in dangerous_origins:
                logger.warning(f"⚠️  SECURITY WARNING: Invalid origin format '{origin}'. Origins should start with http:// or https://")

        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate database connection string security.

        Args:
            v: The database URL to validate.

        Returns:
            str: The validated database URL.
        """
        # Check for hardcoded passwords in non-SQLite databases
        if not v.startswith("sqlite"):
            if "password" in v and any(weak in v for weak in ["password", "123", "admin", "test"]):
                logger.warning("Potentially weak database password detected. Consider using a stronger password.")

        # Warn about SQLite in production
        if v.startswith("sqlite"):
            logger.info("Using SQLite database. Consider PostgreSQL or MySQL for production.")

        return v

    @model_validator(mode="after")
    @classmethod
    def validate_security_combinations(cls, values):
        """Validate security setting combinations.

        Args:
            values: The Settings instance with all field values.

        Returns:
            Settings: The validated Settings instance.
        """
        # Check for dangerous combinations - only log warnings, don't raise errors
        if not values.auth_required and values.mcpgateway_ui_enabled:
            logger.warning("🔓 SECURITY WARNING: Admin UI is enabled without authentication. Consider setting AUTH_REQUIRED=true for production.")

        if values.skip_ssl_verify and not values.dev_mode:
            logger.warning("🔓 SECURITY WARNING: SSL verification is disabled in non-dev mode. This is a security risk! Set SKIP_SSL_VERIFY=false for production.")

        if values.debug and not values.dev_mode:
            logger.warning("🐛 SECURITY WARNING: Debug mode is enabled in non-dev mode. This may leak sensitive information! Set DEBUG=false for production.")

        # Warn about federation without auth
        if values.federation_enabled and not values.auth_required:
            logger.warning("🌐 SECURITY WARNING: Federation is enabled without authentication. This may expose your gateway to unauthorized access.")

        return values

    def get_security_warnings(self) -> List[str]:
        """Get list of security warnings for current configuration.

        Returns:
            List[str]: List of security warning messages.
        """
        warnings = []

        # Authentication warnings
        if not self.auth_required:
            warnings.append("🔓 Authentication is disabled - ensure this is intentional")

        if self.basic_auth_user == "admin":
            warnings.append("⚠️  Using default admin username - consider changing it")

        # SSL/TLS warnings
        if self.skip_ssl_verify:
            warnings.append("🔓 SSL verification is disabled - not recommended for production")

        # Debug/Dev warnings
        if self.debug and not self.dev_mode:
            warnings.append("🐛 Debug mode enabled - disable in production to prevent info leakage")

        if self.dev_mode:
            warnings.append("🔧 Development mode enabled - not for production use")

        # CORS warnings
        if self.cors_enabled and "*" in self.allowed_origins:
            warnings.append("🌐 CORS allows all origins (*) - this is a security risk")

        # Token warnings
        if self.token_expiry > 10080:  # More than 7 days
            warnings.append("⏱️  JWT token expiry is very long - consider shorter duration")

        # Database warnings
        if self.database_url.startswith("sqlite") and not self.dev_mode:
            warnings.append("💾 SQLite database in use - consider PostgreSQL/MySQL for production")

        # Rate limiting warnings
        if self.tool_rate_limit > 1000:
            warnings.append("🚦 Tool rate limit is very high - may allow abuse")

        return warnings

    def get_security_status(self) -> dict:
        """Get comprehensive security status.

        Returns:
            dict: Dictionary containing security status information including score and warnings.
        """

        # Compute a security score: 100 minus 10 for each warning
        security_score = max(0, 100 - 10 * len(self.get_security_warnings()))

        return {
            "secure_secrets": self.jwt_secret_key != "my-test-key",  # nosec B105 - checking for default value
            "auth_enabled": self.auth_required,
            "ssl_verification": not self.skip_ssl_verify,
            "debug_disabled": not self.debug,
            "cors_restricted": "*" not in self.allowed_origins if self.cors_enabled else True,
            "ui_protected": not self.mcpgateway_ui_enabled or self.auth_required,
            "warnings": self.get_security_warnings(),
            "security_score": security_score,
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
    log_to_file: bool = False  # Enable file logging (default: stdout/stderr only)
    log_filemode: str = "a+"  # append or overwrite
    log_file: Optional[str] = None  # Only used if log_to_file=True
    log_folder: Optional[str] = None  # Only used if log_to_file=True

    # Log Rotation (optional - only used if log_to_file=True)
    log_rotation_enabled: bool = False  # Enable log file rotation
    log_max_size_mb: int = 1  # Max file size in MB before rotation (default: 1MB)
    log_backup_count: int = 5  # Number of backup files to keep (default: 5)

    # Log Buffer (for in-memory storage in admin UI)
    log_buffer_size_mb: float = 1.0  # Size of in-memory log buffer in MB

    # Transport
    transport_type: str = "all"  # http, ws, sse, all
    websocket_ping_interval: int = 30  # seconds
    sse_retry_timeout: int = 5000  # milliseconds
    sse_keepalive_enabled: bool = True  # Enable SSE keepalive events
    sse_keepalive_interval: int = 30  # seconds between keepalive events

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

    federation_timeout: int = 120  # seconds
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

    # Validation Gateway URL
    gateway_validation_timeout: int = 5  # seconds

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

    # Core plugin settings
    plugins_enabled: bool = Field(default=False, description="Enable the plugin framework")
    plugin_config_file: str = Field(default="plugins/config.yaml", description="Path to main plugin configuration file")

    # Plugin CLI settings
    plugins_cli_completion: bool = Field(default=False, description="Enable auto-completion for plugins CLI")
    plugins_cli_markup_mode: str | None = Field(default=None, description="Set markup mode for plugins CLI")

    # Development
    dev_mode: bool = False
    reload: bool = False
    debug: bool = False

    # Observability (OpenTelemetry)
    otel_enable_observability: bool = Field(default=True, description="Enable OpenTelemetry observability")
    otel_traces_exporter: str = Field(default="otlp", description="Traces exporter: otlp, jaeger, zipkin, console, none")
    otel_exporter_otlp_endpoint: Optional[str] = Field(default=None, description="OTLP endpoint (e.g., http://localhost:4317)")
    otel_exporter_otlp_protocol: str = Field(default="grpc", description="OTLP protocol: grpc or http")
    otel_exporter_otlp_insecure: bool = Field(default=True, description="Use insecure connection for OTLP")
    otel_exporter_otlp_headers: Optional[str] = Field(default=None, description="OTLP headers (comma-separated key=value)")
    otel_exporter_jaeger_endpoint: Optional[str] = Field(default=None, description="Jaeger endpoint")
    otel_exporter_zipkin_endpoint: Optional[str] = Field(default=None, description="Zipkin endpoint")
    otel_service_name: str = Field(default="mcp-gateway", description="Service name for traces")
    otel_resource_attributes: Optional[str] = Field(default=None, description="Resource attributes (comma-separated key=value)")
    otel_bsp_max_queue_size: int = Field(default=2048, description="Max queue size for batch span processor")
    otel_bsp_max_export_batch_size: int = Field(default=512, description="Max export batch size")
    otel_bsp_schedule_delay: int = Field(default=5000, description="Schedule delay in milliseconds")

    # ===================================
    # Well-Known URI Configuration
    # ===================================

    # Enable well-known URI endpoints
    well_known_enabled: bool = True

    # robots.txt content (default: disallow all crawling for private API)
    well_known_robots_txt: str = """User-agent: *
Disallow: /

# MCP Gateway is a private API gateway
# Public crawling is disabled by default"""

    # security.txt content (optional, user-defined)
    # Example: "Contact: security@example.com\nExpires: 2025-12-31T23:59:59Z\nPreferred-Languages: en"
    well_known_security_txt: str = ""

    # Enable security.txt only if content is provided
    well_known_security_txt_enabled: bool = False

    # Additional custom well-known files (JSON format)
    # Example: {"ai.txt": "This service uses AI for...", "dnt-policy.txt": "Do Not Track policy..."}
    well_known_custom_files: str = "{}"

    # Cache control for well-known files (seconds)
    well_known_cache_max_age: int = 3600  # 1 hour default
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

        Examples:
            >>> Settings.must_be_allowed_sep('-')
            '-'
            >>> Settings.must_be_allowed_sep('--')
            '--'
            >>> Settings.must_be_allowed_sep('_')
            '_'
            >>> Settings.must_be_allowed_sep('.')
            '.'
            >>> Settings.must_be_allowed_sep('invalid')
            '-'
        """
        if not re.fullmatch(cls.valid_slug_separator_regexp, v):
            logger.warning(
                f"Invalid gateway_tool_name_separator '{v}'. Must be '-', '--', '_' or '.'. Defaulting to '-'.",
                stacklevel=2,
            )
            return "-"
        return v

    @property
    def custom_well_known_files(self) -> Dict[str, str]:
        """Parse custom well-known files from JSON string.

        Returns:
            Dict[str, str]: Parsed custom well-known files mapping filename to content.
        """
        try:
            return json.loads(self.well_known_custom_files) if self.well_known_custom_files else {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in WELL_KNOWN_CUSTOM_FILES: {self.well_known_custom_files}")
            return {}

    @field_validator("well_known_security_txt_enabled", mode="after")
    @classmethod
    def _auto_enable_security_txt(cls, v, info):
        """Auto-enable security.txt if content is provided.

        Args:
            v: The current value of well_known_security_txt_enabled.
            info: ValidationInfo containing field data.

        Returns:
            bool: True if security.txt content is provided, otherwise the original value.
        """
        if info.data and "well_known_security_txt" in info.data:
            return bool(info.data["well_known_security_txt"].strip())
        return v

    # -------------------------------
    # Flexible list parsing for envs
    # -------------------------------
    @field_validator(
        "sso_trusted_domains",
        "sso_auto_admin_domains",
        "sso_github_admin_orgs",
        "sso_google_admin_domains",
        mode="before",
    )
    @classmethod
    def _parse_list_from_env(cls, v):  # type: ignore[override]
        """Parse list fields from environment values.

        Accepts either JSON arrays (e.g. '["a","b"]') or comma-separated
        strings (e.g. 'a,b'). Empty or None becomes an empty list.

        Args:
            v: The value to parse, can be None, list, or string.

        Returns:
            list: Parsed list of values.
        """
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    logger.warning("Invalid JSON list in env for list field; falling back to CSV parsing")
            # CSV fallback
            return [item.strip() for item in s.split(",") if item.strip()]
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

        Examples:
            >>> s = Settings(cors_enabled=True, allowed_origins={'http://localhost'})
            >>> cors = s.cors_settings
            >>> cors['allow_origins']
            ['http://localhost']
            >>> cors['allow_credentials']
            True
            >>> s2 = Settings(cors_enabled=False)
            >>> s2.cors_settings
            {}
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
        # valid_types = {"http", "ws", "sse", "all"}
        valid_types = {"sse", "streamablehttp", "all", "http"}
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

    validation_dangerous_js_pattern: str = r"(?i)(?:^|\s|[\"'`<>=])(javascript:|vbscript:|data:\s*[^,]*[;\s]*(javascript|vbscript)|\bon[a-z]+\s*=|<\s*script\b)"

    validation_allowed_url_schemes: List[str] = ["http://", "https://", "ws://", "wss://"]

    # Character validation patterns
    validation_name_pattern: str = r"^[a-zA-Z0-9_.\-\s]+$"  # Allow spaces for names
    validation_identifier_pattern: str = r"^[a-zA-Z0-9_\-\.]+$"  # No spaces for IDs
    validation_safe_uri_pattern: str = r"^[a-zA-Z0-9_\-.:/?=&%]+$"
    validation_unsafe_uri_pattern: str = r'[<>"\'\\]'
    validation_tool_name_pattern: str = r"^[a-zA-Z][a-zA-Z0-9._-]*$"  # MCP tool naming
    validation_tool_method_pattern: str = r"^[a-zA-Z][a-zA-Z0-9_\./-]*$"

    # MCP-compliant size limits (configurable via env)
    validation_max_name_length: int = 255
    validation_max_description_length: int = 8192  # 8KB
    validation_max_template_length: int = 65536  # 64KB
    validation_max_content_length: int = 1048576  # 1MB
    validation_max_json_depth: int = 10
    validation_max_url_length: int = 2048
    validation_max_rpc_param_size: int = 262144  # 256KB

    validation_max_method_length: int = 128

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

    # Header passthrough feature (disabled by default for security)
    enable_header_passthrough: bool = Field(default=False, description="Enable HTTP header passthrough feature (WARNING: Security implications - only enable if needed)")

    # Passthrough headers configuration
    default_passthrough_headers: List[str] = Field(default_factory=list)

    def __init__(self, **kwargs):
        """Initialize Settings with environment variable parsing.

        Args:
            **kwargs: Keyword arguments passed to parent Settings class

        Raises:
            ValueError: When environment variable parsing fails or produces invalid data

        Examples:
            >>> import os
            >>> # Test with no environment variable set
            >>> old_val = os.environ.get('DEFAULT_PASSTHROUGH_HEADERS')
            >>> if 'DEFAULT_PASSTHROUGH_HEADERS' in os.environ:
            ...     del os.environ['DEFAULT_PASSTHROUGH_HEADERS']
            >>> s = Settings()
            >>> s.default_passthrough_headers
            ['X-Tenant-Id', 'X-Trace-Id']
            >>> # Restore original value if it existed
            >>> if old_val is not None:
            ...     os.environ['DEFAULT_PASSTHROUGH_HEADERS'] = old_val
        """
        super().__init__(**kwargs)

        # Parse DEFAULT_PASSTHROUGH_HEADERS environment variable
        default_value = os.environ.get("DEFAULT_PASSTHROUGH_HEADERS")
        if default_value:
            try:
                # Try JSON parsing first
                self.default_passthrough_headers = json.loads(default_value)
                if not isinstance(self.default_passthrough_headers, list):
                    raise ValueError("Must be a JSON array")
            except (json.JSONDecodeError, ValueError):
                # Fallback to comma-separated parsing
                self.default_passthrough_headers = [h.strip() for h in default_value.split(",") if h.strip()]
                logger.info(f"Parsed comma-separated passthrough headers: {self.default_passthrough_headers}")
        else:
            # Safer defaults without Authorization header
            self.default_passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]

        # Configure environment-aware CORS origins if not explicitly set via env or kwargs
        # Only apply defaults if using the default allowed_origins value
        if not os.environ.get("ALLOWED_ORIGINS") and "allowed_origins" not in kwargs and self.allowed_origins == {"http://localhost", "http://localhost:4444"}:
            if self.environment == "development":
                self.allowed_origins = {
                    "http://localhost",
                    "http://localhost:3000",
                    "http://localhost:8080",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:8080",
                    f"http://localhost:{self.port}",
                    f"http://127.0.0.1:{self.port}",
                }
            else:
                # Production origins - construct from app_domain
                self.allowed_origins = {f"https://{self.app_domain}", f"https://app.{self.app_domain}", f"https://admin.{self.app_domain}"}

        # Validate proxy auth configuration
        if not self.mcp_client_auth_enabled and not self.trust_proxy_auth:
            logger.warning(
                "MCP client authentication is disabled but trust_proxy_auth is not set. "
                "This is a security risk! Set TRUST_PROXY_AUTH=true only if MCP Gateway "
                "is behind a trusted authentication proxy."
            )

    # Masking value for all sensitive data
    masked_auth_value: str = "*****"


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

    Examples:
        >>> settings = get_settings()
        >>> isinstance(settings, Settings)
        True
        >>> # Second call returns the same cached instance
        >>> settings2 = get_settings()
        >>> settings is settings2
        True
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
