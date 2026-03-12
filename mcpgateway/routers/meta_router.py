# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/meta_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Tool Router.
This module provides FastAPI routes for meta-tools (describe_tool, execute_tool).

Examples:
    >>> from fastapi import FastAPI
    >>> from mcpgateway.routers.meta_router import router
    >>> app = FastAPI()
    >>> app.include_router(router, prefix="/meta", tags=["Meta Tools"])
    >>> isinstance(router, APIRouter)
    True
"""

# Standard
import time
from typing import Any, Dict, Optional

# Third-Party
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import get_db
from mcpgateway.meta_server.schemas import (
    DescribeToolRequest,
    DescribeToolResponse,
    ExecuteToolRequest,
    ExecuteToolResponse,
    GetSimilarToolsRequest,
    GetSimilarToolsResponse,
    GetToolCategoriesRequest,
    GetToolCategoriesResponse,
    ListToolsRequest,
    ListToolsResponse,
    SearchToolsRequest,
    SearchToolsResponse,
)
from mcpgateway.meta_server.service import get_meta_server_service
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.meta_tool_service import MetaToolService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Create router
router = APIRouter(prefix="/meta", tags=["Meta Tools"])


@router.post("/describe_tool", response_model=DescribeToolResponse)
async def describe_tool(
    req: DescribeToolRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    x_scope: Optional[str] = Header(None, alias="X-Scope"),
) -> DescribeToolResponse:
    """Get detailed information about a specific tool including schema and metadata.

    Args:
        req: Describe tool request
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session
        x_scope: Optional scope header for filtering

    Returns:
        DescribeToolResponse: Tool details

    Raises:
        HTTPException: If tool is not found or access is denied
    """
    try:
        service = MetaToolService(db)
        user_email = current_user_ctx.get("email")
        token_teams = current_user_ctx.get("teams")
        is_admin = current_user_ctx.get("is_admin", False)

        response = await service.describe_tool(
            tool_name=req.tool_name,
            include_metrics=req.include_metrics,
            user_email=user_email,
            token_teams=token_teams,
            is_admin=is_admin,
            scope=x_scope,
        )
        return response
    except ValueError as e:
        logger.warning(f"Tool not found or access denied: {req.tool_name} - {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error describing tool {req.tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/execute_tool", response_model=ExecuteToolResponse)
async def execute_tool(
    req: ExecuteToolRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    x_scope: Optional[str] = Header(None, alias="X-Scope"),
) -> ExecuteToolResponse:
    """Execute a tool by name with the provided arguments.

    Validates input against the tool's JSON schema and routes execution to
    the correct backend server.

    Args:
        req: Execute tool request
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session
        x_scope: Optional scope header for filtering

    Returns:
        ExecuteToolResponse: Execution result with metadata

    Raises:
        HTTPException: If tool is not found, validation fails, or execution fails
    """
    start_time = time.time()

    try:
        service = MetaToolService(db)
        user_email = current_user_ctx.get("email")
        token_teams = current_user_ctx.get("teams")
        is_admin = current_user_ctx.get("is_admin", False)

        # Extract headers for forwarding
        request_headers = dict(request.headers)

        response = await service.execute_tool(
            tool_name=req.tool_name,
            arguments=req.arguments,
            user_email=user_email,
            token_teams=token_teams,
            is_admin=is_admin,
            scope=x_scope,
            request_headers=request_headers,
        )

        # Add execution time
        execution_time_ms = int((time.time() - start_time) * 1000)
        response.execution_time_ms = execution_time_ms

        return response
    except ValueError as e:
        logger.warning(f"Validation error for tool {req.tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        logger.warning(f"Access denied for tool {req.tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing tool {req.tool_name}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/search_tools", response_model=SearchToolsResponse)
async def search_tools(
    req: SearchToolsRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    x_scope: Optional[str] = Header(None, alias="X-Scope"),
) -> SearchToolsResponse:
    """Search for tools using hybrid semantic and keyword search.

    Performs semantic search via embeddings + keyword fallback with scope filtering.

    Args:
        req: Search request parameters
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session
        x_scope: Optional scope header for filtering

    Returns:
        SearchToolsResponse: Ranked search results

    Raises:
        HTTPException: If search fails
    """
    try:
        meta_service = get_meta_server_service()
        
        # Build arguments dict with scope from header if provided
        arguments = req.model_dump()
        if x_scope:
            try:
                import json
                arguments["scope"] = json.loads(x_scope)
            except json.JSONDecodeError:
                logger.warning(f"Invalid X-Scope header: {x_scope}")
        
        # Call the service handler
        result = await meta_service._search_tools(arguments)
        return SearchToolsResponse(**result)
    except Exception as e:
        logger.error(f"Error searching tools: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/list_tools", response_model=ListToolsResponse)
async def list_tools(
    req: ListToolsRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    x_scope: Optional[str] = Header(None, alias="X-Scope"),
) -> ListToolsResponse:
    """List tools with pagination, sorting, and filtering.

    Args:
        req: List request parameters
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session
        x_scope: Optional scope header for filtering

    Returns:
        ListToolsResponse: Paginated tool list

    Raises:
        HTTPException: If listing fails
    """
    try:
        meta_service = get_meta_server_service()
        
        # Build arguments dict with scope from header if provided
        arguments = req.model_dump()
        if x_scope:
            try:
                import json
                arguments["scope"] = json.loads(x_scope)
            except json.JSONDecodeError:
                logger.warning(f"Invalid X-Scope header: {x_scope}")
        
        # Call the service handler
        result = await meta_service._list_tools(arguments)
        return ListToolsResponse(**result)
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/get_similar_tools", response_model=GetSimilarToolsResponse)
async def get_similar_tools(
    req: GetSimilarToolsRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
    x_scope: Optional[str] = Header(None, alias="X-Scope"),
) -> GetSimilarToolsResponse:
    """Find tools similar to a reference tool using vector similarity.

    Args:
        req: Similarity search request
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session
        x_scope: Optional scope header for filtering

    Returns:
        GetSimilarToolsResponse: Similar tools with scores

    Raises:
        HTTPException: If similarity search fails
    """
    try:
        meta_service = get_meta_server_service()
        
        # Build arguments dict with scope from header if provided
        arguments = req.model_dump()
        if x_scope:
            try:
                import json
                arguments["scope"] = json.loads(x_scope)
            except json.JSONDecodeError:
                logger.warning(f"Invalid X-Scope header: {x_scope}")
        
        # Call the service handler
        result = await meta_service._get_similar_tools(arguments)
        return GetSimilarToolsResponse(**result)
    except Exception as e:
        logger.error(f"Error finding similar tools: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@router.post("/get_tool_categories", response_model=GetToolCategoriesResponse)
async def get_tool_categories(
    req: GetToolCategoriesRequest,
    request: Request,
    current_user_ctx: dict = Depends(get_current_user_with_permissions),
    db: Session = Depends(get_db),
) -> GetToolCategoriesResponse:
    """Get aggregated tool categories with counts.

    Args:
        req: Category request parameters
        request: FastAPI request object
        current_user_ctx: Current user context with permissions
        db: Database session

    Returns:
        GetToolCategoriesResponse: Categories with tool counts

    Raises:
        HTTPException: If category aggregation fails
    """
    try:
        meta_service = get_meta_server_service()
        
        # Call the service handler
        arguments = req.model_dump()
        result = await meta_service._get_tool_categories(arguments)
        return GetToolCategoriesResponse(**result)
    except Exception as e:
        logger.error(f"Error getting tool categories: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
