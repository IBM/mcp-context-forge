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
from urllib.parse import urlparse

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

        if not any(value.lower().startswith(scheme) for scheme in _ALLOWED_URL_SCHEMES):
            raise ValueError(f"{field_name} must start with one of: {', '.join(_ALLOWED_URL_SCHEMES)}")

        # Block dangerous URL patterns
        for pattern in _DANGEROUS_URL_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"{field_name} contains unsupported or potentially dangerous protocol")

        # Block IPv6 URLs
        if "[" in value or "]" in value:
            raise ValueError(f"{field_name} contains IPv6 address which is not supported")

        # Block CRLF injection
        if "\r" in value or "\n" in value:
            raise ValueError(f"{field_name} contains line breaks which are not allowed")

        # Block spaces in domain (but allow in query string)
        if " " in value.split("?")[0]:
            raise ValueError(f"{field_name} contains spaces which are not allowed in URLs")

        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f"{field_name} is not a valid URL")

            # Block credentials in URL
            if result.username or result.password:
                raise ValueError(f"{field_name} contains credentials which are not allowed")

            # Validate port number
            if result.port is not None:
                if result.port < 1 or result.port > 65535:
                    raise ValueError(f"{field_name} contains invalid port number")

            # SSRF protection: block dangerous IP addresses (always block 0.0.0.0)
            hostname = result.hostname
            if hostname:
                if hostname == "0.0.0.0":  # nosec B104
                    raise ValueError(f"{field_name} contains invalid IP address (0.0.0.0)")

                # Gate private/reserved IP blocking on plugin-specific settings.
                if get_ssrf_settings().ssrf_protection_enabled:
                    try:
                        addr = ipaddress.ip_address(hostname)
                        for network in _BLOCKED_NETWORKS:
                            if addr in network:
                                raise ValueError(f"{field_name} contains IP address blocked by SSRF protection ({hostname})")
                    except ValueError as ip_err:
                        if "blocked by SSRF" in str(ip_err):
                            raise
                        # Not a valid IP — it's a hostname, which is fine

            # Block HTML tags and script/event-handler patterns in URL
            if _DANGEROUS_HTML_PATTERN.search(value):
                raise ValueError(f"{field_name} contains HTML tags that may cause security issues")
            if _DANGEROUS_JS_PATTERN.search(value):
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
