# -*- coding: utf-8 -*-
"""
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Gateway - Utility API Router.

This module provides utility endpoints for the MCP Gateway including JSON-RPC handling,
WebSocket connections, and protocol detection utilities. It serves as a bridge between
different transport protocols and the core MCP functionality.

Features and Responsibilities:
- JSON-RPC 2.0 compliant request/response handling
- WebSocket endpoint for real-time bidirectional communication
- Protocol detection for proxy scenarios (HTTP/HTTPS)
- URL construction with proper scheme handling
- Multi-service integration (tools, resources, prompts, gateways, etc.)
- Request forwarding and method routing
- Comprehensive error handling with JSON-RPC error responses

Endpoints:
- POST /rpc: Handle JSON-RPC requests with method routing
- WebSocket /ws: Real-time JSON-RPC over WebSocket

Utility Functions:
- get_protocol_from_request: Detect HTTP/HTTPS from headers
- update_url_protocol: Construct URLs with correct protocol

Parameters:
- All endpoints require authentication via JWT Bearer token or Basic Auth
- JSON-RPC requests must follow 2.0 specification format
- WebSocket connections support continuous bidirectional messaging
- Protocol detection handles X-Forwarded-Proto headers for reverse proxies

Returns:
- RPC endpoint returns JSON-RPC 2.0 compliant responses
- WebSocket endpoint maintains persistent connection for real-time communication
- Error responses follow JSON-RPC error format with appropriate codes
"""

# Standard
import asyncio
import json

# Third-Party
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.background import BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import get_db

# Import dependency injection functions
from mcpgateway.dependencies import (
    get_gateway_service,
    get_logging_service,
    get_prompt_service,
    get_resource_service,
    get_root_service,
    get_tool_service,
)
from mcpgateway.models import LogLevel
from mcpgateway.registry import session_registry
from mcpgateway.schemas import RPCRequest
from mcpgateway.transports.sse_transport import SSETransport
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.url_utils import update_url_protocol
from mcpgateway.utils.verify_credentials import require_auth, verify_jwt_token
from mcpgateway.validation.jsonrpc import JSONRPCError

# Initialize logging service first
logging_service = get_logging_service()
logger = logging_service.get_logger("utility routes")

# Initialize service
tool_service = get_tool_service()
resource_service = get_resource_service()
prompt_service = get_prompt_service()
gateway_service = get_gateway_service()
root_service = get_root_service()


# Create API router
utility_router = APIRouter(tags=["Utilities"])


