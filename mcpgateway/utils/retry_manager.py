# -*- coding: utf-8 -*-
"""MCP Gateway Resilient HTTP Client with Retry Logic.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

This module provides a resilient HTTP client that automatically retries requests
in the event of certain errors or status codes. It implements exponential backoff
with jitter for retrying requests, making it suitable for use in environments where
network reliability is a concern or when dealing with rate-limited APIs.

Key Features:
- Automatic retry logic for transient failures
- Exponential backoff with configurable jitter
- Support for HTTP 429 Retry-After headers
- Configurable retry policies and delay parameters
- Async context manager support for resource cleanup
- Standard HTTP methods (GET, POST, PUT, DELETE)
- Comprehensive error classification

The client distinguishes between retryable and non-retryable errors:

Retryable Status Codes:
- 429 (Too Many Requests) - with Retry-After header support
- 503 (Service Unavailable)
- 502 (Bad Gateway)
- 504 (Gateway Timeout)
- 408 (Request Timeout)

Non-Retryable Status Codes:
- 400 (Bad Request)
- 401 (Unauthorized)
- 403 (Forbidden)
- 404 (Not Found)
- 405 (Method Not Allowed)
- 406 (Not Acceptable)

Retryable Network Errors:
- Connection timeouts
- Read timeouts
- Network errors

Dependencies:
- Standard Library: asyncio, logging, random
- Third-party: httpx
- First-party: mcpgateway.config.settings

Example Usage:
    Basic usage with default settings:

        async with ResilientHttpClient() as client:
            response = await client.get("https://api.example.com/data")

    Custom configuration:

        client = ResilientHttpClient(
            max_retries=5,
            base_backoff=2.0,
            max_delay=120.0
        )
        response = await client.post("https://api.example.com/submit", json=data)
        await client.aclose()
"""

# Standard
import asyncio
import logging
import random
from typing import Any, Dict, Optional

# Third-Party
import httpx

# First-Party
from mcpgateway.config import settings

# Configure logger
logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {
    429,  # Too Many Requests
    503,  # Service Unavailable
    502,  # Bad Gateway
    504,  # Gateway Timeout
    408,  # Request Timeout
}

NON_RETRYABLE_STATUS_CODES = {
    400,  # Bad Request
    401,  # Unauthorized
    403,  # Forbidden
    404,  # Not Found
    405,  # Method Not Allowed
    406,  # Not Acceptable
}


