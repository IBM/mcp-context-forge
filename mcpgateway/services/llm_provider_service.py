# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/llm_provider_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Provider Service

This module implements LLM provider management for the MCP Gateway.
It handles provider registration, CRUD operations, model management,
and health checks for the internal LLM Chat feature.
"""

# Standard
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# Third-Party
import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import LLMModel, LLMProvider, LLMProviderType
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

        # Create provider
        provider = LLMProvider(
            name=provider_data.name,
            slug=slugify(provider_data.name),
            description=provider_data.description,
            provider_type=provider_data.provider_type.value,
            api_key=encrypted_api_key,
            api_base=provider_data.api_base,
            api_version=provider_data.api_version,
            config=provider_data.config,
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
            provider.api_base = provider_data.api_base
        if provider_data.api_version is not None:
            provider.api_version = provider_data.api_version
        if provider_data.config is not None:
            provider.config = provider_data.config
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

    def toggle_provider(self, db: Session, provider_id: str) -> LLMProvider:
        """Toggle provider enabled status.

        Args:
            db: Database session.
            provider_id: Provider ID to toggle.

        Returns:
            Updated LLMProvider instance.
        """
        provider = self.get_provider(db, provider_id)
        provider.enabled = not provider.enabled
        db.commit()
        db.refresh(provider)
        logger.info(f"Toggled LLM provider: {provider.name} enabled={provider.enabled}")
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

    def toggle_model(self, db: Session, model_id: str) -> LLMModel:
        """Toggle model enabled status.

        Args:
            db: Database session.
            model_id: Model ID to toggle.

        Returns:
            Updated LLMModel instance.
        """
        model = self.get_model(db, model_id)
        model.enabled = not model.enabled
        db.commit()
        db.refresh(model)
        logger.info(f"Toggled LLM model: {model.model_id} enabled={model.enabled}")
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
            if provider.provider_type == LLMProviderType.OPENAI:
                # Check OpenAI models endpoint
                headers = {"Authorization": f"Bearer {api_key}"}
                base_url = provider.api_base or "https://api.openai.com/v1"
                response = await client.get(f"{base_url}/models", headers=headers, timeout=10.0)
                if response.status_code == 200:
                    status = HealthStatus.HEALTHY
                else:
                    status = HealthStatus.UNHEALTHY
                    error_msg = f"HTTP {response.status_code}"

            elif provider.provider_type == LLMProviderType.OLLAMA:
                # Check Ollama health endpoint
                base_url = provider.api_base or "http://localhost:11434"
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
                    response = await client.get(provider.api_base, timeout=5.0)
                    status = HealthStatus.HEALTHY if response.status_code < 500 else HealthStatus.UNHEALTHY
                else:
                    status = HealthStatus.UNKNOWN
                    error_msg = "No API base URL configured"

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
            config=provider.config,
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