@utility_router.post("/rpc/")
@utility_router.post("/rpc")
async def handle_rpc(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):  # revert this back
    """Handle RPC requests.

    Args:
        request (Request): The incoming FastAPI request.
        db (Session): Database session.
        user (str): The authenticated user.

    Returns:
        Response with the RPC result or error.
    """
    try:
        logger.debug(f"User {user} made an RPC request")
        body = await request.json()
        method = body["method"]
        req_id = body.get("id") if "body" in locals() else None
        params = body.get("params", {})
        server_id = params.get("server_id", None)
        cursor = params.get("cursor")  # Extract cursor parameter

        RPCRequest(jsonrpc="2.0", method=method, params=params)  # Validate the request body against the RPCRequest model

        if method == "initialize":
            result = await session_registry.handle_initialize_logic(body.get("params", {}))
            if hasattr(result, "model_dump"):
                result = result.model_dump(by_alias=True, exclude_none=True)
        elif method == "tools/list":
            if server_id:
                tools = await tool_service.list_server_tools(db, server_id, cursor=cursor)
            else:
                tools = await tool_service.list_tools(db, cursor=cursor)
            result = {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}
        elif method == "list_tools":  # Legacy endpoint
            if server_id:
                tools = await tool_service.list_server_tools(db, server_id, cursor=cursor)
            else:
                tools = await tool_service.list_tools(db, cursor=cursor)
            result = {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}
        elif method == "list_gateways":
            gateways = await gateway_service.list_gateways(db, include_inactive=False)
            result = {"gateways": [g.model_dump(by_alias=True, exclude_none=True) for g in gateways]}
        elif method == "list_roots":
            roots = await root_service.list_roots()
            result = {"roots": [r.model_dump(by_alias=True, exclude_none=True) for r in roots]}
        elif method == "resources/list":
            if server_id:
                resources = await resource_service.list_server_resources(db, server_id)
            else:
                resources = await resource_service.list_resources(db)
            result = {"resources": [r.model_dump(by_alias=True, exclude_none=True) for r in resources]}
        elif method == "resources/read":
            uri = params.get("uri")
            request_id = params.get("requestId", None)
            if not uri:
                raise JSONRPCError(-32602, "Missing resource URI in parameters", params)
            result = await resource_service.read_resource(db, uri, request_id=request_id, user=user)
            if hasattr(result, "model_dump"):
                result = {"contents": [result.model_dump(by_alias=True, exclude_none=True)]}
            else:
                result = {"contents": [result]}
        elif method == "prompts/list":
            if server_id:
                prompts = await prompt_service.list_server_prompts(db, server_id, cursor=cursor)
            else:
                prompts = await prompt_service.list_prompts(db, cursor=cursor)
            result = {"prompts": [p.model_dump(by_alias=True, exclude_none=True) for p in prompts]}
        elif method == "prompts/get":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not name:
                raise JSONRPCError(-32602, "Missing prompt name in parameters", params)
            result = await prompt_service.get_prompt(db, name, arguments)
            if hasattr(result, "model_dump"):
                result = result.model_dump(by_alias=True, exclude_none=True)
        elif method == "ping":
            # Per the MCP spec, a ping returns an empty result.
            result = {}
        elif method == "tools/call":
            # Get request headers
            headers = {k.lower(): v for k, v in request.headers.items()}
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not name:
                raise JSONRPCError(-32602, "Missing tool name in parameters", params)
            try:
                result = await tool_service.invoke_tool(db=db, name=name, arguments=arguments, request_headers=headers)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(by_alias=True, exclude_none=True)
            except ValueError:
                result = await gateway_service.forward_request(db, method, params)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(by_alias=True, exclude_none=True)
        # TODO: Implement methods  # pylint: disable=fixme
        elif method == "resources/templates/list":
            result = {}
        elif method.startswith("roots/"):
            result = {}
        elif method.startswith("notifications/"):
            result = {}
        elif method.startswith("sampling/"):
            result = {}
        elif method.startswith("elicitation/"):
            result = {}
        elif method.startswith("completion/"):
            result = {}
        elif method.startswith("logging/"):
            result = {}
        else:
            # Backward compatibility: Try to invoke as a tool directly
            # This allows both old format (method=tool_name) and new format (method=tools/call)
            headers = {k.lower(): v for k, v in request.headers.items()}
            try:
                result = await tool_service.invoke_tool(db=db, name=method, arguments=params, request_headers=headers)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(by_alias=True, exclude_none=True)
            except (ValueError, Exception):
                # If not a tool, try forwarding to gateway
                try:
                    result = await gateway_service.forward_request(db, method, params)
                    if hasattr(result, "model_dump"):
                        result = result.model_dump(by_alias=True, exclude_none=True)
                except Exception:
                    # If all else fails, return invalid method error
                    raise JSONRPCError(-32000, "Invalid method", params)

        return {"jsonrpc": "2.0", "result": result, "id": req_id}

    except JSONRPCError as e:
        error = e.to_dict()
        return {"jsonrpc": "2.0", "error": error["error"], "id": req_id}
    except Exception as e:
        if isinstance(e, ValueError):
            return JSONResponse(content={"message": "Method invalid"}, status_code=422)
        logger.error(f"RPC error: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": "Internal error", "data": str(e)},
            "id": req_id,
        }


