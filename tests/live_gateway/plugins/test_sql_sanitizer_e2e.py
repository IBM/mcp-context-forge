# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/test_sql_sanitizer_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end gateway test for the native SQL Sanitizer plugin.

Unlike the other suites in this directory, SQL Sanitizer is **not** a cpex wheel
- it ships in the gateway repo at ``plugins/sql_sanitizer/`` and is loaded as a
native plugin. With the committed config (``block_on_violation: true``,
``strip_comments: true``) it scans configured fields for risky SQL and:

* **blocks** dangerous statements (DROP/TRUNCATE/ALTER/GRANT/REVOKE and
  DELETE/UPDATE without a WHERE clause), and
* **sanitizes** otherwise-safe SQL by stripping ``--`` line and ``/* */`` block
  comments in place (a non-blocking mutation).

This suite drives both behaviours over the plugin's tool hook
(``tool_pre_invoke``) via the fast-time-server ``echo`` tool - dangerous SQL is
blocked, safe SQL round-trips unchanged, and commented SQL is echoed back with
its comments stripped.

The plugin's ``prompt_pre_fetch`` hook is intentionally not covered here: a
blocked prompt currently surfaces as an unrelated ``ServerResult`` validation
error rather than a clean violation (a gateway-side issue), so there is no
stable contract to assert against.

The committed config scans ``fields: [sql, query, statement]``; the echo tool's
argument is ``message``, so both enforcement paths add ``message`` to ``fields``
(the static path via ``make_enforce_config --config-override``, the bindings
path via ``config_overrides`` here) so the tool argument is actually scanned.

The tool assertions run against **both** enforcement paths, selected by the
``PLUGIN_ENFORCEMENT`` env var (set by the workflow matrix):

* ``static`` - the gateway boots with SQLSanitizer in ``enforce`` mode (config
  derived from ``plugins/config.yaml``), and
* ``binding`` - the gateway boots with SQLSanitizer ``disabled`` and a runtime
  tool-plugin-binding flips it to ``enforce`` for the test's team+tool.
