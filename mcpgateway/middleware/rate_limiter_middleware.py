# -*- coding: utf-8 -*-
"""Ratelimiting middleware implementation.
Location: ./mcpgateway/middleware/rate_limiter_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhavan Kidambi

The rate limiter middle ware module.
"""

from typing import Any, Awaitable, Callable, Optional, Tuple
import time

# Fast API and starlette dependencies
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import base64
import json

# Limit 
from limits import WindowStats, parse
from limits.aio.strategies import MovingWindowRateLimiter as AsyncMovingWindowRateLimiter
from limits.aio.strategies import FixedWindowRateLimiter as AsyncFixedWindowRateLimiter
from limits.aio.storage import MemoryStorage as AsyncMemoryStorage
from limits.aio.storage import RedisStorage as AsyncRedisStorage
from limits import RateLimitItem

# First party
from mcpgateway.config import  settings
from mcpgateway.services.logging_service import LoggingService

# Import metrics functionality
from mcpgateway.middleware.protection_metrics import ProtectionMetricsService


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting requests using the limits library.
    
    This middleware implements rate limiting with different strategies and limits
    based on the request type and configuration settings.
    """
    
    def __init__(self, app:ASGIApp, metric_service:ProtectionMetricsService):
        """Initialize the rate limiter middleware."""
        super().__init__(app)
        self.metric_service = metric_service
        # Skip initialization if protection suite or rate limiting is not enabled
        if not settings.experimental_protection_suite or not settings.rate_limiting_enabled:
            self.limiter = None
            return
            
        # Initialize storage based on configuration
        if settings.rate_limit_storage_type == "redis":
            self.storage = AsyncRedisStorage(str(settings.redis_url))
        else:
            self.storage = AsyncMemoryStorage()
            
        # Initialize rate limiting strategy
        if settings.rate_limiting_stratergy == "moving-window":
            self.limiter = AsyncMovingWindowRateLimiter(self.storage)
        else:
            self.limiter = AsyncFixedWindowRateLimiter(self.storage)
            
        # Parse rate limits
        self.limits = {
            "default": parse(settings.rate_limit_default),
            "anonymous": parse(settings.rate_limit_anonymous),
            "admin": parse(settings.rate_limit_admin_api),
            "tool": parse(settings.rate_limit_tool_execution),
            "default" : parse(settings.rate_limit_default)
        }

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Process the request and apply rate limiting if enabled.
        
        Args:
            request: The incoming request
            call_next: The next middleware or route handler
            
        Returns:
            The response, potentially with rate limit headers or a 429 status code
        """
        # Skip rate limiting if not enabled and if the request is whitelisted
        if (not settings.experimental_protection_suite or not settings.rate_limiting_enabled \
            or self.limiter is None \
            or self._is_request_whitelisted(request) \
            or self._is_admin_bypass_request(request)):
             return await call_next(request)
            
        # Determine the appropriate rate limit based on the request
        limit_key,limit = self._get_limit_for_request(request)
        logger.debug(f"Checking limit:{limit}")
        # Generate a unique identifier for the client
        identifier = self._get_client_identifier(request)
        logger.debug(f"Identifier:{identifier}")

        # Track if we need to add a warning header
        warning_triggered = False
        warning_limit = None
        warning_remaining = 0
        # Use the configured warning threshold or the default if not set
        warning_threshold = 0.75
        window_stats = None
        remaining = None
        try :
            window_stats = await self.limiter.get_window_stats(limit, identifier)
            current_usage = window_stats[0] if window_stats else 0
            remaining = limit.amount - current_usage if window_stats else limit.amount
                    
            # Check if we're approaching the limit
            if remaining > 0 and remaining <= (limit.amount* (1 - warning_threshold)):
                warning_triggered = True
                warning_limit = limit
                warning_remaining = remaining
        except Exception:
           pass

        reset_time = await self._get_reset_time(identifier, limit)
        logger.info(f"Hitting rate limit with limit_group type: {type(limit)}, identifier: {identifier}")
        is_allowed = await self.limiter.hit(limit, identifier)
        if not is_allowed:
                # Request exceeds rate limit
            response = JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded for {request.url.path}. Please try again later."}
            )
            await self.send_alert(limit_key,request,True,identifier,limit,reset_time,window_stats)
           # Add rate limit headers if enabled
            if settings.rate_limiting_headers_enabled:
                remaining = window_stats[1] if window_stats else 0
                response.headers["X-RateLimit-Limit"] = str(limit.amount)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(reset_time)            
            return response
       # If we've reached here, all rate limits passed 
        
        # Process the request
        response = await call_next(request)
        
        # Add rate limit headers if enabled
        try:
            if settings.rate_limiting_headers_enabled and limit:
                remaining = window_stats[1] if window_stats else 0
                response.headers["X-RateLimit-Limit"] = str(limit.amount)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(reset_time)

                # Add warning header if we're approaching the limit
                if warning_triggered and warning_limit:
                    threshold_percent = int(warning_threshold * 100)
                    await self.send_alert(limit_key,request,False,identifier,limit,reset_time,window_stats)
                    response.headers["X-RateLimit-Warning"] = f"You have used {threshold_percent}% of your rate limit. {warning_remaining} requests remaining."
        except Exception:
            pass   
        return response
    
    async def send_alert(self,limit_key:str,request:Request,isBlocked:bool,identifier:str,limit:RateLimitItem,reset_time:int,window_stats:Optional[WindowStats]):
        # Record request metrics
        if settings.protection_metrics_enabled:
            try:
                await self.metric_service.record_protection_metric(
                    client_id=identifier,
                    client_ip=request.client.host if request.client else None,
                    path=request.url.path,
                    method=request.method,
                    rate_limit_key=limit_key,
                    metric_type="rate_limit",
                    current_usage= window_stats[0] if window_stats else 0,
                    limit=limit.amount,
                    remaining=window_stats[1] if window_stats else 0,
                    reset_time=reset_time,
                    is_blocked=isBlocked,
                )
            except Exception as e:
                # If there's an error recording metrics, log it but continue
                logger.error(f"Error recording protection metric: {e}")

        
    def _get_limit_for_request(self, request: Request) -> Tuple[str,RateLimitItem]:
        """
        Determine which rate limit to apply based on the request.
        
        Args:
            request: The incoming request
            
        Returns:
            A tuple of (limit_key, limits) where limit_key is a string identifier
            and limits is a list of Limit objects
        """
        path = request.url.path
        
        # Check for admin API paths
        if path.startswith("/admin/") or path.startswith("/static/"):
            return "admin",self.limits["admin"]
            
        # Check for anonymous requests (no Authorization header).
        # TODO we are checking only for absence of the header here. Validate the correctness of the header.
        header_name_to_check = "authorization"
        if header_name_to_check.casefold() not in (key.casefold() for key in request.headers):
         return "anonymous",self.limits["anonymous"]

        if path.startswith("/tools/"):
        # Tool execution path
            return "tools",self.limits["tool"]
        
        return path,self.limits["default"]
        
    def _get_client_identifier(self, request: Request) -> str:
        """
        Generate a unique identifier for the client.
        
        Args:
            request: The incoming request
            
        Returns:
            A string identifier for the client
        """
        
        # Check if settings.rate_limit_client_identification_header is defined and not empty
        if settings.rate_limit_client_identification_header:
            # Look for the specified header in the request (case-insensitive)
            for header_name, header_value in request.headers.items():
                if header_name.lower() == settings.rate_limit_client_identification_header.lower() and header_value:
                    return header_value
        
        # If settings.rate_limit_client_identification_header is not defined or the header is not present,
        # try to extract the claim from JWT token if rate_limit_client_jwt_claims is defined
        if settings.rate_limit_client_jwt_claims and ("authorization" in request.headers or "Authorization" in request.headers):
            auth_header = request.headers["authorization"]
            if not auth_header:
                auth_header = request.headers["Authorization"]
            jwt_claim = self._extract_jwt_claim(auth_header, settings.rate_limit_client_jwt_claims)
            if jwt_claim:
                return str(jwt_claim)
        
        # Fallback - IP address + Authorization header if present.
        identifier = request.client.host if request.client else "unknown"
         
        # If there's an Authorization header, use it to make the identifier more specific (case-insensitive)
        auth_header = None
        for header_name, header_value in request.headers.items():
            if header_name.lower() == "authorization":
                auth_header = header_value
                break
                
        if auth_header:
            # Use only a hash or part of the token to avoid storing sensitive information
            # Simple hash function to avoid storing the actual token
            auth_hash = str(hash(auth_header) % 10000)
            identifier = f"{identifier}:{auth_hash}"
            
        return identifier
        
    async def _get_reset_time(self, identifier: str, limit: RateLimitItem) -> int:
        """
        Calculate when the rate limit will reset.
        
        Args:
            identifier: The client identifier
            limit: The limit object
            
        Returns:
            The Unix timestamp when the rate limit will reset
        """
        # Get the current time
        current_time = int(time.time())
        
        # For fixed window, the reset time is the end of the current window
        if settings.rate_limiting_stratergy == "fixed-window":
            # Calculate the end of the current window
            window_size = limit.get_expiry()
            reset_time = current_time + window_size - (current_time % window_size)
            return reset_time
            
        # For moving window, it's more complex as it depends on the current usage
        # For simplicity, we'll return the time when the oldest hit will expire
        try:
            window_stats = await self.limiter.get_window_stats(limit, identifier) if self.limiter else None
            if window_stats and window_stats[0]:  # If there are any hits
                return current_time + limit.get_expiry()
        except Exception:
            # If there's an error getting window stats, just return current time
            pass
            
        return current_time
    
    def _is_request_whitelisted(self, request: Request) -> bool:
        """
        Check if the request is whitelisted based on IP, user agent, or API key.
        Args:
        
        request: The incoming request
                
        Returns:
            True if the request is whitelisted, False otherwise
        """
        return (
                self._is_ip_whitelisted(request) or
                self._is_user_agent_whitelisted(request) or
                self._is_api_key_whitelisted(request)
        )
            
    def _is_ip_whitelisted(self, request: Request) -> bool:
            """
            Check if the client IP is in the whitelist.
            
            Args:
                request: The incoming request
                
            Returns:
                True if the IP is whitelisted, False otherwise
            """
            # Get the client IP
            client_ip = request.client.host if request.client else None
            
            # If we couldn't determine the IP or there's no whitelist, return False
            if not client_ip or not settings.rate_limit_whitelist_ips:
                return False
                
            # Parse the comma-separated whitelist
            whitelist_ips = [ip.strip() for ip in settings.rate_limit_whitelist_ips.split(",") if ip.strip()]
            
            # Check if the IP is in the whitelist
            return client_ip in whitelist_ips
            
    def _is_user_agent_whitelisted(self, request: Request) -> bool:
            """
            Check if the user agent is in the whitelist.
            
            Args:
                request: The incoming request
                
            Returns:
                True if the user agent is whitelisted, False otherwise
            """
            # Get the user agent (case-insensitive)
            # HTTP headers are case-insensitive according to the HTTP specification
            user_agent = None
            for header_name, header_value in request.headers.items():
                if header_name.lower() == "user-agent":
                    user_agent = header_value
                    break
            
            # If there's no user agent or no whitelist, return False
            if not user_agent or not settings.rate_limit_whitelist_user_agents:
                return False
                
            # Parse the comma-separated whitelist
            whitelist_agents = [agent.strip() for agent in settings.rate_limit_whitelist_user_agents.split(",") if agent.strip()]
            
            # Check if any whitelisted agent is in the user agent string
            return any(agent in user_agent for agent in whitelist_agents)
            
    def _is_api_key_whitelisted(self, request: Request) -> bool:
            """
            Check if the API key is in the whitelist.
            
            Args:
                request: The incoming request
                
            Returns:
                True if the API key is whitelisted, False otherwise
            """
            # Get the API key from the Authorization header (case-insensitive)
            # HTTP headers are case-insensitive according to the HTTP specification
            auth_header = None
            for header_name, header_value in request.headers.items():
                if header_name.lower() == "authorization":
                    auth_header = header_value
                    break
            
            # If there's no Authorization header or no whitelist, return False
            if not auth_header or not settings.rate_limit_whitelist_api_keys:
                return False
                
            # Extract the API key from the Authorization header
            # Assuming format: "Bearer <api_key>" or "ApiKey <api_key>"
            parts = auth_header.split()
            if len(parts) != 2:
                return False
                
            api_key = parts[1]
            
            # Parse the comma-separated whitelist
            whitelist_keys = [key.strip() for key in settings.rate_limit_whitelist_api_keys.split(",") if key.strip()]
            
            # Check if the API key is in the whitelist
            return api_key in whitelist_keys
    
    def _is_admin_bypass_request(self, request: Request) -> bool:
            """
            Check if the request is for an admin endpoint and has the bypass header with correct secret.
            
            Args:
                request: The incoming request
                
            Returns:
                True if the request should bypass rate limiting, False otherwise
            """
            # Only apply to admin endpoints
            if not request.url.path.startswith("/admin/"):
                return False
                
            # Check for bypass header (case-insensitive)
            bypass_header_value = None
            for header_name, header_value in request.headers.items():
                if header_name.lower() == settings.rate_limit_admin_bypass_header.lower():
                    bypass_header_value = header_value
                    break
                    
            # If bypass header is present and secret is configured
            if bypass_header_value and settings.rate_limit_admin_bypass_secret:
                # Check if the header value matches the secret
                return bypass_header_value == settings.rate_limit_admin_bypass_secret
                
            return False

    def _extract_jwt_claim(self, auth_header: str, claim_name: str) -> Optional[Any]:
        """
        Extract a claim from a JWT token in the Authorization header.
        
        Args:
            auth_header: The Authorization header value
            claim_name: The name of the claim to extract
            
        Returns:
            The claim value if found, None otherwise
        """
        try:
            # JWT tokens are typically in the format "Bearer <token>"
            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return None
                
            token = parts[1]
            
            # JWT tokens consist of three parts: header.payload.signature
            # We only need the payload part
            token_parts = token.split(".")
            if len(token_parts) != 3:
                return None
                
            # Decode the payload (middle part)
            # Add padding if needed
            payload = token_parts[1]
            padding = "=" * ((4 - len(payload) % 4) % 4)
            payload += padding
            
            # Decode base64 and parse JSON
            decoded_payload = base64.b64decode(payload.replace("-", "+").replace("_", "/"))
            claims = json.loads(decoded_payload)
            
            # Extract the specified claim
            if claim_name in claims:
                return claims[claim_name]
                
        except Exception as e:
            logger.error(f"Error extracting JWT claim: {e}")
            
        return None

 
