# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/portable_credentials.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Credential filtering for portable configuration files.
"""

# Standard
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.header_filtering import is_tool_credential_header_name
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS

_CREDENTIAL_FIELDS = frozenset(
    {
        "auth",
        "auth_value",
        "auth_username",
        "auth_password",
        "auth_token",
        "auth_headers",
        "auth_header_key",
        "auth_header_value",
        "auth_query_params",
        "auth_query_param_key",
        "auth_query_param_value",
        "oauth_config",
        "sigv4_config",
        "client_cert",
        "client_key",
        "add_headers",
    }
)
_SAFE_KEY = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SIGNATURE_QUERY_KEYS = frozenset({"sig", "signature", "x-goog-credential", "x-goog-signature", "x-goog-security-token"})


class InvalidPortableHeaders(ValueError):
    """The file contains malformed operational headers."""


def without_file_credentials(data: dict[str, Any], *, validate_headers: bool = False) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return configuration data with credential values removed.

    Args:
        data: A tool or gateway file entity.
        validate_headers: Reject malformed operational headers in import files.

    Returns:
        Portable entity data and safe names of removed credential fields.

    Raises:
        InvalidPortableHeaders: An import file contains malformed headers.
    """
    removed = set(data.keys() & _CREDENTIAL_FIELDS)
    cleaned = {key: value for key, value in data.items() if key not in _CREDENTIAL_FIELDS and key != "auth_type"}
    if data.get("auth_type") not in {None, "", "none", "one_time_auth"}:
        cleaned["credentials_required"] = True
    headers = cleaned.get("headers")
    if isinstance(headers, dict):
        remaining = {}
        for key, value in headers.items():
            if isinstance(key, str) and (is_tool_credential_header_name(key) or isinstance(value, str) and value in (settings.masked_auth_value, "********")):
                removed.add(f"headers.{key}" if _SAFE_KEY.fullmatch(key) else "headers")
            elif isinstance(key, str) and isinstance(value, str):
                remaining[key] = value
            elif validate_headers:
                raise InvalidPortableHeaders("Operational header names and values must be strings")
        cleaned["headers"] = remaining
    elif headers is not None:
        if validate_headers:
            raise InvalidPortableHeaders("Headers must be an object")
        cleaned.pop("headers")
    if isinstance(cleaned.get("url"), str):
        url = urlsplit(cleaned["url"])
        query_values = data.get("auth_query_params")
        names = STATIC_SENSITIVE_PARAMS | _SIGNATURE_QUERY_KEYS
        if isinstance(query_values, dict):
            names |= {key.lower() for key in query_values if isinstance(key, str)}
        if isinstance(data.get("auth_query_param_key"), str):
            names |= {data["auth_query_param_key"].lower()}
        query = []
        query_changed = False
        for key, value in parse_qsl(url.query, keep_blank_values=True):
            if key.lower() in names or value in (settings.masked_auth_value, "********"):
                removed.add(f"url.query.{key}" if _SAFE_KEY.fullmatch(key) else "url.query")
                query_changed = True
            else:
                query.append((key, value))
        host = url.netloc
        if "@" in host:
            host = host.rsplit("@", 1)[-1]
            removed.add("url.userinfo")
        if query_changed or host != url.netloc:
            cleaned["url"] = urlunsplit(url._replace(netloc=host, query=urlencode(query) if query_changed else url.query))
    if removed:
        cleaned["credentials_required"] = True
    return cleaned, tuple(sorted(removed))
