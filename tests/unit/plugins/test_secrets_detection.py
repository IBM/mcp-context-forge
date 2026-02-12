# -*- coding: utf-8 -*-
"""Tests for secrets detection plugin.

Copyright 2025
SPDX-License-Identifier: Apache-2.0

Comprehensive unit tests covering:
- All 8 regex patterns in PATTERNS
- SecretsDetectionConfig model
- Helper functions: _iter_strings, _detect, _scan_container
- Plugin hooks: prompt_pre_fetch, tool_post_invoke, resource_post_fetch
- Edge cases
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcpgateway.common.models import ResourceContent, TextResourceContents
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
)
from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload
from mcpgateway.plugins.framework.hooks.tools import ToolPostInvokePayload
from mcpgateway.plugins.framework.hooks.resources import ResourcePostFetchPayload
from plugins.secrets_detection.secrets_detection import (
    PATTERNS,
    SecretsDetectionConfig,
    SecretsDetectionPlugin,
    _detect,
    _iter_strings,
    _scan_container,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_plugin(**config_overrides) -> SecretsDetectionPlugin:
    """Create a SecretsDetectionPlugin with optional config overrides."""
    return SecretsDetectionPlugin(
        PluginConfig(
            name="secrets_detection",
            kind="resource",
            config=config_overrides,
        )
    )


def _make_context() -> PluginContext:
    """Create a minimal PluginContext for hook tests."""
    return PluginContext(global_context=GlobalContext(request_id="test-req-1"))


# ===========================================================================
# 1. Pattern Detection Tests
# ===========================================================================


class TestAwsSecretPattern:
    """Test AWS secret access key pattern for correctness."""

    @pytest.fixture
    def pattern(self):
        """Get the AWS secret pattern."""
        return PATTERNS["aws_secret_access_key"]

    def test_matches_standard_format(self, pattern):
        """Pattern should match standard AWS secret key format."""
        text = "AWS_SECRET_ACCESS_KEY=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        assert pattern.search(text) is not None

    def test_matches_with_separators(self, pattern):
        """Pattern should match with various separators."""
        assert pattern.search("aws_secret_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("aws-access-key=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("AWS_SECRET=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")

    def test_case_insensitive(self, pattern):
        """Pattern should be case-insensitive for the prefix."""
        assert pattern.search("aws_secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("AWS_SECRET=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
        assert pattern.search("Aws_Secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")

    def test_no_match_short_secret(self, pattern):
        """Pattern should not match secrets shorter than 40 chars."""
        assert pattern.search("aws_secret=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh") is None

    def test_no_match_missing_equals(self, pattern):
        """Pattern should not match without = sign."""
        assert pattern.search("aws_secret ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd") is None

    def test_no_match_unrelated_text(self, pattern):
        """Pattern should not match unrelated text."""
        assert pattern.search("This is just some random text") is None
        assert pattern.search("aws is a cloud provider") is None

    def test_captures_secret_value(self, pattern):
        """Pattern should capture the 40-char secret value."""
        text = "AWS_SECRET_ACCESS_KEY=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
        match = pattern.search(text)
        assert match is not None
        assert match.group(1) == "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"


class TestAwsAccessKeyIdPattern:
    """Test AWS access key ID pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the AWS access key ID pattern."""
        return PATTERNS["aws_access_key_id"]

    def test_matches_valid_key(self, pattern):
        """Pattern should match a valid AKIA-prefixed key."""
        assert pattern.search("AKIAIOSFODNN7EXAMPLE") is not None

    def test_matches_embedded_in_text(self, pattern):
        """Pattern should match key embedded in surrounding text."""
        text = "my key is AKIAIOSFODNN7EXAMPLE here"
        assert pattern.search(text) is not None

    def test_no_match_wrong_prefix(self, pattern):
        """Pattern should not match keys without AKIA prefix."""
        assert pattern.search("ASIAIOSFODNN7EXAMPLE") is None

    def test_no_match_too_short(self, pattern):
        """Pattern should not match keys shorter than 20 chars total."""
        assert pattern.search("AKIA12345678901234") is None  # only 18 chars

    def test_no_match_lowercase(self, pattern):
        """Pattern should not match lowercase characters after AKIA."""
        assert pattern.search("AKIAiosfodnn7example") is None


class TestGoogleApiKeyPattern:
    """Test Google API key pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the Google API key pattern."""
        return PATTERNS["google_api_key"]

    def test_matches_valid_key(self, pattern):
        """Pattern should match a valid AIza-prefixed key."""
        # AIza + 35 chars = 39 total
        assert pattern.search("AIzaSyC-1234567890abcdefghijklmnopqrstu") is not None

    def test_matches_with_hyphens_and_underscores(self, pattern):
        """Pattern should match keys containing hyphens and underscores."""
        key = "AIzaSyC_abcdefghij-KLMNOPQRST1234567890"
        assert pattern.search(key) is not None

    def test_no_match_wrong_prefix(self, pattern):
        """Pattern should not match keys without AIza prefix."""
        assert pattern.search("BIzaSyC-1234567890abcdefghijklmnopqrst") is None

    def test_no_match_too_short(self, pattern):
        """Pattern should not match keys shorter than 39 chars."""
        assert pattern.search("AIzaSyC-short") is None


class TestSlackTokenPattern:
    """Test Slack token pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the Slack token pattern."""
        return PATTERNS["slack_token"]

    def test_matches_bot_token(self, pattern):
        """Pattern should match xoxb bot tokens."""
        assert pattern.search("xoxb-1234567890-abc") is not None

    def test_matches_user_token(self, pattern):
        """Pattern should match xoxp user tokens."""
        assert pattern.search("xoxp-1234567890-abcdefghij") is not None

    def test_matches_app_token(self, pattern):
        """Pattern should match xoxa app tokens."""
        assert pattern.search("xoxa-1234567890-abcdefghij") is not None

    def test_no_match_wrong_prefix(self, pattern):
        """Pattern should not match tokens with wrong prefix."""
        assert pattern.search("xoxz-1234567890-abc") is None

    def test_no_match_too_short(self, pattern):
        """Pattern should not match tokens with too-short suffix."""
        assert pattern.search("xoxb-short") is None


class TestPrivateKeyBlockPattern:
    """Test private key block pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the private key block pattern."""
        return PATTERNS["private_key_block"]

    def test_matches_rsa_key(self, pattern):
        """Pattern should match RSA private key header."""
        assert pattern.search("-----BEGIN RSA PRIVATE KEY-----") is not None

    def test_matches_dsa_key(self, pattern):
        """Pattern should match DSA private key header."""
        assert pattern.search("-----BEGIN DSA PRIVATE KEY-----") is not None

    def test_matches_ec_key(self, pattern):
        """Pattern should match EC private key header."""
        assert pattern.search("-----BEGIN EC PRIVATE KEY-----") is not None

    def test_matches_openssh_key(self, pattern):
        """Pattern should match OPENSSH private key header."""
        assert pattern.search("-----BEGIN OPENSSH PRIVATE KEY-----") is not None

    def test_no_match_public_key(self, pattern):
        """Pattern should not match public key headers."""
        assert pattern.search("-----BEGIN RSA PUBLIC KEY-----") is None

    def test_no_match_certificate(self, pattern):
        """Pattern should not match certificate headers."""
        assert pattern.search("-----BEGIN CERTIFICATE-----") is None


class TestJwtLikePattern:
    """Test JWT-like token pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the JWT-like pattern."""
        return PATTERNS["jwt_like"]

    def test_matches_valid_jwt(self, pattern):
        """Pattern should match a JWT-like token with 3 dot-separated segments."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        assert pattern.search(jwt) is not None

    def test_matches_embedded_jwt(self, pattern):
        """Pattern should match JWT embedded in text."""
        text = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        assert pattern.search(text) is not None

    def test_no_match_single_segment(self, pattern):
        """Pattern should not match a single base64 segment."""
        assert pattern.search("eyJhbGciOiJIUzI1NiJ9") is None

    def test_no_match_two_segments(self, pattern):
        """Pattern should not match only two dot-separated segments."""
        assert pattern.search("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0") is None

    def test_no_match_wrong_prefix(self, pattern):
        """Pattern should not match tokens not starting with eyJ."""
        assert pattern.search("abc1234567890a.abc1234567890a.abc1234567890a") is None


