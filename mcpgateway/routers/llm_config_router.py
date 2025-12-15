# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llm_config_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Configuration Router.
This module provides FastAPI routes for LLM provider and model management.
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import get_db
from mcpgateway.llm_schemas import (
    GatewayModelsResponse,
    LLMModelCreate,
    LLMModelListResponse,
    LLMModelResponse,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderListResponse,
    LLMProviderResponse,
    LLMProviderUpdate,
    ProviderHealthCheck,
)
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.llm_provider_service import (
    LLMModelConflictError,
    LLMModelNotFoundError,
    LLMProviderNameConflictError,
    LLMProviderNotFoundError,
    LLMProviderService,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
llm_config_router = APIRouter()

# Initialize service
llm_provider_service = LLMProviderService()


# ---------------------------------------------------------------------------
# Provider CRUD Endpoints
# ---------------------------------------------------------------------------


@llm_config_router.post(
    "/providers",
    response_model=LLMProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM Provider",
    description="Create a new LLM provider configuration.",
)
@require_permission("admin.system_config")
async def create_provider(
    provider_data: LLMProviderCreate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMProviderResponse:
    """Create a new LLM provider.

    Args:
        provider_data: Provider configuration data.
        current_user_ctx: Authenticated user context.

    Returns:
        Created provider response.

    Raises:
        HTTPException: If provider name conflicts or creation fails.
    """
    try:
        db = current_user_ctx["db"]
        provider = llm_provider_service.create_provider(
            db=db,
            provider_data=provider_data,
            created_by=current_user_ctx.get("email"),
        )
        model_count = len(provider.models)
        return llm_provider_service.to_provider_response(provider, model_count)
    except LLMProviderNameConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create LLM provider: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create provider: {str(e)}",
        )


@llm_config_router.get(
    "/providers",
    response_model=LLMProviderListResponse,
    summary="List LLM Providers",
    description="List all configured LLM providers.",
)
@require_permission("admin.system_config")
async def list_providers(
    enabled_only: bool = Query(False, description="Only return enabled providers"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMProviderListResponse:
    """List all LLM providers.

    Args:
        enabled_only: Filter to enabled providers only.
        page: Page number.
        page_size: Items per page.
        current_user_ctx: Authenticated user context.

    Returns:
        Paginated list of providers.
    """
    db = current_user_ctx["db"]
    providers, total = llm_provider_service.list_providers(
        db=db,
        enabled_only=enabled_only,
        page=page,
        page_size=page_size,
    )

    provider_responses = [llm_provider_service.to_provider_response(p, len(p.models)) for p in providers]

    return LLMProviderListResponse(
        providers=provider_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@llm_config_router.get(
    "/providers/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Get LLM Provider",
    description="Get a specific LLM provider by ID.",
)
@require_permission("admin.system_config")
async def get_provider(
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMProviderResponse:
    """Get an LLM provider by ID.

    Args:
        provider_id: Provider ID.
        current_user_ctx: Authenticated user context.

    Returns:
        Provider response.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        provider = llm_provider_service.get_provider(db, provider_id)
        model_count = len(provider.models)
        return llm_provider_service.to_provider_response(provider, model_count)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.patch(
    "/providers/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Update LLM Provider",
    description="Update an existing LLM provider.",
)
@require_permission("admin.system_config")
async def update_provider(
    provider_id: str,
    provider_data: LLMProviderUpdate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMProviderResponse:
    """Update an LLM provider.

    Args:
        provider_id: Provider ID.
        provider_data: Updated provider data.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated provider response.

    Raises:
        HTTPException: If provider is not found or name conflicts.
    """
    try:
        db = current_user_ctx["db"]
        provider = llm_provider_service.update_provider(
            db=db,
            provider_id=provider_id,
            provider_data=provider_data,
            modified_by=current_user_ctx.get("email"),
        )
        model_count = len(provider.models)
        return llm_provider_service.to_provider_response(provider, model_count)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except LLMProviderNameConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@llm_config_router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM Provider",
    description="Delete an LLM provider and all its models.",
)
@require_permission("admin.system_config")
async def delete_provider(
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> None:
    """Delete an LLM provider.

    Args:
        provider_id: Provider ID.
        current_user_ctx: Authenticated user context.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        llm_provider_service.delete_provider(db, provider_id)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.post(
    "/providers/{provider_id}/toggle",
    response_model=LLMProviderResponse,
    summary="Toggle LLM Provider",
    description="Toggle the enabled status of an LLM provider.",
)
@require_permission("admin.system_config")
async def toggle_provider(
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMProviderResponse:
    """Toggle provider enabled status.

    Args:
        provider_id: Provider ID.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated provider response.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        provider = llm_provider_service.toggle_provider(db, provider_id)
        model_count = len(provider.models)
        return llm_provider_service.to_provider_response(provider, model_count)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.post(
    "/providers/{provider_id}/health",
    response_model=ProviderHealthCheck,
    summary="Check Provider Health",
    description="Perform a health check on an LLM provider.",
)
@require_permission("admin.system_config")
async def check_provider_health(
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> ProviderHealthCheck:
    """Check health of an LLM provider.

    Args:
        provider_id: Provider ID.
        current_user_ctx: Authenticated user context.

    Returns:
        Health check result.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        return await llm_provider_service.check_provider_health(db, provider_id)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Model CRUD Endpoints
# ---------------------------------------------------------------------------


@llm_config_router.post(
    "/models",
    response_model=LLMModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM Model",
    description="Create a new LLM model for a provider.",
)
@require_permission("admin.system_config")
async def create_model(
    model_data: LLMModelCreate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMModelResponse:
    """Create a new LLM model.

    Args:
        model_data: Model configuration data.
        current_user_ctx: Authenticated user context.

    Returns:
        Created model response.

    Raises:
        HTTPException: If provider is not found or model conflicts.
    """
    try:
        db = current_user_ctx["db"]
        model = llm_provider_service.create_model(db, model_data)
        provider = llm_provider_service.get_provider(db, model.provider_id)
        return llm_provider_service.to_model_response(model, provider)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except LLMModelConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@llm_config_router.get(
    "/models",
    response_model=LLMModelListResponse,
    summary="List LLM Models",
    description="List all configured LLM models.",
)
@require_permission("admin.system_config")
async def list_models(
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    enabled_only: bool = Query(False, description="Only return enabled models"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMModelListResponse:
    """List all LLM models.

    Args:
        provider_id: Filter by provider ID.
        enabled_only: Filter to enabled models only.
        page: Page number.
        page_size: Items per page.
        current_user_ctx: Authenticated user context.

    Returns:
        Paginated list of models.
    """
    db = current_user_ctx["db"]
    models, total = llm_provider_service.list_models(
        db=db,
        provider_id=provider_id,
        enabled_only=enabled_only,
        page=page,
        page_size=page_size,
    )

    model_responses = []
    for model in models:
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
            model_responses.append(llm_provider_service.to_model_response(model, provider))
        except LLMProviderNotFoundError:
            model_responses.append(llm_provider_service.to_model_response(model))

    return LLMModelListResponse(
        models=model_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@llm_config_router.get(
    "/models/{model_id}",
    response_model=LLMModelResponse,
    summary="Get LLM Model",
    description="Get a specific LLM model by ID.",
)
@require_permission("admin.system_config")
async def get_model(
    model_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMModelResponse:
    """Get an LLM model by ID.

    Args:
        model_id: Model ID.
        current_user_ctx: Authenticated user context.

    Returns:
        Model response.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        model = llm_provider_service.get_model(db, model_id)
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
        except LLMProviderNotFoundError:
            provider = None
        return llm_provider_service.to_model_response(model, provider)
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.patch(
    "/models/{model_id}",
    response_model=LLMModelResponse,
    summary="Update LLM Model",
    description="Update an existing LLM model.",
)
@require_permission("admin.system_config")
async def update_model(
    model_id: str,
    model_data: LLMModelUpdate,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMModelResponse:
    """Update an LLM model.

    Args:
        model_id: Model ID.
        model_data: Updated model data.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated model response.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        model = llm_provider_service.update_model(db, model_id, model_data)
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
        except LLMProviderNotFoundError:
            provider = None
        return llm_provider_service.to_model_response(model, provider)
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.delete(
    "/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM Model",
    description="Delete an LLM model.",
)
@require_permission("admin.system_config")
async def delete_model(
    model_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> None:
    """Delete an LLM model.

    Args:
        model_id: Model ID.
        current_user_ctx: Authenticated user context.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        llm_provider_service.delete_model(db, model_id)
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_config_router.post(
    "/models/{model_id}/toggle",
    response_model=LLMModelResponse,
    summary="Toggle LLM Model",
    description="Toggle the enabled status of an LLM model.",
)
@require_permission("admin.system_config")
async def toggle_model(
    model_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> LLMModelResponse:
    """Toggle model enabled status.

    Args:
        model_id: Model ID.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated model response.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        model = llm_provider_service.toggle_model(db, model_id)
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
        except LLMProviderNotFoundError:
            provider = None
        return llm_provider_service.to_model_response(model, provider)
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Gateway Models Endpoint (for LLM Chat dropdown)
# ---------------------------------------------------------------------------


@llm_config_router.get(
    "/gateway/models",
    response_model=GatewayModelsResponse,
    summary="Get Gateway Models",
    description="Get enabled models for the LLM Chat dropdown.",
)
async def get_gateway_models(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> GatewayModelsResponse:
    """Get enabled models for the LLM Chat dropdown.

    This endpoint is used by the LLM Chat UI to populate the model selector.
    It returns only enabled chat-capable models from enabled providers.

    Args:
        db: Database session.
        current_user: Authenticated user.

    Returns:
        List of available gateway models.
    """
    models = llm_provider_service.get_gateway_models(db)
    return GatewayModelsResponse(models=models, count=len(models))
