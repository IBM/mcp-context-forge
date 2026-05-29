# -*- coding: utf-8 -*-
"""Tests for sanitized tool pre-invoke hook diagnostics."""

# Standard
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

# Third-Party
from cpex.framework import HttpHeaderPayload
from pydantic import BaseModel

# First-Party
from mcpgateway.services import tool_service as tool_service_module
from mcpgateway.services.tool_service import _log_tool_pre_invoke_result


def test_tool_pre_invoke_logging_without_modified_payload_logs_only_keys(caplog):
    """No modified payload should be logged without argument or header values."""
    original_args = {"normal\nkey": "visible-value", "wxo_auth": "secret-token"}  # pragma: allowlist secret
    original_headers = HttpHeaderPayload(root={"Authorization": "Bearer secret", "x-wxo-access-token": "secret"})
    pre_result = SimpleNamespace(modified_payload=None)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("rishiserver-list-all-secrets", original_args, original_headers, pre_result)

    assert "modified_payload=None" in caplog.text
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
        "wxo_auth": "secret-token",  # pragma: allowlist secret
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


def test_tool_pre_invoke_logging_sanitizes_tool_and_modified_names(caplog):
    """Caller and plugin-controlled tool names should be sanitized before logging."""
    modified_payload = SimpleNamespace(name="renamed\nCRITICAL\x1b[31m", args={}, headers=None)
    pre_result = SimpleNamespace(modified_payload=modified_payload)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("tool\r\nERROR\x1b[31m", {}, None, pre_result)

    [record] = caplog.records
    assert "\n" not in record.message
    assert "\r" not in record.message
    assert "\x1b" not in record.message
    assert "tool  ERROR [31m" in record.message
    assert "modified_name=renamed CRITICAL [31m" in record.message


def test_tool_pre_invoke_logging_skips_work_when_debug_disabled(monkeypatch):
    """Diagnostics should avoid key extraction overhead unless DEBUG logging is enabled."""

    def fail_if_called(_value):
        raise AssertionError("_mapping_keys should not run when DEBUG is disabled")

    monkeypatch.setattr(tool_service_module, "_mapping_keys", fail_if_called)
    logger = logging.getLogger("mcpgateway.services.tool_service")
    old_level = logger.level
    try:
        logger.setLevel(logging.INFO)
        _log_tool_pre_invoke_result("tool", {"key": "value"}, None, SimpleNamespace(modified_payload=None))
    finally:
        logger.setLevel(old_level)


def test_tool_pre_invoke_logging_is_best_effort(monkeypatch, caplog):
    """Diagnostics failures should not abort tool execution."""

    def broken_sanitizer(_value):
        raise RuntimeError("sanitize failed")

    monkeypatch.setattr(tool_service_module, "sanitize_for_log", broken_sanitizer)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("tool", {"key": "value"}, None, SimpleNamespace(modified_payload=None))

    assert "tool_pre_invoke diagnostic logging failed" in caplog.text


def test_tool_pre_invoke_logging_swallows_logging_handler_failures(monkeypatch):
    """A logging handler failure should not escape the diagnostic helper."""

    class RaisingLogger:
        def isEnabledFor(self, level):
            return level == logging.DEBUG

        def debug(self, *_args, **_kwargs):
            raise RuntimeError("handler failed")

    monkeypatch.setattr(tool_service_module, "logger", RaisingLogger())

    _log_tool_pre_invoke_result("tool", {}, None, SimpleNamespace(modified_payload=None))


def test_tool_pre_invoke_logging_handles_pydantic_model_args(caplog):
    """Pydantic model args should produce field names without logging values."""

    class ArgsModel(BaseModel):
        visible: str
        wxo_auth: str

    args = ArgsModel(visible="keep-me", wxo_auth="secret-token")  # pragma: allowlist secret
    pre_result = SimpleNamespace(modified_payload=None)

    with caplog.at_level(logging.DEBUG, logger="mcpgateway.services.tool_service"):
        _log_tool_pre_invoke_result("tool", args, None, pre_result)

    assert "arg_keys_before=['visible', 'wxo_auth']" in caplog.text
    assert "keep-me" not in caplog.text
    assert "secret-token" not in caplog.text


def test_tool_pre_invoke_logging_hook_paths_are_wired():
    """Guard against dropping diagnostics from one of the four TOOL_PRE_INVOKE paths."""
    tree = ast.parse(Path(tool_service_module.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_log_tool_pre_invoke_result"
    ]

    assert len(calls) == 4
