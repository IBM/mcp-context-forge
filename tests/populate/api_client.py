# -*- coding: utf-8 -*-
"""Async HTTP client for REST API population.

Provides connection pooling, authentication, retry with exponential backoff,
and rate-limit handling for high-throughput API population.
"""

# Standard
import asyncio
import logging
from typing import Any, Dict, List, Optional

# Third-Party
import httpx

logger = logging.getLogger(__name__)


class APIClient:
    """Async HTTP client with connection pooling, auth, and retry logic."""

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        max_connections: int = 100,
        max_concurrent: int = 50,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.timeout = timeout

        # Connection pool
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections // 2,
            keepalive_expiry=30,
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            limits=limits,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

        # Semaphore for concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)

        # Statistics
        self.total_requests = 0
        self.total_errors = 0
        self.total_retries = 0
        self.total_rate_limited = 0

        # Token store: email -> JWT token
        self.user_tokens: Dict[str, str] = {}

    def _auth_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        t = token or self.admin_token
        return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}

    async def request(
        self,
        method: str,
        path: str,
        token: Optional[str] = None,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        expected_status: Optional[List[int]] = None,
    ) -> httpx.Response:
        """Make an HTTP request with retry and rate-limit handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: URL path (e.g., /auth/email/register)
            token: Optional JWT token (uses admin_token if None)
            json: JSON body
            params: Query parameters
            expected_status: Expected status codes (default: [200, 201])

        Returns:
            httpx.Response

        Raises:
            httpx.HTTPStatusError: If request fails after all retries
        """
        if expected_status is None:
            expected_status = [200, 201]

        headers = self._auth_headers(token)
        last_exc = None

        for attempt in range(self.max_retries + 1):
            async with self._semaphore:
                try:
                    self.total_requests += 1
                    response = await self._client.request(
                        method,
                        path,
                        headers=headers,
                        json=json,
                        params=params,
                    )

                    if response.status_code in expected_status:
                        return response

                    # Rate limited - backoff and retry
                    if response.status_code == 429:
                        self.total_rate_limited += 1
                        retry_after = float(response.headers.get("Retry-After", self.retry_base_delay * (2**attempt)))
                        logger.debug(f"Rate limited on {path}, waiting {retry_after:.1f}s")
                        await asyncio.sleep(retry_after)
                        continue

                    # Server error - retry with backoff
                    if response.status_code >= 500:
                        self.total_retries += 1
                        delay = self.retry_base_delay * (2**attempt)
                        logger.debug(f"Server error {response.status_code} on {path}, retry in {delay:.1f}s")
                        await asyncio.sleep(delay)
                        continue

                    # Client error - don't retry (except 429 handled above)
                    self.total_errors += 1
                    logger.warning(f"{method} {path} returned {response.status_code}: {response.text[:200]}")
                    return response

                except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
                    last_exc = exc
                    self.total_retries += 1
                    delay = self.retry_base_delay * (2**attempt)
                    logger.debug(f"Connection error on {path}: {exc}, retry in {delay:.1f}s")
                    await asyncio.sleep(delay)

        self.total_errors += 1
        if last_exc:
            raise last_exc
        raise httpx.HTTPStatusError(
            f"Request failed after {self.max_retries} retries",
            request=httpx.Request(method, path),
            response=response,  # type: ignore[possibly-undefined]
        )

    async def post(self, path: str, json: Any = None, token: Optional[str] = None, expected_status: Optional[List[int]] = None) -> httpx.Response:
        return await self.request("POST", path, token=token, json=json, expected_status=expected_status)

    async def get(self, path: str, token: Optional[str] = None, params: Optional[Dict[str, Any]] = None, expected_status: Optional[List[int]] = None) -> httpx.Response:
        return await self.request("GET", path, token=token, params=params, expected_status=expected_status or [200])

    async def delete(self, path: str, token: Optional[str] = None, expected_status: Optional[List[int]] = None) -> httpx.Response:
        return await self.request("DELETE", path, token=token, expected_status=expected_status or [200, 204])

    async def close(self):
        await self._client.aclose()

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "total_retries": self.total_retries,
            "total_rate_limited": self.total_rate_limited,
        }