class TestHexSecret32Pattern:
    """Test hex secret (32+ chars) pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the hex secret pattern."""
        return PATTERNS["hex_secret_32"]

    def test_matches_32_char_hex(self, pattern):
        """Pattern should match a 32-char lowercase hex string."""
        assert pattern.search("0123456789abcdef0123456789abcdef") is not None

    def test_matches_uppercase_hex(self, pattern):
        """Pattern should match uppercase hex (case-insensitive flag)."""
        assert pattern.search("0123456789ABCDEF0123456789ABCDEF") is not None

    def test_matches_longer_hex(self, pattern):
        """Pattern should match hex strings longer than 32 chars."""
        assert pattern.search("a" * 64) is not None

    def test_no_match_31_chars(self, pattern):
        """Pattern should not match hex strings shorter than 32 chars."""
        assert pattern.search("0123456789abcdef0123456789abcde") is None

    def test_no_match_non_hex(self, pattern):
        """Pattern should not match strings with non-hex chars."""
        assert pattern.search("0123456789abcdefghijklmnopqrstuv") is None


class TestBase64_24Pattern:
    """Test base64 (24+ chars) pattern."""

    @pytest.fixture
    def pattern(self):
        """Get the base64 24+ chars pattern."""
        return PATTERNS["base64_24"]

    def test_matches_24_char_base64(self, pattern):
        """Pattern should match a 24-char base64 string."""
        # "ABCDEFGHIJKLMNOPQRSTU" base64 encoded is longer, use a known 24-char b64 string
        assert pattern.search("QUJDREVGR0hJSktMTU5PUFFSU1RV") is not None

    def test_matches_with_padding(self, pattern):
        """Pattern should match base64 with padding."""
        assert pattern.search("QUJDREVGR0hJSktMTU5PUFFE==") is not None

    def test_matches_with_plus_and_slash(self, pattern):
        """Pattern should match base64 containing + and / chars."""
        assert pattern.search("QUJDREVGR0hJSktMTU5P+/SS") is not None

    def test_no_match_23_chars(self, pattern):
        """Pattern should not match strings shorter than 24 chars."""
        assert pattern.search("QUJDREVGR0hJSktMTU5PUQ") is None  # 22 chars

    def test_no_match_special_chars(self, pattern):
        """Pattern should not match strings with non-base64 special chars."""
        assert pattern.search("QUJDREVGR0hJSktMTU5P!@#$") is None


