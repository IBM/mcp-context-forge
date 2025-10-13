import json
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

SENSITIVE_KEYS = {"password", "secret", "token", "apikey", "access_token", "refresh_token", "client_secret", "authorization", "jwt_token"}

def mask_sensitive_data(data):
    """Recursively mask sensitive keys in dict/list payloads."""
    if isinstance(data, dict):
        return {k: ("******" if k.lower() in SENSITIVE_KEYS else mask_sensitive_data(v)) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_sensitive_data(i) for i in data]
    return data

def mask_jwt_in_cookies(cookie_header):
    """Mask JWT tokens in cookie header while preserving other cookies."""
    if not cookie_header:
        return cookie_header
    
    # Split cookies by semicolon
    cookies = []
    for cookie in cookie_header.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            name, value = cookie.split('=', 1)
            name = name.strip()
            # Mask JWT tokens and other sensitive cookies
            if any(sensitive in name.lower() for sensitive in ['jwt', 'token', 'auth', 'session']):
                cookies.append(f"{name}=******")
            else:
                cookies.append(cookie)
        else:
            cookies.append(cookie)
    
    return '; '.join(cookies)

def mask_sensitive_headers(headers):
    """Mask sensitive headers like Authorization."""
    masked_headers = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if (key_lower in SENSITIVE_KEYS or 
            "auth" in key_lower or 
            "jwt" in key_lower):
            masked_headers[key] = "******"
        elif key_lower == "cookie":
            # Special handling for cookies to mask only JWT tokens
            masked_headers[key] = mask_jwt_in_cookies(value)
        else:
            masked_headers[key] = value
    return masked_headers


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, log_requests: bool = True, log_level: str = "DEBUG", max_body_size: int = 4096):
        super().__init__(app)
        self.log_requests = log_requests
        self.log_level = log_level.upper()
        self.max_body_size = max_body_size  # Expected to be in bytes

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip logging if disabled
        if not self.log_requests:
            return await call_next(request)

        # Always log at INFO level for request payloads to ensure visibility
        log_level = logging.INFO
        
        # Skip if logger level is higher than INFO
        if not logger.isEnabledFor(log_level):
            return await call_next(request)

        body = b""
        try:
            body = await request.body()
            # Avoid logging huge bodies
            if len(body) > self.max_body_size:
                truncated = True
                body_to_log = body[:self.max_body_size]
            else:
                truncated = False
                body_to_log = body

            payload = body_to_log.decode("utf-8", errors="ignore").strip()
            if payload:
                try:
                    json_payload = json.loads(payload)
                    payload_to_log = mask_sensitive_data(json_payload)
                    payload_str = json.dumps(payload_to_log, indent=2)
                except json.JSONDecodeError:
                    # For non-JSON payloads, still mask potential sensitive data
                    payload_str = payload
                    for sensitive_key in SENSITIVE_KEYS:
                        if sensitive_key in payload_str.lower():
                            payload_str = "<contains sensitive data - masked>"
                            break
            else:
                payload_str = "<empty>"

            # Mask sensitive headers
            masked_headers = mask_sensitive_headers(dict(request.headers))

            logger.log(
                log_level,
                f"📩 Incoming request: {request.method} {request.url.path}\n"
                f"Query params: {dict(request.query_params)}\n"
                f"Headers: {masked_headers}\n"
                f"Body: {payload_str}{'... [truncated]' if truncated else ''}"
            )

        except Exception as e:
            logger.warning(f"Failed to log request body: {e}")

        # Recreate request stream for downstream handlers
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        
        # Create new request with the body we've already read
        new_scope = request.scope.copy()
        new_request = Request(new_scope, receive=receive)

        response: Response = await call_next(new_request)
        return response
