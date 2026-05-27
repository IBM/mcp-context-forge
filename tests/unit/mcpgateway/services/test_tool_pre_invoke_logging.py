# -*- coding: utf-8 -*-
"""Tests for sanitized tool pre-invoke hook diagnostics."""

# Standard
import logging
from types import SimpleNamespace

# Third-Party
from cpex.framework import HttpHeaderPayload

# First-Party
from mcpgateway.services.tool_service import _log_tool_pre_invoke_result


def test_tool_pre_invoke_logging_without_modified_payload_logs_only_keys(caplog):
    """No modified payload should be logged without argument or header values."""
    original_args = {"normal\nkey": "visible-value", "wxo_auth": "secret-token"}
    original_headers = HttpHeaderPayload(root={"Authorization": "Bearer secret", "x-wxo-access-token": "secret"})
    pre_result = SimpleNamespace(modified_payload=None)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("rishiserver-list-all-secrets", original_args, original_headers, pre_result)

    assert "modified_payload=False" in caplog.text
    assert "normal key" in caplog.text
    assert "wxo_auth" in caplog.text
    assert "Authorization" in caplog.text
    assert "visible-value" not in caplog.text
    assert "secret-token" not in caplog.text
    assert "Bearer secret" not in caplog.text


def test_tool_pre_invoke_logging_with_modified_payload_logs_key_diffs(caplog):
    """Modified payload diagnostics should show added/removed keys, not values."""
    original_args = {
        "real_arg": "keep-me",
        "wxo_auth": "secret-token",
        "wxo_connection_id": "",
        "wxo_environment_id": "draft",
    }
    original_headers = HttpHeaderPayload(root={"Authorization": "Bearer secret", "x-old": "old-value"})
    modified_payload = SimpleNamespace(
        name="renamed-tool",
        args={"real_arg": "changed-value"},
        headers=HttpHeaderPayload(root={"x-connection": "connection-secret"}),
    )
    pre_result = SimpleNamespace(modified_payload=modified_payload)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("rishiserver-list-all-secrets", original_args, original_headers, pre_result)

    assert "modified_payload=True" in caplog.text
    assert "modified_name=renamed-tool" in caplog.text
    assert "removed_arg_keys=['wxo_auth', 'wxo_connection_id', 'wxo_environment_id']" in caplog.text
    assert "added_arg_keys=[]" in caplog.text
    assert "removed_header_keys=['Authorization', 'x-old']" in caplog.text
    assert "added_header_keys=['x-connection']" in caplog.text
    assert "keep-me" not in caplog.text
    assert "changed-value" not in caplog.text
    assert "secret-token" not in caplog.text
    assert "connection-secret" not in caplog.text


def test_tool_pre_invoke_logging_handles_missing_mappings(caplog):
    """Diagnostics should tolerate absent headers and non-mapping args."""
    pre_result = SimpleNamespace(modified_payload=SimpleNamespace(name="tool", args=None, headers=None))

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("tool", None, None, pre_result)

    assert "modified_payload=True" in caplog.text
    assert "arg_keys_before=None" in caplog.text
    assert "arg_keys_after=None" in caplog.text
    assert "header_keys_before=None" in caplog.text
    assert "header_keys_after=None" in caplog.text
