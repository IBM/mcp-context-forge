# -*- coding: utf-8 -*-
"""URL authentication helpers for query parameter auth.

Provides utilities for appending decrypted auth query parameters to URLs
and sanitizing URLs for safe logging (redacting sensitive query params).

Security Note:
    Query parameter authentication is inherently insecure (CWE-598: Use of GET
    Request Method With Sensitive Query Strings). API keys in URLs may appear
    in proxy logs, browser history, and server access logs. Use only when the
    upstream server (e.g., Tavily MCP) requires this authentication method.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import re
from typing import Dict, FrozenSet, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Static set of commonly sensitive query parameter names
# Used as a fallback when gateway-specific params aren't available
STATIC_SENSITIVE_PARAMS: FrozenSet[str] = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "key",
        "token",
        "access_token",
        "auth",
        "auth_token",
        "secret",
        "password",
        "pwd",
        "credential",
        "credentials",
        "tavilyapikey",  # Tavily-specific
        "tavilyApiKey",  # Tavily-specific (camelCase)
    }
)


def apply_query_param_auth(
    url: str,
    auth_query_params: Optional[Dict[str, str]],
) -> str:
    """Append decrypted auth query parameters to a URL.

    Args:
        url: The base URL to append parameters to.
        auth_query_params: Dict of {param_name: decrypted_value}.
            If None or empty, returns the original URL unchanged.

    Returns:
        URL with auth query parameters appended.

    Example:
        >>> apply_query_param_auth(
        ...     "https://api.tavily.com/mcp",
        ...     {"tavilyApiKey": "secret123"}
        ... )
        'https://api.tavily.com/mcp?tavilyApiKey=secret123'

        >>> apply_query_param_auth(
        ...     "https://api.example.com/search?q=test",
        ...     {"api_key": "abc123"}
        ... )
        'https://api.example.com/search?q=test&api_key=abc123'
    """
    if not auth_query_params:
        return url

    parsed = urlparse(url)

    # Parse existing query params (preserving order and duplicates)
    existing_params = parse_qs(parsed.query, keep_blank_values=True)

    # Flatten existing params (parse_qs returns lists)
    flat_params: Dict[str, str] = {}
    for k, v in existing_params.items():
        flat_params[k] = v[0] if v else ""

    # Add auth params (these will override if same key exists)
    flat_params.update(auth_query_params)

    # Rebuild the query string
    new_query = urlencode(flat_params)

    # Reconstruct URL
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


def sanitize_url_for_logging(
    url: str,
    auth_query_params: Optional[Dict[str, str]] = None,
) -> str:
    """Redact sensitive query parameters from a URL for safe logging.

    This function removes or masks sensitive query parameters to prevent
    API keys and other secrets from appearing in logs, error messages,
    and exception traces.

    Args:
        url: The URL to sanitize.
        auth_query_params: Optional dict of {param_name: value} that are
            known to be sensitive (e.g., the gateway's configured auth params).
            These param names will always be redacted regardless of their value.

    Returns:
        URL with sensitive parameter values replaced with "REDACTED".

    Example:
        >>> sanitize_url_for_logging(
        ...     "https://api.tavily.com/mcp?tavilyApiKey=secret123",
        ...     {"tavilyApiKey": "secret123"}
        ... )
        'https://api.tavily.com/mcp?tavilyApiKey=REDACTED'

        >>> # Also catches static sensitive params
        >>> sanitize_url_for_logging(
        ...     "https://api.example.com?api_key=secret&q=search"
        ... )
        'https://api.example.com?api_key=REDACTED&q=search'
    """
    parsed = urlparse(url)

    if not parsed.query:
        return url

    # Build set of param names to redact
    sensitive_names = set(STATIC_SENSITIVE_PARAMS)
    if auth_query_params:
        # Add gateway-specific param names (case-insensitive lookup)
        sensitive_names.update(k.lower() for k in auth_query_params.keys())
        sensitive_names.update(auth_query_params.keys())  # Also exact case

    # Parse existing query params
    existing_params = parse_qs(parsed.query, keep_blank_values=True)

    # Redact sensitive values
    sanitized_params: Dict[str, str] = {}
    for k, v in existing_params.items():
        # Check if this param name is sensitive (case-insensitive)
        if k.lower() in sensitive_names or k in sensitive_names:
            sanitized_params[k] = "REDACTED"
        else:
            sanitized_params[k] = v[0] if v else ""

    # Rebuild the query string
    new_query = urlencode(sanitized_params)

    # Reconstruct URL
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


# Regex to match URLs in text (http:// or https://)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def sanitize_exception_message(
    message: str,
    auth_query_params: Optional[Dict[str, str]] = None,
) -> str:
    """Sanitize URLs embedded within exception messages.

    Exception messages from HTTP libraries (httpx, aiohttp, etc.) often include
    the full URL, which may contain sensitive query parameters. This function
    finds and sanitizes all URLs in the message.

    Args:
        message: The exception message (str(e)) to sanitize.
        auth_query_params: Optional dict of known sensitive param names.

    Returns:
        Message with all embedded URLs sanitized.

    Example:
        >>> sanitize_exception_message(
        ...     "Connection failed: https://api.tavily.com/mcp?tavilyApiKey=secret123",
        ...     {"tavilyApiKey": "secret123"}
        ... )
        'Connection failed: https://api.tavily.com/mcp?tavilyApiKey=REDACTED'

        >>> sanitize_exception_message(
        ...     "Error connecting to https://api.example.com?api_key=abc&q=test"
        ... )
        'Error connecting to https://api.example.com?api_key=REDACTED&q=test'
    """
    if not message:
        return message

    def replace_url(match: re.Match) -> str:
        """Replace a matched URL with its sanitized version.

        Args:
            match: Regex match object containing the URL.

        Returns:
            Sanitized URL with sensitive params redacted.
        """
        url = match.group(0)
        return sanitize_url_for_logging(url, auth_query_params)

    return _URL_PATTERN.sub(replace_url, message)
