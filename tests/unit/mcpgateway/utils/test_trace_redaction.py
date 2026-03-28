# -*- coding: utf-8 -*-
"""Tests for trace payload redaction helpers."""

# Standard
import json

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.utils.trace_redaction import (
    is_output_capture_enabled,
    redact_sensitive_fields,
    reload_trace_redaction_config,
    safe_serialize,
)


class SampleModel(BaseModel):
    password: str
    nested: dict


def teardown_function():
    reload_trace_redaction_config()


def test_redact_sensitive_fields_recurses_through_dicts_lists_and_tuples(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "password,authorization,api-key")
    reload_trace_redaction_config()

    payload = {
        "password": "secret",
        "nested": [
            {"authorization": "Bearer abc"},
            {"ok": "value"},
            ({"api-key": "xyz"},),
        ],
    }

    assert redact_sensitive_fields(payload) == {
        "password": "***",
        "nested": [
            {"authorization": "***"},
            {"ok": "value"},
            ({"api-key": "***"},),
        ],
    }


def test_is_output_capture_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", "llm.proxy,tool.invoke")
    reload_trace_redaction_config()

    assert is_output_capture_enabled("llm.proxy") is True
    assert is_output_capture_enabled("prompt.render") is False


def test_safe_serialize_supports_model_dump_and_valid_truncation(monkeypatch):
    monkeypatch.setenv("OTEL_MAX_TRACE_PAYLOAD_SIZE", "256")
    reload_trace_redaction_config()

    rendered = safe_serialize(SampleModel(password="secret", nested={"value": "x" * 400}), max_size=120)
    parsed = json.loads(rendered)

    assert parsed["_truncated"] is True
    assert parsed["_original_size"] > 120
    assert isinstance(parsed["_preview"], str)


def test_safe_serialize_returns_json_for_small_payload(monkeypatch):
    monkeypatch.setenv("OTEL_MAX_TRACE_PAYLOAD_SIZE", "512")
    reload_trace_redaction_config()

    rendered = safe_serialize({"ok": True, "value": "small"})

    assert json.loads(rendered) == {"ok": True, "value": "small"}