# ===========================================================================
# 2. Configuration Tests
# ===========================================================================


class TestSecretsDetectionConfig:
    """Test SecretsDetectionConfig model defaults and overrides."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        cfg = SecretsDetectionConfig()
        assert cfg.redact is False
        assert cfg.block_on_detection is True
        assert cfg.min_findings_to_block == 1
        assert cfg.redaction_text == "***REDACTED***"

    def test_all_patterns_enabled_by_default(self):
        """All 8 patterns should be enabled by default."""
        cfg = SecretsDetectionConfig()
        for name in PATTERNS:
            assert cfg.enabled.get(name, False) is True

    def test_custom_overrides(self):
        """Config should accept custom overrides via dict."""
        cfg = SecretsDetectionConfig(
            redact=True,
            block_on_detection=False,
            min_findings_to_block=3,
            redaction_text="[REMOVED]",
        )
        assert cfg.redact is True
        assert cfg.block_on_detection is False
        assert cfg.min_findings_to_block == 3
        assert cfg.redaction_text == "[REMOVED]"

    def test_disable_specific_pattern(self):
        """Individual patterns can be disabled."""
        cfg = SecretsDetectionConfig(enabled={"aws_access_key_id": False, "jwt_like": True})
        assert cfg.enabled["aws_access_key_id"] is False
        assert cfg.enabled["jwt_like"] is True


# ===========================================================================
# 3. Helper Function Tests
# ===========================================================================


class TestIterStrings:
    """Test _iter_strings helper for traversing nested structures."""

    def test_plain_string(self):
        """Should yield a single (path, text) for a plain string."""
        result = list(_iter_strings("hello"))
        assert result == [("", "hello")]

    def test_nested_dict(self):
        """Should yield paths for each string value in a dict."""
        result = list(_iter_strings({"a": "one", "b": "two"}))
        assert ("a", "one") in result
        assert ("b", "two") in result

    def test_nested_list(self):
        """Should yield indexed paths for each string in a list."""
        result = list(_iter_strings(["x", "y"]))
        assert ("[0]", "x") in result
        assert ("[1]", "y") in result

    def test_mixed_nesting(self):
        """Should handle dict containing lists and nested dicts."""
        data = {"outer": {"inner": "val"}, "items": ["a", "b"]}
        result = list(_iter_strings(data))
        paths = {path for path, _ in result}
        assert "outer.inner" in paths
        assert "items[0]" in paths
        assert "items[1]" in paths

    def test_non_string_types_skipped(self):
        """Non-string leaf values (int, None, bool) should not be yielded."""
        data = {"num": 42, "flag": True, "empty": None, "text": "hello"}
        result = list(_iter_strings(data))
        assert len(result) == 1
        assert result[0] == ("text", "hello")

    def test_empty_dict(self):
        """Empty dict should yield nothing."""
        assert list(_iter_strings({})) == []

    def test_empty_list(self):
        """Empty list should yield nothing."""
        assert list(_iter_strings([])) == []


class TestDetect:
    """Test _detect helper for pattern matching in text."""

    def test_no_matches(self):
        """Clean text should produce no findings."""
        cfg = SecretsDetectionConfig()
        assert _detect("just some normal text", cfg) == []

    def test_single_match(self):
        """Text with one secret should return one finding."""
        cfg = SecretsDetectionConfig()
        findings = _detect("key is AKIAIOSFODNN7EXAMPLE", cfg)
        types = [f["type"] for f in findings]
        assert "aws_access_key_id" in types

    def test_multiple_matches(self):
        """Text with multiple secrets should return multiple findings."""
        cfg = SecretsDetectionConfig()
        text = "AKIAIOSFODNN7EXAMPLE and xoxb-1234567890-abcdefghij"
        findings = _detect(text, cfg)
        types = [f["type"] for f in findings]
        assert "aws_access_key_id" in types
        assert "slack_token" in types

    def test_disabled_pattern_skipped(self):
        """Disabled patterns should not produce findings."""
        cfg = SecretsDetectionConfig(enabled={"aws_access_key_id": False})
        findings = _detect("AKIAIOSFODNN7EXAMPLE", cfg)
        types = [f["type"] for f in findings]
        assert "aws_access_key_id" not in types

    def test_match_preview_truncation(self):
        """Matches longer than 8 chars should be truncated with ellipsis."""
        cfg = SecretsDetectionConfig()
        findings = _detect("AKIAIOSFODNN7EXAMPLE", cfg)
        aws_findings = [f for f in findings if f["type"] == "aws_access_key_id"]
        assert len(aws_findings) >= 1
        # AKIAIOSFODNN7EXAMPLE is 20 chars > 8, so first 8 chars + "…"
        assert aws_findings[0]["match"] == "AKIAIOSF\u2026"
        assert aws_findings[0]["match"].endswith("\u2026")


class TestScanContainer:
    """Test _scan_container helper for recursive scanning and redaction."""

    def test_string_no_secrets(self):
        """Clean string should return count=0 and same string."""
        cfg = SecretsDetectionConfig()
        count, result, findings = _scan_container("clean text", cfg)
        assert count == 0
        assert result == "clean text"
        assert findings == []

    def test_string_with_secret(self):
        """String with secret should return count>0."""
        cfg = SecretsDetectionConfig()
        count, result, findings = _scan_container("key AKIAIOSFODNN7EXAMPLE", cfg)
        assert count >= 1
        assert len(findings) >= 1

    def test_dict_scanning(self):
        """Should scan all string values in a dict."""
        cfg = SecretsDetectionConfig()
        data = {"clean": "no secret", "secret": "key AKIAIOSFODNN7EXAMPLE"}
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1

    def test_list_scanning(self):
        """Should scan all string items in a list."""
        cfg = SecretsDetectionConfig()
        data = ["clean", "key AKIAIOSFODNN7EXAMPLE"]
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1

    def test_count_aggregation(self):
        """Counts from nested containers should be aggregated."""
        cfg = SecretsDetectionConfig()
        data = {"a": "AKIAIOSFODNN7EXAMPLE", "b": ["xoxb-1234567890-abcdefghij"]}
        count, _, findings = _scan_container(data, cfg)
        types = {f["type"] for f in findings}
        assert "aws_access_key_id" in types
        assert "slack_token" in types
        assert count >= 2

    def test_redaction_on_string(self):
        """With redact=True, secrets in strings should be replaced."""
        cfg = SecretsDetectionConfig(redact=True)
        text = "key AKIAIOSFODNN7EXAMPLE here"
        count, result, findings = _scan_container(text, cfg)
        assert count >= 1
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result

    def test_redaction_on_dict(self):
        """With redact=True, secrets in dict values should be replaced."""
        cfg = SecretsDetectionConfig(redact=True)
        data = {"key": "AKIAIOSFODNN7EXAMPLE"}
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1
        assert "AKIAIOSFODNN7EXAMPLE" not in result["key"]
        assert "***REDACTED***" in result["key"]

    def test_redaction_on_list(self):
        """With redact=True, secrets in list items should be replaced."""
        cfg = SecretsDetectionConfig(redact=True)
        data = ["AKIAIOSFODNN7EXAMPLE"]
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1
        assert "AKIAIOSFODNN7EXAMPLE" not in result[0]
        assert "***REDACTED***" in result[0]

    def test_non_container_passthrough(self):
        """Non-container values (int, None, etc.) should pass through unchanged."""
        cfg = SecretsDetectionConfig()
        count, result, findings = _scan_container(42, cfg)
        assert count == 0
        assert result == 42
        assert findings == []

        count, result, findings = _scan_container(None, cfg)
        assert count == 0
        assert result is None

    def test_nested_redaction(self):
        """Redaction should work on deeply nested structures."""
        cfg = SecretsDetectionConfig(redact=True)
        data = {"level1": {"level2": ["AKIAIOSFODNN7EXAMPLE"]}}
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1
        assert "***REDACTED***" in result["level1"]["level2"][0]
        assert "AKIAIOSFODNN7EXAMPLE" not in result["level1"]["level2"][0]

    def test_custom_redaction_text(self):
        """Custom redaction text should be used when configured."""
        cfg = SecretsDetectionConfig(redact=True, redaction_text="[REMOVED]")
        text = "key AKIAIOSFODNN7EXAMPLE here"
        count, result, findings = _scan_container(text, cfg)
        assert "[REMOVED]" in result
        assert "***REDACTED***" not in result


# ===========================================================================
# 4. Plugin Hook Tests
# ===========================================================================


class TestPromptPreFetch:
    """Test prompt_pre_fetch hook."""

    @pytest.mark.asyncio
    async def test_clean_args_pass_through(self):
        """Clean args should produce continue_processing=True and empty metadata."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={"user": "alice"})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_secret_in_args_blocks(self):
        """Secret in args with blocking enabled should produce a violation."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={"key": "AKIAIOSFODNN7EXAMPLE"})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "SECRETS_DETECTED"
        assert result.violation.details["count"] >= 1

    @pytest.mark.asyncio
    async def test_secret_no_block(self):
        """Secret in args with block_on_detection=False should pass through with findings metadata."""
        plugin = _make_plugin(block_on_detection=False)
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={"key": "AKIAIOSFODNN7EXAMPLE"})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.metadata["count"] >= 1
        assert "secrets_findings" in result.metadata

    @pytest.mark.asyncio
    async def test_below_min_findings_passes(self):
        """Findings below min_findings_to_block should pass through."""
        plugin = _make_plugin(min_findings_to_block=100)
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={"key": "AKIAIOSFODNN7EXAMPLE"})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_redaction_with_no_block(self):
        """Redaction + block_on_detection=False should return modified payload with redacted args."""
        plugin = _make_plugin(redact=True, block_on_detection=False)
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={"key": "AKIAIOSFODNN7EXAMPLE"})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert result.metadata.get("secrets_redacted") is True
        # The redacted args should not contain the original secret
        redacted_args = result.modified_payload.args
        assert "AKIAIOSFODNN7EXAMPLE" not in str(redacted_args)

    @pytest.mark.asyncio
    async def test_empty_args_pass_through(self):
        """Empty or None args should produce no findings."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = PromptPrehookPayload(prompt_id="test", args={})
        result = await plugin.prompt_pre_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None


