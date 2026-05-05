# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/validators.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Self-contained security validation for the plugin framework.

Contains only the validation methods actually used by framework models
(MCPClientConfig), with hardcoded defaults to avoid any dependency on
mcpgateway.config.settings.

Examples:
    >>> SecurityValidator.validate_url("https://example.com")
    'https://example.com'
"""

# Standard
import ipaddress
import logging
import re
from re import Pattern
from urllib.parse import urlparse, unquote

# First-Party
from mcpgateway.plugins.framework.settings import get_ssrf_settings

logger = logging.getLogger(__name__)

# Defaults matching the gateway's SecurityValidator in mcpgateway/common/validators.py.
# Keep these in sync -- test_transport_type_enum_parity guards the enum,
# but these constants are verified by test_security_validator_url_scheme_parity.
_ALLOWED_URL_SCHEMES = ("http://", "https://", "ws://", "wss://")
_MAX_URL_LENGTH = 2048

# Dangerous URL protocol patterns (matches gateway's _DANGEROUS_URL_PATTERNS)
_DANGEROUS_URL_PATTERNS: list[Pattern[str]] = [
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"data:", re.IGNORECASE),
    re.compile(r"vbscript:", re.IGNORECASE),
    re.compile(r"about:", re.IGNORECASE),
    re.compile(r"chrome:", re.IGNORECASE),
    re.compile(r"file:", re.IGNORECASE),
    re.compile(r"ftp:", re.IGNORECASE),
    re.compile(r"mailto:", re.IGNORECASE),
]

# HTML/script XSS patterns (matches gateway's DANGEROUS_HTML_PATTERN / DANGEROUS_JS_PATTERN).
# Keep in sync with mcpgateway/config.py validation_dangerous_html_pattern / validation_dangerous_js_pattern.
_DANGEROUS_HTML_PATTERN = re.compile(
    r"<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)\b"
    r"|</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|area|map|canvas|applet|frame|frameset|html|head|body|style)>",
    re.IGNORECASE,
)
_DANGEROUS_JS_PATTERN = re.compile(
    r"(?:^|\s|[\"'`<>=])(javascript:|vbscript:|data:\s*[^,]*[;\s]*(javascript|vbscript)|\bon[a-z]+\s*=|<\s*script\b)",
    re.IGNORECASE,
)

# Private/reserved IPv4 networks blocked for SSRF protection
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata
]

# Regex patterns for detecting non-standard escape sequences
_PERCENT_U_ESCAPE_RE = re.compile(r"%[Uu][0-9a-fA-F]{4}")
_JS_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2})")


def _unquote_if_needed(text: str) -> str:
    """Decode percent-encoding only when the input actually contains `%`.

    Most incoming URLs and identifiers have no percent-encoding; skipping
    unquote() in that case avoids a full-string scan + allocation on the hot path.

    NOTE: Mirrored from mcpgateway/common/validators.py pending
    extraction into a shared stdlib-only module (tracked by issue #4434).
    """
    return unquote(text) if "%" in text else text


def _decode_strict(value: str, field_name: str) -> str:
    """Decode once; reject payloads that remain percent-encoded after one pass.

    Blocks the double-encoding bypass class: `%253Cscript%253E` decodes to
    `%3Cscript%3E` under a single unquote(), which slips past regex blocklists
    targeting literal `<script>`. A downstream consumer that decodes a second
    time would then see `<script>`.
    """
    decoded = _unquote_if_needed(value)
    if decoded is not value and unquote(decoded) != decoded:
        raise ValueError(f"{field_name} contains double-encoded characters which are not allowed")
    return decoded


class SecurityValidator:
    """Security validator for the plugin framework.

    Mirrors the SSRF-hardening checks from the gateway's SecurityValidator
    without depending on mcpgateway.config.settings.

    Examples:
        >>> SecurityValidator.validate_url("https://example.com")
        'https://example.com'
    """

    @staticmethod
    def validate_url(value: str, field_name: str = "URL") -> str:
        """Validate URLs for allowed schemes, SSRF protection, and safe structure.

        Credentials, IPv6, dangerous protocols, CRLF injection, spaces in
        domain, and port range are always enforced.  SSRF IP-range blocking
        (private/reserved networks) is gated by the ``ssrf_protection_enabled``
        plugin setting.

        Args:
            value: URL string to validate.
            field_name: Name of the field being validated (for error messages).

        Returns:
            The validated URL string.

        Raises:
            ValueError: If the URL is empty, too long, uses a disallowed
                scheme, contains credentials, targets a blocked IP (when SSRF
                protection is enabled), or is structurally invalid.

        Examples:
            >>> SecurityValidator.validate_url("https://example.com")
            'https://example.com'
            >>> SecurityValidator.validate_url("https://example.com:9000/sse")
            'https://example.com:9000/sse'
            >>> SecurityValidator.validate_url("")
            Traceback (most recent call last):
                ...
            ValueError: URL cannot be empty
            >>> SecurityValidator.validate_url("ftp://example.com")
            Traceback (most recent call last):
                ...
            ValueError: URL must start with one of: http://, https://, ws://, wss://
            >>> SecurityValidator.validate_url("https://user:pass@example.com/")
            Traceback (most recent call last):
                ...
            ValueError: URL contains credentials which are not allowed
            >>> SecurityValidator.validate_url("https://[::1]:8080/")
            Traceback (most recent call last):
                ...
            ValueError: URL contains IPv6 address which is not supported
            >>> SecurityValidator.validate_url("https://0.0.0.0/")
            Traceback (most recent call last):
                ...
            ValueError: URL contains invalid IP address (0.0.0.0)
            >>> SecurityValidator.validate_url("https://example.com/<script>alert(1)</script>")
            Traceback (most recent call last):
                ...
            ValueError: URL contains HTML tags that may cause security issues
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")

        if len(value) > _MAX_URL_LENGTH:
            raise ValueError(f"{field_name} exceeds maximum length of {_MAX_URL_LENGTH}")

        # Single-pass decode + double-encoding rejection (centralised in _decode_strict).
        decoded_value = _decode_strict(value, field_name)

        # Reject IIS-style `%uXXXX` escapes that urllib does not decode.
        # Check both original (`%uXXXX`) and decoded (`%25u003c` → `%u003c`) forms
        # to close the double-encoded `%25uXXXX` bypass.
        if _PERCENT_U_ESCAPE_RE.search(value) or _PERCENT_U_ESCAPE_RE.search(decoded_value):
            raise ValueError(f"{field_name} contains non-standard %u-style escapes which are not allowed")

        # Reject JS-style `\uXXXX`/`\xXX` escapes that bypass blocklists in JS contexts.
        if _JS_ESCAPE_RE.search(decoded_value):
            raise ValueError(f"{field_name} contains JavaScript-style escape sequences which are not allowed")

        # `unquote()` emits U+FFFD for invalid UTF-8 / overlong sequences (e.g. `%c0%bc`);
        # legitimate percent-encoded UTF-8 never decodes to U+FFFD.
        if "\ufffd" in decoded_value:
            raise ValueError(f"{field_name} contains invalid UTF-8 byte sequences which are not allowed")

        # Check allowed schemes (lowercase value once, not per scheme).
        allowed_schemes = _ALLOWED_URL_SCHEMES
        value_lower = value.lower()
        if not any(value_lower.startswith(scheme.lower()) for scheme in allowed_schemes):
            raise ValueError(f"{field_name} must start with one of: {', '.join(allowed_schemes)}")

        # Block dangerous URL patterns anywhere in the decoded URL (defense-in-depth:
        # downstream consumers may extract query/fragment and reuse as URLs elsewhere).
        # Conservative by design; legitimate `mailto:`/`ftp:` in query strings should
        # be sent as separate structured fields rather than embedded in a URL.
        for pattern in _DANGEROUS_URL_PATTERNS:
            if pattern.search(decoded_value):
                raise ValueError(f"{field_name} contains unsupported or potentially dangerous protocol")

        # Block IPv6 URLs (square brackets). Scanning `decoded_value` alone
        # suffices: unquote() never removes non-`%` chars, so any `[` in
        # `value` also appears in `decoded_value`; `%5B` adds a `[` only there.
        if "[" in decoded_value or "]" in decoded_value:
            raise ValueError(f"{field_name} contains IPv6 address which is not supported")

        # Block protocol-relative URLs
        if value.startswith("//"):
            raise ValueError(f"{field_name} contains protocol-relative URL which is not supported")

        # Reject C0 control characters (literal or decoded from %00–%1f) and DEL.
        # Subsumes the prior CRLF-only check: NUL (%00), TAB (%09), VT (%0b),
        # FF (%0c), and DEL (%7f) are equally illegitimate in URLs.
        if any(ch != " " and ch < "\x20" for ch in decoded_value) or "\x7f" in decoded_value:
            raise ValueError(f"{field_name} contains control characters which are not allowed")

        # Literal space check uses `value` (NOT decoded): `%20` is the standard
        # encoding for space in paths and must remain valid. Authority-level
        # encoded-space bypass is handled separately after urlparse below.
        if " " in value.split("?", maxsplit=1)[0]:
            raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")

        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f"{field_name} is not a valid URL")

            # Additional validation: ensure netloc doesn't contain brackets (double-check)
            if "[" in result.netloc or "]" in result.netloc:
                raise ValueError(f"{field_name} contains IPv6 address which is not supported")

            # urlparse does not decode netloc; decode to catch `exam%20ple.com`-style
            # authority injection without breaking encoded-space in path/query.
            decoded_netloc = _unquote_if_needed(result.netloc)
            if any(ch.isspace() for ch in decoded_netloc):
                raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")

            # SSRF hostname check: urlparse does NOT percent-decode `hostname`,
            # so `%31%32%37%2E%30%2E%30%2E%31` (= 127.0.0.1) bypasses without this.
            hostname = result.hostname
            if hostname:
                decoded_hostname = _unquote_if_needed(hostname)
                if decoded_hostname == "0.0.0.0":  # nosec B104 - blocked for security
                    raise ValueError(f"{field_name} contains invalid IP address (0.0.0.0)")

                # Gate private/reserved IP blocking on plugin-specific settings.
                if get_ssrf_settings().ssrf_protection_enabled:
                    try:
                        addr = ipaddress.ip_address(decoded_hostname)
                        for network in _BLOCKED_NETWORKS:
                            if addr in network:
                                raise ValueError(f"{field_name} contains IP address blocked by SSRF protection ({decoded_hostname})")
                    except ValueError as ip_err:
                        if "blocked by SSRF" in str(ip_err):
                            raise
                        # Not a valid IP — it's a hostname, which is fine

            # Credentials: `result.username`/`password` catches literal `user:pass@`;
            # `@` in decoded_netloc catches percent-encoded userinfo (e.g. `user%3Apass@`).
            if result.username or result.password or "@" in decoded_netloc:
                raise ValueError(f"{field_name} contains credentials which are not allowed")

            # Validate port number
            if result.port is not None:
                if result.port < 1 or result.port > 65535:
                    raise ValueError(f"{field_name} contains invalid port number")

            # Block HTML tags and script/event-handler patterns in URL
            if _DANGEROUS_HTML_PATTERN.search(decoded_value):
                raise ValueError(f"{field_name} contains HTML tags that may cause security issues")
            if _DANGEROUS_JS_PATTERN.search(decoded_value):
                raise ValueError(f"{field_name} contains script patterns that may cause security issues")

        except ValueError:
            raise
        except Exception:
            raise ValueError(f"{field_name} is not a valid URL")

        return value


def validate_plugin_url(value: str, field_name: str = "URL") -> str:
    """Plugin framework URL validation entry point.

    Args:
        value: The URL string to validate.
        field_name: Descriptive name for error messages.

    Returns:
        The validated URL string.
    """
    return SecurityValidator.validate_url(value, field_name)