class ResilientHttpClient:
    """A resilient HTTP client with automatic retry capabilities.

    This client automatically retries requests in the event of certain errors
    or status codes using exponential backoff with jitter. It's designed to
    handle transient network issues and rate limiting gracefully.

    The retry logic implements:
    - Exponential backoff: delay = base_backoff * (2 ** attempt)
    - Jitter: random additional delay to prevent thundering herd
    - Respect for HTTP 429 Retry-After headers
    - Maximum delay caps to prevent excessive waiting

    Attributes:
        max_retries: Maximum number of retry attempts
        base_backoff: Base delay in seconds before first retry
        max_delay: Maximum delay between retries in seconds
        jitter_max: Maximum jitter fraction (0-1) to add randomness
        client_args: Additional arguments for httpx.AsyncClient
        client: The underlying httpx.AsyncClient instance

    Examples:
        >>> # Test initialization with default values
        >>> client = ResilientHttpClient()
        >>> client.max_retries > 0
        True
        >>> client.base_backoff > 0
        True
        >>> client.max_delay > 0
        True
        >>> isinstance(client.client, httpx.AsyncClient)
        True

        >>> # Test initialization with custom values
        >>> client = ResilientHttpClient(max_retries=5, base_backoff=2.0)
        >>> client.max_retries
        5
        >>> client.base_backoff
        2.0

        >>> # Test client_args parameter
        >>> args = {"timeout": 30.0}
        >>> client = ResilientHttpClient(client_args=args)
        >>> client.client_args
        {'timeout': 30.0}
    """

    def __init__(
        self,
        max_retries: int = settings.retry_max_attempts,
        base_backoff: float = settings.retry_base_delay,
        max_delay: float = settings.retry_max_delay,
        jitter_max: float = settings.retry_jitter_max,
        client_args: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the ResilientHttpClient with configurable retry behavior.

        Args:
            max_retries: Maximum number of retry attempts before giving up
            base_backoff: Base delay in seconds before retrying a request
            max_delay: Maximum backoff delay in seconds
            jitter_max: Maximum jitter fraction (0-1) to add randomness
            client_args: Additional arguments to pass to httpx.AsyncClient

        Examples:
            >>> # Test default initialization
            >>> client = ResilientHttpClient()
            >>> client.max_retries >= 0
            True
            >>> client.base_backoff >= 0
            True

            >>> # Test parameter assignment
            >>> client = ResilientHttpClient(max_retries=10, base_backoff=5.0)
            >>> client.max_retries
            10
            >>> client.base_backoff
            5.0

            >>> # Test client_args handling
            >>> client = ResilientHttpClient(client_args=None)
            >>> client.client_args
            {}
        """
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_delay = max_delay
        self.jitter_max = jitter_max
        self.client_args = client_args or {}
        self.client = httpx.AsyncClient(**self.client_args)

    async def _sleep_with_jitter(self, base: float, jitter_range: float):
        """Sleep for a period with added jitter to prevent thundering herd.

        Implements jittered exponential backoff by adding random delay to
        the base sleep time. The total delay is capped at max_delay.

        Args:
            base: Base sleep time in seconds
            jitter_range: Maximum additional random delay in seconds

        Examples:
            >>> import asyncio
            >>> client = ResilientHttpClient()
            >>> # Test that method exists and is callable
            >>> callable(client._sleep_with_jitter)
            True

            >>> # Test delay calculation logic (without actual sleep)
            >>> base_time = 2.0
            >>> jitter = 1.0
            >>> # Simulate the delay calculation
            >>> import random
            >>> delay = base_time + random.uniform(0, jitter)
            >>> delay >= base_time
            True
            >>> delay <= base_time + jitter
            True
        """
        # random.uniform() is safe here as jitter is only used for retry timing, not security
        delay = base + random.uniform(0, jitter_range)  # noqa: DUO102 # nosec B311
        # Ensure delay doesn't exceed the max allowed
        delay = min(delay, self.max_delay)
        await asyncio.sleep(delay)

    def _should_retry(self, exc: Exception, response: Optional[httpx.Response]) -> bool:
        """Determine whether a request should be retried.

        Evaluates the exception and response to decide if the request should
        be retried based on error type and HTTP status code.

        Args:
            exc: Exception raised during the request
            response: HTTP response object if available

        Returns:
            True if the request should be retried, False otherwise

        Examples:
            >>> client = ResilientHttpClient()
            >>> # Test network errors (should retry)
            >>> client._should_retry(httpx.ConnectTimeout("Connection timeout"), None)
            True
            >>> client._should_retry(httpx.ReadTimeout("Read timeout"), None)
            True
            >>> client._should_retry(httpx.NetworkError("Network error"), None)
            True

            >>> # Test non-retryable status codes
            >>> from unittest.mock import Mock
            >>> response_400 = Mock()
            >>> response_400.status_code = 400
            >>> client._should_retry(Exception(), response_400)
            False

            >>> response_401 = Mock()
            >>> response_401.status_code = 401
            >>> client._should_retry(Exception(), response_401)
            False

            >>> # Test retryable status codes
            >>> response_429 = Mock()
            >>> response_429.status_code = 429
            >>> client._should_retry(Exception(), response_429)
            True

            >>> response_503 = Mock()
            >>> response_503.status_code = 503
            >>> client._should_retry(Exception(), response_503)
            True

            >>> # Test unknown status codes (should not retry)
            >>> response_418 = Mock()
            >>> response_418.status_code = 418
            >>> client._should_retry(Exception(), response_418)
            False
        """
        if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError)):
            return True
        if response:
            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                logger.info(f"Response {response.status_code}: Not retrying.")
                return False
            if response.status_code in RETRYABLE_STATUS_CODES:
                logger.info(f"Response {response.status_code}: Retrying.")
                return True
        return False

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make a resilient HTTP request with automatic retries.

        Performs an HTTP request with automatic retry logic for transient
        failures. Implements exponential backoff with jitter and respects
        HTTP 429 Retry-After headers.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            url: Target URL for the request
            **kwargs: Additional parameters to pass to httpx.request

        Returns:
            HTTP response object from the successful request

        Raises:
            httpx.HTTPError: For non-retryable HTTP errors or when max retries exceeded
            last_exc: The last exception encountered during the retries, raised if the request
                    ultimately fails after all retry attempts.
            Exception: The last exception encountered if all retries fail

        Note:
            This method requires actual HTTP connectivity for complete testing.
            Doctests focus on validating method existence and basic parameter
            handling without making actual network requests.

        Examples:
            >>> client = ResilientHttpClient()
            >>> # Test method exists and is callable
            >>> callable(client.request)
            True

            >>> # Test parameter validation
            >>> import asyncio
            >>> # Method should accept string parameters
            >>> method = "GET"
            >>> url = "https://example.com"
            >>> isinstance(method, str) and isinstance(url, str)
            True
        """
        attempt = 0
        last_exc = None
        response = None

        while attempt < self.max_retries:
            try:
                logger.debug(f"Attempt {attempt + 1} to {method} {url}")
                response = await self.client.request(method, url, **kwargs)

                if response.status_code in NON_RETRYABLE_STATUS_CODES or response.is_success:
                    return response

                # Handle 429 - Retry-After header
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        retry_after_sec = float(retry_after)
                        logger.info(f"Rate-limited. Retrying after {retry_after_sec}s.")
                        await asyncio.sleep(retry_after_sec)
                        attempt += 1
                        continue

                if not self._should_retry(Exception(), response):
                    return response

            except Exception as exc:
                if not self._should_retry(exc, None):
                    raise
                last_exc = exc
                logger.warning(f"Retrying due to error: {exc}")

            # Backoff calculation
            delay = self.base_backoff * (2**attempt)
            jitter = delay * self.jitter_max
            await self._sleep_with_jitter(delay, jitter)
            attempt += 1
            logger.debug(f"Retry scheduled after delay of {delay:.2f} seconds.")

        if last_exc:
            raise last_exc

        logger.error(f"Max retries reached for {url}")
        return response

    async def get(self, url: str, **kwargs):
        """Make a resilient GET request.

        Args:
            url: URL to send the GET request to
            **kwargs: Additional parameters to pass to the request

        Returns:
            HTTP response object from the GET request

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.get)
            True
            >>> # Verify it's an async method
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.get)
            True
        """
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        """Make a resilient POST request.

        Args:
            url: URL to send the POST request to
            **kwargs: Additional parameters to pass to the request

        Returns:
            HTTP response object from the POST request

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.post)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.post)
            True
        """
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        """Make a resilient PUT request.

        Args:
            url: URL to send the PUT request to
            **kwargs: Additional parameters to pass to the request

        Returns:
            HTTP response object from the PUT request

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.put)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.put)
            True
        """
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        """Make a resilient DELETE request.

        Args:
            url: URL to send the DELETE request to
            **kwargs: Additional parameters to pass to the request

        Returns:
            HTTP response object from the DELETE request

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.delete)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.delete)
            True
        """
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self):
        """Close the underlying HTTP client gracefully.

        Ensures proper cleanup of the httpx.AsyncClient and its resources.

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.aclose)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.aclose)
            True
        """
        await self.client.aclose()

    async def __aenter__(self):
        """Asynchronous context manager entry point.

        Returns:
            The client instance for use in async with statements

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.__aenter__)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.__aenter__)
            True
        """
        return self

    async def __aexit__(self, *args):
        """Asynchronous context manager exit point.

        Ensures the HTTP client is properly closed after use, even if
        exceptions occur during the context manager block.

        Args:
            *args: Exception information passed by the context manager
                  (exc_type, exc_value, traceback) or None values if no exception

        Examples:
            >>> client = ResilientHttpClient()
            >>> callable(client.__aexit__)
            True
            >>> import inspect
            >>> inspect.iscoroutinefunction(client.__aexit__)
            True
        """
        await self.aclose()