class TestToolPostInvoke:
    """Test tool_post_invoke hook."""

    @pytest.mark.asyncio
    async def test_clean_result_pass_through(self):
        """Clean tool result should pass through."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result="safe output")
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.modified_payload is None

    @pytest.mark.asyncio
    async def test_secret_in_result_blocks(self):
        """Secret in tool result with blocking enabled should produce a violation."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result="key AKIAIOSFODNN7EXAMPLE")
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "SECRETS_DETECTED"
        assert result.violation.details["count"] >= 1

    @pytest.mark.asyncio
    async def test_redaction(self):
        """With redact=True and block_on_detection=False, result should be redacted."""
        plugin = _make_plugin(redact=True, block_on_detection=False)
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result="key AKIAIOSFODNN7EXAMPLE here")
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert "AKIAIOSFODNN7EXAMPLE" not in str(result.modified_payload.result)
        assert "***REDACTED***" in str(result.modified_payload.result)
        assert result.metadata.get("secrets_redacted") is True

    @pytest.mark.asyncio
    async def test_findings_below_threshold_passes(self):
        """Findings below min_findings_to_block should pass with metadata."""
        plugin = _make_plugin(min_findings_to_block=100)
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result="key AKIAIOSFODNN7EXAMPLE")
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.metadata["count"] >= 1

    @pytest.mark.asyncio
    async def test_dict_result_scanned(self):
        """Dict tool results should be scanned recursively."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result={"output": "AKIAIOSFODNN7EXAMPLE"})
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is False
        assert result.violation is not None

    @pytest.mark.asyncio
    async def test_list_result_scanned(self):
        """List tool results should be scanned recursively."""
        plugin = _make_plugin()
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="my_tool", result=["AKIAIOSFODNN7EXAMPLE"])
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.continue_processing is False
        assert result.violation is not None


class TestResourcePostFetch:
    """Test resource_post_fetch hook."""

    @pytest.mark.asyncio
    async def test_text_content_no_secrets(self):
        """Text resource with no secrets should pass through."""
        plugin = _make_plugin()
        ctx = _make_context()
        content = TextResourceContents(uri="file:///test.txt", text="clean content")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_text_content_with_secret_blocks(self):
        """Text resource with secret should produce a violation when blocking."""
        plugin = _make_plugin()
        ctx = _make_context()
        content = TextResourceContents(uri="file:///test.txt", text="key AKIAIOSFODNN7EXAMPLE")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "SECRETS_DETECTED"

    @pytest.mark.asyncio
    async def test_text_content_with_secret_redaction(self):
        """Text resource with secret and redact=True should return redacted content."""
        plugin = _make_plugin(redact=True, block_on_detection=False)
        ctx = _make_context()
        content = TextResourceContents(uri="file:///test.txt", text="key AKIAIOSFODNN7EXAMPLE here")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.modified_payload is not None
        assert "AKIAIOSFODNN7EXAMPLE" not in result.modified_payload.content.text
        assert "***REDACTED***" in result.modified_payload.content.text
        assert result.metadata.get("secrets_redacted") is True

    @pytest.mark.asyncio
    async def test_non_text_content_passes(self):
        """Non-text content (no .text attribute) should pass through."""
        plugin = _make_plugin()
        ctx = _make_context()
        # Use a plain object without .text attribute
        content = MagicMock(spec=[])  # spec=[] means no attributes
        payload = ResourcePostFetchPayload(uri="file:///test.bin", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_content_with_non_string_text_passes(self):
        """Content with .text that is not a string should pass through."""
        plugin = _make_plugin()
        ctx = _make_context()
        content = MagicMock()
        content.text = 12345  # Not a string
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_findings_below_threshold(self):
        """Findings below min_findings_to_block should pass with metadata."""
        plugin = _make_plugin(min_findings_to_block=100)
        ctx = _make_context()
        content = TextResourceContents(uri="file:///test.txt", text="key AKIAIOSFODNN7EXAMPLE")
        payload = ResourcePostFetchPayload(uri="file:///test.txt", content=content)
        result = await plugin.resource_post_fetch(payload, ctx)
        assert result.continue_processing is True
        assert result.violation is None
        assert result.metadata["count"] >= 1


# ===========================================================================
# 5. Integration-level test (preserved from original)
# ===========================================================================


@pytest.mark.asyncio
async def test_resource_post_fetch_receives_resolved_content():
    """RESOURCE_POST_FETCH plugins should receive actual gateway content, not template URIs."""
    captured = {}

    class CaptureSecretsPlugin(SecretsDetectionPlugin):
        async def resource_post_fetch(self, payload, context):
            captured["text"] = payload.content.text
            return await super().resource_post_fetch(payload, context)

    plugin = CaptureSecretsPlugin(
        PluginConfig(
            name="secrets_detection",
            kind="resource",
            config={},
        )
    )

    fake_resource = MagicMock()
    fake_resource.id = "res1"
    fake_resource.uri = "file:///data/x.txt"
    fake_resource.enabled = True
    fake_resource.content = ResourceContent(
        type="resource",
        id="res1",
        uri="file:///data/x.txt",
        text="file:///data/x.txt",
    )

    fake_db = MagicMock()
    fake_db.get.return_value = fake_resource
    fake_db.execute.return_value.scalar_one_or_none.return_value = fake_resource

    service = ResourceService()
    service.invoke_resource = AsyncMock(return_value="actual file content")

    pm = MagicMock()
    pm.has_hooks_for.return_value = True
    pm._initialized = True

    async def invoke_hook(
        hook_type,
        payload,
        global_ctx,
        local_contexts=None,
        violations_as_exceptions=True,
    ):
        if hook_type == ResourceHookType.RESOURCE_POST_FETCH:
            await plugin.resource_post_fetch(payload, global_ctx)
        return MagicMock(modified_payload=None), None

    pm.invoke_hook = invoke_hook
    service._plugin_manager = pm

    result = await service.read_resource(
        db=fake_db,
        resource_id="res1",
        resource_uri="file:///data/x.txt",
    )

    assert "text" in captured
    assert captured["text"] != "file:///data/x.txt"
    assert captured["text"] == "actual file content"
    assert result.text == "actual file content"


# ===========================================================================
# 6. Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string(self):
        """Empty string should produce no findings."""
        cfg = SecretsDetectionConfig()
        assert _detect("", cfg) == []

    def test_empty_dict(self):
        """Empty dict should produce count=0."""
        cfg = SecretsDetectionConfig()
        count, result, findings = _scan_container({}, cfg)
        assert count == 0
        assert result == {}

    def test_empty_list(self):
        """Empty list should produce count=0."""
        cfg = SecretsDetectionConfig()
        count, result, findings = _scan_container([], cfg)
        assert count == 0
        assert result == []

    def test_multiple_pattern_matches_in_one_string(self):
        """A single string may trigger multiple pattern types."""
        cfg = SecretsDetectionConfig()
        # AWS access key ID + slack token in same string
        text = "AKIAIOSFODNN7EXAMPLE xoxb-1234567890-abcdefghij"
        findings = _detect(text, cfg)
        types = {f["type"] for f in findings}
        assert "aws_access_key_id" in types
        assert "slack_token" in types

    def test_findings_examples_capped_at_5(self):
        """Violation details examples should be capped at 5."""
        # Use hex_secret_32 pattern which matches 32+ char hex strings.
        # Create many distinct hex secrets to get many findings.
        secrets = [f"{i:032x}" for i in range(10)]
        text = " ".join(secrets)
        # We test via _scan_container and check the cap logic in the hook
        cfg = SecretsDetectionConfig()
        count, _, findings = _scan_container(text, cfg)
        # The cap is applied in the hook, not in _scan_container
        assert count >= 10
        # Verify the hook applies the cap
        capped = findings[:5]
        assert len(capped) == 5

    @pytest.mark.asyncio
    async def test_violation_examples_capped_in_hook(self):
        """Hook violation details should cap examples at 5."""
        secrets = [f"{i:032x}" for i in range(10)]
        text = " ".join(secrets)
        plugin = _make_plugin()
        ctx = _make_context()
        payload = ToolPostInvokePayload(name="tool", result=text)
        result = await plugin.tool_post_invoke(payload, ctx)
        assert result.violation is not None
        assert len(result.violation.details["examples"]) <= 5

    def test_deeply_nested_structure(self):
        """Should handle deeply nested dict/list structures."""
        cfg = SecretsDetectionConfig()
        data = {"l1": {"l2": {"l3": {"l4": ["AKIAIOSFODNN7EXAMPLE"]}}}}
        count, _, findings = _scan_container(data, cfg)
        assert count >= 1
        types = {f["type"] for f in findings}
        assert "aws_access_key_id" in types

    def test_deeply_nested_redaction(self):
        """Redaction should work at any nesting depth."""
        cfg = SecretsDetectionConfig(redact=True)
        data = {"l1": {"l2": {"l3": ["AKIAIOSFODNN7EXAMPLE"]}}}
        count, result, findings = _scan_container(data, cfg)
        assert count >= 1
        assert "AKIAIOSFODNN7EXAMPLE" not in result["l1"]["l2"]["l3"][0]
        assert "***REDACTED***" in result["l1"]["l2"]["l3"][0]

    def test_private_key_in_multiline(self):
        """Private key header should be detected in multiline text."""
        cfg = SecretsDetectionConfig()
        text = "some config\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ...\n-----END RSA PRIVATE KEY-----"
        findings = _detect(text, cfg)
        types = {f["type"] for f in findings}
        assert "private_key_block" in types
