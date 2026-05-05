# -*- coding: utf-8 -*-
"""Shared URL percent-encoding attack vectors for validator regression tests.

This module provides parametrize lists for testing that URL validators correctly
detect and block percent-encoded injection payloads (CRLF, HTML/script, dangerous
protocols, credentials, double-encoding, etc.) while accepting legitimate encoded
characters in paths and query strings.

Used by:
- tests/unit/mcpgateway/validation/test_validators_advanced.py::TestValidateUrlPercentEncoding
- tests/unit/mcpgateway/plugins/framework/test_validators.py::TestSecurityValidatorPercentEncoding

Context: PR #4335 hardened SecurityValidator.validate_url() against percent-
encoded bypass attacks. These test vectors ensure the hardening stays in place.
"""

# CRLF injection vectors (%0d = CR, %0a = LF)
ENCODED_CRLF_VECTORS = [
    ("https://example.com/%0d%0aHost:evil.com", "control characters"),
    ("https://example.com/%0D%0AHost:evil.com", "control characters"),
    ("https://example.com/%0a", "control characters"),
    ("https://example.com/%0d", "control characters"),
]

# HTML tag injection vectors
ENCODED_HTML_TAG_VECTORS = [
    "https://example.com/%3Cscript%3Ealert(1)%3C/script%3E",
    "https://example.com/%3cscript%3ealert(1)%3c/script%3e",
    "https://example.com/%3Ciframe%20src=x%3E",
]

# Dangerous protocol injection vectors
ENCODED_DANGEROUS_PROTOCOL_VECTORS = [
    "https://example.com/?x=javascript%3Aalert(1)",
    "https://example.com/?x=JAVASCRIPT%3Aalert(1)",
    "https://example.com/?x=vbscript%3Amsgbox(1)",
    "https://example.com/?x=data%3Atext/html,<script>",
]

# IPv6 bracket vectors (literal addresses)
ENCODED_IPV6_BRACKET_VECTORS = [
    "https://%5B%3A%3A1%5D:8080/",
    "https://%5B::1%5D:8080/",
]

# Whitespace in authority (space = %20, tab = %09)
ENCODED_WHITESPACE_AUTHORITY_VECTORS = [
    ("https://exam%20ple.com/", "spaces"),
    ("https://example%09.com/", "control characters"),
]

# Double-encoded payloads (%25 = %)
DOUBLE_ENCODED_VECTORS = [
    "https://example.com/%253Cscript%253E",
    "https://example.com/%250d%250aHost:evil.com",
    "https://example.com/%2520",
]

# IIS-style Unicode escapes (%uXXXX)
IIS_UNICODE_ESCAPE_VECTORS = [
    "https://example.com/%u003cscript%u003e",
    "https://example.com/%U003C",
]

# JavaScript-style escape sequences (\uXXXX, \xXX)
JS_UNICODE_ESCAPE_VECTORS = [
    "https://example.com/%5Cu003cscript%5Cu003e",
    "https://example.com/%5Cx3c",
    "https://example.com/path\\u003cscript",
]

# UTF-8 overlong or invalid sequences (produce U+FFFD)
UTF8_OVERLONG_VECTORS = [
    "https://example.com/%C0%BC",
    "https://example.com/%c0%bcscript",
    "https://example.com/%ED%A0%80",
]

# Legitimate encoded characters (regression: must pass)
LEGITIMATE_ENCODED_ACCEPTED_VECTORS = [
    "https://example.com/hello%20world",
    "https://example.com/?q=hello%20world",
    "https://example.com/foo%2Fbar",
    "https://example.com/caf%C3%A9",
    "https://example.com/%2B",
]
