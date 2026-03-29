# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/llm_provider_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Provider Service

This module implements LLM provider management for ContextForge.
It handles provider registration, CRUD operations, model management,
and health checks for the internal LLM Chat feature.
"""

# Standard
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Third-Party
import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import LLMModel, LLMProvider, LLMProviderType
from mcpgateway.llm_provider_configs import PROVIDER_CONFIGS
from mcpgateway.llm_schemas import (
    GatewayModelInfo,
    HealthStatus,
    LLMModelCreate,
    LLMModelResponse,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    ProviderHealthCheck,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.services_auth import decode_auth, encode_auth

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

_ENCRYPTED_PROVIDER_CONFIG_KEY = "_mcpgateway_encrypted_value_v1"
_PROVIDER_CONFIG_DATA_KEY = "data"
_PROVIDER_CONFIG_LEGACY_VALUE_KEY = "value"
_BASE_SENSITIVE_PROVIDER_CONFIG_KEYS = {
    "api_key",
    "auth_token",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_access_key",
    "session_token",
    "credentials_json",
    "password",
    "private_key",
    "aws_secret_access_key",
    "aws_session_token",
}
_PORTKEY_EXTRA_HEADER_FIELD_MAPPINGS = {
    "forward_headers": "x-portkey-forward-headers",
    "azure_resource_name": "x-portkey-azure-resource-name",
    "azure_deployment_id": "x-portkey-azure-deployment-id",
    "azure_api_version": "x-portkey-azure-api-version",
    "azure_model_name": "x-portkey-azure-model-name",
    "vertex_project_id": "x-portkey-vertex-project-id",
    "vertex_region": "x-portkey-vertex-region",
    "aws_access_key_id": "x-portkey-aws-access-key-id",
    "aws_secret_access_key": "x-portkey-aws-secret-access-key",
    "aws_region": "x-portkey-aws-region",
    "aws_session_token": "x-portkey-aws-session-token",
}
_PORTKEY_PROVIDER_SLUGS = {
    LLMProviderType.OPENAI: "openai",
    LLMProviderType.AZURE_OPENAI: "azure-openai",
    LLMProviderType.ANTHROPIC: "anthropic",
    LLMProviderType.BEDROCK: "bedrock",
    LLMProviderType.GOOGLE_VERTEX: "vertex-ai",
    LLMProviderType.OLLAMA: "ollama",
    LLMProviderType.OPENAI_COMPATIBLE: "openai",
    LLMProviderType.COHERE: "cohere",
    LLMProviderType.MISTRAL: "mistral",
    LLMProviderType.GROQ: "groq",
    LLMProviderType.TOGETHER: "together-ai",
}
_PORTKEY_TRANSLATABLE_PROVIDER_TYPES = frozenset(_PORTKEY_PROVIDER_SLUGS)
_PORTKEY_INTERNAL_PROVIDER_TYPES = frozenset(
    {
        LLMProviderType.OPENAI,
        LLMProviderType.AZURE_OPENAI,
        LLMProviderType.ANTHROPIC,
        LLMProviderType.BEDROCK,
        LLMProviderType.GOOGLE_VERTEX,
        LLMProviderType.OPENAI_COMPATIBLE,
        LLMProviderType.COHERE,
        LLMProviderType.MISTRAL,
        LLMProviderType.GROQ,
        LLMProviderType.TOGETHER,
        LLMProviderType.PORTKEY,
    }
)


def _normalize_provider_config_key(key: str) -> str:
    """Normalize provider config key names for matching.

    Args:
        key: Raw provider config field name.

    Returns:
        Canonical lowercase key using underscore separators.
    """
    normalized = str(key).strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _build_sensitive_provider_config_keys() -> set[str]:
    """Build normalized sensitive key set from defaults and provider schemas.

    Returns:
        Set of normalized keys that should be treated as sensitive.
    """
    sensitive_keys = {_normalize_provider_config_key(key) for key in _BASE_SENSITIVE_PROVIDER_CONFIG_KEYS}
    for provider_definition in PROVIDER_CONFIGS.values():
        for field_definition in provider_definition.config_fields:
            key_name = _normalize_provider_config_key(field_definition.name)
            if field_definition.field_type == "password":
                sensitive_keys.add(key_name)
    return sensitive_keys


_SENSITIVE_PROVIDER_CONFIG_KEYS = frozenset(_build_sensitive_provider_config_keys())


def _is_sensitive_provider_config_key(key: str) -> bool:
    """Return whether a provider config key is sensitive.

    Args:
        key: Candidate provider config key.

    Returns:
        ``True`` when key should be protected; otherwise ``False``.
    """
    return _normalize_provider_config_key(key) in _SENSITIVE_PROVIDER_CONFIG_KEYS


def _is_encrypted_provider_config_value(value: Any) -> bool:
    """Return whether a config fragment is an encrypted envelope.

    Args:
        value: Config fragment to inspect.

    Returns:
        ``True`` when fragment matches encrypted envelope structure.
    """
    return isinstance(value, dict) and isinstance(value.get(_ENCRYPTED_PROVIDER_CONFIG_KEY), str)


def _encrypt_provider_config_secret(value: Any, existing_value: Any = None) -> Any:
    """Encrypt a single sensitive provider config value.

    Args:
        value: Incoming value from create/update payload.
        existing_value: Existing stored value for masked-value merge behavior.

    Returns:
        Encrypted envelope, preserved existing value, or ``None`` for explicit clear.
    """
    if value is None or value == "":
        return value

    if value == settings.masked_auth_value:
        if existing_value in (None, ""):
            return None
        if _is_encrypted_provider_config_value(existing_value):
            return existing_value
        return _encrypt_provider_config_secret(existing_value, None)

    if _is_encrypted_provider_config_value(value):
        return value

    encrypted = encode_auth({_PROVIDER_CONFIG_DATA_KEY: value})
    return {_ENCRYPTED_PROVIDER_CONFIG_KEY: encrypted}


def _protect_provider_config_fragment(config_fragment: Any, existing_fragment: Any = None) -> Any:
    """Recursively protect sensitive provider config values.

    Args:
        config_fragment: Incoming config fragment to protect.
        existing_fragment: Existing persisted fragment for merge behavior.

    Returns:
        Config fragment with sensitive values protected.
    """
    if isinstance(config_fragment, dict):
        existing_dict = existing_fragment if isinstance(existing_fragment, dict) else {}
        protected: Dict[str, Any] = {}
        for key, value in config_fragment.items():
            existing_value = existing_dict.get(key)
            if _is_sensitive_provider_config_key(key):
                protected[key] = _encrypt_provider_config_secret(value, existing_value)
            else:
                protected[key] = _protect_provider_config_fragment(value, existing_value)
        return protected

    if isinstance(config_fragment, list):
        existing_list = existing_fragment if isinstance(existing_fragment, list) else []
        return [_protect_provider_config_fragment(value, existing_list[idx] if idx < len(existing_list) else None) for idx, value in enumerate(config_fragment)]

    return config_fragment


def protect_provider_config_for_storage(config: Optional[Dict[str, Any]], existing_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Encrypt sensitive provider config fields before database persistence.

    Args:
        config: Incoming provider configuration payload.
        existing_config: Existing stored configuration used for masked-value merges.

    Returns:
        Provider config structure with sensitive fields protected for storage.
    """
    if not isinstance(config, dict):
        return {}
    return _protect_provider_config_fragment(config, existing_config)


