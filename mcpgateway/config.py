# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

ContextForge AI Gateway Configuration.
This module defines configuration settings for ContextForge AI Gateway using Pydantic.
It loads configuration from environment variables with sensible defaults.

Environment variables:
- APP_NAME: Gateway name (default: "ContextForge")
- HOST: Host to bind to (default: "127.0.0.1")
- PORT: Port to listen on (default: 4444)
- DATABASE_URL: SQLite database URL (default: "sqlite:///./mcp.db")
- BASIC_AUTH_USER: Username for API Basic auth when enabled (default: "admin")
- BASIC_AUTH_PASSWORD: Password for API Basic auth when enabled (default: "changeme")
- LOG_LEVEL: Logging level (default: "INFO")
- SKIP_SSL_VERIFY: Disable SSL verification (default: False)
- AUTH_REQUIRED: Require authentication (default: True)
- TRANSPORT_TYPE: Transport mechanisms (default: "all")
- DOCS_ALLOW_BASIC_AUTH: Allow basic auth for docs (default: False)
- RESOURCE_CACHE_SIZE: Max cached resources (default: 1000)
- RESOURCE_CACHE_TTL: Cache TTL in seconds (default: 3600)
- TOOL_TIMEOUT: Tool invocation timeout (default: 60)
- PROMPT_CACHE_SIZE: Max cached prompts (default: 100)
- HEALTH_CHECK_INTERVAL: Gateway health check interval (default: 300)
- REQUIRE_TOKEN_EXPIRATION: Require JWT tokens to have expiration (default: True)
- REQUIRE_JTI: Require JTI claim in tokens for revocation (default: True)
- REQUIRE_USER_IN_DB: Require all users to exist in database (default: False)

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
import logging
import os
from pathlib import Path
import re
import sys
from typing import Annotated, Any, ClassVar, Dict, List, Literal, NotRequired, Optional, Self, Set, TypedDict
from urllib.parse import urlparse

# Third-Party
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import orjson
from pydantic import AliasChoices, Field, field_validator, HttpUrl, model_validator, PositiveInt, SecretStr, ValidationInfo
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Only configure basic logging if no handlers exist yet
# This prevents conflicts with LoggingService while ensuring config logging works
if not logging.getLogger().handlers:
    # Respect LOG_LEVEL environment variable for early logging configuration
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
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
        "SSO_ENTRA_ADMIN_GROUPS",
        "LOG_DETAILED_SKIP_ENDPOINTS",
        "CONTENT_ALLOWED_RESOURCE_MIMETYPES",
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
                orjson.loads(s)
                continue
            except Exception:
                pass  # nosec B110 - Intentionally continue with CSV parsing if JSON parsing fails
        # Convert CSV to JSON array
        items = [item.strip() for item in s.split(",") if item.strip()]
        os.environ[key] = orjson.dumps(items).decode()


_normalize_env_list_vars()


# Default content type for outgoing requests to Forge
FORGE_CONTENT_TYPE = os.getenv("FORGE_CONTENT_TYPE", "application/json")

# UI embedding / visibility controls
UI_HIDABLE_SECTIONS = frozenset(
    {
        "overview",
        "servers",
        "gateways",
        "tools",
        "prompts",
        "resources",
        "roots",
        "mcp-registry",
        "metrics",
        "plugins",
        "export-import",
        "logs",
        "version-info",
        "maintenance",
        "teams",
        "users",
        "agents",
        "grpc-services",
        "tokens",
        "settings",
    }
)
UI_HIDABLE_HEADER_ITEMS = frozenset({"logout", "team_selector", "user_identity", "theme_toggle"})
UI_HIDE_SECTION_ALIASES = {
    "catalog": "servers",
    "virtual_servers": "servers",
    "a2a-agents": "agents",
    "a2a": "agents",
    "api_tokens": "tokens",
    "llm-settings": "settings",
}


