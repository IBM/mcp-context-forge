# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_meta_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for mcpgateway.utils.meta_protocol — per-request _meta protocol helpers.
"""

# First-Party
from mcpgateway.utils.meta_protocol import (
    CAPABILITY_NOT_SUPPORTED,
    build_client_meta,
    check_capability,
    extract_protocol_meta,
    has_modern_meta_attempt,
    is_legacy_upstream,
    is_modern_meta,
    is_modern_protocol_version,
    stamp_server_info_meta,
    strip_modern_meta_for_legacy_upstream,
    synthesise_meta_for_modern_upstream,
)

_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


class TestIsModernProtocolVersion:
    """Tests for is_modern_protocol_version()."""

    def test_returns_true_for_2026_era(self):
        """A 2026-07-28 version string is modern."""
        assert is_modern_protocol_version("2026-07-28") is True

    def test_returns_false_for_handshake_era_versions(self):
        """Handshake-era versions are not modern."""
        assert is_modern_protocol_version("2025-11-25") is False
        assert is_modern_protocol_version("2024-11-05") is False

    def test_returns_false_for_none(self):
        """None is not modern."""
        assert is_modern_protocol_version(None) is False

    def test_returns_false_for_empty_string(self):
        """An empty string is not modern."""
        assert is_modern_protocol_version("") is False


class TestIsModernMeta:
    """Tests for is_modern_meta()."""

    def test_returns_true_when_both_mandatory_keys_present(self):
        """A meta dict with both mandatory keys is modern."""
        assert is_modern_meta(_MODERN_META) is True

    def test_returns_false_when_only_protocol_version_present(self):
        """A meta dict with only protocolVersion is not fully modern."""
        assert is_modern_meta({"io.modelcontextprotocol/protocolVersion": "2026-07-28"}) is False

    def test_returns_false_when_only_client_capabilities_present(self):
        """A meta dict with only clientCapabilities is not fully modern."""
        assert is_modern_meta({"io.modelcontextprotocol/clientCapabilities": {}}) is False

    def test_returns_false_when_key_absent(self):
        """A meta dict without namespaced keys is not modern."""
        assert is_modern_meta({"progressToken": 1}) is False

    def test_returns_false_for_none(self):
        """None is not modern."""
        assert is_modern_meta(None) is False

    def test_returns_false_for_empty_dict(self):
        """An empty dict is not modern."""
        assert is_modern_meta({}) is False

    def test_returns_false_for_non_dict(self):
        """A non-dict value is not modern."""
        assert is_modern_meta("string") is False  # type: ignore[arg-type]


class TestHasModernMetaAttempt:
    """Tests for has_modern_meta_attempt()."""

    def test_returns_true_when_protocol_version_only(self):
        """A meta dict with only protocolVersion signals a modern attempt."""
        assert has_modern_meta_attempt({"io.modelcontextprotocol/protocolVersion": "2026-07-28"}) is True

    def test_returns_true_when_capabilities_only(self):
        """A meta dict with only clientCapabilities signals a modern attempt."""
        assert has_modern_meta_attempt({"io.modelcontextprotocol/clientCapabilities": {}}) is True

    def test_returns_true_when_both_keys_present(self):
        """A fully modern meta dict signals a modern attempt."""
        assert has_modern_meta_attempt(_MODERN_META) is True

    def test_returns_false_for_legacy_meta(self):
        """A meta dict with no namespaced keys is not a modern attempt."""
        assert has_modern_meta_attempt({"progressToken": 1}) is False

    def test_returns_false_for_none(self):
        """None is not a modern attempt."""
        assert has_modern_meta_attempt(None) is False

    def test_returns_false_for_empty_dict(self):
        """An empty dict is not a modern attempt."""
        assert has_modern_meta_attempt({}) is False


class TestExtractProtocolMeta:
    """Tests for extract_protocol_meta()."""

    def test_extracts_version_and_caps(self):
        """Both values are extracted when present."""
        meta = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
        }
        pv, caps = extract_protocol_meta(meta)
        assert pv == "2026-07-28"
        assert caps == {"elicitation": {}}

    def test_returns_none_none_for_none(self):
        """None input returns (None, None)."""
        assert extract_protocol_meta(None) == (None, None)

    def test_returns_none_when_keys_absent(self):
        """Returns (None, None) when neither key is present."""
        pv, caps = extract_protocol_meta({"progressToken": 1})
        assert pv is None
        assert caps is None

    def test_ignores_non_string_version(self):
        """A non-string version value returns None."""
        meta = {
            "io.modelcontextprotocol/protocolVersion": 12345,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        pv, caps = extract_protocol_meta(meta)
        assert pv is None
        assert caps == {}

    def test_ignores_non_dict_capabilities(self):
        """A non-dict capabilities value returns None."""
        meta = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": "bad",
        }
        pv, caps = extract_protocol_meta(meta)
        assert pv == "2026-07-28"
        assert caps is None


class TestCheckCapability:
    """Tests for check_capability()."""

    def test_present_capability_returns_true(self):
        """A present capability key returns True."""
        assert check_capability({"elicitation": {}}, "elicitation") is True

    def test_absent_capability_returns_false(self):
        """A missing capability key returns False."""
        assert check_capability({}, "elicitation") is False

    def test_none_capabilities_returns_false(self):
        """None capabilities returns False."""
        assert check_capability(None, "elicitation") is False

    def test_absent_key_with_none_caps_returns_false(self):
        """None capabilities returns False."""
        assert check_capability(None, "sampling") is False

    def test_key_present_with_none_value_returns_true(self):
        """Key presence signals capability even when value is None (per MCP spec)."""
        assert check_capability({"elicitation": None}, "elicitation") is True

    def test_truthy_value_returns_true(self):
        """Any truthy value returns True."""
        assert check_capability({"sampling": {"maxTokens": 100}}, "sampling") is True


class TestStampServerInfoMeta:
    """Tests for stamp_server_info_meta()."""

    def test_injects_server_info_key(self):
        """serverInfo is injected into result._meta."""
        result = {"tools": []}
        out = stamp_server_info_meta(result, "ContextForge", "1.0.11")
        assert out["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "ContextForge"
        assert out["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == "1.0.11"

    def test_returns_same_dict(self):
        """The same dict object is returned."""
        result = {}
        out = stamp_server_info_meta(result, "CF", "1.0.0")
        assert out is result

    def test_preserves_existing_meta_keys(self):
        """Existing _meta keys are preserved."""
        result = {"_meta": {"progressToken": 42}}
        stamp_server_info_meta(result, "CF", "1.0.0")
        assert result["_meta"]["progressToken"] == 42
        assert "io.modelcontextprotocol/serverInfo" in result["_meta"]

    def test_non_dict_result_is_unchanged(self):
        """A non-dict result is returned unchanged."""
        result = ["item"]  # type: ignore[assignment]
        out = stamp_server_info_meta(result, "CF", "1.0.0")
        assert out is result
        assert "_meta" not in out

    def test_non_dict_existing_meta_is_replaced_not_crash(self):
        """A non-dict _meta value (e.g. a string) is replaced rather than causing a crash."""
        result = {"_meta": "unexpected_string"}
        out = stamp_server_info_meta(result, "CF", "1.0.0")
        assert isinstance(out["_meta"], dict)
        assert "io.modelcontextprotocol/serverInfo" in out["_meta"]

    def test_list_existing_meta_is_replaced_not_crash(self):
        """A list _meta value is replaced rather than causing a crash."""
        result = {"_meta": ["bad", "value"]}
        out = stamp_server_info_meta(result, "CF", "1.0.0")
        assert isinstance(out["_meta"], dict)
        assert "io.modelcontextprotocol/serverInfo" in out["_meta"]


class TestBuildClientMeta:
    """Tests for build_client_meta()."""

    def test_contains_mandatory_keys(self):
        """The returned dict contains all three mandatory keys."""
        m = build_client_meta("2026-07-28", "ContextForge", "1.0.11")
        assert m["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert m["io.modelcontextprotocol/clientInfo"] == {"name": "ContextForge", "version": "1.0.11"}
        assert m["io.modelcontextprotocol/clientCapabilities"] == {}

    def test_custom_capabilities(self):
        """Custom capabilities are embedded correctly."""
        m = build_client_meta("2026-07-28", "CF", "1.0.0", {"elicitation": {}})
        assert m["io.modelcontextprotocol/clientCapabilities"] == {"elicitation": {}}

    def test_none_capabilities_defaults_to_empty(self):
        """None capabilities defaults to an empty dict."""
        m = build_client_meta("2026-07-28", "CF", "1.0.0", None)
        assert m["io.modelcontextprotocol/clientCapabilities"] == {}


class TestSynthesiseMetaForModernUpstream:
    """Tests for synthesise_meta_for_modern_upstream()."""

    def test_adds_protocol_keys_when_absent(self):
        """Protocol keys are added when the inbound meta has none."""
        out = synthesise_meta_for_modern_upstream({}, {"sampling": {}}, "2026-07-28", "CF", "1.0.0")
        assert out["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert "io.modelcontextprotocol/clientCapabilities" in out
        assert "io.modelcontextprotocol/clientInfo" in out

    def test_preserves_existing_non_protocol_keys(self):
        """Non-protocol keys (e.g. progressToken) are preserved."""
        out = synthesise_meta_for_modern_upstream({"progressToken": 7}, None, "2026-07-28", "CF", "1.0.0")
        assert out["progressToken"] == 7
        assert out["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"

    def test_does_not_overwrite_existing_protocol_keys(self):
        """Existing protocol keys in inbound meta are not overwritten."""
        inbound = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
            "io.modelcontextprotocol/clientInfo": {"name": "my-client", "version": "2.0"},
        }
        out = synthesise_meta_for_modern_upstream(inbound, None, "2026-07-28", "CF", "1.0.0")
        assert out["io.modelcontextprotocol/clientInfo"]["name"] == "my-client"
        assert out["io.modelcontextprotocol/clientCapabilities"] == {"elicitation": {}}

    def test_none_existing_meta(self):
        """None existing meta is treated as an empty dict."""
        out = synthesise_meta_for_modern_upstream(None, None, "2026-07-28", "CF", "1.0.0")
        assert "io.modelcontextprotocol/protocolVersion" in out

    def test_uses_session_capabilities_when_provided(self):
        """Session capabilities are embedded when inbound caps are absent."""
        out = synthesise_meta_for_modern_upstream({}, {"sampling": {}}, "2026-07-28", "CF", "1.0.0")
        assert out["io.modelcontextprotocol/clientCapabilities"] == {"sampling": {}}


class TestStripModernMetaForLegacyUpstream:
    """Tests for strip_modern_meta_for_legacy_upstream()."""

    def test_strips_all_namespaced_keys(self):
        """All four namespaced protocol keys are removed."""
        meta = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1.0"},
            "io.modelcontextprotocol/serverInfo": {"name": "srv", "version": "1.0"},
        }
        out = strip_modern_meta_for_legacy_upstream(meta)
        assert out is None

    def test_preserves_non_protocol_keys(self):
        """progressToken and tracing keys survive stripping."""
        meta = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
            "progressToken": 42,
            "traceparent": "00-abc-def-01",
        }
        out = strip_modern_meta_for_legacy_upstream(meta)
        assert out == {"progressToken": 42, "traceparent": "00-abc-def-01"}

    def test_returns_none_for_none_input(self):
        """None input returns None."""
        assert strip_modern_meta_for_legacy_upstream(None) is None

    def test_returns_none_for_empty_dict(self):
        """An empty dict returns None."""
        assert strip_modern_meta_for_legacy_upstream({}) is None

    def test_returns_none_when_only_protocol_keys(self):
        """A dict with only protocol keys returns None after stripping."""
        assert strip_modern_meta_for_legacy_upstream({"io.modelcontextprotocol/protocolVersion": "2026-07-28"}) is None

    def test_does_not_mutate_original(self):
        """The original dict is not modified."""
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "progressToken": 1}
        original = dict(meta)
        strip_modern_meta_for_legacy_upstream(meta)
        assert meta == original


class TestIsLegacyUpstream:
    """Tests for is_legacy_upstream()."""

    def test_modern_upstream_has_server_info_key(self):
        """A capabilities dict with serverInfo signals a modern upstream."""
        caps = {"io.modelcontextprotocol/serverInfo": {"name": "srv", "version": "1.0"}}
        assert is_legacy_upstream(caps) is False

    def test_legacy_upstream_has_no_server_info_key(self):
        """A capabilities dict without serverInfo signals a legacy upstream."""
        assert is_legacy_upstream({"tools": {}, "resources": {}}) is True

    def test_none_capabilities_is_legacy(self):
        """None capabilities signals a legacy upstream (fail-safe default)."""
        assert is_legacy_upstream(None) is True

    def test_empty_dict_is_legacy(self):
        """An empty capabilities dict signals a legacy upstream."""
        assert is_legacy_upstream({}) is True

    def test_non_dict_is_legacy(self):
        """A non-dict capabilities value signals a legacy upstream."""
        assert is_legacy_upstream("bad") is True  # type: ignore[arg-type]


class TestCapabilityNotSupportedConstant:
    """Validate the -32021 constant value."""

    def test_value(self):
        """CAPABILITY_NOT_SUPPORTED must be -32021."""
        assert CAPABILITY_NOT_SUPPORTED == -32021
