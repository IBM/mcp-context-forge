# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/llm_proxy_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Proxy Router.
This module provides OpenAI-compatible API endpoints for the internal
LLM proxy service. It routes requests to configured LLM providers.
"""

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.config import settings
from mcpgateway.db import get_db
from mcpgateway.llm_schemas import ChatCompletionRequest, ChatCompletionResponse
from mcpgateway.services.llm_provider_service import (
    LLMModelNotFoundError,
    LLMProviderNotFoundError,
)
from mcpgateway.services.llm_proxy_service import (
    LLMProxyAuthError,
    LLMProxyRequestError,
    LLMProxyService,
)
from mcpgateway.services.logging_service import LoggingService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
llm_proxy_router = APIRouter()

# Initialize service
llm_proxy_service = LLMProxyService()


@llm_proxy_router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    summary="Chat Completions",
    description="Create a chat completion using configured LLM providers. OpenAI-compatible API.",
    responses={
        200: {"description": "Chat completion response"},
        400: {"description": "Invalid request"},
        401: {"description": "Authentication required"},
        404: {"description": "Model not found"},
        500: {"description": "Provider error"},
    },
)
async def chat_completions(
    request: ChatCompletionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a chat completion.

    This endpoint is compatible with the OpenAI Chat Completions API.
    It routes requests to configured LLM providers based on the model ID.

    Args:
        request: Chat completion request (OpenAI-compatible).
        db: Database session.
        current_user: Authenticated user.

    Returns:
        ChatCompletionResponse or StreamingResponse for streaming requests.

    Raises:
        HTTPException: If model not found, streaming disabled, or provider error.
    """
    # Check if streaming is enabled
    if request.stream and not settings.llm_streaming_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Streaming is disabled in gateway configuration",
        )

    try:
        if request.stream:
            # Return streaming response
            return StreamingResponse(
                llm_proxy_service.chat_completion_stream(db, request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # Return regular response
            return await llm_proxy_service.chat_completion(db, request)

    except LLMModelNotFoundError as e:
        logger.warning(f"Model not found: {request.model}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except LLMProviderNotFoundError as e:
        logger.warning(f"Provider not found for model: {request.model}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except LLMProxyAuthError as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except LLMProxyRequestError as e:
        logger.error(f"Proxy request error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error in chat completion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}",
        )


@llm_proxy_router.get(
    "/models",
    summary="List Models",
    description="List available models from configured providers. OpenAI-compatible API.",
)
async def list_models(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List available models.

    Returns a list of available models in OpenAI-compatible format.

    Args:
        db: Database session.
        current_user: Authenticated user.

    Returns:
        List of available models.
    """
    # First-Party
    from mcpgateway.services.llm_provider_service import LLMProviderService

    provider_service = LLMProviderService()
    models = provider_service.get_gateway_models(db)

    # Format as OpenAI-compatible response
    model_list = []
    for model in models:
        model_list.append(
            {
                "id": model.model_id,
                "object": "model",
                "created": 0,
                "owned_by": model.provider_name,
            }
        )

    return {
        "object": "list",
        "data": model_list,
    }