class Settings(BaseSettings):
    """
    ContextForge AI Gateway configuration settings.

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
        'ContextForge'
        >>> s5.host in ('0.0.0.0', '127.0.0.1')  # Default can be either
        True
        >>> s5.port
        4444
        >>> s5.auth_required
        True
        >>> isinstance(s5.allowed_origins, set)
        True
        >>> s6 = Settings(log_detailed_skip_endpoints=["/metrics", "/health"])
        >>> s6.log_detailed_skip_endpoints
        ['/metrics', '/health']
        >>> s7 = Settings(log_detailed_sample_rate=0.5)
        >>> s7.log_detailed_sample_rate
        0.5
        >>> s8 = Settings(log_resolve_user_identity=True)
        >>> s8.log_resolve_user_identity
        True
        >>> s9 = Settings()
        >>> s9.log_detailed_skip_endpoints
        []
        >>> s9.log_detailed_sample_rate
        1.0
        >>> s9.log_resolve_user_identity
        False
    """

    # Basic Settings
    app_name: str = "ContextForge"
    host: str = "127.0.0.1"
    port: PositiveInt = Field(default=4444, ge=1, le=65535)
    client_mode: bool = False
    docs_allow_basic_auth: bool = False  # Allow basic auth for docs
    api_allow_basic_auth: bool = Field(
        default=False,
        description="Allow Basic authentication for API endpoints. Disabled by default for security. Use JWT or API tokens instead.",
    )
    database_url: str = Field(
        default="sqlite:///./mcp.db",
        description=(
            "Database connection URL. Supports SQLite (dev) and PostgreSQL (production). "
            "For PostgreSQL with custom schema, use the 'options' query parameter: "
            "postgresql://user:pass@host:5432/db?options=-c%20search_path=schema_name "
            "(See Issue #1535 for details)"
        ),
    )

    # Absolute paths resolved at import-time (still override-able via env vars)
    templates_dir: Path = Field(default_factory=lambda: Path(str(files("mcpgateway") / "templates")))
    static_dir: Path = Field(default_factory=lambda: Path(str(files("mcpgateway") / "static")))

    # Template auto-reload: False for production (default), True for development
    # Disabling prevents re-parsing templates on each request, improving performance under load
    # Use TEMPLATES_AUTO_RELOAD=true for development (make dev sets this automatically)
    templates_auto_reload: bool = Field(default=False, description="Auto-reload Jinja2 templates on change (enable for development)")

    app_root_path: str = ""

    # Protocol
    protocol_version: str = "2025-11-25"
    experimental_rust_mcp_runtime_enabled: bool = Field(
        default=False,
        description="Proxy POST /mcp traffic through the experimental Rust MCP runtime sidecar.",
    )
    experimental_rust_mcp_runtime_url: str = Field(
        default="http://127.0.0.1:8787",
        description="Base URL for the experimental Rust MCP runtime sidecar.",
    )
    experimental_rust_mcp_runtime_uds: Optional[str] = Field(
        default=None,
        description="Optional Unix domain socket path for the experimental Rust MCP runtime sidecar.",
    )
    experimental_rust_mcp_runtime_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout in seconds for Python-to-Rust MCP runtime proxy requests.",
    )
    experimental_rust_mcp_session_core_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned MCP session metadata core while keeping Python as the fallback transport backend.",
    )
    experimental_rust_mcp_event_store_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned resumable MCP event-store backend for Streamable HTTP sessions.",
    )
    experimental_rust_mcp_resume_core_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned public MCP replay/resume path for GET /mcp with Last-Event-ID while keeping Python fallback available.",
    )
    experimental_rust_mcp_live_stream_core_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned public MCP live GET /mcp SSE path while keeping Python as the fallback upstream stream source.",
    )
    experimental_rust_mcp_affinity_core_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned MCP session-affinity forwarding path while keeping Python worker forwarding as the fallback.",
    )
    experimental_rust_mcp_session_auth_reuse_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust-owned MCP session-bound auth-context reuse path for direct public /mcp ingress.",
    )
    mcp_rust_ingress: Literal["internal", "public"] = Field(
        default="internal",
        description=(
            "Selects which Rust MCP ingress shape MCPIngressMount uses when boot mode is "
            "edge or full and no shadow override is in effect. 'internal' (default) uses "
            "the trusted Python→Rust forwarder (RustMCPRuntimeProxy) over the internal "
            "listener at MCP_RUST_LISTEN_HTTP/UDS; 'public' uses an nginx-style reverse "
            "proxy to the Rust public listener at MCP_RUST_PUBLIC_LISTEN_HTTP — useful "
            "for single-process deployments without nginx in front. Pydantic rejects "
            "any other value at config load."
        ),
    )
    mcp_rust_public_proxy_upstream: str = Field(
        default="http://127.0.0.1:8787",
        description=(
            "Upstream URL the 'public' MCP ingress shape forwards to. Defaults to the " "loopback address that matches docker-entrypoint.sh's " "MCP_RUST_PUBLIC_LISTEN_HTTP=0.0.0.0:8787 default."
        ),
    )
    experimental_rust_a2a_runtime_enabled: bool = Field(
        default=False,
        description="Enable the experimental Rust A2A runtime sidecar for registered A2A agent invocations.",
    )
    experimental_rust_a2a_runtime_delegate_enabled: bool = Field(
        default=False,
        description="Delegate registered A2A agent invocations to the experimental Rust A2A runtime sidecar.",
    )
    experimental_rust_a2a_runtime_managed: bool = Field(
        default=True,
        description="Whether the gateway should launch and supervise the experimental Rust A2A runtime sidecar locally.",
    )
    experimental_rust_a2a_runtime_url: str = Field(
        default="http://127.0.0.1:8788",
        description="Base URL for the experimental Rust A2A runtime sidecar.",
    )
    experimental_rust_a2a_runtime_uds: Optional[str] = Field(
        default=None,
        description="Optional Unix domain socket path for the experimental Rust A2A runtime sidecar.",
    )
    experimental_rust_a2a_runtime_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Timeout in seconds for Python-to-Rust A2A runtime proxy requests.",
    )

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
    jwt_issuer_verification: bool = True
    auth_required: bool = True
    allow_unauthenticated_admin: bool = Field(
        default=False,
        description="Allow unauthenticated requests to receive platform-admin context when AUTH_REQUIRED=false (dangerous; development-only override).",
    )
    # Session token configuration (short-lived for security)
    token_expiry: int = Field(default=20, ge=5, le=1440, description="Session token expiry in minutes (5-1440). Recommended: 5-20 minutes for security.")  # 20 minutes (was 10080 = 70 days)

    # Idle timeout configuration
    token_idle_timeout: int = Field(default=60, ge=5, le=1440, description="Maximum idle time in minutes before token requires refresh (5-1440).")  # 60 minutes

    # Token blocklist cleanup
    token_blocklist_cleanup_hours: int = Field(default=24, ge=1, le=168, description="Hours to retain expired tokens in blocklist before cleanup (1-168).")

    require_token_expiration: bool = Field(default=True, description="Require all JWT tokens to have expiration claims (secure default)")
    require_jti: bool = Field(default=True, description="Require JTI (JWT ID) claim in all tokens for revocation support (secure default)")
    require_user_in_db: bool = Field(
        default=False,
        description="Require all authenticated users to exist in the database. When true, disables the platform admin bootstrap mechanism. WARNING: Enabling this on a fresh deployment will lock you out.",
    )
    embed_environment_in_tokens: bool = Field(default=False, description="Embed environment claim in gateway-issued JWTs for environment isolation")
    validate_token_environment: bool = Field(default=False, description="Reject tokens with mismatched environment claim (tokens without env claim are allowed)")

    # JSON Schema Validation for registration (Tool Input Schemas, Prompt schemas, etc)
    json_schema_validation_strict: bool = Field(default=True, description="Strict schema validation mode - reject invalid JSON schemas")

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
    sso_okta_scope: str = Field(default="openid profile email", description="Okta OIDC scopes (space-separated)")
    okta_group_mapping: Optional[str] = Field(default=None, description="JSON mapping of Okta group names to team UUIDs")

    sso_keycloak_enabled: bool = Field(default=False, description="Enable Keycloak OIDC authentication")
    sso_keycloak_base_url: Optional[str] = Field(default=None, description="Keycloak base URL (e.g., https://keycloak.example.com)")
    sso_keycloak_public_base_url: Optional[str] = Field(
        default=None,
        description="Browser-facing Keycloak base URL for authorization redirects (e.g., http://localhost:8180)",
    )
    sso_keycloak_realm: str = Field(default="master", description="Keycloak realm name")
    sso_keycloak_client_id: Optional[str] = Field(default=None, description="Keycloak client ID")
    sso_keycloak_client_secret: Optional[SecretStr] = Field(default=None, description="Keycloak client secret")
    sso_keycloak_map_realm_roles: bool = Field(default=True, description="Map Keycloak realm roles to gateway teams")
    sso_keycloak_map_client_roles: bool = Field(default=False, description="Map Keycloak client roles to gateway RBAC")
    sso_keycloak_role_mappings: Dict[str, str] = Field(default_factory=dict, description="Map Keycloak groups/roles to ContextForge roles (JSON: {group_or_role: role_name})")
    sso_keycloak_default_role: Optional[str] = Field(default=None, description="Default ContextForge role for Keycloak users without role mapping")
    sso_keycloak_resolve_team_scope_to_personal_team: bool = Field(default=False, description="Resolve team-scoped Keycloak role mappings to the user's personal team")
    sso_keycloak_username_claim: str = Field(default="preferred_username", description="JWT claim for username")

    # Security Validation & Sanitization
    experimental_validate_io: bool = Field(default=False, description="Enable experimental input validation and output sanitization")
    experimental_rust_request_logging_masking_enabled: bool = Field(
        default=False,
        description="Enable experimental Rust native extension for request logging sensitive-data masking",
    )
    validation_middleware_enabled: bool = Field(default=False, description="Enable validation middleware for all requests")
    validation_strict: bool = Field(default=True, description="Strict validation mode - reject on violations")
    sanitize_output: bool = Field(default=True, description="Sanitize output to remove control characters")
    allowed_roots: List[str] = Field(default_factory=list, description="Allowed root paths for resource access")
    max_path_depth: int = Field(default=10, description="Maximum allowed path depth")
    max_param_length: int = Field(default=10000, description="Maximum parameter length")
    meta_max_keys: int = Field(default=16, description="Maximum number of keys in user-supplied meta_data forwarded to upstream MCP servers (CWE-400)")
    meta_max_depth: int = Field(default=2, description="Maximum nesting depth for user-supplied meta_data forwarded to upstream MCP servers (CWE-400)")
    meta_max_bytes: int = Field(default=4096, description="Maximum JSON-encoded byte size for user-supplied meta_data forwarded to upstream MCP servers (CWE-400)")
    dangerous_patterns: List[str] = Field(
        default_factory=lambda: [
            r"[;&|`$(){}\[\]<>]",  # Shell metacharacters
            r"\.\.[\\/]",  # Path traversal
            r"[\x00-\x1f\x7f-\x9f]",  # Control characters
        ],
        description="Regex patterns for dangerous input",
    )
    tool_description_forbidden_patterns_enabled: bool = Field(default=True, description="Enable forbidden pattern validation on tool descriptions. Set to false to disable all checks.")
    tool_description_forbidden_patterns: List[str] = Field(
        default_factory=lambda: ["&&", "||", "$(", "> ", "< "],
        description='Substrings forbidden in tool descriptions. Override via TOOL_DESCRIPTION_FORBIDDEN_PATTERNS env var as a JSON array, e.g. \'["&&","||"]\'.',
    )

    sso_keycloak_email_claim: str = Field(default="email", description="JWT claim for email")
    sso_keycloak_groups_claim: str = Field(default="groups", description="JWT claim for groups/roles")

    sso_entra_enabled: bool = Field(default=False, description="Enable Microsoft Entra ID OIDC authentication")
    sso_entra_client_id: Optional[str] = Field(default=None, description="Microsoft Entra ID client ID")
    sso_entra_client_secret: Optional[SecretStr] = Field(default=None, description="Microsoft Entra ID client secret")
    sso_entra_tenant_id: Optional[str] = Field(default=None, description="Microsoft Entra ID tenant ID")
    sso_entra_groups_claim: str = Field(default="groups", description="JWT claim for EntraID groups (groups/roles)")
    sso_entra_admin_groups: Annotated[list[str], NoDecode] = Field(default_factory=list, description="EntraID groups granting platform_admin role (CSV/JSON)")
    sso_entra_role_mappings: Dict[str, str] = Field(default_factory=dict, description="Map EntraID groups to ContextForge roles (JSON: {group_id: role_name})")
    sso_entra_default_role: Optional[str] = Field(default=None, description="Default role for EntraID users without group mapping (None = no role assigned)")
    sso_entra_sync_roles_on_login: bool = Field(default=True, description="Synchronize role assignments on each login")
    sso_entra_graph_api_enabled: bool = Field(default=True, description="Enable Microsoft Graph fallback for EntraID groups overage claims")
    sso_entra_graph_api_timeout: int = Field(default=10, ge=1, le=120, description="Timeout in seconds for Microsoft Graph group fallback requests")
    sso_entra_graph_api_max_groups: int = Field(default=0, ge=0, description="Maximum groups to keep from Graph fallback (0 = no limit)")

    sso_adfs_enabled: bool = Field(default=False, description="Enable ADFS OIDC authentication")
    sso_adfs_client_id: Optional[str] = Field(default=None, description="ADFS OAuth client ID")
    sso_adfs_client_secret: Optional[SecretStr] = Field(default=None, description="ADFS OAuth client secret")
    sso_adfs_authorization_url: Optional[str] = Field(default=None, description="ADFS authorization endpoint URL (e.g., https://adfs.example.com/adfs/oauth2/authorize/)")
    sso_adfs_token_url: Optional[str] = Field(default=None, description="ADFS token endpoint URL (e.g., https://adfs.example.com/adfs/oauth2/token/)")
    sso_adfs_issuer: Optional[str] = Field(default=None, description="ADFS issuer URL (e.g., https://adfs.example.com/adfs)")
    sso_adfs_scope: Optional[str] = Field(default="openid profile email", description="ADFS OAuth scopes (space-separated)")
    sso_adfs_display_name: Optional[str] = Field(default="ADFS Login", description="Display name shown on login page for ADFS")

    sso_generic_enabled: bool = Field(default=False, description="Enable generic OIDC provider (Keycloak, Auth0, etc.)")
    sso_generic_provider_id: Optional[str] = Field(default=None, description="Provider ID (e.g., 'keycloak', 'auth0', 'authentik')")
    sso_generic_display_name: Optional[str] = Field(default=None, description="Display name shown on login page")
    sso_generic_client_id: Optional[str] = Field(default=None, description="Generic OIDC client ID")
    sso_generic_client_secret: Optional[SecretStr] = Field(default=None, description="Generic OIDC client secret")
    sso_generic_authorization_url: Optional[str] = Field(default=None, description="Authorization endpoint URL")
    sso_generic_token_url: Optional[str] = Field(default=None, description="Token endpoint URL")
    sso_generic_userinfo_url: Optional[str] = Field(default=None, description="Userinfo endpoint URL")
    sso_generic_issuer: Optional[str] = Field(default=None, description="OIDC issuer URL")
    sso_generic_jwks_uri: Optional[str] = Field(default=None, description="OIDC JWKS endpoint URL for token signature verification")
    sso_generic_scope: Optional[str] = Field(default="openid profile email", description="OAuth scopes (space-separated)")

    # SSO Settings
    sso_auto_create_users: bool = Field(default=True, description="Automatically create users from SSO providers")
    sso_trusted_domains: Annotated[list[str], NoDecode] = Field(default_factory=list, description="Trusted email domains (CSV or JSON list)")
    sso_preserve_admin_auth: bool = Field(default=True, description="Preserve local admin authentication when SSO is enabled")
    sso_auto_disable_unconfigured_providers: bool = Field(
        default=False,
        description=(
            "Automatically disable SSO providers not present in environment configuration during bootstrap. "
            "When enabled, providers configured in the database but missing from SSO_*_ENABLED environment variables "
            "will be disabled. This enforces environment config as the single source of truth. "
            "Default: false (preserves manually configured providers for backward compatibility)."
        ),
    )

    # SSO Admin Assignment Settings
    sso_auto_admin_domains: Annotated[list[str], NoDecode] = Field(default_factory=list, description="Admin domains (CSV or JSON list)")
    sso_github_admin_orgs: Annotated[list[str], NoDecode] = Field(default_factory=list, description="GitHub orgs granting admin (CSV/JSON)")
    sso_google_admin_domains: Annotated[list[str], NoDecode] = Field(default_factory=list, description="Google admin domains (CSV/JSON)")
    sso_require_admin_approval: bool = Field(default=False, description="Require admin approval for new SSO registrations")

    # ADFS-specific Settings
    sso_adfs_default_email_domain: Optional[str] = Field(
        default=None, description="Default email domain for ADFS when UPN is plain username (e.g., 'company.com' converts 'user123' to 'user123@company.com')"
    )

    # MCP Client Authentication
    mcp_client_auth_enabled: bool = Field(default=True, description="Enable JWT authentication for MCP client operations")
    mcp_require_auth: Optional[bool] = Field(
        default=None,
        description=(
            "Require authentication for /mcp endpoints. "
            "When unset, inherits AUTH_REQUIRED. "
            "Set false explicitly to allow unauthenticated access to public items only; "
            "set true to require a valid Bearer token for all /mcp requests."
        ),
    )
    trust_proxy_auth: bool = Field(
        default=False,
        description="Trust proxy authentication headers (required when mcp_client_auth_enabled=false)",
    )
    trust_proxy_auth_dangerously: bool = Field(
        default=False,
        description="Acknowledge and allow trusted proxy headers when MCP_CLIENT_AUTH_ENABLED=false (dangerous; only for strictly trusted proxy deployments).",
    )
    proxy_user_header: str = Field(default="X-Authenticated-User", description="Header containing authenticated username from proxy")

    #  Encryption key phrase for auth storage
    auth_encryption_secret: SecretStr = Field(default=SecretStr("my-test-salt"))

    # Query Parameter Authentication (INSECURE - disabled by default)
    insecure_allow_queryparam_auth: bool = Field(
        default=False,
        description=("Enable query parameter authentication for gateway peers. " "WARNING: API keys may appear in proxy logs. See CWE-598."),
    )
    insecure_queryparam_auth_allowed_hosts: List[str] = Field(
        default_factory=list,
        description=("Allowlist of hosts permitted to use query parameter auth. " "Empty list allows any host when feature is enabled. " "Format: ['mcp.tavily.com', 'api.example.com']"),
    )

    # ===================================
    # Identity Propagation Configuration
    # ===================================
    # Controls how end-user identity is forwarded to upstream MCP servers.

    identity_propagation_enabled: bool = Field(
        default=False,
        description="Enable end-user identity propagation to upstream MCP servers",
    )
    identity_propagation_mode: Literal["headers", "meta", "both"] = Field(
        default="both",
        description="How to propagate identity: 'headers' (HTTP headers), 'meta' (MCP _meta field), 'both'",
    )
    identity_propagation_headers_prefix: str = Field(
        default="X-Forwarded-User",
        description="Prefix for identity propagation HTTP headers",
    )
    identity_sensitive_attributes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["password_hash", "internal_id", "ssn"],
        description="User attributes to strip before propagating to upstream servers",
    )
    identity_sign_claims: bool = Field(
        default=False,
        description="Sign propagated user claims with HMAC for verification",
    )
    identity_claims_secret: Optional[str] = Field(
        default=None,
        description="Secret key for signing propagated identity claims (uses JWT_SECRET_KEY if unset)",
    )

    # ===================================
    # SSRF Protection Configuration
    # ===================================
    # Server-Side Request Forgery (SSRF) protection prevents the gateway from being
    # used to access internal resources or cloud metadata services.

    ssrf_protection_enabled: bool = Field(
        default=True,
        description="Enable SSRF protection for gateway/tool URLs. Blocks access to dangerous endpoints.",
    )

    ssrf_blocked_networks: List[str] = Field(
        default=[
            # Cloud metadata services (ALWAYS dangerous - credential exposure)
            "169.254.169.254/32",  # AWS/GCP/Azure instance metadata
            "169.254.169.123/32",  # AWS NTP service
            "fd00::1/128",  # IPv6 cloud metadata
            # Link-local (often used for cloud metadata)
            "169.254.0.0/16",  # Full link-local IPv4 range
            "fe80::/10",  # IPv6 link-local
        ],
        description=(
            "CIDR ranges to block for SSRF protection. These are ALWAYS blocked regardless of other settings. " "Default blocks cloud metadata endpoints. Add private ranges for stricter security."
        ),
    )

    ssrf_blocked_hosts: List[str] = Field(
        default=[
            "metadata.google.internal",  # GCP metadata hostname
            "metadata.internal",  # Generic cloud metadata
        ],
        description="Hostnames to block for SSRF protection. Matched case-insensitively.",
    )

    ssrf_allow_localhost: bool = Field(
        default=False,
        description=("Allow localhost/loopback addresses (127.0.0.0/8, ::1). " "Default false for safer production behavior."),
    )

    ssrf_allow_private_networks: bool = Field(
        default=False,
        description=(
            "Allow RFC 1918 private network addresses (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16). " "When false, private destinations are blocked unless explicitly listed in SSRF_ALLOWED_NETWORKS."
        ),
    )

    ssrf_allowed_networks: List[str] = Field(
        default_factory=list,
        description=("Optional CIDR allowlist for internal/private destinations. " "Used when SSRF_ALLOW_PRIVATE_NETWORKS=false to allow specific internal ranges."),
    )

    ssrf_dns_fail_closed: bool = Field(
        default=True,
        description=(
            "Fail closed on DNS resolution errors. When true, URLs that cannot be resolved "
            "are rejected. When false, unresolvable hostnames are allowed through "
            "(hostname blocklist still applies)."
        ),
    )

    # UAID Cross-Gateway Routing Security
    uaid_allowed_domains: List[str] = Field(
        default_factory=list,
        description=(
            "Domain allowlist for UAID cross-gateway routing. When not empty, only UAIDs with endpoints "
            "ending in these domains will be allowed for cross-gateway routing. Empty list = allow all domains."
        ),
    )

    uaid_max_length: int = Field(
        default=2048,
        ge=512,  # Minimum: accommodate shortest valid UAID
        le=2048,  # Maximum: MUST match database column length (a2a_agents.uaid String(2048))
        description=(
            "Maximum allowed length for UAID strings. Used to prevent DoS attacks via "
            "excessively long UAID parsing. Must not exceed database column limit (2048). "
            "Default 2048 matches database capacity. Operators can reduce for stricter DoS "
            "protection but cannot exceed database schema limit."
        ),
    )

    uaid_max_federation_hops: int = Field(
        default=5,
        ge=1,
        le=10,
        description=(
            "Maximum UAID cross-gateway federation hops. Each outbound hop stamps "
            "`X-Contextforge-UAID-Hop: N+1`; inbound calls at hop >= this limit are "
            "rejected with 404 to break recursion. Covers both A→B→A loops and "
            "self-referential `endpoint_url` loops. Default 5 accommodates "
            "multi-tenant partner chains (Prod → Partner1 → Partner2 → Partner3) "
            "while still terminating loops quickly (a ping-pong trips in 4 hops)."
        ),
    )

    # OAuth Configuration
    oauth_request_timeout: int = Field(default=30, description="OAuth request timeout in seconds")
    oauth_max_retries: int = Field(default=3, description="Maximum retries for OAuth token requests")

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
    dcr_client_name_template: str = Field(default="ContextForge ({gateway_name})", description="Template for client_name in DCR requests")

    # Refresh token behavior
    dcr_request_refresh_token_when_unsupported: bool = Field(
        default=False,
        description="Request refresh_token even when AS metadata omits grant_types_supported. Enable for AS servers that support refresh tokens but don't advertise it.",
    )

    # ===================================
    # OAuth Discovery (RFC 8414)
    # ===================================

    oauth_discovery_enabled: bool = Field(default=True, description="Enable OAuth AS metadata discovery (RFC 8414)")

    oauth_preferred_code_challenge_method: str = Field(default="S256", description="Preferred PKCE code challenge method (S256 or plain)")

    # Email-Based Authentication
    email_auth_enabled: bool = Field(default=True, description="Enable email-based authentication")
    public_registration_enabled: bool = Field(
        default=False,
        description="Allow unauthenticated users to self-register accounts. When false, only admins can create users via /admin/users endpoint.",
    )
    allow_public_visibility: bool = Field(
        default=True,
        description="When false, creating or updating any entity with public visibility is blocked in team scope.",
    )
    protect_all_admins: bool = Field(
        default=True,
        description="When true (default), prevent any admin from being demoted, deactivated, or locked out via API/UI. When false, only the last active admin is protected.",
    )
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

    # Password change enforcement and policy toggles
    password_change_enforcement_enabled: bool = Field(default=True, description="Master switch for password change enforcement checks")
    admin_require_password_change_on_bootstrap: bool = Field(default=True, description="Force admin to change password after bootstrap")
    detect_default_password_on_login: bool = Field(default=True, description="Detect default password during login and mark user for change")
    require_password_change_for_default_password: bool = Field(default=True, description="Require password change when user is created with the default password")
    password_policy_enabled: bool = Field(default=True, description="Enable password complexity validation for new/changed passwords")
    password_prevent_reuse: bool = Field(default=True, description="Prevent reusing the current password when changing")
    password_max_age_days: int = Field(default=90, description="Password maximum age in days before expiry forces a change")
    # Account Security Configuration
    max_failed_login_attempts: int = Field(default=5, description="Maximum failed login attempts before account lockout")
    account_lockout_duration_minutes: int = Field(default=60, description="Account lockout duration in minutes")
    account_lockout_notification_enabled: bool = Field(default=True, description="Send lockout notification emails when accounts are locked")
    failed_login_min_response_ms: int = Field(default=250, description="Minimum response duration for failed login attempts to reduce timing side channels")

    # Self-service password reset
    password_reset_enabled: bool = Field(default=True, description="Enable self-service password reset workflow (set false to disable public forgot/reset endpoints)")
    password_reset_token_expiry_minutes: int = Field(default=60, description="Password reset token expiration time in minutes")
    password_reset_rate_limit: int = Field(default=5, description="Maximum password reset requests allowed per email in each rate-limit window")
    password_reset_rate_window_minutes: int = Field(default=15, description="Password reset request rate-limit window in minutes")
    password_reset_invalidate_sessions: bool = Field(default=True, description="Invalidate active sessions after password reset")
    password_reset_min_response_ms: int = Field(default=250, description="Minimum response duration for forgot-password requests to reduce timing side channels")

    # Email delivery for auth notifications
    smtp_enabled: bool = Field(
        default=False,
        description="Enable SMTP email delivery for password reset and account lockout notifications (when false, reset requests are accepted but no email is sent)",
    )
    smtp_host: Optional[str] = Field(default=None, description="SMTP server host")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_user: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[SecretStr] = Field(default=None, description="SMTP password")
    smtp_from_email: Optional[str] = Field(default=None, description="From email address used for auth notifications")
    smtp_from_name: str = Field(default="ContextForge", description="From display name used for auth notifications")
    smtp_use_tls: bool = Field(default=True, description="Use STARTTLS for SMTP connections")
    smtp_use_ssl: bool = Field(default=False, description="Use implicit SSL/TLS for SMTP connections")
    smtp_timeout_seconds: int = Field(default=15, description="SMTP connection timeout in seconds")

    # Personal Teams Configuration
    auto_create_personal_teams: bool = Field(default=True, description="Enable automatic personal team creation for new users")
    personal_team_prefix: str = Field(default="", description="Personal team naming prefix")
    max_teams_per_user: int = Field(default=50, description="Maximum number of teams a user can belong to")
    max_members_per_team: int = Field(default=100, description="Maximum number of members per team")
    invitation_expiry_days: int = Field(default=7, description="Number of days before team invitations expire")
    require_email_verification_for_invites: bool = Field(default=True, description="Require email verification for team invitations")

    # Team Governance
    allow_team_creation: bool = Field(default=True, description="Allow users to create organizational teams. Admins can always create teams.")
    allow_team_join_requests: bool = Field(default=True, description="Allow users to request to join public teams")
    allow_team_invitations: bool = Field(default=True, description="Allow team owners to send invitations")

    # Default Role Configuration
    default_admin_role: str = Field(default="platform_admin", description="Global role assigned to admin users")
    default_user_role: str = Field(default="platform_viewer", description="Global role assigned to non-admin users")
    default_team_owner_role: str = Field(default="team_admin", description="Team-scoped role assigned to team owners (e.g. personal team creator)")
    default_team_member_role: str = Field(default="viewer", description="Team-scoped role assigned to team members")

    # UI/Admin Feature Flags
    mcpgateway_ui_enabled: bool = False
    mcpgateway_admin_api_enabled: bool = False
    mcpgateway_ui_airgapped: bool = Field(default=False, description="Use local CDN assets instead of external CDNs for airgapped deployments")
    mcpgateway_ui_embedded: bool = Field(default=False, description="Enable embedded UI mode (hides select header controls by default)")
    mcpgateway_ui_hide_sections: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "CSV/JSON list of UI sections to hide. "
            "Valid values: overview, servers, gateways, tools, prompts, resources, roots, mcp-registry, "
            "metrics, plugins, export-import, logs, version-info, maintenance, teams, users, agents, tokens, settings"
        ),
    )
    mcpgateway_ui_hide_header_items: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="CSV/JSON list of header items to hide. Valid values: logout, team_selector, user_identity, theme_toggle",
    )
    mcpgateway_ui_hide_sections_admin: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=("CSV/JSON list of UI sections to hide for admin users. " "Same valid values as MCPGATEWAY_UI_HIDE_SECTIONS. " "When unset, admins see all sections."),
    )
    mcpgateway_ui_hide_header_items_admin: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="CSV/JSON list of header items to hide for admin users. Same valid values as MCPGATEWAY_UI_HIDE_HEADER_ITEMS.",
    )
    mcpgateway_bulk_import_enabled: bool = True
    mcpgateway_bulk_import_max_tools: int = 200
    mcpgateway_bulk_import_rate_limit: int = 10

    # UI Tool Test Configuration
    mcpgateway_ui_tool_test_timeout: int = Field(default=60000, description="Tool test timeout in milliseconds for the admin UI")

    # Tool Execution Cancellation
    mcpgateway_tool_cancellation_enabled: bool = Field(default=True, description="Enable gateway-authoritative tool execution cancellation with REST API endpoints")

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

    # Direct Proxy Configuration (disabled by default)
    mcpgateway_direct_proxy_enabled: bool = Field(default=False, description="Enable direct_proxy gateway mode for pass-through MCP operations")
    mcpgateway_direct_proxy_timeout: int = Field(default=30, description="Default timeout in seconds for direct proxy MCP operations")

    # ===================================
    # Performance Monitoring Configuration
    # ===================================
    mcpgateway_performance_tracking: bool = Field(default=False, description="Enable performance tracking tab in admin UI")
    mcpgateway_performance_collection_interval: int = Field(default=10, ge=1, le=300, description="Metric collection interval in seconds")
    mcpgateway_performance_retention_hours: int = Field(default=24, ge=1, le=168, description="Snapshot retention period in hours")
    mcpgateway_performance_retention_days: int = Field(default=90, ge=1, le=365, description="Aggregate retention period in days")
    mcpgateway_performance_max_snapshots: int = Field(default=10000, ge=100, le=1000000, description="Maximum performance snapshots to retain")
    mcpgateway_performance_distributed: bool = Field(default=False, description="Enable distributed mode metrics aggregation via Redis")
    mcpgateway_performance_net_connections_enabled: bool = Field(default=True, description="Enable network connections counting (can be CPU intensive)")
    mcpgateway_performance_net_connections_cache_ttl: int = Field(default=15, ge=1, le=300, description="Cache TTL for net_connections in seconds")

    # MCP Server Catalog Configuration
    mcpgateway_catalog_enabled: bool = Field(default=True, description="Enable MCP server catalog feature")
    mcpgateway_catalog_file: str = Field(default="mcp-catalog.yml", description="Path to catalog configuration file")
    mcpgateway_catalog_auto_health_check: bool = Field(default=True, description="Automatically health check catalog servers")
    mcpgateway_catalog_cache_ttl: int = Field(default=3600, description="Catalog cache TTL in seconds")
    mcpgateway_catalog_page_size: int = Field(default=100, description="Number of catalog servers per page")

    # ContextForge Bootstrap Roles In DB Configuration
    mcpgateway_bootstrap_roles_in_db_enabled: bool = Field(default=False, description="Enable ContextForge add additional roles in db")
    mcpgateway_bootstrap_roles_in_db_file: str = Field(default="additional_roles_in_db.json", description="Path to add additional roles in db")

    # Elicitation support (MCP 2025-06-18)
    mcpgateway_elicitation_enabled: bool = Field(default=True, description="Enable elicitation passthrough support (MCP 2025-06-18)")
    mcpgateway_elicitation_timeout: int = Field(default=60, description="Default timeout for elicitation requests in seconds")
    mcpgateway_elicitation_max_concurrent: int = Field(default=100, description="Maximum concurrent elicitation requests")

    # Security
    skip_ssl_verify: bool = Field(
        default=False,
        description="Skip SSL certificate verification for ALL outbound HTTPS requests "
        "(federation, MCP servers, LLM providers, A2A agents). "
        "WARNING: Only enable in dev environments with self-signed certificates.",
    )
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
        """Convert string 'null', 'none', or empty/whitespace-only string to Python None to disable iframe restrictions.

        Args:
            v: The X-Frame-Options value to normalize.

        Returns:
            None if v is None, an empty/whitespace-only string, or case-insensitive 'null'/'none';
            otherwise returns the stripped string value.
        """
        if v is None:
            return None
        val = v.strip()
        if val == "" or val.lower() in ("null", "none"):
            return None
        return val

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

    llmchat_enabled: bool = Field(default=True, description="Enable LLM Chat feature")
    mcpgateway_stdio_transport_enabled: bool = Field(
        default=False,
        description=("Enable stdio transport for MCP chat client configuration. Disabled by default; " "set true only in trusted environments that intentionally need stdio process execution."),
    )
    toolops_enabled: bool = Field(default=False, description="Enable ToolOps feature")
    plugins_can_override_rbac: bool = Field(
        default=False,
        description=("Allow HTTP_AUTH_CHECK_PERMISSION plugins to short-circuit built-in RBAC grants. " "Disabled by default so plugin grant decisions are audit-only unless explicitly enabled."),
    )
    plugins_can_override_auth_headers: bool = Field(
        default=False,
        description=(
            "DANGEROUS: Allow pre-request plugin hooks to override auth-sensitive headers "
            "(authorization, cookie, x-api-key, proxy-authorization) that the client already sent. "
            "Disabled by default because a malicious or misconfigured plugin could impersonate any "
            "user by rewriting the Authorization header. Only enable when all loaded plugins are "
            "fully trusted and the deployment requires token exchange (e.g. WXO auth). "
            "Requires a server restart to take effect."
        ),
    )

    # database-backed polling settings for session message delivery
    poll_interval: float = Field(default=1.0, description="Initial polling interval in seconds for checking new session messages")
    max_interval: float = Field(default=5.0, description="Maximum polling interval in seconds when the session is idle")
    backoff_factor: float = Field(default=1.5, description="Multiplier used to gradually increase the polling interval during inactivity")

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
                loaded = orjson.loads(v)
                if isinstance(loaded, list):
                    return loaded
            except orjson.JSONDecodeError:
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
            weak_secrets = ["my-test-key", "my-test-key-but-now-longer-than-32-bytes", "my-test-salt", "changeme", "secret", "password"]
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
                logger.warning("🔓 SECURITY WARNING: Default BASIC_AUTH_PASSWORD detected! Please change it if you enable API_ALLOW_BASIC_AUTH.")

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
                logger.info("Using SQLite database. Consider PostgreSQL for production.")

        return v

    @model_validator(mode="after")
    def validate_security_combinations(self) -> Self:
        """Validate security setting combinations.  Only logs warnings; no changes are made.

        Returns:
            Itself.
        """
        if not self.client_mode:
            # Check for dangerous combinations - only log warnings, don't raise errors
            if not self.auth_required and self.mcpgateway_ui_enabled:
                logger.warning("🔓 SECURITY WARNING: Admin UI is enabled without authentication. Consider setting AUTH_REQUIRED=true for production.")

            if self.skip_ssl_verify and not self.dev_mode:
                logger.warning("🔓 SECURITY WARNING: SSL verification is disabled in non-dev mode. This is a security risk! Set SKIP_SSL_VERIFY=false for production.")

            if self.debug and not self.dev_mode:
                logger.warning("🐛 SECURITY WARNING: Debug mode is enabled in non-dev mode. This may leak sensitive information! Set DEBUG=false for production.")

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
            warnings.append("💾 SQLite database in use - consider PostgreSQL for production")

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
            "secure_secrets": (self.jwt_secret_key.get_secret_value() if isinstance(self.jwt_secret_key, SecretStr) else self.jwt_secret_key)
            not in ("my-test-key", "my-test-key-but-now-longer-than-32-bytes"),  # nosec B105 - checking for default values
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

    # HTTPX Client Configuration (for shared singleton client)
    # See: https://www.python-httpx.org/advanced/#pool-limits
    # Formula: max_connections = expected_concurrent_outbound_requests × 1.5
    httpx_max_connections: int = Field(
        default=200,
        ge=10,
        le=1000,
        description="Maximum total concurrent HTTP connections (global, not per-host). " "Increase for high-traffic deployments with many outbound calls.",
    )
    httpx_max_keepalive_connections: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Maximum idle keepalive connections to retain (typically 50% of max_connections)",
    )
    httpx_keepalive_expiry: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Seconds before idle keepalive connections are closed",
    )
    httpx_connect_timeout: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="Timeout in seconds for establishing new connections (5s for LAN, increase for WAN)",
    )
    httpx_read_timeout: float = Field(
        default=120.0,
        ge=1.0,
        le=600.0,
        description="Timeout in seconds for reading response data (set high for slow MCP tool calls)",
    )
    httpx_write_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=600.0,
        description="Timeout in seconds for writing request data",
    )
    httpx_pool_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Timeout in seconds waiting for a connection from the pool (fail fast on exhaustion)",
    )
    httpx_http2_enabled: bool = Field(
        default=False,
        description="Enable HTTP/2 (requires h2 package; enable only if upstreams support HTTP/2)",
    )
    httpx_admin_read_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="Read timeout for admin UI operations (model fetching, health checks). " "Shorter than httpx_read_timeout to fail fast on admin pages.",
    )

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
                parsed = set(orjson.loads(v))
            except orjson.JSONDecodeError:
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

    # Detailed Request Logging Configuration
    log_detailed_max_body_size: int = Field(
        default=16384,  # 16KB - sensible default for request body logging
        ge=1024,
        le=1048576,  # Max 1MB
        description="Maximum request body size to log in detailed mode (bytes). Separate from log_max_size_mb which is for file rotation.",
    )

    # Optional: endpoints to skip for detailed request logging (prefix match)
    log_detailed_skip_endpoints: List[str] = Field(
        default_factory=list,
        description="List of path prefixes to skip when log_detailed_requests is enabled",
    )

    # Whether to attempt resolving user identity via DB fallback when logging.
    # Keep default False to avoid implicit DB queries during normal request handling.
    log_resolve_user_identity: bool = Field(
        default=False,
        description="If true, RequestLoggingMiddleware will attempt DB fallback to resolve user identity when needed",
    )

    # Sampling rate for detailed request logging (0.0-1.0). Applied when log_detailed_requests is enabled.
    log_detailed_sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Fraction of requests to sample for detailed logging (0.0-1.0)",
    )

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

    # Include paths for tracing (regex patterns)
    observability_include_paths: List[str] = Field(
        default_factory=lambda: [
            r"^/rpc/?$",
            r"^/sse$",
            r"^/message$",
            r"^/mcp(?:/|$)",
            r"^/servers/[^/]+/mcp/?$",
            r"^/servers/[^/]+/sse$",
            r"^/servers/[^/]+/message$",
            r"^/a2a(?:/|$)",
        ],
        description="Regex patterns to include for tracing (when empty, all paths are eligible before excludes)",
    )

    # Exclude paths from tracing (regex patterns)
    observability_exclude_paths: List[str] = Field(
        default_factory=lambda: ["/health", "/healthz", "/ready", "/metrics", "/static/.*"],
        description="Regex patterns to exclude from tracing (applies after include patterns)",
    )

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
    structured_logging_database_enabled: bool = Field(default=False, description="Persist structured logs to database (enables /api/logs/* endpoints, impacts performance)")
    structured_logging_external_enabled: bool = Field(default=False, description="Send logs to external systems")

    # Performance Tracking Configuration
    performance_tracking_enabled: bool = Field(default=True, description="Enable performance tracking and metrics")
    performance_threshold_database_query_ms: float = Field(default=100.0, description="Alert threshold for database queries (ms)")
    performance_threshold_tool_invocation_ms: float = Field(default=2000.0, description="Alert threshold for tool invocations (ms)")
    performance_threshold_resource_read_ms: float = Field(default=1000.0, description="Alert threshold for resource reads (ms)")
    performance_threshold_http_request_ms: float = Field(default=500.0, description="Alert threshold for HTTP requests (ms)")
    performance_degradation_multiplier: float = Field(default=1.5, description="Alert if performance degrades by this multiplier vs baseline")

    # Audit Trail Configuration
    # Audit trail logging is disabled by default for performance.
    # When enabled, it logs all CRUD operations (create, read, update, delete) on resources.
    # WARNING: This causes a database write on every API request and can cause significant load.
    audit_trail_enabled: bool = Field(default=False, description="Enable audit trail logging to database for compliance")
    permission_audit_enabled: bool = Field(
        default=False,
        description="Enable permission audit logging for RBAC checks (writes a row per permission check)",
    )

    # Security Logging Configuration
    # Security event logging is disabled by default for performance.
    # When enabled, it logs authentication attempts, authorization failures, and security events.
    # WARNING: "all" level logs every request and can cause significant database write load.
    security_logging_enabled: bool = Field(default=False, description="Enable security event logging to database")
    security_logging_level: Literal["all", "failures_only", "high_severity"] = Field(
        default="failures_only",
        description=(
            "Security logging level: "
            "'all' = log all events including successful auth (high DB load), "
            "'failures_only' = log only authentication/authorization failures, "
            "'high_severity' = log only high/critical severity events"
        ),
    )
    security_failed_auth_threshold: int = Field(default=5, description="Failed auth attempts before high severity alert")
    security_threat_score_alert: float = Field(default=0.7, description="Threat score threshold for alerts (0.0-1.0)")
    security_rate_limit_window_minutes: int = Field(default=5, description="Time window for rate limit checks (minutes)")

    # API Token Tracking Configuration
    # Controls how token usage and last_used timestamps are tracked
    token_usage_logging_enabled: bool = Field(default=True, description="Enable API token usage logging middleware")
    token_last_used_update_interval_minutes: int = Field(default=5, ge=1, le=1440, description="Minimum minutes between last_used timestamp updates (rate-limits DB writes)")

    # Metrics Aggregation Configuration
    metrics_aggregation_enabled: bool = Field(default=True, description="Enable automatic log aggregation into performance metrics")
    metrics_aggregation_backfill_hours: int = Field(default=6, ge=0, le=168, description="Hours of structured logs to backfill into performance metrics on startup")
    metrics_aggregation_window_minutes: int = Field(default=5, description="Time window for metrics aggregation (minutes)")
    metrics_aggregation_auto_start: bool = Field(default=False, description="Automatically run the log aggregation loop on application startup")
    yield_batch_size: int = Field(
        default=1000,
        ge=100,
        le=100000,
        description="Number of rows fetched per batch when streaming hourly metric data from the database. "
        "Used to limit memory usage during aggregation and percentile calculations. "
        "Smaller values reduce memory footprint but increase DB round-trips; larger values improve throughput "
        "at the cost of higher memory usage.",
    )

    # Execution Metrics Recording
    # Controls whether tool/resource/prompt/server/A2A execution metrics are written to the database.
    # Disable if using external observability (ELK, Datadog, Splunk).
    # Note: Does NOT affect log aggregation (METRICS_AGGREGATION_ENABLED) or Prometheus (ENABLE_METRICS).
    db_metrics_recording_enabled: bool = Field(
        default=True, description="Enable recording of execution metrics (tool/resource/prompt/server/A2A) to database. Disable if using external observability."
    )

    # Metrics Buffer Configuration (for batching tool/resource/prompt metrics writes)
    metrics_buffer_enabled: bool = Field(default=True, description="Enable buffered metrics writes (reduces DB pressure under load)")
    metrics_buffer_flush_interval: int = Field(default=60, ge=5, le=300, description="Seconds between automatic metrics buffer flushes")
    metrics_buffer_max_size: int = Field(default=1000, ge=100, le=10000, description="Maximum buffered metrics before forced flush")

    # Metrics Cache Configuration (for caching aggregate metrics queries)
    metrics_cache_enabled: bool = Field(default=True, description="Enable in-memory caching for aggregate metrics queries")
    metrics_cache_ttl_seconds: int = Field(default=60, ge=1, le=300, description="TTL for cached aggregate metrics in seconds")

    # Metrics Cleanup Configuration (automatic deletion of old metrics)
    metrics_cleanup_enabled: bool = Field(default=True, description="Enable automatic cleanup of old metrics data")
    metrics_retention_days: int = Field(default=7, ge=1, le=365, description="Days to retain raw metrics before cleanup (fallback when rollup disabled)")
    metrics_cleanup_interval_hours: int = Field(default=1, ge=1, le=168, description="Hours between automatic cleanup runs")
    metrics_cleanup_batch_size: int = Field(default=10000, ge=100, le=100000, description="Batch size for metrics deletion (prevents long locks)")

    # Metrics Rollup Configuration (hourly aggregation for historical queries)
    metrics_rollup_enabled: bool = Field(default=True, description="Enable hourly metrics rollup for efficient historical queries")
    metrics_rollup_interval_hours: int = Field(default=1, ge=1, le=24, description="Hours between rollup runs")
    metrics_rollup_retention_days: int = Field(default=365, ge=30, le=3650, description="Days to retain hourly rollup data")
    metrics_rollup_late_data_hours: int = Field(
        default=1, ge=1, le=48, description="Hours to re-process on each run to catch late-arriving data (smaller = less CPU, larger = more tolerance for delayed metrics)"
    )
    metrics_delete_raw_after_rollup: bool = Field(default=True, description="Delete raw metrics after hourly rollup exists (recommended for production)")
    metrics_delete_raw_after_rollup_hours: int = Field(default=1, ge=1, le=8760, description="Hours to retain raw metrics when hourly rollup exists")

    # Auth Cache Configuration (reduces DB queries during authentication)
    auth_cache_enabled: bool = Field(default=True, description="Enable Redis/in-memory caching for authentication data (user, team, revocation)")
    auth_cache_user_ttl: int = Field(default=60, ge=10, le=300, description="TTL in seconds for cached user data")
    auth_cache_revocation_ttl: int = Field(default=30, ge=5, le=120, description="TTL in seconds for token revocation cache (security-critical, keep short)")
    auth_cache_team_ttl: int = Field(default=60, ge=10, le=300, description="TTL in seconds for team membership cache")
    auth_cache_role_ttl: int = Field(default=60, ge=10, le=300, description="TTL in seconds for user role in team cache")
    auth_cache_teams_enabled: bool = Field(default=True, description="Enable caching for get_user_teams() (default: true)")
    auth_cache_teams_ttl: int = Field(default=60, ge=10, le=300, description="TTL in seconds for user teams list cache")
    auth_cache_batch_queries: bool = Field(default=True, description="Batch auth DB queries into single call (reduces 3 queries to 1)")

    # Registry Cache Configuration (reduces DB queries for list endpoints)
    registry_cache_enabled: bool = Field(default=True, description="Enable caching for registry list endpoints (tools, prompts, resources, etc.)")
    registry_cache_tools_ttl: int = Field(default=20, ge=5, le=300, description="TTL in seconds for tools list cache")
    registry_cache_prompts_ttl: int = Field(default=15, ge=5, le=300, description="TTL in seconds for prompts list cache")
    registry_cache_resources_ttl: int = Field(default=15, ge=5, le=300, description="TTL in seconds for resources list cache")
    registry_cache_agents_ttl: int = Field(default=20, ge=5, le=300, description="TTL in seconds for agents list cache")
    registry_cache_servers_ttl: int = Field(default=20, ge=5, le=300, description="TTL in seconds for servers list cache")
    registry_cache_gateways_ttl: int = Field(default=20, ge=5, le=300, description="TTL in seconds for gateways list cache")
    registry_cache_catalog_ttl: int = Field(default=300, ge=60, le=600, description="TTL in seconds for catalog servers list cache (external catalog, changes infrequently)")

    # Tool Lookup Cache Configuration (reduces hot-path DB lookups in invoke_tool)
    tool_lookup_cache_enabled: bool = Field(default=True, description="Enable tool lookup cache (tool name -> tool config)")
    tool_lookup_cache_ttl_seconds: int = Field(default=60, ge=5, le=600, description="TTL in seconds for tool lookup cache entries")
    tool_lookup_cache_negative_ttl_seconds: int = Field(default=10, ge=1, le=60, description="TTL in seconds for negative tool lookup cache entries")
    tool_lookup_cache_l1_maxsize: int = Field(default=10000, ge=100, le=1000000, description="Max entries for in-memory tool lookup cache (L1)")
    tool_lookup_cache_l2_enabled: bool = Field(default=True, description="Enable Redis-backed tool lookup cache (L2) when cache_type=redis")

    # Admin Stats Cache Configuration (reduces dashboard query overhead)
    admin_stats_cache_enabled: bool = Field(default=True, description="Enable caching for admin dashboard statistics")
    admin_stats_cache_system_ttl: int = Field(default=60, ge=10, le=300, description="TTL in seconds for system stats cache")
    admin_stats_cache_observability_ttl: int = Field(default=30, ge=10, le=120, description="TTL in seconds for observability stats cache")
    admin_stats_cache_tags_ttl: int = Field(default=120, ge=30, le=600, description="TTL in seconds for tags listing cache")
    admin_stats_cache_plugins_ttl: int = Field(default=120, ge=30, le=600, description="TTL in seconds for plugin stats cache")
    admin_stats_cache_performance_ttl: int = Field(default=60, ge=15, le=300, description="TTL in seconds for performance aggregates cache")

    # Team Member Count Cache Configuration (reduces N+1 queries in admin UI)
    team_member_count_cache_enabled: bool = Field(default=True, description="Enable Redis caching for team member counts")
    team_member_count_cache_ttl: int = Field(default=300, ge=30, le=3600, description="TTL in seconds for team member count cache (default: 5 minutes)")

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
    mcpgateway_ws_relay_enabled: bool = Field(default=False, description="Enable WebSocket JSON-RPC relay endpoint at /ws")
    mcpgateway_reverse_proxy_enabled: bool = Field(default=False, description="Enable reverse-proxy transport endpoints under /reverse-proxy/*")
    transport_type: str = "all"  # http, ws, sse, all
    websocket_ping_interval: int = 30  # seconds
    sse_retry_timeout: int = 5000  # milliseconds - client retry interval on disconnect
    sse_keepalive_enabled: bool = True  # Enable SSE keepalive events
    sse_keepalive_interval: int = 30  # seconds between keepalive events
    sse_send_timeout: float = 30.0  # seconds - timeout for ASGI send() calls, protects against hung connections
    sse_rapid_yield_window_ms: int = 1000  # milliseconds - time window for rapid yield detection
    sse_rapid_yield_max: int = 50  # max yields per window before assuming client disconnected (0=disabled)

    # Gateway/Server Connection Timeout
    # Timeout in seconds for HTTP requests to registered gateways and MCP servers.
    # Used by: GatewayService, ToolService, ServerService for health checks and tool invocations.
    # Note: Previously part of federation settings, retained for gateway connectivity.
    federation_timeout: int = 120

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
                    parsed = orjson.loads(s)
                    return parsed if isinstance(parsed, list) else []
                except orjson.JSONDecodeError:
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
    rest_response_text_max_length: int = Field(
        default=5000,
        ge=1000,
        le=100000,
        description="Maximum length of response text to return for non-JSON REST API responses. "
        "Longer responses are truncated to prevent exposing excessive sensitive data. "
        "Default: 5000 characters. Range: 1000-100000.",
    )

    # Content Security - Size Limits
    content_max_resource_size: int = Field(default=102400, ge=1024, le=10485760, description="Maximum size in bytes for resource content (default: 100KB)")  # 100KB  # Minimum 1KB  # Maximum 10MB
    content_max_prompt_size: int = Field(default=10240, ge=512, le=1048576, description="Maximum size in bytes for prompt templates (default: 10KB)")  # 10KB  # Minimum 512 bytes  # Maximum 1MB

    # Content Security - MIME Type Restrictions (US-2)
    content_allowed_resource_mimetypes: List[str] = Field(
        default_factory=lambda: [
            "text/plain",
            "text/markdown",
            "text/html",
            "text/csv",
            "application/json",
            "application/xml",
            "application/yaml",
            "application/pdf",
            "application/octet-stream",
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/svg+xml",
            "image/webp",
            "audio/mpeg",
            "audio/wav",
            "video/mp4",
            "video/webm",
        ],
        description="Allowed MIME types for resources. In strict mode, only types explicitly listed here are accepted. Vendor types (application/x-*, text/x-*) and suffix types (+json, +xml) must be explicitly added if needed.",
    )
    content_strict_mime_validation: bool = Field(
        default=False,
        description="Enable strict MIME type validation for resources (US-2). Set to false to log violations without blocking.",
    )

    # Content Security - Template Validation (US-4)
    content_validate_prompt_templates: bool = Field(
        default=True,
        description="Enable prompt template validation for syntax and security patterns (US-4). Validates Jinja2 syntax and blocks dangerous patterns.",
    )
    content_blocked_template_patterns: List[str] = Field(
        default_factory=lambda: [
            r"__import__",  # Python import injection
            r"__builtins__",  # Access to builtins
            r"__globals__",  # Access to globals
            r"__locals__",  # Access to locals
            r"__class__",  # Class introspection
            r"__base__",  # Base class access
            r"__subclasses__",  # Subclass enumeration
            r"eval\s*\(",  # Eval function
            r"exec\s*\(",  # Exec function
            r"compile\s*\(",  # Compile function
            r"open\s*\(",  # File operations
            r"file\s*\(",  # File operations
            r"input\s*\(",  # Input operations
            r"__\w+__",  # Any dunder method
        ],
        description="Regex patterns for dangerous template constructs (US-4). Blocks Python injection attempts in Jinja2 templates.",
    )

    # Content Security - Malicious Pattern Detection (US-3)
    content_pattern_detection_enabled: bool = Field(
        default=True,
        description="Enable malicious pattern detection in resources and prompts (US-3). Scans for XSS, command injection, SQL injection, and template injection patterns.",
    )
    content_pattern_validation_mode: str = Field(
        default="strict",
        description="Validation mode for pattern detection (US-3): 'strict' (block), 'moderate' (warn+block), 'lenient' (warn only).",
    )
    content_blocked_patterns: List[str] = Field(
        default_factory=lambda: [
            # XSS patterns
            r"<script[^>]*>.*?</script>",  # Script tags
            r"javascript:",  # JavaScript protocol
            r"on\w+\s*=",  # Event handlers: onclick, onerror, etc.
            r"<iframe[^>]*>",  # Iframe injection
            # Command injection
            r";\s*rm\s+-rf",  # Dangerous rm command
            r"&&|\|\|",  # Command chaining
            r"`[^`]+`",  # Backtick execution
            r"\$\([^)]+\)",  # Command substitution
            # SQL injection
            r"(?i)(union|select|insert|update|delete|drop)\s+",  # SQL keywords
            r"--\s*$",  # SQL comments
            r"'\s*or\s*'1'\s*=\s*'1",  # Classic SQL injection
            # Template injection - more specific patterns to avoid false positives
            r"\{\{\s*config\s*\}\}",  # Direct Jinja2 config object access (not variables containing "config")
            r"\{\{\s*config\.",  # Jinja2 config attribute access
            r"\{%\s*for\s+\w+\s+in\s+config",  # Jinja2 loops over config object
            r"\$\{.*\}",  # Expression evaluation
        ],
        description="Regex patterns for malicious content detection (US-3). Blocks XSS, command injection, SQL injection, and template injection attempts.",
    )
    content_pattern_cache_enabled: bool = Field(
        default=True,
        description="Enable caching of pattern validation results (US-3). Improves performance by caching validation outcomes.",
    )
    content_pattern_max_scan_size: int = Field(
        default=200_000,
        ge=1024,
        description="Maximum bytes of content that will be scanned for malicious patterns (US-3). Content exceeding this limit is rejected with a ContentPatternError. This bounds worst-case regex execution time as hard defense against ReDoS (CWE-400) independent of the per-pattern timeout.",
    )
    content_pattern_regex_timeout: float = Field(
        default=1.0,
        gt=0.0,
        description="Per-pattern regex execution timeout in seconds (US-3). Used natively on Python 3.13+ via re.search(..., timeout=) and as a soft thread-join timeout on older Pythons. Primary ReDoS defense is content_pattern_max_scan_size; this is defense-in-depth.",
    )

    # Timeout for SSE task group cleanup (seconds).
    # When an SSE connection is cancelled, this controls how long to wait for
    # internal tasks to respond before forcing cleanup. Shorter values reduce
    # CPU waste during anyio _deliver_cancellation spin loops but may interrupt
    # legitimate cleanup. Only affects cancelled connections, not normal operation.
    # See: https://github.com/agronholm/anyio/issues/695
    sse_task_group_cleanup_timeout: float = 5.0

    # =========================================================================
    # EXPERIMENTAL: anyio _deliver_cancellation spin loop workaround
    # =========================================================================
    # When enabled, monkey-patches anyio's CancelScope._deliver_cancellation to
    # limit the number of retry iterations. This prevents 100% CPU spin loops
    # when tasks don't respond to CancelledError (anyio issue #695).
    #
    # WARNING: This is a workaround for an upstream issue. May be removed when
    # anyio or MCP SDK fix the underlying problem. Enable only if you experience
    # CPU spin loops during SSE/MCP connection cleanup.
    #
    # Trade-offs when enabled:
    # - Prevents indefinite CPU spin (good)
    # - May leave some tasks uncancelled after max iterations (usually harmless)
    # - Worker recycling (GUNICORN_MAX_REQUESTS) cleans up orphaned tasks
    #
    # See: https://github.com/agronholm/anyio/issues/695
    # Env: ANYIO_CANCEL_DELIVERY_PATCH_ENABLED
    anyio_cancel_delivery_patch_enabled: bool = False

    # Maximum iterations for _deliver_cancellation before giving up.
    # Only used when anyio_cancel_delivery_patch_enabled=True.
    # Higher values = more attempts to cancel tasks, but longer potential spin.
    # Lower values = faster recovery, but more orphaned tasks.
    # Env: ANYIO_CANCEL_DELIVERY_MAX_ITERATIONS
    anyio_cancel_delivery_max_iterations: int = 100

    # Session Affinity (multi-worker downstream-session → worker routing).
    # The upstream-session pooling surface that used to share this section is
    # gone as of #4205 — see mcpgateway.services.upstream_session_registry.
    mcpgateway_session_affinity_enabled: bool = False  # Global session affinity toggle
    mcpgateway_session_affinity_ttl: int = 300  # Session affinity binding TTL
    mcpgateway_pool_rpc_forward_timeout: int = 30  # Timeout for forwarding RPC requests to owner worker

    # Prompts
    prompt_cache_size: int = 100
    max_prompt_size: int = 100 * 1024  # 100KB
    prompt_render_timeout: int = 10  # seconds

    # Health Checks
    # Interval in seconds between gateway health checks.
    health_check_interval: int = 60
    # Timeout in seconds for each health check request
    health_check_timeout: int = 5
    # Per-check timeout (seconds) to bound total time of one gateway health check
    # Env: GATEWAY_HEALTH_CHECK_TIMEOUT
    gateway_health_check_timeout: float = 5.0
    # Consecutive failures before marking gateway offline
    unhealthy_threshold: int = 3
    # Max concurrent health checks per worker
    max_concurrent_health_checks: int = 10

    # Auto-refresh tools/resources/prompts from gateways during health checks
    # When enabled, tools/resources/prompts are fetched and synced with DB during health checks
    auto_refresh_servers: bool = Field(default=False, description="Enable automatic tool/resource/prompt refresh during gateway health checks")

    # Per-gateway refresh configuration (used when auto_refresh_servers is True)
    # Gateways can override this with their own refresh_interval_seconds
    gateway_auto_refresh_interval: int = Field(default=300, ge=60, description="Default refresh interval in seconds for gateway tools/resources/prompts sync (minimum 60 seconds)")

    # Hot/Cold Server Classification
    # Classify servers by usage (hot = active sessions, cold = inactive) for optimized polling
    # Poll intervals auto-derived: hot = gateway_auto_refresh_interval (1x), cold = 3x
    # Classification refresh uses gateway_auto_refresh_interval (no separate config needed)
    hot_cold_classification_enabled: bool = Field(default=False, description="Enable hot/cold server classification for staggered polling (requires Redis for multi-worker)")

    # Validation Gateway URL
    gateway_validation_timeout: int = 5  # seconds
    gateway_max_redirects: int = 5

    filelock_name: str = "gateway_service_leader.lock"

    # Default Roots
    default_roots: List[str] = []

    # Database
    db_driver: str = "postgresql+psycopg"
    db_pool_size: int = 200
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_max_retries: int = 30  # Max attempts with exponential backoff (≈5 min total)
    db_retry_interval_ms: int = 2000  # Base interval; doubles each attempt, ±25% jitter
    db_max_backoff_seconds: int = 30  # Cap for exponential backoff (jitter applied after cap)

    # Database Performance Optimization
    use_postgresdb_percentiles: bool = Field(
        default=True,
        description="Use database-native percentile functions (percentile_cont) for performance metrics. "
        "When enabled, PostgreSQL uses native SQL percentile calculations (5-10x faster). "
        "When disabled or using SQLite, falls back to Python-based percentile calculations. "
        "Recommended: true for PostgreSQL, auto-detected for SQLite.",
    )

    # psycopg3-specific: Number of times a query must be executed before it's
    # prepared server-side. Set to 0 to disable, 1 to prepare immediately.
    # Default of 5 balances memory usage with query performance.
    db_prepare_threshold: int = Field(default=5, ge=0, le=100, description="psycopg3 prepare_threshold for auto-prepared statements")

    # Connection pool class: "auto" (default), "null", or "queue"
    # - "auto": Uses NullPool when PgBouncer detected, QueuePool otherwise
    # - "null": Always use NullPool (recommended with PgBouncer - lets PgBouncer handle pooling)
    # - "queue": Always use QueuePool (application-side pooling)
    db_pool_class: Literal["auto", "null", "queue"] = Field(
        default="auto",
        description="Connection pool class: auto (NullPool with PgBouncer), null, or queue",
    )

    # Pre-ping connections before checkout (validates connection is alive)
    # - "auto": Enabled for non-PgBouncer, disabled for PgBouncer (default)
    # - "true": Always enable (adds SELECT 1 overhead but catches stale connections)
    # - "false": Always disable
    db_pool_pre_ping: Literal["auto", "true", "false"] = Field(
        default="auto",
        description="Pre-ping connections: auto, true, or false",
    )

    # SQLite busy timeout: Maximum time (ms) SQLite will wait to acquire a database lock before returning SQLITE_BUSY.
    db_sqlite_busy_timeout: int = Field(default=5000, ge=1000, le=60000, description="SQLite busy timeout in milliseconds (default: 5000ms)")

    # Cache
    cache_type: Literal["redis", "memory", "none", "database"] = "database"  # memory or redis or database
    redis_url: Optional[str] = "redis://localhost:6379/0"
    cache_prefix: str = "mcpgw:"
    session_ttl: int = 3600
    message_ttl: int = 600
    redis_max_retries: int = 30  # Max attempts with exponential backoff (≈5 min total)
    redis_retry_interval_ms: int = 2000  # Base interval; doubles each attempt, ±25% jitter
    redis_max_backoff_seconds: int = 30  # Cap for exponential backoff (jitter applied after cap)

    # GlobalConfig In-Memory Cache (Issue #1715)
    # Caches GlobalConfig (passthrough headers) to eliminate redundant DB queries
    global_config_cache_ttl: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="TTL in seconds for GlobalConfig in-memory cache (default: 60)",
    )

    # A2A Stats In-Memory Cache
    # Caches A2A agent counts (total, active) to eliminate redundant COUNT queries
    a2a_stats_cache_ttl: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="TTL in seconds for A2A stats in-memory cache (default: 30)",
    )

    # Redis Parser Configuration (ADR-026)
    # hiredis C parser provides up to 83x faster response parsing for large responses
    redis_parser: Literal["auto", "hiredis", "python"] = Field(
        default="auto",
        description="Redis protocol parser: auto (use hiredis if available), hiredis (require hiredis), python (pure-Python)",
    )

    # Redis Connection Pool - Performance Optimized
    redis_decode_responses: bool = Field(default=True, description="Return strings instead of bytes")
    redis_max_connections: int = Field(default=50, description="Connection pool size per worker")
    redis_socket_timeout: float = Field(default=2.0, description="Socket read/write timeout in seconds")
    redis_socket_connect_timeout: float = Field(default=2.0, description="Connection timeout in seconds")
    redis_retry_on_timeout: bool = Field(default=True, description="Retry commands on timeout")
    redis_health_check_interval: int = Field(default=30, description="Seconds between connection health checks (0=disabled)")

    redis_operation_timeout: float = Field(
        default=0.5, gt=0.0, description="Timeout for individual Redis operations in seconds (get/set/delete). " "Should be lower than redis_socket_timeout for faster fallback to in-memory cache."
    )
    redis_circuit_failure_threshold: int = Field(
        default=3,
        gt=0,
        description="Consecutive Redis failures (timeouts or connection errors) that trip the circuit breaker and route subsequent calls to the in-memory cache.",
    )
    redis_circuit_open_duration: float = Field(
        default=30.0,
        gt=0.0,
        description="Seconds the circuit remains open before a single probe is allowed. A successful probe closes the circuit; a failed probe extends the cooldown.",
    )

    # Redis Leader Election - Multi-Node Deployments
    redis_leader_ttl: int = Field(default=15, description="Leader election TTL in seconds")
    redis_leader_key: str = Field(default="gateway_service_leader", description="Leader key name")
    redis_leader_heartbeat_interval: int = Field(default=5, description="Seconds between leader heartbeats")

    # streamable http transport
    use_stateful_sessions: bool = False  # Set to False to use stateless sessions without event store
    json_response_enabled: bool = True  # Enable JSON responses instead of SSE streams
    streamable_http_max_events_per_stream: int = 100  # Ring buffer capacity per stream
    streamable_http_event_ttl: int = 3600  # Event stream TTL in seconds (1 hour)

    # GET /mcp server-to-client stream (ADR-052)
    # When True, GET /mcp returns an SSE stream that delivers server-initiated
    # JSON-RPC messages (notifications and server-initiated requests) for the
    # session identified by Mcp-Session-Id. Requires use_stateful_sessions=True.
    # Backend (Redis vs in-memory) follows cache_type — see ADR-052 for the
    # single-node vs multi-node fallback contract.
    mcp_get_stream_enabled: bool = True
    # TTL for the per-session listener claim. Refreshed by heartbeat while the
    # GET handler holds the connection; expires shortly after disconnect so a
    # client can reconnect without operator intervention.
    mcp_get_stream_listener_ttl_seconds: int = 30
    # Soft cap (bytes) on how much the body-peek helpers will buffer
    # before stopping the peek and falling through to the SDK's
    # streaming receive path. The request is NEVER rejected — the
    # cap only bounds peek-path memory. Bare-uvicorn deployments
    # without an upstream nginx have no other body cap; the body-peek
    # path runs on every POST that has a pending request or hits a
    # no-session MCP path. 4 MiB matches typical RPC payload sizes
    # and stops trickle attacks dead without stranding legitimate
    # large ``sampling/createMessage`` responses.
    mcp_body_peek_max_bytes: int = 4 * 1024 * 1024

    # Development
    dev_mode: bool = False
    reload: bool = False
    debug: bool = False

    # Observability (OpenTelemetry)
    deployment_env: str = Field(default="development", validation_alias=AliasChoices("DEPLOYMENT_ENV", "ENVIRONMENT"), description="Deployment environment label")
    otel_enable_observability: bool = Field(default=False, description="Enable OpenTelemetry observability")
    otel_traces_exporter: str = Field(default="otlp", description="Traces exporter: otlp, jaeger, zipkin, console, none")
    otel_exporter_otlp_endpoint: Optional[str] = Field(default=None, description="OTLP endpoint (e.g., http://localhost:4317)")
    otel_exporter_otlp_protocol: str = Field(default="grpc", description="OTLP protocol: grpc or http")
    otel_exporter_otlp_insecure: bool = Field(default=True, description="Use insecure connection for OTLP")
    otel_exporter_otlp_headers: Optional[str] = Field(default=None, description="OTLP headers (comma-separated key=value)")
    otel_emit_langfuse_attributes: Optional[bool] = Field(
        default=None,
        description="Emit Langfuse-specific span attributes. Defaults to auto-enable when a Langfuse OTLP endpoint is configured.",
    )
    otel_capture_identity_attributes: Optional[bool] = Field(
        default=None,
        description="Capture user/team identity span attributes. Defaults to auto-enable when Langfuse-specific attributes are emitted.",
    )
    otel_copy_resource_attrs_to_spans: bool = Field(default=False, description="Copy selected OTEL resource attributes onto spans")
    otel_redact_fields: str = Field(
        default="password,secret,token,api_key,authorization,credential,auth_value,access_token,refresh_token,auth_token,client_secret,cookie,set-cookie,private_key,session_id,sessionid",
        description="Comma-separated trace payload field names to redact before export",
    )
    otel_max_trace_payload_size: int = Field(default=32768, ge=256, description="Maximum serialized trace payload size in characters")
    otel_capture_input_spans: str = Field(default="", description="Comma-separated span names allowed to capture input payloads")
    otel_capture_output_spans: str = Field(default="", description="Comma-separated span names allowed to capture output payloads")
    langfuse_otel_endpoint: Optional[str] = Field(default=None, description="Langfuse OTLP/HTTP endpoint override")
    langfuse_public_key: Optional[SecretStr] = Field(default=None, description="Langfuse project public key for derived OTLP auth")
    langfuse_secret_key: Optional[SecretStr] = Field(default=None, description="Langfuse project secret key for derived OTLP auth")
    langfuse_otel_auth: Optional[SecretStr] = Field(default=None, description="Base64-encoded Langfuse OTLP basic auth override")
    otel_exporter_jaeger_endpoint: Optional[str] = Field(default=None, description="Jaeger endpoint")
    otel_exporter_jaeger_user: Optional[str] = Field(default=None, description="Jaeger collector username")
    otel_exporter_jaeger_password: Optional[SecretStr] = Field(default=None, description="Jaeger collector password")
    otel_exporter_zipkin_endpoint: Optional[str] = Field(default=None, description="Zipkin endpoint")
    otel_service_name: str = Field(default="mcp-gateway", description="Service name for traces")
    otel_resource_attributes: Optional[str] = Field(default=None, description="Resource attributes (comma-separated key=value)")
    otel_bsp_max_queue_size: int = Field(default=2048, description="Max queue size for batch span processor")
    otel_bsp_max_export_batch_size: int = Field(default=512, description="Max export batch size")
    otel_bsp_schedule_delay: int = Field(default=5000, description="Schedule delay in milliseconds")

    # ===================================

    # ===================================
    # OpenTelemetry Baggage Configuration
    # ===================================

    otel_baggage_enabled: bool = Field(
        default=False,
        description="Enable HTTP header to W3C baggage conversion for distributed tracing context propagation",
    )
    otel_baggage_header_mappings: str = Field(
        default="[]",
        description=("JSON array of header-to-baggage mappings. " 'Example: [{"header_name": "X-Tenant-ID", "baggage_key": "tenant.id"}]'),
    )
    otel_baggage_propagate_to_external: bool = Field(
        default=False,
        description=(
            "Propagate baggage to external downstream services via W3C baggage header. "
            "When false (default), baggage is captured in spans only for internal observability. "
            "Enable only for trusted internal microservices."
        ),
    )
    otel_baggage_max_items: int = Field(
        default=32,
        ge=1,
        le=64,
        description="Maximum number of baggage items from headers (security limit to prevent DoS)",
    )
    otel_baggage_max_size_bytes: int = Field(
        default=8192,
        ge=1024,
        le=16384,
        description="Maximum total size of header-derived baggage in bytes (security limit)",
    )
    otel_baggage_log_rejected: bool = Field(
        default=True,
        description="Log rejected headers for security auditing",
    )
    otel_baggage_log_sanitization: bool = Field(
        default=True,
        description="Log sanitization events for compliance tracking",
    )

    # Well-Known URI Configuration
    # ===================================

    # Enable well-known URI endpoints
    well_known_enabled: bool = True

    # robots.txt content (default: disallow all crawling for private API)
    well_known_robots_txt: str = """User-agent: *
Disallow: /

# ContextForge is a private API gateway
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

    # ===================================
    # Performance / Startup Tuning
    # ===================================

    slug_refresh_batch_size: int = Field(default=1000, description="Batch size for gateway/tool slug refresh at startup")
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
            return orjson.loads(self.well_known_custom_files) if self.well_known_custom_files else {}
        except orjson.JSONDecodeError:
            logger.error(f"Invalid JSON in WELL_KNOWN_CUSTOM_FILES: {self.well_known_custom_files}")
            return {}

    @property
    def hot_server_check_interval(self) -> float:
        """Hot server polling interval (auto-derived from gateway_auto_refresh_interval).

        Hot servers (top 20% by usage) are polled at the same rate as gateway tool refresh.

        Returns:
            float: Hot server check interval in seconds (equals gateway_auto_refresh_interval)
        """
        return float(self.gateway_auto_refresh_interval)

    @property
    def cold_server_check_interval(self) -> float:
        """Cold server polling interval (auto-derived from gateway_auto_refresh_interval).

        Cold servers (remaining 80%) are polled at 3x the gateway refresh rate to save resources.

        Examples:
            - gateway_auto_refresh_interval=300s → cold=900s (15 minutes)
            - gateway_auto_refresh_interval=60s → cold=180s (3 minutes)

        Returns:
            float: Cold server check interval in seconds (3x gateway_auto_refresh_interval)
        """
        return float(self.gateway_auto_refresh_interval * 3)

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

    @field_validator("experimental_rust_mcp_runtime_uds", "experimental_rust_a2a_runtime_uds", mode="after")
    @classmethod
    def _validate_experimental_rust_runtime_uds(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        """Validate the optional UDS path used for a Rust sidecar runtime.

        Args:
            value: Candidate UDS path from configuration.
            info: Pydantic field metadata for the current field.

        Returns:
            The normalized absolute UDS path, or ``None`` when unset.

        Raises:
            ValueError: If the path is not absolute or its parent directory is missing.
        """
        if value in (None, ""):
            return None

        field_name = info.field_name or "experimental_rust_runtime_uds"
        uds_path = Path(value).expanduser()
        if not uds_path.is_absolute():
            raise ValueError(f"{field_name} must be an absolute path")
        if not uds_path.parent.exists():
            raise ValueError(f"{field_name} parent directory does not exist: {uds_path.parent}")
        return str(uds_path)

    # -------------------------------
    # Flexible list parsing for envs
    # -------------------------------
    @field_validator(
        "sso_entra_admin_groups",
        "sso_trusted_domains",
        "sso_auto_admin_domains",
        "sso_github_admin_orgs",
        "sso_google_admin_domains",
        "insecure_queryparam_auth_allowed_hosts",
        "mcpgateway_ui_hide_sections",
        "mcpgateway_ui_hide_header_items",
        "mcpgateway_ui_hide_sections_admin",
        "mcpgateway_ui_hide_header_items_admin",
        "tool_description_forbidden_patterns",
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
                    parsed = orjson.loads(s)
                    return parsed if isinstance(parsed, list) else []
                except Exception:
                    logger.warning("Invalid JSON list in env for list field; falling back to CSV parsing")
            # CSV fallback
            return [item.strip() for item in s.split(",") if item.strip()]
        raise ValueError("Invalid type for list field")

    @field_validator("tool_description_forbidden_patterns", mode="after")
    @classmethod
    def _filter_empty_forbidden_patterns(cls, value: list[str]) -> list[str]:
        """Strip empty/blank entries that would match every description.

        Args:
            value: List of forbidden pattern strings.

        Returns:
            list[str]: Filtered list with empty/blank entries removed.
        """
        return [p for p in value if p and p.strip()]

    @field_validator("mcpgateway_ui_hide_sections", "mcpgateway_ui_hide_sections_admin", mode="after")
    @classmethod
    def _validate_ui_hide_sections(cls, value: list[str]) -> list[str]:
        """Normalize and filter hidable UI sections.

        Args:
            value: Candidate section identifiers from environment/config.

        Returns:
            list[str]: Normalized unique section identifiers.
        """
        normalized: list[str] = []
        seen: set[str] = set()

        for item in value:
            candidate = str(item).strip().lower()
            if not candidate:
                continue
            candidate = UI_HIDE_SECTION_ALIASES.get(candidate, candidate)
            if candidate not in UI_HIDABLE_SECTIONS:
                logger.warning("Ignoring invalid MCPGATEWAY_UI_HIDE_SECTIONS item: %s", item)
                continue
            if candidate not in seen:
                seen.add(candidate)
                normalized.append(candidate)

        return normalized

    @field_validator("mcpgateway_ui_hide_header_items", "mcpgateway_ui_hide_header_items_admin", mode="after")
    @classmethod
    def _validate_ui_hide_header_items(cls, value: list[str]) -> list[str]:
        """Normalize and filter hidable header items.

        Args:
            value: Candidate header identifiers from environment/config.

        Returns:
            list[str]: Normalized unique header identifiers.
        """
        normalized: list[str] = []
        seen: set[str] = set()

        for item in value:
            candidate = str(item).strip().lower()
            if not candidate:
                continue
            if candidate not in UI_HIDABLE_HEADER_ITEMS:
                logger.warning("Ignoring invalid MCPGATEWAY_UI_HIDE_HEADER_ITEMS item: %s", item)
                continue
            if candidate not in seen:
                seen.add(candidate)
                normalized.append(candidate)

        return normalized

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
    validation_name_pattern: str = r"^[a-zA-Z0-9_.\- ]+$"  # Allow spaces for names (literal space, not \s to reject control chars)
    validation_identifier_pattern: str = r"^[a-zA-Z0-9_\-\.]+$"  # No spaces for IDs
    validation_safe_uri_pattern: str = r"^[a-zA-Z0-9_\-.:/?=&%{}]+$"
    validation_unsafe_uri_pattern: str = r'[<>"\'\\]'
    validation_tool_name_pattern: str = r"^[a-zA-Z0-9_][a-zA-Z0-9._/-]*$"  # MCP tool naming per SEP-986
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

    # Passthrough headers source priority
    # - "env": Environment variable always wins (ideal for Kubernetes/containerized deployments)
    # - "db": Database take precedence if configured, env as fallback (default)
    # - "merge": Union of both sources - env provides base, other configuration in DB can add more headers
    passthrough_headers_source: Literal["env", "db", "merge"] = Field(
        default="db",
        description="Source priority for passthrough headers: env (environment always wins), db (database wins, default), merge (combine both)",
    )

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
                self.default_passthrough_headers = orjson.loads(default_value)
                if not isinstance(self.default_passthrough_headers, list):
                    raise ValueError("Must be a JSON array")
            except (orjson.JSONDecodeError, ValueError):
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
                # Production origins - construct from app_domain (extract hostname from HttpUrl)
                app_domain_host = urlparse(str(self.app_domain)).hostname or "localhost"
                self.allowed_origins = {f"https://{app_domain_host}", f"https://app.{app_domain_host}", f"https://admin.{app_domain_host}"}

        # MCP transport auth policy:
        # - If MCP_REQUIRE_AUTH is unset, derive it from AUTH_REQUIRED
        # - If AUTH_REQUIRED=true but MCP_REQUIRE_AUTH=false is explicit, emit a warning
        if self.mcp_require_auth is None:
            self.mcp_require_auth = bool(self.auth_required)
            logger.info(
                "MCP_REQUIRE_AUTH not set; defaulting to %s to match AUTH_REQUIRED=%s.",
                self.mcp_require_auth,
                self.auth_required,
            )
        elif self.auth_required and self.mcp_require_auth is False:
            logger.warning("AUTH_REQUIRED=true but MCP_REQUIRE_AUTH=false. MCP endpoints (/servers/*/mcp) allow unauthenticated access to public items.")

        # Validate proxy auth configuration
        if not self.mcp_client_auth_enabled and self.trust_proxy_auth and not self.trust_proxy_auth_dangerously:
            logger.warning(
                "TRUST_PROXY_AUTH=true ignored because TRUST_PROXY_AUTH_DANGEROUSLY is false "
                "while MCP_CLIENT_AUTH_ENABLED=false. Set TRUST_PROXY_AUTH_DANGEROUSLY=true "
                "only behind a strictly trusted authentication proxy."
            )
            self.trust_proxy_auth = False
        elif not self.mcp_client_auth_enabled and self.trust_proxy_auth and self.trust_proxy_auth_dangerously:
            logger.warning("TRUST_PROXY_AUTH_DANGEROUSLY=true acknowledged. Requests may trust identity headers from the upstream proxy.")
        elif not self.mcp_client_auth_enabled and not self.trust_proxy_auth:
            logger.warning(
                "MCP client authentication is disabled but trust_proxy_auth is not set. "
                "This is a security risk! Set TRUST_PROXY_AUTH=true only if ContextForge "
                "is behind a trusted authentication proxy."
            )

        if not self.auth_required and self.allow_unauthenticated_admin:
            logger.warning("ALLOW_UNAUTHENTICATED_ADMIN=true acknowledged while AUTH_REQUIRED=false. Unauthenticated requests may receive admin context.")

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

    ENABLE_METRICS: bool = Field(False, description="Enable Prometheus metrics endpoint at /metrics/prometheus (requires authentication)")
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

    @property
    def plugins(self) -> Any:
        """Access plugin framework settings via ``settings.plugins``.

        Returns a ``LazySettingsWrapper`` from the plugin framework that
        provides lightweight ``@property`` accessors for startup-critical
        fields and a ``__getattr__`` fallback to the full ``PluginsSettings``.

        Returns:
            The plugin framework settings wrapper.
        """
        # Third-Party
        from cpex.framework.settings import settings as _plugin_settings  # pylint: disable=import-outside-toplevel

        return _plugin_settings

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
        print(orjson.dumps(schema, option=orjson.OPT_INDENT_2).decode())
        sys.exit(0)
    settings.log_summary()
