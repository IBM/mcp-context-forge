# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/middleware/tbac_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

TBAC middleware for MCP ``tools/call`` authorization checks.
"""

# Standard
from typing import Any, Dict, Optional, Union

# Third-Party
from fastapi import HTTPException, Request
import orjson
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# First-Party
from mcpgateway.schemas_tbac import TBACClaims
from mcpgateway.services.tbac_policy_engine import TBACPolicyEngine, TBACPolicyError
from mcpgateway.utils.orjson_response import ORJSONResponse
from mcpgateway.utils.verify_credentials import get_auth_bearer_token_from_request, verify_jwt_token_cached


class TBACMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces task-based access control for tools/call."""

    def __init__(self, app):
        super().__init__(app)
        self._engine = TBACPolicyEngine()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method.upper() != "POST":
            return await call_next(request)

        path = request.url.path or ""
        if not self._is_mcp_path(path):
            return await call_next(request)

        body, parse_error = await self._load_json_body(request)
        if parse_error is not None:
            return self._jsonrpc_error_response(code=-32700, message="Parse error", request_id=None, status_code=400)

        if body is None:
            return await call_next(request)

        if not isinstance(body, dict):
            return self._jsonrpc_error_response(code=-32600, message="Invalid JSON-RPC request payload", request_id=None, status_code=400)

        method = body.get("method")
        if method != "tools/call":
            return await call_next(request)

        req_id = self._safe_request_id(body.get("id"))
        if body.get("jsonrpc") != "2.0":
            return self._jsonrpc_error_response(code=-32600, message="Invalid JSON-RPC version", request_id=req_id, status_code=400)

        params = body.get("params")
        if not isinstance(params, dict):
            return self._jsonrpc_error_response(code=-32600, message="Invalid JSON-RPC params", request_id=req_id, status_code=400)

        token = getattr(request.state, "bearer_token", None) or get_auth_bearer_token_from_request(request)
        if not token:
            return self._jsonrpc_error_response(
                code=-32003,
                message="TBAC authorization failed: missing bearer token",
                request_id=req_id,
                status_code=403,
            )

        try:
            payload = await verify_jwt_token_cached(token, request)
        except HTTPException as exc:
            return self._jsonrpc_error_response(
                code=-32003,
                message=f"TBAC authorization failed: {exc.detail}",
                request_id=req_id,
                status_code=403,
            )

        claims = TBACClaims.model_validate(payload)
        try:
            self._engine.evaluate(claims, body)
        except TBACPolicyError as exc:
            return self._jsonrpc_error_response(
                code=-32003,
                message=exc.message,
                request_id=req_id,
                status_code=403,
                data=exc.data,
            )

        # Preserve original end-user identity for downstream transport handlers.
        request.state.tbac_user_identity = payload.get("sub") or payload.get("email") or payload.get("username")
        request.state.tbac_claims = claims.model_dump(mode="python", exclude_none=True)
        return await call_next(request)

    @staticmethod
    def _is_mcp_path(path: str) -> bool:
        return path.startswith("/mcp") or path.startswith("/_internal/mcp") or path.endswith("/mcp")

    @staticmethod
    async def _load_json_body(request: Request) -> tuple[Optional[Any], Optional[Exception]]:
        raw = await request.body()
        if not raw:
            return None, None
        try:
            parsed = orjson.loads(raw)
            return parsed, None
        except orjson.JSONDecodeError as exc:
            return None, exc

    @staticmethod
    def _safe_request_id(req_id: Any) -> Optional[Union[int, str]]:
        if isinstance(req_id, bool):
            return None
        if isinstance(req_id, (str, int)):
            return req_id
        return None

    @staticmethod
    def _jsonrpc_error_response(*, code: int, message: str, request_id: Optional[Union[int, str]], status_code: int, data: Optional[Dict[str, Any]] = None) -> ORJSONResponse:
        error: Dict[str, Any] = {"code": code, "message": message}
        if data:
            error["data"] = data
        return ORJSONResponse(status_code=status_code, content={"jsonrpc": "2.0", "error": error, "id": request_id})
