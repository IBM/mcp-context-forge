# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sigv4_redaction_lists.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Every redaction list carries every name in ``SIGV4_REDACT_NAMES``.
"""

# Standard
from pathlib import Path

# First-Party
from mcpgateway.config import Settings
from mcpgateway.middleware.request_logging_middleware import SENSITIVE_KEYS
from mcpgateway.utils.sigv4 import SIGV4_REDACT_NAMES, SIGV4_SENSITIVE_KEYS
from mcpgateway.utils.trace_redaction import _DEFAULT_REDACT_FIELDS
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS

REPO_ROOT = Path(__file__).resolve().parents[4]
OTEL_DEFAULT = Settings.model_fields["otel_redact_fields"].default


def test_constant_holds_sensitive_keys_and_wire_names():
    assert set(SIGV4_REDACT_NAMES) == set(SIGV4_SENSITIVE_KEYS) | {"x-amz-security-token", "x-amz-signature", "x-amz-credential"}


def test_siem_default_contains_every_name():
    assert set(SIGV4_REDACT_NAMES) <= set(Settings.model_fields["siem_export_redact_fields"].default_factory())


def test_otel_default_contains_every_name():
    assert set(SIGV4_REDACT_NAMES) <= set(OTEL_DEFAULT.split(","))


def test_trace_redaction_default_contains_every_name():
    assert set(SIGV4_REDACT_NAMES) <= set(_DEFAULT_REDACT_FIELDS.split(","))


def test_url_sensitive_params_contain_every_name():
    assert set(SIGV4_REDACT_NAMES) <= STATIC_SENSITIVE_PARAMS


def test_request_logging_sensitive_keys_contain_every_name_with_underscores():
    assert {name.replace("-", "_") for name in SIGV4_REDACT_NAMES} <= SENSITIVE_KEYS


def test_env_example_otel_list_matches_config_default():
    line = next(line for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines() if line.startswith("# OTEL_REDACT_FIELDS="))
    assert set(line.split("=", 1)[1].split(",")) == set(OTEL_DEFAULT.split(","))


def test_langfuse_doc_otel_list_matches_config_default():
    text = (REPO_ROOT / "docs" / "docs" / "manage" / "observability" / "langfuse.md").read_text(encoding="utf-8")
    line = next(line.strip() for line in text.splitlines() if line.strip().startswith("OTEL_REDACT_FIELDS="))
    assert set(line.split("=", 1)[1].split(",")) == set(OTEL_DEFAULT.split(","))
