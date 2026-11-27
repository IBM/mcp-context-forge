# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_sigv4_redaction_lists.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Every redaction list carries every name in ``SIGV4_REDACT_NAMES``.
"""

# Standard
import json
from pathlib import Path
import re

# Third-Party
import pytest

# First-Party
from mcpgateway.config import Settings
from mcpgateway.middleware.request_logging_middleware import mask_sensitive_data, SENSITIVE_KEYS
from mcpgateway.utils import sigv4
from mcpgateway.utils.sigv4_names import SIGV4_REDACT_NAMES, SIGV4_SENSITIVE_KEYS, SIGV4_WIRE_NAMES
from mcpgateway.utils.trace_redaction import _DEFAULT_REDACT_FIELDS
from mcpgateway.utils.url_auth import STATIC_SENSITIVE_PARAMS

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
OTEL_DEFAULT = Settings.model_fields["otel_redact_fields"].default
assert isinstance(OTEL_DEFAULT, str)


def _siem_default():
    factory = Settings.model_fields["siem_export_redact_fields"].default_factory
    assert factory is not None
    return factory()


def _assert_covers(names, container, label):
    missing = sorted(set(names) - set(container))
    assert not missing, f"{label} lacks SigV4 names: {missing}"


def _only_match(lines, prefix, label):
    matches = [line for line in lines if line.startswith(prefix)]
    assert len(matches) == 1, f"{label}: expected exactly one {prefix!r} line, found {len(matches)}"
    return matches[0].split("=", 1)[1]


def test_constant_holds_sensitive_keys_and_wire_names():
    assert set(SIGV4_REDACT_NAMES) == set(SIGV4_SENSITIVE_KEYS) | set(SIGV4_WIRE_NAMES)
    assert set(SIGV4_REDACT_NAMES) == {"secret_access_key", "session_token", "x-amz-security-token", "x-amz-signature", "x-amz-credential"}


def test_constant_has_no_duplicates_and_is_lowercase():
    assert len(SIGV4_REDACT_NAMES) == len(set(SIGV4_REDACT_NAMES))
    assert all(name == name.lower() for name in SIGV4_REDACT_NAMES)


def test_sigv4_module_reexports_the_names():
    assert sigv4.SIGV4_REDACT_NAMES is SIGV4_REDACT_NAMES
    assert sigv4.SIGV4_SENSITIVE_KEYS is SIGV4_SENSITIVE_KEYS


def test_siem_default_contains_every_name():
    _assert_covers(SIGV4_REDACT_NAMES, _siem_default(), "siem_export_redact_fields")


def test_otel_default_contains_every_name():
    _assert_covers(SIGV4_REDACT_NAMES, OTEL_DEFAULT.split(","), "otel_redact_fields")


def test_trace_redaction_default_contains_every_name():
    _assert_covers(SIGV4_REDACT_NAMES, _DEFAULT_REDACT_FIELDS.split(","), "trace_redaction defaults")


def test_otel_and_trace_redaction_defaults_match():
    assert set(OTEL_DEFAULT.split(",")) == set(_DEFAULT_REDACT_FIELDS.split(","))


def test_url_sensitive_params_contain_the_wire_names():
    _assert_covers(SIGV4_WIRE_NAMES, STATIC_SENSITIVE_PARAMS, "STATIC_SENSITIVE_PARAMS")


def test_request_logging_sensitive_keys_contain_every_name_with_underscores():
    _assert_covers(["secret_access_key", "session_token", "x_amz_security_token", "x_amz_signature", "x_amz_credential"], SENSITIVE_KEYS, "SENSITIVE_KEYS")


@pytest.mark.parametrize("key", ["secret_access_key", "session_token", "x-amz-security-token", "x-amz-signature", "x-amz-credential"])
def test_request_logging_masks_every_name(key):
    masked = mask_sensitive_data({key: "leaked-value"})
    assert "leaked-value" not in json.dumps(masked)


def test_env_example_otel_list_matches_config_default():
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    value = _only_match(lines, "# OTEL_REDACT_FIELDS=", ".env.example")
    assert set(value.split(",")) == set(OTEL_DEFAULT.split(","))


def test_env_example_siem_list_matches_config_default():
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    value = _only_match(lines, "# SIEM_EXPORT_REDACT_FIELDS=", ".env.example")
    assert set(json.loads(value)) == set(_siem_default())


def test_langfuse_doc_otel_list_matches_config_default():
    text = (REPO_ROOT / "docs" / "docs" / "manage" / "observability" / "langfuse.md").read_text(encoding="utf-8")
    matches = re.findall(r"^\s+OTEL_REDACT_FIELDS=(\S+)$", text, flags=re.MULTILINE)
    assert len(matches) == 1, f"langfuse.md: expected exactly one OTEL_REDACT_FIELDS example, found {len(matches)}"
    assert set(matches[0].split(",")) == set(OTEL_DEFAULT.split(","))


def test_helm_values_otel_list_matches_config_default():
    text = (REPO_ROOT / "charts" / "mcp-stack" / "values.yaml").read_text(encoding="utf-8")
    matches = re.findall(r'^\s*#\s*OTEL_REDACT_FIELDS:\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert len(matches) == 1, f"values.yaml: expected exactly one OTEL_REDACT_FIELDS example, found {len(matches)}"
    assert set(matches[0].split(",")) == set(OTEL_DEFAULT.split(","))
