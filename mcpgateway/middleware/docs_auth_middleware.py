"""Documentation authentication middleware for MCP Gateway.

Protects FastAPI documentation endpoints (/docs, /redoc, /openapi.json)
with Bearer token or Basic authentication.
"""

# Third-Party
from fastapi import (
    HTTPException,
    Request,
)
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.utils.verify_credentials import require_auth_override


class DocsAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to protect FastAPI documentation routes with authentication.

    Protects /docs, /redoc, and /openapi.json endpoints using Bearer token
    or Basic authentication. Rejects unauthorized requests with 401/403 errors.
    """

    async def dispatch(self, request: Request, call_next):
        """Process request and enforce authentication for documentation routes.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or endpoint handler

        Returns:
            Response from next handler or authentication error
        """
        protected_paths = ["/docs", "/redoc", "/openapi.json"]

        if any(request.url.path.startswith(p) for p in protected_paths):
            try:
                token = request.headers.get("Authorization")
                cookie_token = request.cookies.get("jwt_token")

                # Simulate what Depends(require_auth) would do
                await require_auth_override(token, cookie_token)
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail}, headers=e.headers if e.headers else None)

        # Proceed to next middleware or route
        return await call_next(request)
