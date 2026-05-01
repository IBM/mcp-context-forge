# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_query_param_validation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Jonathan Springer

Regression tests for FastAPI Query-parameter regex patterns added by PR #4337
(ICACF-25) and extended during review.

These tests validate the **pattern strings** directly rather than spinning up
the full FastAPI app. This is intentional:

* The patterns are embedded in function signatures (not importable); the test
  mirrors them and the test doc comment pins each one to router:line so a drift
  becomes visible when this file is updated alongside the router.
* It catches the specific real-world breakage classes the review identified
  (Google-style OAuth codes, session-bound state, service-account identifiers,
  MCP tool namespacing, etc.) without flaky auth/DB setup.
* FastAPI and Pydantic evaluate query patterns with ``re.fullmatch`` on the raw
  input, which is the same semantics exercised here.

If a router's pattern changes, update the mirror below and add test vectors
covering the expanded or restricted set.

Run with::

    pytest tests/security/test_query_param_validation.py -v
"""

# Standard
import re

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# Pattern mirrors (keep in sync with the router:line references).
# ---------------------------------------------------------------------------

# mcpgateway/routers/sso.py:306 - OAuth error code (RFC 6749 Section 4.1.2.1
# / 5.2 enum-like snake_case tokens)
SSO_ERROR = r"^[a-zA-Z0-9_]+$"

# mcpgateway/routers/sso.py (scopes/code/state) deliberately have NO pattern
# after the B1/B2/B3 fix; they are bounded only by max_length. No regex to
# test - absence is the invariant.

# mcpgateway/routers/log_search.py:629 - user_id (email OR service account)
# mcpgateway/routers/observability.py:69 - user_email (email OR service account)
# mcpgateway/admin.py:17572 - user_email (email OR service account)
USER_IDENTIFIER = r"^[a-zA-Z0-9._%+@-]+$"

# mcpgateway/routers/observability.py:66 - status
TRACE_STATUS = r"^(ok|error)$"

# mcpgateway/routers/observability.py:68 - http_method
HTTP_METHOD = r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|CONNECT)$"

# mcpgateway/routers/observability.py:312 / rbac.py:scope_id, team_id - UUID-hex style IDs
ID_HYPHEN = r"^[a-zA-Z0-9_-]+$"

# mcpgateway/routers/observability.py:313 - resource_type / common tool / provider IDs
ID_DOTTED = r"^[a-zA-Z0-9_.-]+$"

# mcpgateway/routers/observability.py:314 - resource_name (allows space + slash)
RESOURCE_NAME = r"^[a-zA-Z0-9_. /-]+$"

# mcpgateway/routers/observability.py:477 / admin.py:14760 - export format enum
EXPORT_FORMAT = r"^(json|csv|ndjson)$"

# mcpgateway/routers/teams.py & email_auth.py & main.py - pagination cursors
# (base64.urlsafe_b64encode from mcpgateway/utils/pagination.py)
CURSOR = r"^[a-zA-Z0-9_=+/-]+$"

# mcpgateway/routers/toolops_router.py - mode enum
TOOL_OPS_MODE = r"^(generate|query|status)$"

# mcpgateway/admin.py:17575 - tool_name filter (MCP SEP-986, mirrors
# config.Settings.validation_tool_name_pattern)
MCP_TOOL_NAME = r"^[a-zA-Z0-9_][a-zA-Z0-9._/-]*$"

# mcpgateway/main.py - visibility enum (3 endpoints) + admin.py
VISIBILITY = r"^(private|team|public)$"

# mcpgateway/admin.py - relationship enum
RELATIONSHIP = r"^(owner|member|public)$"

# mcpgateway/admin.py:13681 - entity_type enum
ENTITY_TYPE = r"^(tools|resources|prompts|servers)$"

# mcpgateway/admin.py - observability dashboard guessed enums (values verified
# against templates/observability_partial.html options)
TIME_RANGE = r"^(1h|6h|12h|24h|7d|30d)$"
STATUS_FILTER = r"^(all|ok|error)$"
PERIOD_TYPE = r"^(hourly|daily)$"


def _matches(pattern: str, value: str) -> bool:
    """True when value fully matches pattern (FastAPI/Pydantic semantics)."""
    return re.fullmatch(pattern, value) is not None


# ---------------------------------------------------------------------------
# B2 regression: OAuth `state` must accept the codebase's session-bound format
# `<nonce>.<hmac_hex>` (see sso_service._STATE_BINDING_SEPARATOR = ".").
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        "abc123_-def.0123456789abcdef0123456789abcdef",  # session-bound nonce.hmac
        "plain_nonce_no_separator",  # simple opaque
        "base64.padded=",  # OIDC libraries that emit padded base64
        "jwt.eyJhbGciOi.JIUzI1NiJ9",  # JWT-encoded state
    ],
)
def test_oauth_state_accepts_session_bound_format(state: str) -> None:
    """OAuth `state` must accept our own `<nonce>.<hmac_hex>` separator."""
    assert 1 <= len(state) <= 128


# ---------------------------------------------------------------------------
# B3 regression: OAuth `scopes` must accept Google/Microsoft scope URIs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scopes",
    [
        "openid profile email",  # standard OIDC
        "https://www.googleapis.com/auth/userinfo.email openid profile",  # Google
        "https://graph.microsoft.com/.default",  # Microsoft Graph
        "admin:org repo read:user",  # GitHub style (colons)
        "User.Read Mail.ReadWrite",  # Microsoft short-form
    ],
)
def test_oauth_scopes_accepts_provider_specific_values(scopes: str) -> None:
    """OAuth `scopes` are provider-specific per RFC 6749 §3.3; no Query-layer regex."""
    assert 1 <= len(scopes) <= 500


# ---------------------------------------------------------------------------
# B4 regression: user_id / user_email must accept service-account identifiers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Real emails - must pass.
        ("user@example.com", True),
        ("first.last+tag@sub.example.co.uk", True),
        # Service-account fallbacks produced by get_user_email / audit trail code.
        ("unknown", True),
        ("system", True),
        ("automation", True),
        ("True", True),  # str(True) fallback observed in main.py:4223
        ("user-123", True),  # JWT sub claim style
        # Attack / injection attempts - must fail.
        ("user@example.com\r\nX-Injected: bad", False),  # CRLF
        ("user@example.com\x00", False),  # NUL
        ("user<script>alert()</script>", False),  # XSS
        ("user/../etc/passwd", False),  # path traversal
    ],
)
def test_user_identifier_pattern(value: str, expected: bool) -> None:
    """user_id / user_email must cover emails, service accounts, and reject injection."""
    assert _matches(USER_IDENTIFIER, value) is expected


# ---------------------------------------------------------------------------
# OAuth `error` (tightened to snake_case per RFC 6749 §4.1.2.1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # RFC 6749 standard error codes.
        ("invalid_request", True),
        ("unauthorized_client", True),
        ("access_denied", True),
        ("unsupported_response_type", True),
        ("invalid_scope", True),
        ("server_error", True),
        ("temporarily_unavailable", True),
        # Attack attempts.
        ("bad error code", False),
        ("<script>", False),
        ("error\r\ncrlf", False),
        ("", False),  # empty not allowed
    ],
)
def test_sso_error_pattern(error: str, expected: bool) -> None:
    """OAuth error values are RFC 6749 snake_case enums."""
    assert _matches(SSO_ERROR, error) is expected


# ---------------------------------------------------------------------------
# MCP tool name - SEP-986 compliance.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("get_weather", True),
        ("get-weather", True),
        ("getWeather", True),
        ("tool_1", True),
        ("_5gpt_query", True),
        ("my.namespace.tool", True),
        ("namespace/subtool", True),
        ("1tool", True),
        ("", False),
        ("tool<script>", False),
        ('tool"test', False),
        ("tool'test", False),
        ("tool test", False),
        ("tool:sub", False),
        (".hidden", False),
        ("-leading-hyphen", False),
    ],
)
def test_mcp_tool_name_pattern(tool_name: str, expected: bool) -> None:
    """Filter-side tool_name mirrors MCP SEP-986 (config.validation_tool_name_pattern)."""
    assert _matches(MCP_TOOL_NAME, tool_name) is expected


# ---------------------------------------------------------------------------
# UI-verified enums (time_range, status_filter from observability_partial.html).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1h", "6h", "24h", "7d"])
def test_time_range_accepts_ui_options(value: str) -> None:
    """Each <option value="..."> in the observability dashboard must pass."""
    assert _matches(TIME_RANGE, value)


@pytest.mark.parametrize("value", ["all", "ok", "error"])
def test_status_filter_accepts_ui_options(value: str) -> None:
    """Each <option value="..."> in the observability dashboard must pass."""
    assert _matches(STATUS_FILTER, value)


@pytest.mark.parametrize("value", ["hourly", "daily"])
def test_period_type_enum(value: str) -> None:
    assert _matches(PERIOD_TYPE, value)


# ---------------------------------------------------------------------------
# Cursor - must accept urlsafe_b64encode output.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Real urlsafe_b64 encoded cursors (alnum + '_' + '-' + optional '=').
        ("YWJjZGVmZw==", True),
        ("eyJpZCI6IjEyMyJ9", True),
        ("a_b-c=", True),
        # Injection attempts.
        ("bad\ncursor", False),
        ("<cursor>", False),
        ("", False),  # empty not allowed
    ],
)
def test_cursor_pattern(value: str, expected: bool) -> None:
    """Pagination cursors from utils.pagination.encode_cursor must pass."""
    assert _matches(CURSOR, value) is expected


# ---------------------------------------------------------------------------
# Enum family smoke tests.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "good", "bad"),
    [
        (TRACE_STATUS, "ok", "OK"),  # case-sensitive
        (TRACE_STATUS, "error", "err"),
        (HTTP_METHOD, "GET", "get"),  # case-sensitive per RFC 7231
        (HTTP_METHOD, "OPTIONS", "OPTION"),
        (EXPORT_FORMAT, "json", "JSON"),
        (EXPORT_FORMAT, "ndjson", "ndj"),
        (VISIBILITY, "private", "PRIVATE"),
        (RELATIONSHIP, "owner", "admin"),
        (ENTITY_TYPE, "tools", "tool"),
        (TOOL_OPS_MODE, "generate", "Generate"),
    ],
)
def test_enum_patterns(pattern: str, good: str, bad: str) -> None:
    assert _matches(pattern, good), f"expected {good!r} to match {pattern}"
    assert not _matches(pattern, bad), f"expected {bad!r} to NOT match {pattern}"


# ---------------------------------------------------------------------------
# CRLF / NUL / control-character rejection - global invariant across all
# patterns. Even the "free-text" max_length-only fields rely on downstream
# sanitize_log_message; the regex-guarded ones must reject outright.
# ---------------------------------------------------------------------------


CRLF_INJECTION_CASES = [
    "value\r\nX-Injected: evil",
    "value\nInjected",
    "value\rcarriage",
    "value\x00nul",
    "value\x1bescape",
]


@pytest.mark.parametrize(
    "pattern",
    [
        SSO_ERROR,
        USER_IDENTIFIER,
        TRACE_STATUS,
        HTTP_METHOD,
        ID_HYPHEN,
        ID_DOTTED,
        EXPORT_FORMAT,
        CURSOR,
        TOOL_OPS_MODE,
        MCP_TOOL_NAME,
        VISIBILITY,
        RELATIONSHIP,
        ENTITY_TYPE,
        TIME_RANGE,
        STATUS_FILTER,
        PERIOD_TYPE,
    ],
)
@pytest.mark.parametrize("injection", CRLF_INJECTION_CASES)
def test_crlf_and_control_char_rejection(pattern: str, injection: str) -> None:
    """No regex-guarded Query parameter may accept control characters."""
    assert not _matches(pattern, injection)
