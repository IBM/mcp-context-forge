# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llm_admin_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Admin Router.
This module provides HTMX-based admin UI endpoints for LLM provider
and model management.
"""

# Standard
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.middleware.rbac import get_current_user_with_permissions, require_permission
from mcpgateway.services.llm_provider_service import (
    LLMModelNotFoundError,
    LLMProviderNotFoundError,
    LLMProviderService,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
llm_admin_router = APIRouter()

# Initialize service
llm_provider_service = LLMProviderService()


# ---------------------------------------------------------------------------
# LLM Providers Partial
# ---------------------------------------------------------------------------


@llm_admin_router.get("/providers/html", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def get_providers_partial(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get HTML partial for LLM providers list.

    Args:
        request: FastAPI request object.
        page: Page number.
        per_page: Items per page.
        current_user_ctx: Authenticated user context.

    Returns:
        HTML partial for providers table.
    """
    db = current_user_ctx["db"]

    providers, total = llm_provider_service.list_providers(
        db=db,
        page=page,
        page_size=per_page,
    )

    # Create pagination info
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1
    pagination = {
        "total_items": total,
        "page": page,
        "page_size": per_page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

    # Prepare provider data
    provider_data = []
    for provider in providers:
        provider_data.append(
            {
                "id": provider.id,
                "name": provider.name,
                "slug": provider.slug,
                "description": provider.description,
                "provider_type": provider.provider_type,
                "api_base": provider.api_base,
                "enabled": provider.enabled,
                "health_status": provider.health_status,
                "last_health_check": provider.last_health_check,
                "model_count": len(provider.models),
                "created_at": provider.created_at,
                "updated_at": provider.updated_at,
            }
        )

    return request.app.state.templates.TemplateResponse(
        "llm_providers_partial.html",
        {
            "request": request,
            "providers": provider_data,
            "provider_types": LLMProviderType.get_all_types(),
            "pagination": pagination,
            "root_path": request.scope.get("root_path", ""),
        },
    )


# ---------------------------------------------------------------------------
# LLM Models Partial
# ---------------------------------------------------------------------------


@llm_admin_router.get("/models/html", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def get_models_partial(
    request: Request,
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get HTML partial for LLM models list.

    Args:
        request: FastAPI request object.
        provider_id: Filter by provider ID.
        page: Page number.
        per_page: Items per page.
        current_user_ctx: Authenticated user context.

    Returns:
        HTML partial for models table.
    """
    db = current_user_ctx["db"]

    models, total = llm_provider_service.list_models(
        db=db,
        provider_id=provider_id,
        page=page,
        page_size=per_page,
    )

    # Create pagination info
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1
    pagination = {
        "total_items": total,
        "page": page,
        "page_size": per_page,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

    # Prepare model data with provider info
    model_data = []
    for model in models:
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
            provider_name = provider.name
            provider_type = provider.provider_type
        except LLMProviderNotFoundError:
            provider_name = "Unknown"
            provider_type = "unknown"

        model_data.append(
            {
                "id": model.id,
                "model_id": model.model_id,
                "model_name": model.model_name,
                "model_alias": model.model_alias,
                "description": model.description,
                "provider_id": model.provider_id,
                "provider_name": provider_name,
                "provider_type": provider_type,
                "supports_chat": model.supports_chat,
                "supports_streaming": model.supports_streaming,
                "supports_function_calling": model.supports_function_calling,
                "supports_vision": model.supports_vision,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
                "enabled": model.enabled,
                "deprecated": model.deprecated,
                "created_at": model.created_at,
                "updated_at": model.updated_at,
            }
        )

    # Get providers for dropdown
    providers, _ = llm_provider_service.list_providers(db, enabled_only=True)
    provider_options = [{"id": p.id, "name": p.name} for p in providers]

    return request.app.state.templates.TemplateResponse(
        "llm_models_partial.html",
        {
            "request": request,
            "models": model_data,
            "providers": provider_options,
            "selected_provider_id": provider_id,
            "pagination": pagination,
            "root_path": request.scope.get("root_path", ""),
        },
    )


# ---------------------------------------------------------------------------
# Provider Actions
# ---------------------------------------------------------------------------


@llm_admin_router.post("/providers/{provider_id}/toggle", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def toggle_provider_html(
    request: Request,
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Toggle provider enabled status and return updated row.

    Args:
        request: FastAPI request object.
        provider_id: Provider ID to toggle.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated provider row HTML.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        provider = llm_provider_service.toggle_provider(db, provider_id)

        return request.app.state.templates.TemplateResponse(
            "llm_provider_row.html",
            {
                "request": request,
                "provider": {
                    "id": provider.id,
                    "name": provider.name,
                    "slug": provider.slug,
                    "provider_type": provider.provider_type,
                    "api_base": provider.api_base,
                    "enabled": provider.enabled,
                    "health_status": provider.health_status,
                    "model_count": len(provider.models),
                },
                "root_path": request.scope.get("root_path", ""),
            },
        )
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_admin_router.post("/providers/{provider_id}/health")
@require_permission("admin.system_config")
async def check_provider_health(
    request: Request,
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
):
    """Check provider health and return status JSON.

    Args:
        request: FastAPI request object.
        provider_id: Provider ID to check.
        current_user_ctx: Authenticated user context.

    Returns:
        JSON with status, provider_id, latency_ms, and optional error.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        health = await llm_provider_service.check_provider_health(db, provider_id)

        return {
            "status": health.status.value,
            "provider_id": health.provider_id,
            "latency_ms": int(health.response_time_ms) if health.response_time_ms else None,
            "error": health.error,
        }
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_admin_router.delete("/providers/{provider_id}", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def delete_provider_html(
    request: Request,
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Delete provider and return empty response for row removal.

    Args:
        request: FastAPI request object.
        provider_id: Provider ID to delete.
        current_user_ctx: Authenticated user context.

    Returns:
        Empty response for HTMX row removal.

    Raises:
        HTTPException: If provider is not found.
    """
    try:
        db = current_user_ctx["db"]
        llm_provider_service.delete_provider(db, provider_id)
        return HTMLResponse(content="", status_code=200)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# Model Actions
# ---------------------------------------------------------------------------


@llm_admin_router.post("/models/{model_id}/toggle", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def toggle_model_html(
    request: Request,
    model_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Toggle model enabled status and return updated row.

    Args:
        request: FastAPI request object.
        model_id: Model ID to toggle.
        current_user_ctx: Authenticated user context.

    Returns:
        Updated model row HTML.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        model = llm_provider_service.toggle_model(db, model_id)

        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
            provider_name = provider.name
        except LLMProviderNotFoundError:
            provider_name = "Unknown"

        return request.app.state.templates.TemplateResponse(
            "llm_model_row.html",
            {
                "request": request,
                "model": {
                    "id": model.id,
                    "model_id": model.model_id,
                    "model_name": model.model_name,
                    "provider_name": provider_name,
                    "supports_streaming": model.supports_streaming,
                    "supports_function_calling": model.supports_function_calling,
                    "supports_vision": model.supports_vision,
                    "enabled": model.enabled,
                    "deprecated": model.deprecated,
                },
                "root_path": request.scope.get("root_path", ""),
            },
        )
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@llm_admin_router.delete("/models/{model_id}", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def delete_model_html(
    request: Request,
    model_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Delete model and return empty response for row removal.

    Args:
        request: FastAPI request object.
        model_id: Model ID to delete.
        current_user_ctx: Authenticated user context.

    Returns:
        Empty response for HTMX row removal.

    Raises:
        HTTPException: If model is not found.
    """
    try:
        db = current_user_ctx["db"]
        llm_provider_service.delete_model(db, model_id)
        return HTMLResponse(content="", status_code=200)
    except LLMModelNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ---------------------------------------------------------------------------
# LLM API Info/Test Partial
# ---------------------------------------------------------------------------


@llm_admin_router.get("/api-info/html", response_class=HTMLResponse)
@require_permission("admin.system_config")
async def get_api_info_partial(
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
) -> HTMLResponse:
    """Get HTML partial for LLM API info and testing.

    Args:
        request: FastAPI request object.
        current_user_ctx: Authenticated user context.

    Returns:
        HTML partial for API info and testing.
    """
    # First-Party
    from mcpgateway.config import settings

    db = current_user_ctx["db"]

    # Get enabled providers and models
    providers, total_providers = llm_provider_service.list_providers(db, enabled_only=True)
    models, total_models = llm_provider_service.list_models(db, enabled_only=True)

    # Prepare model data with provider info
    model_data = []
    for model in models:
        try:
            provider = llm_provider_service.get_provider(db, model.provider_id)
            model_data.append(
                {
                    "model_id": model.model_id,
                    "model_name": model.model_name,
                    "provider": {"name": provider.name},
                    "supports_chat": model.supports_chat,
                    "supports_streaming": model.supports_streaming,
                    "supports_vision": model.supports_vision,
                    "supports_function_calling": model.supports_function_calling,
                }
            )
        except LLMProviderNotFoundError:
            continue

    stats = {
        "total_providers": total_providers,
        "total_models": total_models,
    }

    return request.app.state.templates.TemplateResponse(
        "llm_api_info_partial.html",
        {
            "request": request,
            "providers": providers,
            "models": model_data,
            "stats": stats,
            "llmchat_enabled": settings.llmchat_enabled,
            "root_path": request.scope.get("root_path", ""),
        },
    )


# ---------------------------------------------------------------------------
# LLM API Test (Admin) - No API Key Required
# ---------------------------------------------------------------------------


@llm_admin_router.post("/test")
@require_permission("admin.system_config")
async def admin_test_api(
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
):
    """Test LLM API without requiring an API key.

    This endpoint allows admins to test LLM models directly without needing
    to enter or have access to a virtual API key.

    Args:
        request: FastAPI request object.
        current_user_ctx: Authenticated user context.

    Returns:
        Test result with metrics.

    Raises:
        HTTPException: If test fails.
    """
    # Standard
    import time

    # Third-Party
    from fastapi.responses import JSONResponse

    # First-Party
    from mcpgateway.services.llm_proxy_service import LLMProxyService

    db = current_user_ctx["db"]
    body = await request.json()

    test_type = body.get("test_type", "models")
    model_id = body.get("model_id")
    message = body.get("message", "Hello! Please respond with a short greeting.")
    max_tokens = body.get("max_tokens", 100)

    start_time = time.time()

    try:
        if test_type == "models":
            # List available models
            models = llm_provider_service.get_gateway_models(db)
            duration_ms = int((time.time() - start_time) * 1000)

            model_list = [{"id": m.model_id, "owned_by": m.provider_name} for m in models]

            return JSONResponse(
                content={
                    "success": True,
                    "test_type": "models",
                    "data": {"object": "list", "data": model_list},
                    "metrics": {
                        "duration": duration_ms,
                        "modelCount": len(model_list),
                    },
                }
            )

        elif test_type == "chat":
            if not model_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="model_id is required for chat test",
                )

            # First-Party
            from mcpgateway.llm_schemas import ChatCompletionRequest, ChatMessage

            # Create chat completion request
            chat_request = ChatCompletionRequest(
                model=model_id,
                messages=[ChatMessage(role="user", content=message)],
                max_tokens=max_tokens,
                stream=False,
            )

            proxy_service = LLMProxyService()
            response = await proxy_service.chat_completion(db, chat_request)
            duration_ms = int((time.time() - start_time) * 1000)

            # Extract assistant message
            assistant_message = ""
            if response.choices and len(response.choices) > 0:
                assistant_message = response.choices[0].message.content or ""

            return JSONResponse(
                content={
                    "success": True,
                    "test_type": "chat",
                    "data": response.model_dump(),
                    "assistant_message": assistant_message,
                    "metrics": {
                        "duration": duration_ms,
                        "promptTokens": response.usage.prompt_tokens if response.usage else 0,
                        "completionTokens": response.usage.completion_tokens if response.usage else 0,
                        "totalTokens": response.usage.total_tokens if response.usage else 0,
                        "responseModel": response.model,
                    },
                }
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown test type: {test_type}",
            )

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Admin test failed: {e}")
        return JSONResponse(
            content={
                "success": False,
                "error": str(e),
                "metrics": {"duration": duration_ms},
            },
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Provider Defaults and Model Discovery
# ---------------------------------------------------------------------------


@llm_admin_router.get("/provider-defaults")
@require_permission("admin.system_config")
async def get_provider_defaults(
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
):
    """Get default configuration for all provider types.

    Args:
        request: FastAPI request object.
        current_user_ctx: Authenticated user context.

    Returns:
        Dictionary of provider type to default config.
    """
    return LLMProviderType.get_provider_defaults()


@llm_admin_router.post("/providers/{provider_id}/fetch-models")
@require_permission("admin.system_config")
async def fetch_provider_models(
    request: Request,
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
):
    """Fetch available models from a provider's API.

    Args:
        request: FastAPI request object.
        provider_id: Provider ID to fetch models from.
        current_user_ctx: Authenticated user context.

    Returns:
        List of available models from the provider.

    Raises:
        HTTPException: If provider is not found.
    """
    # Third-Party
    import httpx

    # First-Party
    from mcpgateway.utils.services_auth import decode_auth

    db = current_user_ctx["db"]

    try:
        provider = llm_provider_service.get_provider(db, provider_id)
    except LLMProviderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # Get provider defaults for model list support
    defaults = LLMProviderType.get_provider_defaults()
    provider_config = defaults.get(provider.provider_type, {})

    if not provider_config.get("supports_model_list"):
        return {
            "success": False,
            "error": f"Provider type '{provider.provider_type}' does not support model listing",
            "models": [],
        }

    # Build API URL
    base_url = provider.api_base or provider_config.get("api_base", "")
    if not base_url:
        return {
            "success": False,
            "error": "No API base URL configured",
            "models": [],
        }

    models_endpoint = provider_config.get("models_endpoint", "/models")
    url = f"{base_url.rstrip('/')}{models_endpoint}"

    # Get API key if needed
    headers = {"Content-Type": "application/json"}
    if provider.api_key:
        auth_data = decode_auth(provider.api_key)
        api_key = auth_data.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            # Parse models based on provider type
            models = []
            if "data" in data:
                # OpenAI-compatible format
                for model in data["data"]:
                    model_id = model.get("id", "")
                    models.append(
                        {
                            "id": model_id,
                            "name": model.get("name", model_id),
                            "owned_by": model.get("owned_by", provider.provider_type),
                            "created": model.get("created"),
                        }
                    )
            elif "models" in data:
                # Ollama native format or Cohere format
                for model in data["models"]:
                    if isinstance(model, dict):
                        model_id = model.get("name", model.get("id", ""))
                        models.append(
                            {
                                "id": model_id,
                                "name": model_id,
                                "owned_by": provider.provider_type,
                            }
                        )
                    else:
                        models.append(
                            {
                                "id": str(model),
                                "name": str(model),
                                "owned_by": provider.provider_type,
                            }
                        )

            return {
                "success": True,
                "models": models,
                "count": len(models),
            }

    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            "models": [],
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "error": f"Connection error: {str(e)}",
            "models": [],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "models": [],
        }


@llm_admin_router.post("/providers/{provider_id}/sync-models")
@require_permission("admin.system_config")
async def sync_provider_models(
    request: Request,
    provider_id: str,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
):
    """Sync models from provider API to database.

    Fetches available models from the provider and creates model records
    for any that don't already exist.

    Args:
        request: FastAPI request object.
        provider_id: Provider ID to sync models for.
        current_user_ctx: Authenticated user context.

    Returns:
        Sync results with counts of added/skipped models.
    """
    # First-Party
    from mcpgateway.llm_schemas import LLMModelCreate

    db = current_user_ctx["db"]

    # First fetch models from the provider
    fetch_result = await fetch_provider_models(request, provider_id, current_user_ctx)

    if not fetch_result.get("success"):
        return fetch_result

    models = fetch_result.get("models", [])
    if not models:
        return {
            "success": True,
            "message": "No models found to sync",
            "added": 0,
            "skipped": 0,
        }

    # Get existing models for this provider
    existing_models, _ = llm_provider_service.list_models(db, provider_id=provider_id)
    existing_model_ids = {m.model_id for m in existing_models}

    added = 0
    skipped = 0

    for model in models:
        model_id = model.get("id", "")
        if not model_id:
            continue

        if model_id in existing_model_ids:
            skipped += 1
            continue

        # Create the model
        try:
            model_create = LLMModelCreate(
                provider_id=provider_id,
                model_id=model_id,
                model_name=model.get("name", model_id),
                description=f"Auto-synced from {model.get('owned_by', 'provider')}",
                supports_chat=True,
                supports_streaming=True,
                enabled=True,
            )
            llm_provider_service.create_model(db, model_create)
            added += 1
        except Exception as e:
            logger.warning(f"Failed to create model {model_id}: {e}")
            skipped += 1

    return {
        "success": True,
        "message": f"Synced models: {added} added, {skipped} skipped",
        "added": added,
        "skipped": skipped,
        "total": len(models),
    }