def _decrypt_provider_config_fragment(config_fragment: Any) -> Any:
    """Recursively decrypt provider config fragments for runtime usage.

    Args:
        config_fragment: Stored config fragment, possibly encrypted.

    Returns:
        Runtime-ready fragment with decryptable values restored.
    """
    if _is_encrypted_provider_config_value(config_fragment):
        encrypted_payload = config_fragment.get(_ENCRYPTED_PROVIDER_CONFIG_KEY)
        try:
            decoded = decode_auth(encrypted_payload)
            if isinstance(decoded, dict):
                if _PROVIDER_CONFIG_DATA_KEY in decoded:
                    return decoded[_PROVIDER_CONFIG_DATA_KEY]
                if _PROVIDER_CONFIG_LEGACY_VALUE_KEY in decoded:
                    return decoded[_PROVIDER_CONFIG_LEGACY_VALUE_KEY]
        except Exception as exc:
            logger.warning("Failed to decrypt provider config fragment: %s", exc)
        return config_fragment

    if isinstance(config_fragment, dict):
        return {key: _decrypt_provider_config_fragment(value) for key, value in config_fragment.items()}

    if isinstance(config_fragment, list):
        return [_decrypt_provider_config_fragment(value) for value in config_fragment]

    return config_fragment


def decrypt_provider_config_for_runtime(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return runtime-ready provider config with encrypted fields decrypted.

    Args:
        config: Stored provider configuration payload.

    Returns:
        Provider config with decryptable sensitive fields restored.
    """
    if not isinstance(config, dict):
        return {}
    return _decrypt_provider_config_fragment(config)


def _provider_type_value(provider: LLMProvider) -> str:
    """Return the normalized provider type string for a provider-like object."""
    return str(getattr(provider, "provider_type", "") or "").strip().lower()


def _get_secret_value(secret_like: Any) -> str:
    """Return the plain-text value for SecretStr-like objects or strings."""
    if secret_like in (None, ""):
        return ""
    if hasattr(secret_like, "get_secret_value"):
        return str(secret_like.get_secret_value())
    return str(secret_like)


def current_llm_gateway_mode() -> str:
    """Return the normalized external LLM gateway runtime mode."""
    mode = str(getattr(settings, "llm_gateway_mode", "direct") or "direct").strip().lower()
    return "direct" if mode in {"", "off"} else mode


def llm_gateway_proxy_mode_enabled() -> bool:
    """Return whether public LLM proxy traffic should route through the external gateway."""
    return current_llm_gateway_mode() in {"edge", "full"}


def llm_gateway_internal_mode_enabled() -> bool:
    """Return whether internal LangChain/admin flows should route through the external gateway."""
    return current_llm_gateway_mode() == "full"


def llm_gateway_shadow_mode_enabled() -> bool:
    """Return whether direct proxy traffic should be mirrored to the external gateway."""
    return current_llm_gateway_mode() == "shadow"


def provider_supports_portkey_translation(provider: LLMProvider, *, internal: bool = False) -> bool:
    """Return whether a provider can be translated to Portkey headers."""
    provider_type = _provider_type_value(provider)
    if provider_type == LLMProviderType.PORTKEY:
        return True
    supported_types = _PORTKEY_INTERNAL_PROVIDER_TYPES if internal else _PORTKEY_TRANSLATABLE_PROVIDER_TYPES
    return provider_type in supported_types


def should_route_provider_via_llm_gateway(provider: LLMProvider) -> bool:
    """Return whether public `/v1` proxy traffic should use the external LLM gateway."""
    provider_type = _provider_type_value(provider)
    if provider_type == LLMProviderType.PORTKEY:
        return True
    return llm_gateway_proxy_mode_enabled() and provider_supports_portkey_translation(provider)


def should_shadow_provider_via_llm_gateway(provider: LLMProvider) -> bool:
    """Return whether public `/v1` proxy traffic should be mirrored to the external gateway."""
    provider_type = _provider_type_value(provider)
    return provider_type != LLMProviderType.PORTKEY and llm_gateway_shadow_mode_enabled() and provider_supports_portkey_translation(provider)


def should_use_llm_gateway_for_internal_provider(provider: LLMProvider) -> bool:
    """Return whether internal provider usage should route through the external gateway."""
    provider_type = _provider_type_value(provider)
    if provider_type == LLMProviderType.PORTKEY:
        return True
    return llm_gateway_internal_mode_enabled() and provider_supports_portkey_translation(provider, internal=True)


def should_use_portkey_for_model_discovery(provider: LLMProvider) -> bool:
    """Return whether provider model discovery should route through Portkey."""
    return should_use_llm_gateway_for_internal_provider(provider)


def get_portkey_api_base(provider: LLMProvider) -> str:
    """Return the Portkey gateway base URL for a provider."""
    provider_type = _provider_type_value(provider)
    defaults = LLMProviderType.get_provider_defaults()
    default_base = defaults.get(LLMProviderType.PORTKEY, {}).get("api_base", "http://127.0.0.1:8787/v1")
    if provider_type == LLMProviderType.PORTKEY:
        return (getattr(provider, "api_base", None) or getattr(settings, "llm_gateway_url", None) or default_base).rstrip("/")
    return (getattr(settings, "llm_gateway_url", None) or default_base).rstrip("/")


def get_provider_api_key(provider: LLMProvider) -> Optional[str]:
    """Return a provider API key decrypted for runtime use."""
    raw_api_key = getattr(provider, "api_key", None)
    if not raw_api_key:
        return None

    try:
        auth_data = decode_auth(raw_api_key)
        if isinstance(auth_data, dict):
            return auth_data.get("api_key")
        return str(auth_data)
    except Exception as exc:
        logger.error("Failed to decode API key for provider %s: %s", getattr(provider, "name", "<unknown>"), exc)
        return None


def _stringify_portkey_header_value(value: Any) -> Optional[str]:
    """Normalize Portkey header values to strings."""
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(list(value) if isinstance(value, set) else value)
    return str(value)


def _normalized_default_api_base(provider_type: str) -> str:
    """Return the default API base for a provider type when available."""
    defaults = LLMProviderType.get_provider_defaults().get(provider_type, {})
    return str(defaults.get("api_base") or "").rstrip("/")


def _normalize_base_url(url: Optional[str]) -> Optional[str]:
    """Normalize a base URL for Portkey custom-host usage."""
    if not url:
        return None
    return str(url).rstrip("/")


def _extract_azure_resource_name(api_base: Optional[str]) -> Optional[str]:
    """Derive the Azure resource name from an Azure OpenAI base URL."""
    normalized = _normalize_base_url(api_base)
    if not normalized:
        return None
    match = re.search(r"https?://([^.]+)\.openai\.azure\.com", normalized)
    if match:
        return match.group(1)
    return None


def _derive_translated_portkey_provider_slug(provider: LLMProvider, provider_config: Dict[str, Any]) -> Optional[str]:
    """Return the Portkey provider slug for a translated provider record."""
    override = _stringify_portkey_header_value(provider_config.get("portkey_provider"))
    if override:
        return override
    return _PORTKEY_PROVIDER_SLUGS.get(_provider_type_value(provider))


def _derive_translated_portkey_custom_host(provider: LLMProvider, provider_config: Dict[str, Any]) -> Optional[str]:
    """Return the custom upstream host for translated providers when needed."""
    explicit = _stringify_portkey_header_value(provider_config.get("custom_host") or provider_config.get("portkey_custom_host"))
    if explicit:
        return explicit.rstrip("/")

    provider_type = _provider_type_value(provider)
    api_base = _normalize_base_url(getattr(provider, "api_base", None))
    default_api_base = _normalized_default_api_base(provider_type)

    if provider_type == LLMProviderType.OPENAI_COMPATIBLE:
        return api_base

    if provider_type == LLMProviderType.OLLAMA and api_base:
        return api_base[:-3] if api_base.endswith("/v1") else api_base

    if provider_type == LLMProviderType.OPENAI and api_base and api_base != _normalized_default_api_base(LLMProviderType.OPENAI):
        return api_base

    if provider_type == LLMProviderType.ANTHROPIC and api_base and api_base != default_api_base:
        return api_base

    if provider_type == LLMProviderType.COHERE and api_base and api_base != default_api_base:
        return api_base

    if provider_type == LLMProviderType.MISTRAL and api_base and api_base != default_api_base:
        return api_base

    if provider_type == LLMProviderType.GROQ and api_base and api_base != default_api_base:
        return api_base

    if provider_type == LLMProviderType.TOGETHER and api_base and api_base != default_api_base:
        return api_base

    return None


def _apply_translated_portkey_provider_headers(
    headers: Dict[str, str],
    provider: LLMProvider,
    provider_config: Dict[str, Any],
    *,
    model: Any = None,
) -> None:
    """Populate provider-specific Portkey headers for translated providers."""
    provider_type = _provider_type_value(provider)

    if provider_type == LLMProviderType.AZURE_OPENAI:
        resource_name = _stringify_portkey_header_value(provider_config.get("resource_name")) or _extract_azure_resource_name(getattr(provider, "api_base", None))
        deployment_name = _stringify_portkey_header_value(provider_config.get("deployment_name") or provider_config.get("deployment")) or (
            getattr(model, "model_id", None) if model is not None else None
        )
        api_version = _stringify_portkey_header_value(provider_config.get("api_version") or getattr(provider, "api_version", None) or "2024-02-15-preview")
        model_name = _stringify_portkey_header_value(getattr(model, "model_id", None))

        if resource_name:
            headers["x-portkey-azure-resource-name"] = resource_name
        if deployment_name:
            headers["x-portkey-azure-deployment-id"] = deployment_name
        if api_version:
            headers["x-portkey-azure-api-version"] = api_version
        if model_name:
            headers["x-portkey-azure-model-name"] = model_name
        return

    if provider_type == LLMProviderType.BEDROCK:
        access_key_id = _stringify_portkey_header_value(provider_config.get("access_key_id") or provider_config.get("aws_access_key_id"))
        secret_access_key = _stringify_portkey_header_value(provider_config.get("secret_access_key") or provider_config.get("aws_secret_access_key"))
        session_token = _stringify_portkey_header_value(provider_config.get("session_token") or provider_config.get("aws_session_token"))
        region = _stringify_portkey_header_value(provider_config.get("region") or provider_config.get("region_name") or provider_config.get("aws_region"))

        if access_key_id:
            headers["x-portkey-aws-access-key-id"] = access_key_id
        if secret_access_key:
            headers["x-portkey-aws-secret-access-key"] = secret_access_key
        if session_token:
            headers["x-portkey-aws-session-token"] = session_token
        if region:
            headers["x-portkey-aws-region"] = region
        return

    if provider_type == LLMProviderType.GOOGLE_VERTEX:
        project_id = _stringify_portkey_header_value(provider_config.get("project_id") or provider_config.get("vertex_project_id"))
        region = _stringify_portkey_header_value(provider_config.get("location") or provider_config.get("region") or provider_config.get("vertex_region"))

        if project_id:
            headers["x-portkey-vertex-project-id"] = project_id
        if region:
            headers["x-portkey-vertex-region"] = region


def _should_forward_portkey_authorization(provider: LLMProvider, portkey_provider: Optional[str], virtual_key: Optional[str]) -> bool:
    """Return whether the upstream provider API key should be forwarded as Authorization."""
    provider_type = _provider_type_value(provider)
    if virtual_key:
        return False
    if portkey_provider and portkey_provider.startswith("@"):
        return False
    if provider_type == LLMProviderType.BEDROCK:
        return False
    return True


def build_portkey_headers(
    provider: LLMProvider,
    *,
    model: Any = None,
    include_content_type: bool = False,
    include_authorization: bool = True,
) -> Dict[str, str]:
    """Build Portkey request headers from a stored provider record."""
    provider_config = decrypt_provider_config_for_runtime(getattr(provider, "config", None))
    headers: Dict[str, str] = {}
    if include_content_type:
        headers["Content-Type"] = "application/json"

    provider_type = _provider_type_value(provider)
    if provider_type == LLMProviderType.PORTKEY:
        portkey_provider = _stringify_portkey_header_value(provider_config.get("provider"))
    else:
        portkey_provider = _derive_translated_portkey_provider_slug(provider, provider_config)

    virtual_key = _stringify_portkey_header_value(provider_config.get("virtual_key"))
    custom_host = (
        _stringify_portkey_header_value(provider_config.get("custom_host"))
        if provider_type == LLMProviderType.PORTKEY
        else _derive_translated_portkey_custom_host(provider, provider_config)
    )

    if portkey_provider:
        headers["x-portkey-provider"] = portkey_provider
    elif custom_host:
        # Portkey expects an explicit provider when routing to a custom host.
        headers["x-portkey-provider"] = "openai"

    if virtual_key:
        headers["x-portkey-virtual-key"] = virtual_key

    portkey_api_key = _stringify_portkey_header_value(provider_config.get("portkey_api_key")) or _get_secret_value(getattr(settings, "llm_gateway_portkey_api_key", ""))
    if portkey_api_key:
        headers["x-portkey-api-key"] = portkey_api_key

    portkey_config = _stringify_portkey_header_value(provider_config.get("portkey_config")) or _stringify_portkey_header_value(getattr(settings, "llm_gateway_portkey_config", ""))
    if portkey_config:
        headers["x-portkey-config"] = portkey_config

    if custom_host:
        headers["x-portkey-custom-host"] = custom_host

    for field_name, header_name in _PORTKEY_EXTRA_HEADER_FIELD_MAPPINGS.items():
        value = _stringify_portkey_header_value(provider_config.get(field_name))
        if value:
            headers[header_name] = value

    if provider_type != LLMProviderType.PORTKEY:
        _apply_translated_portkey_provider_headers(headers, provider, provider_config, model=model)

    provider_api_key = get_provider_api_key(provider) if include_authorization else None
    if include_authorization and provider_api_key and _should_forward_portkey_authorization(provider, portkey_provider, virtual_key):
        headers["Authorization"] = f"Bearer {provider_api_key}"

    return headers


def _mask_provider_config_fragment(config_fragment: Any) -> Any:
    """Recursively mask sensitive provider config values for API responses.

    Args:
        config_fragment: Runtime config fragment.

    Returns:
        Fragment with sensitive values replaced by mask markers.
    """
    if isinstance(config_fragment, dict):
        masked: Dict[str, Any] = {}
        for key, value in config_fragment.items():
            if _is_sensitive_provider_config_key(key):
                masked[key] = settings.masked_auth_value if value not in (None, "") else value
            else:
                masked[key] = _mask_provider_config_fragment(value)
        return masked

    if isinstance(config_fragment, list):
        return [_mask_provider_config_fragment(value) for value in config_fragment]

    return config_fragment


def sanitize_provider_config_for_response(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return API-safe provider config with sensitive fields masked.

    Args:
        config: Stored provider configuration payload.

    Returns:
        Provider config suitable for API responses with masked secrets.
    """
    runtime_config = decrypt_provider_config_for_runtime(config)
    return _mask_provider_config_fragment(runtime_config)


class LLMProviderError(Exception):
    """Base class for LLM provider-related errors."""


class LLMProviderNotFoundError(LLMProviderError):
    """Raised when a requested LLM provider is not found."""


class LLMProviderNameConflictError(LLMProviderError):
    """Raised when an LLM provider name conflicts with an existing one."""

    def __init__(self, name: str, provider_id: Optional[str] = None):
        """Initialize the exception.

        Args:
            name: The conflicting provider name.
            provider_id: Optional ID of the existing provider.
        """
        self.name = name
        self.provider_id = provider_id
        message = f"LLM Provider already exists with name: {name}"
        if provider_id:
            message += f" (ID: {provider_id})"
        super().__init__(message)


class LLMProviderValidationError(LLMProviderError, ValueError):
    """Raised when provider payload validation fails."""


class LLMModelNotFoundError(LLMProviderError):
    """Raised when a requested LLM model is not found."""


class LLMModelConflictError(LLMProviderError):
    """Raised when an LLM model conflicts with an existing one."""


class LLMProviderService:
    """Service for managing LLM providers and models.

    Provides methods to create, list, retrieve, update, and delete
    provider and model records. Also supports health checks.
    """

    def __init__(self) -> None:
        """Initialize a new LLMProviderService instance."""
        self._initialized = False

    @staticmethod
    def _validate_provider_api_base(api_base: Optional[str]) -> None:
        """Validate provider api_base against core URL + SSRF rules.

        Args:
            api_base: Provider base URL to validate.

        Raises:
            LLMProviderValidationError: If URL fails core or SSRF validation.
        """
        if api_base:
            try:
                SecurityValidator.validate_url(api_base, "Provider API base URL")
            except ValueError as exc:
                raise LLMProviderValidationError(str(exc)) from exc

    async def initialize(self) -> None:
        """Initialize the LLM provider service."""
        if not self._initialized:
            logger.info("Initializing LLM Provider Service")
            self._initialized = True

    async def shutdown(self) -> None:
        """Shutdown the LLM provider service."""
        if self._initialized:
            logger.info("Shutting down LLM Provider Service")
            self._initialized = False

    # ---------------------------------------------------------------------------
    # Provider CRUD Operations
    # ---------------------------------------------------------------------------

    def create_provider(
        self,
        db: Session,
        provider_data: LLMProviderCreate,
        created_by: Optional[str] = None,
    ) -> LLMProvider:
        """Create a new LLM provider.

        Args:
            db: Database session.
            provider_data: Provider data to create.
            created_by: Username of creator.

        Returns:
            Created LLMProvider instance.

        Raises:
            LLMProviderNameConflictError: If provider name already exists.
        """
        # Check for name conflict
        existing = db.execute(select(LLMProvider).where(LLMProvider.name == provider_data.name)).scalar_one_or_none()

        if existing:
            raise LLMProviderNameConflictError(provider_data.name, existing.id)

        # Encrypt API key if provided
        encrypted_api_key = None
        if provider_data.api_key:
            encrypted_api_key = encode_auth({"api_key": provider_data.api_key})

        self._validate_provider_api_base(provider_data.api_base)

        # Create provider
        provider = LLMProvider(
            name=provider_data.name,
            slug=slugify(provider_data.name),
            description=provider_data.description,
            provider_type=provider_data.provider_type.value,
            api_key=encrypted_api_key,
            api_base=provider_data.api_base,
            api_version=provider_data.api_version,
            config=protect_provider_config_for_storage(provider_data.config),
            default_model=provider_data.default_model,
            default_temperature=provider_data.default_temperature,
            default_max_tokens=provider_data.default_max_tokens,
            enabled=provider_data.enabled,
            plugin_ids=provider_data.plugin_ids,
            created_by=created_by,
        )

        try:
            db.add(provider)
            db.commit()
            db.refresh(provider)
            logger.info(f"Created LLM provider: {provider.name} (ID: {provider.id})")
            return provider
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Failed to create LLM provider: {e}")
            raise LLMProviderNameConflictError(provider_data.name)

    def get_provider(self, db: Session, provider_id: str) -> LLMProvider:
        """Get an LLM provider by ID.

        Args:
            db: Database session.
            provider_id: Provider ID to retrieve.

        Returns:
            LLMProvider instance.

        Raises:
            LLMProviderNotFoundError: If provider not found.
        """
        provider = db.execute(select(LLMProvider).where(LLMProvider.id == provider_id)).scalar_one_or_none()

        if not provider:
            raise LLMProviderNotFoundError(f"Provider not found: {provider_id}")

        return provider

    def get_provider_by_slug(self, db: Session, slug: str) -> LLMProvider:
        """Get an LLM provider by slug.

        Args:
            db: Database session.
            slug: Provider slug to retrieve.

        Returns:
            LLMProvider instance.

        Raises:
            LLMProviderNotFoundError: If provider not found.
        """
        provider = db.execute(select(LLMProvider).where(LLMProvider.slug == slug)).scalar_one_or_none()

        if not provider:
            raise LLMProviderNotFoundError(f"Provider not found: {slug}")

        return provider

    def list_providers(
        self,
        db: Session,
        enabled_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[LLMProvider], int]:
        """List all LLM providers.

        Args:
            db: Database session.
            enabled_only: Only return enabled providers.
            page: Page number (1-indexed).
            page_size: Items per page.

        Returns:
            Tuple of (providers list, total count).
        """
        query = select(LLMProvider)

        if enabled_only:
            query = query.where(LLMProvider.enabled.is_(True))

        # Get total count efficiently using func.count()
        count_query = select(func.count(LLMProvider.id))  # pylint: disable=not-callable
        if enabled_only:
            count_query = count_query.where(LLMProvider.enabled.is_(True))
        total = db.execute(count_query).scalar() or 0

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(LLMProvider.name)

        providers = list(db.execute(query).scalars().all())
        return providers, total

    def update_provider(
        self,
        db: Session,
        provider_id: str,
        provider_data: LLMProviderUpdate,
        modified_by: Optional[str] = None,
    ) -> LLMProvider:
        """Update an LLM provider.

        Args:
            db: Database session.
            provider_id: Provider ID to update.
            provider_data: Updated provider data.
            modified_by: Username of modifier.

        Returns:
            Updated LLMProvider instance.

        Raises:
            LLMProviderNotFoundError: If provider not found.
            LLMProviderNameConflictError: If new name conflicts.
            IntegrityError: If database constraint violation.
        """
        provider = self.get_provider(db, provider_id)

        # Check for name conflict if name is being changed
        if provider_data.name and provider_data.name != provider.name:
            existing = db.execute(
                select(LLMProvider).where(
                    and_(
                        LLMProvider.name == provider_data.name,
                        LLMProvider.id != provider_id,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                raise LLMProviderNameConflictError(provider_data.name, existing.id)

            provider.name = provider_data.name
            provider.slug = slugify(provider_data.name)

        # Update fields if provided
        if provider_data.description is not None:
            provider.description = provider_data.description
        if provider_data.provider_type is not None:
            provider.provider_type = provider_data.provider_type.value
        if provider_data.api_key is not None:
            provider.api_key = encode_auth({"api_key": provider_data.api_key})
        if provider_data.api_base is not None:
            self._validate_provider_api_base(provider_data.api_base)
            provider.api_base = provider_data.api_base
        if provider_data.api_version is not None:
            provider.api_version = provider_data.api_version
        if provider_data.config is not None:
            provider.config = protect_provider_config_for_storage(
                provider_data.config,
                existing_config=provider.config if isinstance(provider.config, dict) else None,
            )
        if provider_data.default_model is not None:
            provider.default_model = provider_data.default_model
        if provider_data.default_temperature is not None:
            provider.default_temperature = provider_data.default_temperature
        if provider_data.default_max_tokens is not None:
            provider.default_max_tokens = provider_data.default_max_tokens
        if provider_data.enabled is not None:
            provider.enabled = provider_data.enabled
        if provider_data.plugin_ids is not None:
            provider.plugin_ids = provider_data.plugin_ids

        provider.modified_by = modified_by

        try:
            db.commit()
            db.refresh(provider)
            logger.info(f"Updated LLM provider: {provider.name} (ID: {provider.id})")
            return provider
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Failed to update LLM provider: {e}")
            raise

    def delete_provider(self, db: Session, provider_id: str) -> bool:
        """Delete an LLM provider.

        Args:
            db: Database session.
            provider_id: Provider ID to delete.

        Returns:
            True if deleted successfully.

        Raises:
            LLMProviderNotFoundError: If provider not found.
        """
        provider = self.get_provider(db, provider_id)
        provider_name = provider.name

        db.delete(provider)
        db.commit()
        logger.info(f"Deleted LLM provider: {provider_name} (ID: {provider_id})")
        return True

    def set_provider_state(self, db: Session, provider_id: str, activate: Optional[bool] = None) -> LLMProvider:
        """Set provider enabled state.

        Args:
            db: Database session.
            provider_id: Provider ID to update.
            activate: If provided, sets enabled to this value. If None, inverts current state (legacy behavior).

        Returns:
            Updated LLMProvider instance.
        """
        provider = self.get_provider(db, provider_id)
        if activate is None:
            # Legacy toggle behavior for backward compatibility
            provider.enabled = not provider.enabled
        else:
            provider.enabled = activate
        db.commit()
        db.refresh(provider)
        logger.info(f"Set LLM provider state: {provider.name} enabled={provider.enabled}")
        return provider

    # ---------------------------------------------------------------------------
    # Model CRUD Operations
    # ---------------------------------------------------------------------------

    def create_model(
        self,
        db: Session,
        model_data: LLMModelCreate,
    ) -> LLMModel:
        """Create a new LLM model.

        Args:
            db: Database session.
            model_data: Model data to create.

        Returns:
            Created LLMModel instance.

        Raises:
            LLMProviderNotFoundError: If provider not found.
            LLMModelConflictError: If model already exists for provider.
        """
        # Verify provider exists
        self.get_provider(db, model_data.provider_id)

        # Check for conflict
        existing = db.execute(
            select(LLMModel).where(
                and_(
                    LLMModel.provider_id == model_data.provider_id,
                    LLMModel.model_id == model_data.model_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            raise LLMModelConflictError(f"Model {model_data.model_id} already exists for provider {model_data.provider_id}")

        model = LLMModel(
            provider_id=model_data.provider_id,
            model_id=model_data.model_id,
            model_name=model_data.model_name,
            model_alias=model_data.model_alias,
            description=model_data.description,
            supports_chat=model_data.supports_chat,
            supports_streaming=model_data.supports_streaming,
            supports_function_calling=model_data.supports_function_calling,
            supports_vision=model_data.supports_vision,
            context_window=model_data.context_window,
            max_output_tokens=model_data.max_output_tokens,
            enabled=model_data.enabled,
            deprecated=model_data.deprecated,
        )

        try:
            db.add(model)
            db.commit()
            db.refresh(model)
            logger.info(f"Created LLM model: {model.model_id} (ID: {model.id})")
            return model
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Failed to create LLM model: {e}")
            raise LLMModelConflictError(f"Model conflict: {model_data.model_id}")

    def get_model(self, db: Session, model_id: str) -> LLMModel:
        """Get an LLM model by ID.

        Args:
            db: Database session.
            model_id: Model ID to retrieve.

        Returns:
            LLMModel instance.

        Raises:
            LLMModelNotFoundError: If model not found.
        """
        model = db.execute(select(LLMModel).where(LLMModel.id == model_id)).scalar_one_or_none()

        if not model:
            raise LLMModelNotFoundError(f"Model not found: {model_id}")

        return model

    def list_models(
        self,
        db: Session,
        provider_id: Optional[str] = None,
        enabled_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[LLMModel], int]:
        """List LLM models.

        Args:
            db: Database session.
            provider_id: Filter by provider ID.
            enabled_only: Only return enabled models.
            page: Page number (1-indexed).
            page_size: Items per page.

        Returns:
            Tuple of (models list, total count).
        """
        query = select(LLMModel)

        if provider_id:
            query = query.where(LLMModel.provider_id == provider_id)
        if enabled_only:
            query = query.where(LLMModel.enabled.is_(True))

        # Get total count efficiently using func.count()
        count_query = select(func.count(LLMModel.id))  # pylint: disable=not-callable
        if provider_id:
            count_query = count_query.where(LLMModel.provider_id == provider_id)
        if enabled_only:
            count_query = count_query.where(LLMModel.enabled.is_(True))
        total = db.execute(count_query).scalar() or 0

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(LLMModel.model_name)

        models = list(db.execute(query).scalars().all())
        return models, total

    def update_model(
        self,
        db: Session,
        model_id: str,
        model_data: LLMModelUpdate,
    ) -> LLMModel:
        """Update an LLM model.

        Args:
            db: Database session.
            model_id: Model ID to update.
            model_data: Updated model data.

        Returns:
            Updated LLMModel instance.
        """
        model = self.get_model(db, model_id)

        if model_data.model_id is not None:
            model.model_id = model_data.model_id
        if model_data.model_name is not None:
            model.model_name = model_data.model_name
        if model_data.model_alias is not None:
            model.model_alias = model_data.model_alias
        if model_data.description is not None:
            model.description = model_data.description
        if model_data.supports_chat is not None:
            model.supports_chat = model_data.supports_chat
        if model_data.supports_streaming is not None:
            model.supports_streaming = model_data.supports_streaming
        if model_data.supports_function_calling is not None:
            model.supports_function_calling = model_data.supports_function_calling
        if model_data.supports_vision is not None:
            model.supports_vision = model_data.supports_vision
        if model_data.context_window is not None:
            model.context_window = model_data.context_window
        if model_data.max_output_tokens is not None:
            model.max_output_tokens = model_data.max_output_tokens
        if model_data.enabled is not None:
            model.enabled = model_data.enabled
        if model_data.deprecated is not None:
            model.deprecated = model_data.deprecated

        db.commit()
        db.refresh(model)
        logger.info(f"Updated LLM model: {model.model_id} (ID: {model.id})")
        return model

    def delete_model(self, db: Session, model_id: str) -> bool:
        """Delete an LLM model.

        Args:
            db: Database session.
            model_id: Model ID to delete.

        Returns:
            True if deleted successfully.
        """
        model = self.get_model(db, model_id)
        model_name = model.model_id

        db.delete(model)
        db.commit()
        logger.info(f"Deleted LLM model: {model_name} (ID: {model_id})")
        return True

    def set_model_state(self, db: Session, model_id: str, activate: Optional[bool] = None) -> LLMModel:
        """Set model enabled state.

        Args:
            db: Database session.
            model_id: Model ID to update.
            activate: If provided, sets enabled to this value. If None, inverts current state (legacy behavior).

        Returns:
            Updated LLMModel instance.
        """
        model = self.get_model(db, model_id)
        if activate is None:
            # Legacy toggle behavior for backward compatibility
            model.enabled = not model.enabled
        else:
            model.enabled = activate
        db.commit()
        db.refresh(model)
        logger.info(f"Set LLM model state: {model.model_id} enabled={model.enabled}")
        return model

    # ---------------------------------------------------------------------------
    # Gateway Models (for LLM Chat dropdown)
    # ---------------------------------------------------------------------------

    def get_gateway_models(self, db: Session) -> List[GatewayModelInfo]:
        """Get enabled models for the LLM Chat dropdown.

        Args:
            db: Database session.

        Returns:
            List of GatewayModelInfo for enabled models.
        """
        # Get enabled models from enabled providers
        query = (
            select(LLMModel, LLMProvider)
            .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
            .where(
                and_(
                    LLMModel.enabled.is_(True),
                    LLMProvider.enabled.is_(True),
                    LLMModel.supports_chat.is_(True),
                )
            )
            .order_by(LLMProvider.name, LLMModel.model_name)
        )

        results = db.execute(query).all()

        models = []
        for model, provider in results:
            models.append(
                GatewayModelInfo(
                    id=model.id,
                    model_id=model.model_id,
                    model_name=model.model_name,
                    provider_id=provider.id,
                    provider_name=provider.name,
                    provider_type=provider.provider_type,
                    supports_streaming=model.supports_streaming,
                    supports_function_calling=model.supports_function_calling,
                    supports_vision=model.supports_vision,
                )
            )

        return models

    # ---------------------------------------------------------------------------
    # Health Check Operations
    # ---------------------------------------------------------------------------

    async def check_provider_health(
        self,
        db: Session,
        provider_id: str,
    ) -> ProviderHealthCheck:
        """Check health of an LLM provider.

        Args:
            db: Database session.
            provider_id: Provider ID to check.

        Returns:
            ProviderHealthCheck result.
        """
        provider = self.get_provider(db, provider_id)

        start_time = datetime.now(timezone.utc)
        status = HealthStatus.UNKNOWN
        error_msg = None
        response_time_ms = None

        try:
            # Get API key
            api_key = None
            if provider.api_key:
                auth_data = decode_auth(provider.api_key)
                api_key = auth_data.get("api_key")

            # Perform health check based on provider type using shared HTTP client
            # First-Party
            from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

            client = await get_http_client()
            if should_use_llm_gateway_for_internal_provider(provider):
                base_url = get_portkey_api_base(provider)
                self._validate_provider_api_base(base_url)
                headers = build_portkey_headers(provider)
                response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=10.0)
                if response.status_code == 200:
                    status = HealthStatus.HEALTHY
                else:
                    status = HealthStatus.UNHEALTHY
                    error_msg = f"HTTP {response.status_code}"

            elif provider.provider_type == LLMProviderType.OPENAI:
                # Check OpenAI models endpoint
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                base_url = provider.api_base or "https://api.openai.com/v1"
                self._validate_provider_api_base(base_url)
                response = await client.get(f"{base_url}/models", headers=headers, timeout=10.0)
                if response.status_code == 200:
                    status = HealthStatus.HEALTHY
                else:
                    status = HealthStatus.UNHEALTHY
                    error_msg = f"HTTP {response.status_code}"

            elif provider.provider_type == LLMProviderType.OLLAMA:
                # Check Ollama health endpoint
                base_url = provider.api_base or "http://localhost:11434"
                self._validate_provider_api_base(base_url)
                # Handle OpenAI-compatible endpoint (/v1)
                if base_url.rstrip("/").endswith("/v1"):
                    # Use OpenAI-compatible models endpoint
                    response = await client.get(f"{base_url.rstrip('/')}/models", timeout=10.0)
                else:
                    # Use native Ollama API
                    response = await client.get(f"{base_url.rstrip('/')}/api/tags", timeout=10.0)
                if response.status_code == 200:
                    status = HealthStatus.HEALTHY
                else:
                    status = HealthStatus.UNHEALTHY
                    error_msg = f"HTTP {response.status_code}"

            else:
                # Generic check - just verify connectivity
                if provider.api_base:
                    self._validate_provider_api_base(provider.api_base)
                    response = await client.get(provider.api_base, timeout=5.0)
                    status = HealthStatus.HEALTHY if response.status_code < 500 else HealthStatus.UNHEALTHY
                else:
                    status = HealthStatus.UNKNOWN
                    error_msg = "No API base URL configured"

        except ValueError as e:
            status = HealthStatus.UNHEALTHY
            error_msg = str(e)
        except httpx.TimeoutException:
            status = HealthStatus.UNHEALTHY
            error_msg = "Connection timeout"
        except httpx.RequestError as e:
            status = HealthStatus.UNHEALTHY
            error_msg = f"Connection error: {str(e)}"
        except Exception as e:
            status = HealthStatus.UNHEALTHY
            error_msg = f"Error: {str(e)}"

        end_time = datetime.now(timezone.utc)
        response_time_ms = (end_time - start_time).total_seconds() * 1000

        # Update provider health status
        provider.health_status = status.value
        provider.last_health_check = end_time
        db.commit()

        return ProviderHealthCheck(
            provider_id=provider.id,
            provider_name=provider.name,
            provider_type=provider.provider_type,
            status=status,
            response_time_ms=response_time_ms,
            error=error_msg,
            checked_at=end_time,
        )

    def to_provider_response(
        self,
        provider: LLMProvider,
        model_count: int = 0,
    ) -> LLMProviderResponse:
        """Convert LLMProvider to LLMProviderResponse.

        Args:
            provider: LLMProvider instance.
            model_count: Number of models for this provider.

        Returns:
            LLMProviderResponse instance.
        """
        return LLMProviderResponse(
            id=provider.id,
            name=provider.name,
            slug=provider.slug,
            description=provider.description,
            provider_type=provider.provider_type,
            api_base=provider.api_base,
            api_version=provider.api_version,
            config=sanitize_provider_config_for_response(provider.config),
            default_model=provider.default_model,
            default_temperature=provider.default_temperature,
            default_max_tokens=provider.default_max_tokens,
            enabled=provider.enabled,
            health_status=provider.health_status,
            last_health_check=provider.last_health_check,
            plugin_ids=provider.plugin_ids,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
            created_by=provider.created_by,
            modified_by=provider.modified_by,
            model_count=model_count,
        )

    def to_model_response(
        self,
        model: LLMModel,
        provider: Optional[LLMProvider] = None,
    ) -> LLMModelResponse:
        """Convert LLMModel to LLMModelResponse.

        Args:
            model: LLMModel instance.
            provider: Optional provider for name/type info.

        Returns:
            LLMModelResponse instance.
        """
        return LLMModelResponse(
            id=model.id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            model_name=model.model_name,
            model_alias=model.model_alias,
            description=model.description,
            supports_chat=model.supports_chat,
            supports_streaming=model.supports_streaming,
            supports_function_calling=model.supports_function_calling,
            supports_vision=model.supports_vision,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            enabled=model.enabled,
            deprecated=model.deprecated,
            created_at=model.created_at,
            updated_at=model.updated_at,
            provider_name=provider.name if provider else None,
            provider_type=provider.provider_type if provider else None,
        )
