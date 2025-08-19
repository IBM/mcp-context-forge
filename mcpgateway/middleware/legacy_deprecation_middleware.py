# Third-Party
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# First-Party
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger("legacy routes")


def is_legacy_path(path: str) -> bool:
    """
    Check if the given path is a legacy (unversioned) API endpoint.
    Legacy paths:
    - Do NOT start with /v1/ or /experimental/
    - Are not static, docs, openapi, admin, health, ready, or root paths

    Args:
        path: The request path to check

    Returns:
        bool: True if path is a legacy API endpoint, False otherwise
    """
    if not path or path == "/":
        return False
    if path.startswith(("/docs", "/openapi", "/redoc", "/static", "/admin", "/health", "/ready", "/version")):
        return False
    if path.startswith(("/v1/", "/experimental/")):
        return False
    # Check for API endpoints that should be versioned
    api_endpoints = ["/tools", "/resources", "/prompts", "/servers", "/gateways", "/roots", "/protocol", "/metrics", "/rpc"]
    return any(path.startswith(endpoint) for endpoint in api_endpoints)


class LegacyDeprecationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if is_legacy_path(path):
            # LOUD warning in logs
            logger.warning(f"DEPRECATED API CALL: {path} " f"-> Suggested migration: /v1{path}")

            # Don't rewrite path since root routes are now directly mounted
            response: Response = await call_next(request)

            # Add deprecation headers
            response.headers.update(
                {
                    "X-API-Deprecated": "true",
                    "X-API-Removal-Version": "0.7.0",
                    "X-API-Migration-Guide": "/docs/migration-urgent",
                    "Warning": '299 - "This API version will be removed in 0.7.0. Migrate immediately."',
                }
            )
            return response

        # Not legacy — pass through
        return await call_next(request)
