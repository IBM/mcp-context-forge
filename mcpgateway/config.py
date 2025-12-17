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
import json  # consider typjson for type safety loading from configuration data.
import logging
import os
from pathlib import Path
import re
import sys
from typing import Annotated, Any, ClassVar, Dict, List, Literal, NotRequired, Optional, Self, Set, TypedDict

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import Field, field_validator, HttpUrl, model_validator, PositiveInt, SecretStr, ValidationInfo
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
    port: PositiveInt = Field(default=4444, ge=1, le=65535)
    client_mode: bool = False
    docs_allow_basic_auth: bool = False  # Allow basic auth for docs
    database_url: str = Field(
        default="sqlite:///./mcp.db",
        description=(
            "Database connection URL. Supports SQLite, PostgreSQL, MySQL/MariaDB. "
            "For PostgreSQL with custom schema, use the 'options' query parameter: "
            "postgresql://user:pass@host:5432/db?options=-c%20search_path=schema_name "
            "(See Issue #1535 for details)"
        ),
    )

    # Absolute paths resolved at import-time (still override-able via env vars)
    templates_dir: Path = Field(default_factory=lambda: Path(str(files("mcpgateway") / "templates")))
    static_dir: Path = Field(default_factory=lambda: Path(str(files("mcpgateway") / "static")))

    app_root_path: str = ""

    # Protocol
    protocol_version: str = "2025-06-18"

    # Authentication
    basic_auth_user: str = "admin"
    basic_auth_password: SecretStr = Field(default=SecretStr("changeme"))
    jwt_algorithm: str = "HS256"
    jwt_secret_key: SecretStr = Field(default=SecretStr("my-test-key"))
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
    sso_github_client_secret: Optional[SecretStr] = Field(default=None, description="GitHub OAuth client secret")

    sso_google_enabled: bool = Field(default=False, description="Enable Google OAuth authentication")
    sso_google_client_id: Optional[str] = Field(default=None, description="Google OAuth client ID")
    sso_google_client_secret: Optional[SecretStr] = Field(default=None, description="Google OAuth client secret")

    sso_ibm_verify_enabled: bool = Field(default=False, description="Enable IBM Security Verify OIDC authentication")
    sso_ibm_verify_client_id: Optional[str] = Field(default=None, description="IBM Security Verify client ID")
    sso_ibm_verify_client_secret: Optional[SecretStr] = Field(default=None, description="IBM Security Verify client secret")
    sso_ibm_verify_issuer: Optional[str] = Field(default=None, description="IBM Security Verify OIDC issuer URL")

    sso_okta_enabled: bool = Field(default=False, description="Enable Okta OIDC authentication")
    sso_okta_client_id: Optional[str] = Field(default=None, description="Okta client ID")
    sso_okta_client_secret: Optional[SecretStr] = Field(default=None, description="Okta client secret")
    sso_okta_issuer: Optional[str] = Field(default=None, description="Okta issuer URL")

    sso_keycloak_enabled: bool = Field(default=False, description="Enable Keycloak OIDC authentication")
    sso_keycloak_base_url: Optional[str] = Field(default=None, description="Keycloak base URL (e.g., https://keycloak.example.com)")
    sso_keycloak_realm: str = Field(default="master", description="Keycloak realm name")
    sso_keycloak_client_id: Optional[str] = Field(default=None, description="Keycloak client ID")
    sso_keycloak_client_secret: Optional[SecretStr] = Field(default=None, description="Keycloak client secret")
    sso_keycloak_map_realm_roles: bool = Field(default=True, description="Map Keycloak realm roles to gateway teams")
    sso_keycloak_map_client_roles: bool = Field(default=False, description="Map Keycloak client roles to gateway RBAC")
    sso_keycloak_username_claim: str = Field(default="preferred_username", description="JWT claim for username")

    # Security Validation & Sanitization
    experimental_validate_io: bool = Field(default=False, description="Enable experimental input validation and output sanitization")
    validation_middleware_enabled: bool = Field(default=False, description="Enable validation middleware for all requests")
    validation_strict: bool = Field(default=True, description="Strict validation mode - reject on violations")
    sanitize_output: bool = Field(default=True, description="Sanitize output to remove control characters")
    allowed_roots: List[str] = Field(default_factory=list, description="Allowed root paths for resource access")
    max_path_depth: int = Field(default=10, description="Maximum allowed path depth")
    max_param_length: int = Field(default=10000, description="Maximum parameter length")
    dangerous_patterns: List[str] = Field(
        default_factory=lambda: [
            r"[;&|`$(){}\[\]<>]",  # Shell metacharacters
            r"\.\.[\\/]",  # Path traversal
            r"[\x00-\x1f\x7f-\x9f]",  # Control characters
        ],
        description="Regex patterns for dangerous input",
    )

    sso_keycloak_email_claim: str = Field(default="email", description="JWT claim for email")
    sso_keycloak_groups_claim: str = Field(default="groups", description="JWT claim for groups/roles")

    sso_entra_enabled: bool = Field(default=False, description="Enable Microsoft Entra ID OIDC authentication")
    sso_entra_client_id: Optional[str] = Field(default=None, description="Microsoft Entra ID client ID")
    sso_entra_client_secret: Optional[SecretStr] = Field(default=None, description="Microsoft Entra ID client secret")
    sso_entra_tenant_id: Optional[str] = Field(default=None, description="Microsoft Entra ID tenant ID")

    sso_generic_enabled: bool = Field(default=False, description="Enable generic OIDC provider (Keycloak, Auth0, etc.)")
    sso_generic_provider_id: Optional[str] = Field(default=None, description="Provider ID (e.g., 'keycloak', 'auth0', 'authentik')")
    sso_generic_display_name: Optional[str] = Field(default=None, description="Display name shown on login page")
    sso_generic_client_id: Optional[str] = Field(default=None, description="Generic OIDC client ID")
    sso_generic_client_secret: Optional[SecretStr] = Field(default=None, description="Generic OIDC client secret")
    sso_generic_authorization_url: Optional[str] = Field(default=None, description="Authorization endpoint URL")
    sso_generic_token_url: Optional[str] = Field(default=None, description="Token endpoint URL")
    sso_generic_userinfo_url: Optional[str] = Field(default=None, description="Userinfo endpoint URL")
    sso_generic_issuer: Optional[str] = Field(default=None, description="OIDC issuer URL")
    sso_generic_scope: Optional[str] = Field(default="openid profile email", description="OAuth scopes (space-separated)")

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
    auth_encryption_secret: SecretStr = Field(default=SecretStr("my-test-salt"))

    # OAuth Configuration
    oauth_request_timeout: int = Field(default=30, description="OAuth request timeout in seconds")
    oauth_max_retries: int = Field(default=3, description="Maximum retries for OAuth token requests")
    oauth_default_timeout: int = Field(default=3600, description="Default OAuth token timeout in seconds")

    # ===================================
    # Dynamic Client Registration (DCR) - Client Mode
    # ===================================

    # Enable DCR client functionality
    dcr_enabled: bool = Field(default=True, description="Enable Dynamic Client Registration (RFC 7591) - gateway acts as DCR client")

    # Auto-register when missing credentials
    dcr_auto_register_on_missing_credentials: bool = Field(default=True, description="Automatically register with AS when gateway has issuer but no client_id")

    # Default scopes for DCR
    dcr_default_scopes: List[str] = Field(default=["mcp:read"], description="Default MCP scopes to request during DCR")

    # Issuer allowlist (empty = allow any)
    dcr_allowed_issuers: List[str] = Field(default_factory=list, description="Optional allowlist of issuer URLs for DCR (empty = allow any)")

    # Token endpoint auth method
    dcr_token_endpoint_auth_method: str = Field(default="client_secret_basic", description="Token endpoint auth method for DCR (client_secret_basic or client_secret_post)")

    # Metadata cache TTL
    dcr_metadata_cache_ttl: int = Field(default=3600, description="AS metadata cache TTL in seconds (RFC 8414 discovery)")

    # Client name template
    dcr_client_name_template: str = Field(default="MCP Gateway ({gateway_name})", description="Template for client_name in DCR requests")

    # ===================================
    # OAuth Discovery (RFC 8414)
    # ===================================

    oauth_discovery_enabled: bool = Field(default=True, description="Enable OAuth AS metadata discovery (RFC 8414)")

    oauth_preferred_code_challenge_method: str = Field(default="S256", description="Preferred PKCE code challenge method (S256 or plain)")

    # Email-Based Authentication
    email_auth_enabled: bool = Field(default=True, description="Enable email-based authentication")
    platform_admin_email: str = Field(default="admin@example.com", description="Platform administrator email address")
    platform_admin_password: SecretStr = Field(default=SecretStr("changeme"), description="Platform administrator password")
    default_user_password: SecretStr = Field(default=SecretStr("changeme"), description="Default password for new users")  # nosec B105
    platform_admin_full_name: str = Field(default="Platform Administrator", description="Platform administrator full name")

    # Argon2id Password Hashing Configuration
    argon2id_time_cost: int = Field(default=3, description="Argon2id time cost (number of iterations)")
    argon2id_memory_cost: int = Field(default=65536, description="Argon2id memory cost in KiB")
    argon2id_parallelism: int = Field(default=1, description="Argon2id parallelism (number of threads)")

    # Password Policy Configuration
    password_min_length: int = Field(default=8, description="Minimum password length")
    password_require_uppercase: bool = Field(default=True, description="Require uppercase letters in passwords")
    password_require_lowercase: bool = Field(default=True, description="Require lowercase letters in passwords")
    password_require_numbers: bool = Field(default=False, description="Require numbers in passwords")
    password_require_special: bool = Field(default=True, description="Require special characters in passwords")

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
    mcpgateway_ui_airgapped: bool = Field(default=False, description="Use local CDN assets instead of external CDNs for airgapped deployments")
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

    # gRPC Support Configuration (EXPERIMENTAL - disabled by default)
    mcpgateway_grpc_enabled: bool = Field(default=False, description="Enable gRPC to MCP translation support (experimental feature)")
    mcpgateway_grpc_reflection_enabled: bool = Field(default=True, description="Enable gRPC server reflection by default")
    mcpgateway_grpc_max_message_size: int = Field(default=4194304, description="Maximum gRPC message size in bytes (4MB)")
    mcpgateway_grpc_timeout: int = Field(default=30, description="Default gRPC call timeout in seconds")
    mcpgateway_grpc_tls_enabled: bool = Field(default=False, description="Enable TLS for gRPC connections by default")

    # ===================================
    # Performance Monitoring Configuration
    # ===================================
    mcpgateway_performance_tracking: bool = Field(default=False, description="Enable performance tracking tab in admin UI")
    mcpgateway_performance_collection_interval: int = Field(default=10, ge=1, le=300, description="Metric collection interval in seconds")
    mcpgateway_performance_retention_hours: int = Field(default=24, ge=1, le=168, description="Snapshot retention period in hours")
    mcpgateway_performance_retention_days: int = Field(default=90, ge=1, le=365, description="Aggregate retention period in days")
    mcpgateway_performance_max_snapshots: int = Field(default=10000, ge=100, le=1000000, description="Maximum performance snapshots to retain")
    mcpgateway_performance_distributed: bool = Field(default=False, description="Enable distributed mode metrics aggregation via Redis")

    # MCP Server Catalog Configuration
    mcpgateway_catalog_enabled: bool = Field(default=True, description="Enable MCP server catalog feature")
    mcpgateway_catalog_file: str = Field(default="mcp-catalog.yml", description="Path to catalog configuration file")
    mcpgateway_catalog_auto_health_check: bool = Field(default=True, description="Automatically health check catalog servers")
    mcpgateway_catalog_cache_ttl: int = Field(default=3600, description="Catalog cache TTL in seconds")
    mcpgateway_catalog_page_size: int = Field(default=100, description="Number of catalog servers per page")

    # Elicitation support (MCP 2025-06-18)
    mcpgateway_elicitation_enabled: bool = Field(default=True, description="Enable elicitation passthrough support (MCP 2025-06-18)")
    mcpgateway_elicitation_timeout: int = Field(default=60, description="Default timeout for elicitation requests in seconds")
    mcpgateway_elicitation_max_concurrent: int = Field(default=100, description="Maximum concurrent elicitation requests")

    # Security
    skip_ssl_verify: bool = False
    cors_enabled: bool = True

    # Environment
    environment: Literal["development", "staging", "production"] = Field(default="development")

    # Domain configuration
    app_domain: HttpUrl = Field(default=HttpUrl("http://localhost:4444"))

    # Security settings
    secure_cookies: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")

    # CORS settings
    cors_allow_credentials: bool = Field(default=True)

    # Security Headers Configuration
    security_headers_enabled: bool = Field(default=True)
    x_frame_options: Optional[str] = Field(default="DENY")

    @field_validator("x_frame_options")
    @classmethod
    def normalize_x_frame_options(cls, v: Optional[str]) -> Optional[str]:
        """Convert string 'null' or 'none' to Python None to disable iframe restrictions.

        Args:
            v: The x_frame_options value from environment/config

        Returns:
            None if v is "null" or "none" (case-insensitive), otherwise returns v unchanged
        """
        if isinstance(v, str) and v.lower() in ("null", "none"):
            return None
        return v

    x_content_type_options_enabled: bool = Field(default=True)
    x_xss_protection_enabled: bool = Field(default=True)
    x_download_options_enabled: bool = Field(default=True)
    hsts_enabled: bool = Field(default=True)
    hsts_max_age: int = Field(default=31536000)  # 1 year
    hsts_include_subdomains: bool = Field(default=True)
    remove_server_headers: bool = Field(default=True)

    # Response Compression Configuration
    compression_enabled: bool = Field(default=True, description="Enable response compression (Brotli, Zstd, GZip)")
    compression_minimum_size: int = Field(default=500, ge=0, description="Minimum response size in bytes to compress (0 = compress all)")
    compression_gzip_level: int = Field(default=6, ge=1, le=9, description="GZip compression level (1=fastest, 9=best compression)")
    compression_brotli_quality: int = Field(default=4, ge=0, le=11, description="Brotli compression quality (0-3=fast, 4-9=balanced, 10-11=max)")
    compression_zstd_level: int = Field(default=3, ge=1, le=22, description="Zstd compression level (1-3=fast, 4-9=balanced, 10+=slow)")

    # For allowed_origins, strip '' to ensure we're passing on valid JSON via env
    # Tell pydantic *not* to touch this env var - our validator will.
    allowed_origins: Annotated[Set[str], NoDecode] = {
        "http://localhost",
        "http://localhost:4444",
    }

    # Security validation thresholds
    min_secret_length: int = 32
    min_password_length: int = 12
    require_strong_secrets: bool = False  # Default to False for backward compatibility, will be enforced in 1.0.0

    llmchat_enabled: bool = Field(default=False, description="Enable LLM Chat feature")
    toolops_enabled: bool = Field(default=False, description="Enable ToolOps feature")

    # redis configurations for Maintaining Chat Sessions in multi-worker environment
    llmchat_session_ttl: int = Field(default=300, description="Seconds for active_session key TTL")
    llmchat_session_lock_ttl: int = Field(default=30, description="Seconds for lock expiry")
    llmchat_session_lock_retries: int = Field(default=10, description="How many times to poll while waiting")
    llmchat_session_lock_wait: float = Field(default=0.2, description="Seconds between polls")
    llmchat_chat_history_ttl: int = Field(default=3600, description="Seconds for chat history expiry")
    llmchat_chat_history_max_messages: int = Field(default=50, description="Maximum message history to store per user")

    # LLM Settings (Internal API for LLM Chat)
    llm_api_prefix: str = Field(default="/v1", description="API prefix for internal LLM endpoints")
    llm_request_timeout: int = Field(default=120, description="Request timeout in seconds for LLM API calls")
    llm_streaming_enabled: bool = Field(default=True, description="Enable streaming responses for LLM Chat")
    llm_health_check_interval: int = Field(default=300, description="Provider health check interval in seconds")

    @field_validator("allowed_roots", mode="before")
    @classmethod
    def parse_allowed_roots(cls, v):
        """Parse allowed roots from environment variable or config value.

        Args:
            v: The input value to parse

        Returns:
            list: Parsed list of allowed root paths
        """
        if isinstance(v, str):
            # Support both JSON array and comma-separated values
            v = v.strip()
            if not v:
                return []
            # Try JSON first
            try:
                loaded = json.loads(v)
                if isinstance(loaded, list):
                    return loaded
            except json.JSONDecodeError:
                # Not a valid JSON array → fallback to comma-separated parsing
                pass
            # Fallback to comma-split
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("jwt_secret_key", "auth_encryption_secret")
    @classmethod
    def validate_secrets(cls, v: Any, info: ValidationInfo) -> SecretStr:
        """
        Validate that secret keys meet basic security requirements.

        This validator is applied to the `jwt_secret_key` and `auth_encryption_secret` fields.
        It performs the following checks:

        1. Detects default or weak secrets (e.g., "changeme", "secret", "password").
        Logs a warning if detected.

        2. Checks minimum length (at least 32 characters). Logs a warning if shorter.

        3. Performs a basic entropy check (at least 10 unique characters). Logs a warning if low.

        Notes:
            - Logging is used for warnings; the function does not raise exceptions.
            - The original value is returned as a `SecretStr` for safe handling.

        Args:
            v: The secret value to validate.
            info: Pydantic validation info object, used to get the field name.

        Returns:
            SecretStr: The validated secret value, wrapped as a SecretStr if it wasn't already.
        """

        field_name = info.field_name

        # Extract actual string value safely
        if isinstance(v, SecretStr):
            value = v.get_secret_value()
        else:
            value = str(v)

        # Check for default/weak secrets
        if not info.data.get("client_mode"):
            weak_secrets = ["my-test-key", "my-test-salt", "changeme", "secret", "password"]
            if value.lower() in weak_secrets:
                logger.warning(f"🔓 SECURITY WARNING - {field_name}: Default/weak secret detected! Please set a strong, unique value for production.")

            # Check minimum length
            if len(value) < 32:
                logger.warning(f"⚠️  SECURITY WARNING - {field_name}: Secret should be at least 32 characters long. Current length: {len(value)}")

            # Basic entropy check (at least 10 unique characters)
            if len(set(value)) < 10:
                logger.warning(f"🔑 SECURITY WARNING - {field_name}: Secret has low entropy. Consider using a more random value.")

        # Always return SecretStr to keep it secret-safe
        return v if isinstance(v, SecretStr) else SecretStr(value)

    @field_validator("basic_auth_password")
    @classmethod
    def validate_admin_password(cls, v: str | SecretStr, info: ValidationInfo) -> SecretStr:
        """Validate admin password meets security requirements.

        Args:
            v: The admin password value to validate.
            info: ValidationInfo containing field data.

        Returns:
            SecretStr: The validated admin password value, wrapped as SecretStr.
        """
        # Extract actual string value safely
        if isinstance(v, SecretStr):
            value = v.get_secret_value()
        else:
            value = v

        if not info.data.get("client_mode"):
            if value == "changeme":  # nosec B105 - checking for default value
                logger.warning("🔓 SECURITY WARNING: Default admin password detected! Please change the BASIC_AUTH_PASSWORD immediately.")

            # Note: We can't access password_min_length here as it's not set yet during validation
            # Using default value of 8 to match the field default
            min_length = 8  # This matches the default in password_min_length field
            if len(value) < min_length:
                logger.warning(f"⚠️  SECURITY WARNING: Admin password should be at least {min_length} characters long. Current length: {len(value)}")

            # Check password complexity
            has_upper = any(c.isupper() for c in value)
            has_lower = any(c.islower() for c in value)
            has_digit = any(c.isdigit() for c in value)
            has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', value))

            complexity_score = sum([has_upper, has_lower, has_digit, has_special])
            if complexity_score < 3:
                logger.warning("🔐 SECURITY WARNING: Admin password has low complexity. Should contain at least 3 of: uppercase, lowercase, digits, special characters")

        # Always return SecretStr to keep it secret-safe
        return v if isinstance(v, SecretStr) else SecretStr(value)

    @field_validator("allowed_origins")
    @classmethod
    def validate_cors_origins(cls, v: Any, info: ValidationInfo) -> set[str] | None:
        """Validate CORS allowed origins.

        Args:
            v: The set of allowed origins to validate.
            info: ValidationInfo containing field data.

        Returns:
            set: The validated set of allowed origins.

        Raises:
            ValueError: If allowed_origins is not a set or list of strings.
        """
        if v is None:
            return v
        if not isinstance(v, (set, list)):
            raise ValueError("allowed_origins must be a set or list of strings")

        dangerous_origins = ["*", "null", ""]
        if not info.data.get("client_mode"):
            for origin in v:
                if origin in dangerous_origins:
                    logger.warning(f"🌐 SECURITY WARNING: Dangerous CORS origin '{origin}' detected. Consider specifying explicit origins instead of wildcards.")

                # Validate URL format
                if not origin.startswith(("http://", "https://")) and origin not in dangerous_origins:
                    logger.warning(f"⚠️  SECURITY WARNING: Invalid origin format '{origin}'. Origins should start with http:// or https://")

        return set({str(origin) for origin in v})

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str, info: ValidationInfo) -> str:
        """Validate database connection string security.

        Args:
            v: The database URL to validate.
            info: ValidationInfo containing field data.

        Returns:
            str: The validated database URL.
        """
        # Check for hardcoded passwords in non-SQLite databases
        if not info.data.get("client_mode"):
            if not v.startswith("sqlite"):
                if "password" in v and any(weak in v for weak in ["password", "123", "admin", "test"]):
                    logger.warning("Potentially weak database password detected. Consider using a stronger password.")

            # Warn about SQLite in production
            if v.startswith("sqlite"):
                logger.info("Using SQLite database. Consider PostgreSQL or MySQL for production.")

        return v

    @model_validator(mode="after")
    def validate_security_combinations(self) -> Self:
        """Validate security setting combinations.  Only logs warnings; no changes are made.

        Returns:
            Itself.
        """
        if self.client_mode:
            return self

        # Check for dangerous combinations - only log warnings, don't raise errors
        if not self.auth_required and self.mcpgateway_ui_enabled:
            logger.warning("🔓 SECURITY WARNING: Admin UI is enabled without authentication. Consider setting AUTH_REQUIRED=true for production.")

        if self.skip_ssl_verify and not self.dev_mode:
            logger.warning("🔓 SECURITY WARNING: SSL verification is disabled in non-dev mode. This is a security risk! Set SKIP_SSL_VERIFY=false for production.")

        if self.debug and not self.dev_mode:
            logger.warning("🐛 SECURITY WARNING: Debug mode is enabled in non-dev mode. This may leak sensitive information! Set DEBUG=false for production.")

        # Warn about federation without auth
        if self.federation_enabled and not self.auth_required:
            logger.warning("🌐 SECURITY WARNING: Federation is enabled without authentication. This may expose your gateway to unauthorized access.")

        return self

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

    class SecurityStatus(TypedDict):
        """TypedDict for comprehensive security status."""

        secure_secrets: bool
        auth_enabled: bool
        ssl_verification: bool
        debug_disabled: bool
        cors_restricted: bool
        ui_protected: bool
        warnings: List[str]
        security_score: int

    def get_security_status(self) -> SecurityStatus:
        """Get comprehensive security status.

        Returns:
            SecurityStatus: Dictionary containing security status information including score and warnings.
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
    def _parse_allowed_origins(cls, v: Any) -> Set[str]:
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
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="ERROR")
    log_requests: bool = Field(default=False, description="Enable request payload logging with sensitive data masking")
    log_format: Literal["json", "text"] = "json"  # json or text
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

    # ===================================
    # Observability Configuration
    # ===================================

    # Enable observability features (traces, spans, metrics)
    observability_enabled: bool = Field(default=False, description="Enable observability tracing and metrics collection")

    # Automatic HTTP request tracing
    observability_trace_http_requests: bool = Field(default=True, description="Automatically trace HTTP requests")

    # Trace retention period (days)
    observability_trace_retention_days: int = Field(default=7, ge=1, description="Number of days to retain trace data")

    # Maximum traces to store (prevents unbounded growth)
    observability_max_traces: int = Field(default=100000, ge=1000, description="Maximum number of traces to retain")

    # Sample rate (0.0 to 1.0) - 1.0 means trace everything
    observability_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Trace sampling rate (0.0-1.0)")

    # Exclude paths from tracing (regex patterns)
    observability_exclude_paths: List[str] = Field(default_factory=lambda: ["/health", "/healthz", "/ready", "/metrics", "/static/.*"], description="Paths to exclude from tracing (regex)")

    # Enable performance metrics
    observability_metrics_enabled: bool = Field(default=True, description="Enable metrics collection")

    # Enable span events
    observability_events_enabled: bool = Field(default=True, description="Enable event logging within spans")

    # Correlation ID Settings
    correlation_id_enabled: bool = Field(default=True, description="Enable automatic correlation ID tracking for requests")
    correlation_id_header: str = Field(default="X-Correlation-ID", description="HTTP header name for correlation ID")
    correlation_id_preserve: bool = Field(default=True, description="Preserve correlation IDs from incoming requests")
    correlation_id_response_header: bool = Field(default=True, description="Include correlation ID in response headers")

    # ===================================
    # Database Query Logging (N+1 Detection)
    # ===================================
    db_query_log_enabled: bool = Field(default=False, description="Enable database query logging to file (for N+1 detection)")
    db_query_log_file: str = Field(default="logs/db-queries.log", description="Path to database query log file")
    db_query_log_json_file: str = Field(default="logs/db-queries.jsonl", description="Path to JSON Lines query log file")
    db_query_log_format: str = Field(default="both", description="Log format: 'json', 'text', or 'both'")
    db_query_log_min_queries: int = Field(default=1, ge=1, description="Only log requests with >= N queries")
    db_query_log_include_params: bool = Field(default=False, description="Include query parameters (may expose sensitive data)")
    db_query_log_detect_n1: bool = Field(default=True, description="Automatically detect and flag N+1 query patterns")
    db_query_log_n1_threshold: int = Field(default=3, ge=2, description="Number of similar queries to flag as potential N+1")

    # Structured Logging Configuration
    structured_logging_enabled: bool = Field(default=True, description="Enable structured JSON logging with database persistence")
    structured_logging_database_enabled: bool = Field(default=True, description="Persist structured logs to database")
    structured_logging_external_enabled: bool = Field(default=False, description="Send logs to external systems")

    # Performance Tracking Configuration
    performance_tracking_enabled: bool = Field(default=True, description="Enable performance tracking and metrics")
    performance_threshold_database_query_ms: float = Field(default=100.0, description="Alert threshold for database queries (ms)")
    performance_threshold_tool_invocation_ms: float = Field(default=2000.0, description="Alert threshold for tool invocations (ms)")
    performance_threshold_resource_read_ms: float = Field(default=1000.0, description="Alert threshold for resource reads (ms)")
    performance_threshold_http_request_ms: float = Field(default=500.0, description="Alert threshold for HTTP requests (ms)")
    performance_degradation_multiplier: float = Field(default=1.5, description="Alert if performance degrades by this multiplier vs baseline")

    # Security Logging Configuration
    security_logging_enabled: bool = Field(default=True, description="Enable security event logging")
    security_failed_auth_threshold: int = Field(default=5, description="Failed auth attempts before high severity alert")
    security_threat_score_alert: float = Field(default=0.7, description="Threat score threshold for alerts (0.0-1.0)")
    security_rate_limit_window_minutes: int = Field(default=5, description="Time window for rate limit checks (minutes)")

    # Metrics Aggregation Configuration
    metrics_aggregation_enabled: bool = Field(default=True, description="Enable automatic log aggregation into performance metrics")
    metrics_aggregation_backfill_hours: int = Field(default=6, ge=0, le=168, description="Hours of structured logs to backfill into performance metrics on startup")
    metrics_aggregation_window_minutes: int = Field(default=5, description="Time window for metrics aggregation (minutes)")
    metrics_aggregation_auto_start: bool = Field(default=False, description="Automatically run the log aggregation loop on application startup")

    # Log Search Configuration
    log_search_max_results: int = Field(default=1000, description="Maximum results per log search query")
    log_retention_days: int = Field(default=30, description="Number of days to retain logs in database")

    # External Log Integration Configuration
    elasticsearch_enabled: bool = Field(default=False, description="Send logs to Elasticsearch")
    elasticsearch_url: Optional[str] = Field(default=None, description="Elasticsearch cluster URL")
    elasticsearch_index_prefix: str = Field(default="mcpgateway-logs", description="Elasticsearch index prefix")
    syslog_enabled: bool = Field(default=False, description="Send logs to syslog")
    syslog_host: Optional[str] = Field(default=None, description="Syslog server host")
    syslog_port: int = Field(default=514, description="Syslog server port")
    webhook_logging_enabled: bool = Field(default=False, description="Send logs to webhook endpoints")
    webhook_logging_urls: List[str] = Field(default_factory=list, description="Webhook URLs for log delivery")

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
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_up = v.upper()
        if v_up not in allowed:
            raise ValueError(f"Invalid log_level: {v}")
        return v_up

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
    federation_peers: List[HttpUrl] = Field(default_factory=list)

    @field_validator("federation_peers", mode="before")
    @classmethod
    def _parse_federation_peers(cls, v: Any) -> List[str]:
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
        if v is None:
            return []  # always return a list

        if isinstance(v, str):
            v = v.strip()
            if len(v) > 1 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            try:
                peers = json.loads(v)
            except json.JSONDecodeError:
                peers = [s.strip() for s in v.split(",") if s.strip()]
            return peers  # type: ignore[no-any-return]

        # Convert other iterables to list
        return list(v)

    federation_timeout: int = 120  # seconds
    federation_sync_interval: int = 300  # seconds

    # SSO
    # For sso_issuers strip out quotes to ensure we're passing valid JSON via env
    sso_issuers: Optional[list[HttpUrl]] = Field(default=None)

    @field_validator("sso_issuers", mode="before")
    @classmethod
    def parse_issuers(cls, v: Any) -> list[str]:
        """
        Parse and validate the SSO issuers configuration value.

        Accepts:
        - JSON array string: '["https://idp1.com", "https://idp2.com"]'
        - Comma-separated string: "https://idp1.com, https://idp2.com"
        - Empty string or None → []
        - Already-parsed list

        Args:
            v: The input value to parse.

        Returns:
            list[str]: Parsed list of issuer URLs.

        Raises:
            ValueError: If the input is not a valid format.
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
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON for SSO_ISSUERS: {v!r}")
            # Fallback to comma-separated parsing
            return [item.strip() for item in s.split(",") if item.strip()]
        raise ValueError("Invalid type for SSO_ISSUERS")

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
    max_concurrent_health_checks: int = 20  # maximum concurrent health checks per worker

    # Validation Gateway URL
    gateway_validation_timeout: int = 5  # seconds
    gateway_max_redirects: int = 5

    filelock_name: str = "gateway_service_leader.lock"

    # Default Roots
    default_roots: List[str] = []

    # Database
    db_driver: str = "mariadb+mariadbconnector"
    db_pool_size: int = 200
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_max_retries: int = 3
    db_retry_interval_ms: int = 2000

    # Cache
    cache_type: Literal["redis", "memory", "none", "database"] = "database"  # memory or redis or database
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
    plugins_cli_markup_mode: Literal["markdown", "rich", "disabled"] | None = Field(default=None, description="Set markup mode for plugins CLI")

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
    def _auto_enable_security_txt(cls, v: Any, info: ValidationInfo) -> bool:
        """Auto-enable security.txt if content is provided.

        Args:
            v: The current value of well_known_security_txt_enabled.
            info: ValidationInfo containing field data.

        Returns:
            bool: True if security.txt content is provided, otherwise the original value.
        """
        if info.data and "well_known_security_txt" in info.data:
            return bool(info.data["well_known_security_txt"].strip())
        return bool(v)

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
    def _parse_list_from_env(cls, v: None | str | list[str]) -> list[str]:
        """Parse list fields from environment values.

        Accepts either JSON arrays (e.g. '["a","b"]') or comma-separated
        strings (e.g. 'a,b'). Empty or None becomes an empty list.

        Args:
            v: The value to parse, can be None, list, or string.

        Returns:
            list: Parsed list of values.

        Raises:
            ValueError: If the value type is invalid for list field parsing.
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
        raise ValueError("Invalid type for list field")

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
        return f"{self.basic_auth_user}:{self.basic_auth_password.get_secret_value()}"

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

    class DatabaseSettings(TypedDict):
        """TypedDict for SQLAlchemy database settings."""

        pool_size: int
        max_overflow: int
        pool_timeout: int
        pool_recycle: int
        connect_args: dict[str, Any]  # consider more specific type if needed

    @property
    def database_settings(self) -> DatabaseSettings:
        """
        Get SQLAlchemy database settings.

        Returns:
            DatabaseSettings: Dictionary containing SQLAlchemy database configuration options.

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

    class CORSSettings(TypedDict):
        """TypedDict for CORS settings."""

        allow_origins: NotRequired[List[str]]
        allow_credentials: NotRequired[bool]
        allow_methods: NotRequired[List[str]]
        allow_headers: NotRequired[List[str]]

    @property
    def cors_settings(self) -> CORSSettings:
        """Get CORS settings.

        Returns:
            CORSSettings: Dictionary containing CORS configuration options.

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
    validation_safe_uri_pattern: str = r"^[a-zA-Z0-9_\-.:/?=&%{}]+$"
    validation_unsafe_uri_pattern: str = r'[<>"\'\\]'
    validation_tool_name_pattern: str = r"^[a-zA-Z][a-zA-Z0-9._-]*$"  # MCP tool naming
    validation_tool_method_pattern: str = r"^[a-zA-Z][a-zA-Z0-9_\./-]*$"

    # MCP-compliant size limits (configurable via env)
    validation_max_name_length: int = 255
    validation_max_description_length: int = 8192  # 8KB
    validation_max_template_length: int = 65536  # 64KB
    validation_max_content_length: int = 1048576  # 1MB
    validation_max_json_depth: int = Field(
        default=int(os.getenv("VALIDATION_MAX_JSON_DEPTH", "30")),
        description=(
            "Maximum allowed JSON nesting depth for tool/resource schemas. "
            "Increased from 10 to 30 for compatibility with deeply nested schemas "
            "like Notion MCP (issue #1542). Override with VALIDATION_MAX_JSON_DEPTH "
            "environment variable. Minimum: 1, Maximum: 100"
        ),
        ge=1,
        le=100,
    )
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
    enable_overwrite_base_headers: bool = Field(default=False, description="Enable overwriting of base headers")

    # Passthrough headers configuration
    default_passthrough_headers: List[str] = Field(default_factory=list)

    # ===================================
    # Pagination Configuration
    # ===================================

    # Default number of items per page for paginated endpoints
    pagination_default_page_size: int = Field(default=50, ge=1, le=1000, description="Default number of items per page")

    # Maximum allowed items per page (prevents abuse)
    pagination_max_page_size: int = Field(default=500, ge=1, le=10000, description="Maximum allowed items per page")

    # Minimum items per page
    pagination_min_page_size: int = Field(default=1, ge=1, description="Minimum items per page")

    # Threshold for switching from offset to cursor-based pagination
    pagination_cursor_threshold: int = Field(default=10000, ge=1, description="Threshold for cursor-based pagination")

    # Enable cursor-based pagination globally
    pagination_cursor_enabled: bool = Field(default=True, description="Enable cursor-based pagination")

    # Default sort field for paginated queries
    pagination_default_sort_field: str = Field(default="created_at", description="Default sort field")

    # Default sort order for paginated queries
    pagination_default_sort_order: str = Field(default="desc", pattern="^(asc|desc)$", description="Default sort order")

    # Maximum offset allowed for offset-based pagination (prevents abuse)
    pagination_max_offset: int = Field(default=100000, ge=0, description="Maximum offset for pagination")

    # Cache pagination counts for performance (seconds)
    pagination_count_cache_ttl: int = Field(default=300, ge=0, description="Cache TTL for pagination counts")

    # Enable pagination links in API responses
    pagination_include_links: bool = Field(default=True, description="Include pagination links")

    # Base URL for pagination links (defaults to request URL)
    pagination_base_url: Optional[str] = Field(default=None, description="Base URL for pagination links")

    # Ed25519 keys for signing
    enable_ed25519_signing: bool = Field(default=False, description="Enable Ed25519 signing for certificates")
    prev_ed25519_private_key: SecretStr = Field(default=SecretStr(""), description="Previous Ed25519 private key for signing")
    prev_ed25519_public_key: Optional[str] = Field(default=None, description="Derived previous Ed25519 public key")
    ed25519_private_key: SecretStr = Field(default=SecretStr(""), description="Ed25519 private key for signing")
    ed25519_public_key: Optional[str] = Field(default=None, description="Derived Ed25519 public key")

    @model_validator(mode="after")
    def derive_public_keys(self) -> "Settings":
        """
        Derive public keys after all individual field validations are complete.

        Returns:
            Settings: The updated Settings instance with derived public keys.
        """
        for private_key_field in ["ed25519_private_key", "prev_ed25519_private_key"]:
            public_key_field = private_key_field.replace("private", "public")

            # 1. Get the private key SecretStr object
            private_key_secret: SecretStr = getattr(self, private_key_field)

            # 2. Proceed only if a key is present and the public key hasn't been set
            pem = private_key_secret.get_secret_value().strip()
            if not pem:
                continue

            try:
                # Load the private key
                private_key = serialization.load_pem_private_key(pem.encode(), password=None)
                if not isinstance(private_key, ed25519.Ed25519PrivateKey):
                    # This check is useful, though model_validator should not raise
                    # for an invalid key if the field validator has already passed.
                    continue

                # Derive and PEM-encode the public key
                public_key = private_key.public_key()
                public_pem = public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode()

                # 3. Set the public key attribute directly on the model instance (self)
                setattr(self, public_key_field, public_pem)
                # logger.info(f"Derived and stored {public_key_field} automatically.")

            except Exception:
                logger.warning("Failed to derive public key for private_key")
                # You can choose to raise an error here if a failure should halt model creation

        return self

    def __init__(self, **kwargs: Any) -> None:
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

    def log_summary(self) -> None:
        """
        Log a summary of the application settings.

        Dumps the current settings to a dictionary while excluding sensitive
        information such as `database_url` and `memcached_url`, and logs it
        at the INFO level.

        This method is useful for debugging or auditing purposes without
        exposing credentials or secrets in logs.
        """
        summary = self.model_dump(exclude={"database_url", "memcached_url"})
        logger.info(f"Application settings summary: {summary}")

    ENABLE_METRICS: bool = Field(True, description="Enable Prometheus metrics instrumentation")
    METRICS_EXCLUDED_HANDLERS: str = Field("", description="Comma-separated regex patterns for paths to exclude from metrics")
    METRICS_NAMESPACE: str = Field("default", description="Prometheus metrics namespace")
    METRICS_SUBSYSTEM: str = Field("", description="Prometheus metrics subsystem")
    METRICS_CUSTOM_LABELS: str = Field("", description='Comma-separated "key=value" pairs for static custom labels')


@lru_cache()
def get_settings(**kwargs: Any) -> Settings:
    """Get cached settings instance.

    Args:
        **kwargs: Keyword arguments to pass to the Settings setup.

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
    cfg = Settings(**kwargs)
    # Validate that transport_type is correct; will
    # raise if mis-configured.
    cfg.validate_transport()
    # Ensure sqlite DB directories exist if needed.
    cfg.validate_database()
    # Return the one-and-only Settings instance (cached).
    return cfg


def generate_settings_schema() -> dict[str, Any]:
    """
    Return the JSON Schema describing the Settings model.

    This schema can be used for validation or documentation purposes.

    Returns:
        dict: A dictionary representing the JSON Schema of the Settings model.
    """
    return Settings.model_json_schema(mode="validation")


# Lazy "instance" of settings
class LazySettingsWrapper:
    """Lazily initialize settings singleton on getattr"""

    def __getattr__(self, key: str) -> Any:
        """Get the real settings object and forward to it

        Args:
            key: The key to fetch from settings

        Returns:
            Any: The value of the attribute on the settings
        """
        return getattr(get_settings(), key)


settings = LazySettingsWrapper()


if __name__ == "__main__":
    if "--schema" in sys.argv:
        schema = generate_settings_schema()
        print(json.dumps(schema, indent=2))
        sys.exit(0)
    settings.log_summary()