"""

from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import httpx
import pytest

# First-Party
from tests.live_gateway.helpers.mcp_test_helpers import skip_no_gateway
from tests.live_gateway.plugins import _helpers

pytestmark = [pytest.mark.e2e, skip_no_gateway]

PLUGIN_NAME = "SQLSanitizer"

# The echo tool's argument is ``message``, which the committed config's
# ``fields`` (sql/query/statement) does not include - so both enforcement paths
# add ``message`` so the tool argument is scanned. On the static path this is
# applied by make_enforce_config (--config-override); on the bindings path it is
# passed through plugin_enforcement's config_overrides below.
_FIELDS_OVERRIDE: dict[str, Any] = {"fields": ["sql", "query", "statement", "message"]}

# Exact block message the gateway surfaces when SQLSanitizer blocks a tool call.
# The gateway wraps violations as
# "{hook} blocked by plugin {name}: {code} - {reason} ({description})"
# (plugins/framework/manager.py); the plugin's violation strings are constants,
# so the full message is deterministic.
EXPECTED_TOOL_BLOCK = "tool_pre_invoke blocked by plugin SQLSanitizer: SQL_SANITIZER - Risky SQL detected (Potentially dangerous SQL detected in tool args)"

# (label, sql) the sanitizer must block: the five blocked statements plus
# DELETE/UPDATE without a WHERE clause.
BLOCK_CASES = [
    ("drop", "DROP TABLE users"),
    ("truncate", "TRUNCATE TABLE logs"),
    ("alter", "ALTER TABLE users ADD c int"),
    ("grant", "GRANT ALL ON db TO bob"),
    ("revoke", "REVOKE SELECT ON db FROM bob"),
    ("delete_without_where", "DELETE FROM users"),
    ("update_without_where", "UPDATE users SET active=0"),
]

# (label, sql) the sanitizer must leave byte-for-byte unchanged: a plain SELECT
# and DELETE/UPDATE that *do* carry a WHERE clause.
PASSTHROUGH_CASES = [
    ("select", "SELECT id FROM users WHERE id=1"),
    ("delete_with_where", "DELETE FROM users WHERE id=1"),
    ("update_with_where", "UPDATE users SET active=0 WHERE id=1"),
]

# (label, sql, sanitized) - safe SQL whose comments are stripped in place (a
# non-blocking mutation). The replacement leaves the surrounding whitespace, so
# the line comment leaves a trailing space and the block comment leaves two
# spaces; both forms are asserted exactly.
SANITIZE_CASES = [
    ("line_comment", "SELECT 1 -- secret comment", "SELECT 1 "),
    ("block_comment", "SELECT 1 /* secret */ FROM dual", "SELECT 1  FROM dual"),
]


@pytest.fixture(scope="module", autouse=True)
def _enforcement(admin_client: httpx.Client, fast_time_server: dict[str, str]):
    """Activate the enforcement path under test (static config or DB binding).

    Fails fast unless SQLSanitizer loaded on the gateway, and - on the bindings
    path - creates the runtime binding (scoped to the suite's team+echo-tool,
    with ``message`` added to the scanned fields) that makes the tool hook
    enforce, removing it on teardown.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.

    Yields:
        ``None`` once the enforcement path is active.
    """
    with _helpers.plugin_enforcement(
        admin_client,
        fast_time_server=fast_time_server,
        plugin_name=PLUGIN_NAME,
        config_overrides=_FIELDS_OVERRIDE,
    ):
        yield


def _echo(admin_client: httpx.Client, fast_time_server: dict[str, str], message: str) -> dict:
    """Echo ``message`` through the gateway, driving the tool SQL hook.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        message: Text to echo through the gateway (and its plugin hook).

    Returns:
        The JSON-RPC ``result`` payload from ``tools/call``.
    """
    server_id = fast_time_server["server_id"]
    token = fast_time_server["token"]
    session_id = _helpers.initialize_session(admin_client, server_id=server_id, token=token)
    return _helpers.call_tool(
        admin_client,
        server_id=server_id,
        token=token,
        tool_name=fast_time_server["echo_tool"],
        arguments={"message": message},
        session_id=session_id,
        request_id=1,
    )


@pytest.mark.parametrize("label, sql", BLOCK_CASES, ids=[c[0] for c in BLOCK_CASES])
def test_tool_dangerous_sql_is_blocked(admin_client: httpx.Client, fast_time_server: dict[str, str], label: str, sql: str) -> None:
    """Dangerous SQL in a tool argument is blocked by SQLSanitizer.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        label: Case label (for test ids).
        sql: Dangerous SQL the sanitizer must block.
    """
    result = _echo(admin_client, fast_time_server, sql)

    assert result == {"content": [{"type": "text", "text": EXPECTED_TOOL_BLOCK}], "isError": True}


@pytest.mark.parametrize("label, sql", PASSTHROUGH_CASES, ids=[c[0] for c in PASSTHROUGH_CASES])
def test_tool_safe_sql_passes_through(admin_client: httpx.Client, fast_time_server: dict[str, str], label: str, sql: str) -> None:
    """Safe SQL round-trips through a tool unchanged.

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        label: Case label (for test ids).
        sql: Safe SQL the sanitizer must leave untouched.
    """
    result = _echo(admin_client, fast_time_server, sql)

    assert result == {"content": [{"type": "text", "text": sql}], "isError": False}


@pytest.mark.parametrize("label, sql, sanitized", SANITIZE_CASES, ids=[c[0] for c in SANITIZE_CASES])
def test_tool_comments_are_stripped(admin_client: httpx.Client, fast_time_server: dict[str, str], label: str, sql: str, sanitized: str) -> None:
    """Comments in otherwise-safe SQL are stripped in place (not blocked).

    Args:
        admin_client: Authenticated admin HTTP client.
        fast_time_server: Provisioned virtual server fixture value.
        label: Case label (for test ids).
        sql: SQL containing a comment.
        sanitized: Expected echoed text with the comment removed.
    """
    result = _echo(admin_client, fast_time_server, sql)

    assert result == {"content": [{"type": "text", "text": sanitized}], "isError": False}
