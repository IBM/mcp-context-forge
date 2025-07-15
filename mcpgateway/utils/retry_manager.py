# -*- coding: utf-8 -*-
"""MCP Gateway Retry Manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan

This module provides a resilient HTTP client that automatically retries requests
in the event of certain errors or status codes. It supports exponential backoff
with jitter for retrying requests, making it suitable for use in environments where
network reliability is a concern.

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
    """
    A resilient HTTP client that automatically retries requests in the event of
    certain errors or status codes. It supports exponential backoff with jitter
    for retrying requests.

    Attributes:
        max_retries (int): The maximum number of retries before giving up.
        base_backoff (float): The base backoff time in seconds.
        max_delay (float): The maximum delay (in seconds) between retries.
        jitter_max (float): The maximum jitter fraction to apply to delay.
        client_args (dict): Optional arguments to configure the HTTP client.
        client (httpx.AsyncClient): The underlying HTTP client.
    """

    def __init__(
        self,
        max_retries: int = settings.retry_max_attempts,
        base_backoff: float = settings.retry_base_delay,
        max_delay: float = settings.retry_max_delay,
        jitter_max: float = settings.retry_jitter_max,
        client_args: Optional[Dict[str, Any]] = None,
    ):
        """
        Initializes the ResilientHttpClient with configurable retry behavior.

        Args:
            max_retries (int): The maximum number of retries. Default is 3.
            base_backoff (float): The base backoff time (in seconds) before retrying a request. Default is 1.0.
            max_delay (float): The maximum backoff delay in seconds. Default is 60.0.
            jitter_max (float): The maximum jitter fraction (0-1). Default is 0.5.
            client_args (dict, optional): Additional arguments to pass to the httpx client. Default is None.
        """
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_delay = max_delay
        self.jitter_max = jitter_max
        self.client_args = client_args or {}
        self.client = httpx.AsyncClient(**self.client_args)

    async def _sleep_with_jitter(self, base: float, jitter_range: float):
        """
        Sleeps for a period of time with added jitter.

        Args:
            base (float): The base sleep time.
            jitter_range (float): The range within which the jitter will be applied.
        """
        delay = base + random.uniform(0, jitter_range)
        # Ensure delay doesn't exceed the max allowed
        delay = min(delay, self.max_delay)
        await asyncio.sleep(delay)

    def _should_retry(self, exc: Exception, response: Optional[httpx.Response]) -> bool:
        """
        Determines whether a request should be retried based on the error or response.

        Args:
            exc (Exception): The exception raised during the request.
            response (Optional[httpx.Response]): The response object, if any.

        Returns:
            bool: True if the request should be retried, False otherwise.
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
        """
        Makes a resilient HTTP request with automatic retries for retryable errors.

        Args:
            method (str): The HTTP method (GET, POST, PUT, DELETE).
            url (str): The URL to send the request to.
            **kwargs: Additional parameters to pass to the request.

        Returns:
            httpx.Response: The response object from the HTTP request.

        Raises:
            Exception: If the request fails after the maximum number of retries.
            last_exc: The last exception encountered during the retries, raised if the request
                    ultimately fails after all retry attempts.
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
        """
        Makes a resilient GET request.

        Args:
            url (str): The URL to send the GET request to.
            **kwargs: Additional parameters to pass to the request.

        Returns:
            httpx.Response: The response object from the GET request.
        """
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        """
        Makes a resilient POST request.

        Args:
            url (str): The URL to send the POST request to.
            **kwargs: Additional parameters to pass to the request.

        Returns:
            httpx.Response: The response object from the POST request.
        """
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        """
        Makes a resilient PUT request.

        Args:
            url (str): The URL to send the PUT request to.
            **kwargs: Additional parameters to pass to the request.

        Returns:
            httpx.Response: The response object from the PUT request.
        """
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        """
        Makes a resilient DELETE request.

        Args:
            url (str): The URL to send the DELETE request to.
            **kwargs: Additional parameters to pass to the request.

        Returns:
            httpx.Response: The response object from the DELETE request.
        """
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self):
        """
        Closes the underlying HTTP client gracefully.
        """
        await self.client.aclose()

    async def __aenter__(self):
        """
        Asynchronous context manager entry point.

        Returns:
            ResilientHttpClient: The client instance.
        """
        return self

    async def __aexit__(self, *args):
        """
        Asynchronous context manager exit point.

        Closes the HTTP client after use.

        Args:
            *args: Variable length argument list passed by the context manager.
                Typically contains exception information (if any) or other context.
        """
        await self.aclose()
