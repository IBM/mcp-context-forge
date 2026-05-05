# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/common/_url_hardening.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Shared URL-hardening helpers for SecurityValidator classes.

This module provides stdlib-only pure functions for URL validation,
extracted from mcpgateway/common/validators.py and
mcpgateway/plugins/framework/validators.py to eliminate code duplication.

Design constraints:
- MUST be stdlib-only (no import from mcpgateway.config.settings)
- Pure functions (no state, no settings dependencies)
- All helpers accept field_name parameter for error messages
- Raise ValueError with descriptive messages

Used by:
- mcpgateway/common/validators.py (gateway SecurityValidator)
- mcpgateway/plugins/framework/validators.py (plugin framework SecurityValidator)

Context: Issues #4434, #4435 - URL hardening consolidation.
"""

# Standard
import re
from urllib.parse import ParseResult, unquote

# Regex patterns for detecting non-standard escape sequences
_PERCENT_U_ESCAPE_RE = re.compile(r"%[Uu][0-9a-fA-F]{4}")
_JS_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2})")


def _unquote_if_needed(text: str) -> str:
    """Decode percent-encoding only when the input actually contains `%`.

    Most incoming URLs and identifiers have no percent-encoding; skipping
    unquote() in that case avoids a full-string scan + allocation on the hot path.
    """
    return unquote(text) if "%" in text else text


def _decode_and_check_encoding(value: str, field_name: str) -> str:
    """Single-pass decode + double-encoding + IIS/JS-escape + U+FFFD rejection.

    Blocks the double-encoding bypass class: `%253Cscript%253E` decodes to
    `%3Cscript%3E` under a single unquote(), which slips past regex blocklists
    targeting literal `<script>`. A downstream consumer that decodes a second
    time would then see `<script>`.

    Also rejects:
    - IIS-style `%uXXXX` escapes that urllib does not decode
    - JS-style `\\uXXXX`/`\\xXX` escapes that bypass blocklists
    - Invalid UTF-8 / overlong sequences (produce U+FFFD)

    Returns:
        The decoded URL string.

    Raises:
        ValueError: If double-encoded, contains non-standard escapes,
            or invalid UTF-8 sequences.
    """
    # Single-pass decode + double-encoding rejection
    decoded = _unquote_if_needed(value)
    if decoded is not value and unquote(decoded) != decoded:
        raise ValueError(f"{field_name} contains double-encoded characters which are not allowed")

    # Reject IIS-style `%uXXXX` escapes that urllib does not decode
    if _PERCENT_U_ESCAPE_RE.search(value) or _PERCENT_U_ESCAPE_RE.search(decoded):
        raise ValueError(f"{field_name} contains non-standard %u-style escapes which are not allowed")

    # Reject JS-style `\uXXXX`/`\xXX` escapes
    if _JS_ESCAPE_RE.search(decoded):
        raise ValueError(f"{field_name} contains JavaScript-style escape sequences which are not allowed")

    # `unquote()` emits U+FFFD for invalid UTF-8 / overlong sequences
    if "\ufffd" in decoded:
        raise ValueError(f"{field_name} contains invalid UTF-8 byte sequences which are not allowed")

    return decoded


def _check_structural_forbidden_chars(value: str, decoded_value: str, field_name: str) -> None:
    """Check for forbidden structural characters in URLs.

    Validates:
    - IPv6 brackets (literal `[`/`]` or encoded `%5B`/`%5D`)
    - C0 control characters (literal or decoded from %00-%1f) and DEL
    - Protocol-relative URLs (`//` prefix)
    - Spaces in authority (before `?`)

    Raises:
        ValueError: If any forbidden characters or patterns are found.
    """
    # Block IPv6 URLs (square brackets in decoded value)
    if "[" in decoded_value or "]" in decoded_value:
        raise ValueError(f"{field_name} contains IPv6 address which is not supported")

    # Block protocol-relative URLs
    if value.startswith("//"):
        raise ValueError(f"{field_name} contains protocol-relative URL which is not supported")

    # Reject C0 control characters (literal or decoded) and DEL
    if any(ch != " " and ch < "\x20" for ch in decoded_value) or "\x7f" in decoded_value:
        raise ValueError(f"{field_name} contains control characters which are not allowed")

    # Block spaces in domain (literal check on value, not decoded)
    if " " in value.split("?", maxsplit=1)[0]:
        raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")


def _check_netloc(result: "ParseResult", field_name: str) -> str:
    """Validate and return decoded netloc after whitespace/credentials checks.

    Args:
        result: urlparse() result containing the parsed URL components.
        field_name: Name of the field being validated (for error messages).

    Returns:
        The decoded netloc string.

    Raises:
        ValueError: If netloc contains spaces or credentials.
    """
    # urlparse does not decode netloc; decode to catch `exam%20ple.com`-style
    decoded_netloc = _unquote_if_needed(result.netloc)

    # Check for whitespace in decoded netloc
    if any(ch.isspace() for ch in decoded_netloc):
        raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")

    # Check for credentials in netloc (literal or encoded)
    if result.username or result.password or "@" in decoded_netloc:
        raise ValueError(f"{field_name} contains credentials which are not allowed")

    return decoded_netloc