@utility_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handle WebSocket connection to relay JSON-RPC requests to the internal RPC endpoint.

    Accepts incoming text messages, parses them as JSON-RPC requests, sends them to /rpc,
    and returns the result to the client over the same WebSocket.

    Args:
        websocket: The WebSocket connection instance.
    """
    try:
        # Authenticate WebSocket connection
        if settings.mcp_client_auth_enabled or settings.auth_required:
            # Extract auth from query params or headers
            token = None
            # Try to get token from query parameter
            if "token" in websocket.query_params:
                token = websocket.query_params["token"]
            # Try to get token from Authorization header
            elif "authorization" in websocket.headers:
                auth_header = websocket.headers["authorization"]
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

            # Check for proxy auth if MCP client auth is disabled
            if not settings.mcp_client_auth_enabled and settings.trust_proxy_auth:
                proxy_user = websocket.headers.get(settings.proxy_user_header)
                if not proxy_user and not token:
                    await websocket.close(code=1008, reason="Authentication required")
                    return
            elif settings.auth_required and not token:
                await websocket.close(code=1008, reason="Authentication required")
                return

            # Verify JWT token if provided and MCP client auth is enabled
            if token and settings.mcp_client_auth_enabled:
                try:
                    await verify_jwt_token(token)
                except Exception:
                    await websocket.close(code=1008, reason="Invalid authentication")
                    return

        await websocket.accept()
        while True:
            try:
                data = await websocket.receive_text()
                client_args = {"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify}
                async with ResilientHttpClient(client_args=client_args) as client:
                    response = await client.post(
                        f"http://localhost:{settings.port}/rpc",
                        json=json.loads(data),
                        headers={"Content-Type": "application/json"},
                    )
                    await websocket.send_text(response.text)
            except JSONRPCError as e:
                await websocket.send_text(json.dumps(e.to_dict()))
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "error": {"code": -32700, "message": "Parse error"},
                            "id": None,
                        }
                    )
                )
            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}")
                await websocket.close(code=1011)
                break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket connection error: {str(e)}")
        try:
            await websocket.close(code=1011)
        except Exception as er:
            logger.error(f"Error while closing WebSocket: {er}")


@utility_router.get("/sse")
async def utility_sse_endpoint(request: Request, user: str = Depends(require_auth)):
    """
    Establish a Server-Sent Events (SSE) connection for real-time updates.

    Args:
        request (Request): The incoming HTTP request.
        user (str): Authenticated username.

    Returns:
        StreamingResponse: A streaming response that keeps the connection
        open and pushes events to the client.

    Raises:
        HTTPException: Returned with **500 Internal Server Error** if the SSE connection cannot be established or an unexpected error occurs while creating the transport.
    """
    try:
        logger.debug("User %s requested SSE connection", user)
        base_url = update_url_protocol(request)

        transport = SSETransport(base_url=base_url)
        await transport.connect()
        await session_registry.add_session(transport.session_id, transport)

        asyncio.create_task(session_registry.respond(None, user, session_id=transport.session_id, base_url=base_url))

        response = await transport.create_sse_response(request)
        tasks = BackgroundTasks()
        tasks.add_task(session_registry.remove_session, transport.session_id)
        response.background = tasks
        logger.info("SSE connection established: %s", transport.session_id)
        return response
    except Exception as e:
        logger.error("SSE connection error: %s", e)
        raise HTTPException(status_code=500, detail="SSE connection failed")


@utility_router.post("/message")
async def utility_message_endpoint(request: Request, user: str = Depends(require_auth)):
    """
    Handle a JSON-RPC message directed to a specific SSE session.

    Args:
        request (Request): Incoming request containing the JSON-RPC payload.
        user (str): Authenticated user.

    Returns:
        JSONResponse: ``{"status": "success"}`` with HTTP 202 on success.

    Raises:
        HTTPException: * **400 Bad Request** - ``session_id`` query parameter is missing or the payload cannot be parsed as JSON.
            * **500 Internal Server Error** - An unexpected error occurs while broadcasting the message.
    """
    try:
        logger.debug("User %s sent a message to SSE session", user)

        session_id = request.query_params.get("session_id")
        if not session_id:
            logger.error("Missing session_id in message request")
            raise HTTPException(status_code=400, detail="Missing session_id")

        message = await request.json()

        await session_registry.broadcast(
            session_id=session_id,
            message=message,
        )

        return JSONResponse(content={"status": "success"}, status_code=202)

    except ValueError as e:
        logger.error("Invalid message format: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Message handling error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to process message")


@utility_router.post("/logging/setLevel")
async def set_log_level(request: Request, user: str = Depends(require_auth)) -> None:
    """
    Update the server's log level at runtime.

    Args:
        request: HTTP request with log level JSON body.
        user: Authenticated user.

    Returns:
        None
    """
    logger.debug(f"User {user} requested to set log level")
    body = await request.json()
    level = LogLevel(body["level"])
    await logging_service.set_level(level)
    return None
