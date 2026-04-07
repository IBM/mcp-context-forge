# -*- coding: utf-8 -*-
"""Tests for the focused validation sidecar Locust scenario."""

# Standard
import json

# First-Party
from tests.loadtest.validation_sidecar_payloads import (
    build_rejected_initialize_payload,
    build_safe_initialize_payload,
)


def test_safe_initialize_payload_is_large_and_protocol_shaped() -> None:
    """The accepted payload should stay protocol-valid while being large enough to stress validation."""
    payload = build_safe_initialize_payload()

    assert payload["protocolVersion"] == "2024-11-05"
    assert payload["clientInfo"]["name"].startswith("validation-loadtest-")
    assert len(json.dumps(payload)) > 4_000
    assert "<script>" not in json.dumps(payload)


def test_rejected_initialize_payload_contains_dangerous_string() -> None:
    """The rejected payload should carry the same protocol shape with a validation-triggering string."""
    payload = build_rejected_initialize_payload()

    assert payload["protocolVersion"] == "2024-11-05"
    assert payload["clientInfo"]["name"] == "<script>alert(1)</script>"
    assert len(json.dumps(payload)) > 4_000
