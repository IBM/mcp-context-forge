# -*- coding: utf-8 -*-
"""Tests for secrets detection plugin regex patterns."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from mcpgateway.common.models import ResourceContent
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.plugins.framework import PluginConfig, ResourceHookType
from plugins.secrets_detection.secrets_detection import SecretsDetectionPlugin

# Try to import Rust implementation
try:
    import secret_detection as rust_secret_detection

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    rust_secret_detection = None
    # Fail in CI if Rust plugins are required
    if os.environ.get("REQUIRE_RUST_PLUGINS") == "1":
        raise ImportError("Rust plugin 'secret_detection' is required in CI but not available")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "use_rust",
    [
        pytest.param(False, id="python"),
        pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"), id="rust"),
    ],
)
async def test_resource_post_fetch_receives_resolved_content(use_rust):
    """
    RESOURCE_POST_FETCH plugins should receive actual gateway content,
    not template URIs.

    Tests with both Python and Rust implementations.
    """

    captured = {}

    # Subclass the real plugin to capture payload.content.text
    class CaptureSecretsPlugin(SecretsDetectionPlugin):
        async def resource_post_fetch(self, payload, context):
            captured["text"] = payload.content.text
            # Force use of specific implementation
            self._cfg.redact = False  # Ensure we can test detection
            return await super().resource_post_fetch(payload, context)

    plugin = CaptureSecretsPlugin(
        PluginConfig(
            name="secrets_detection",
            kind="resource",
            config={"use_rust": use_rust},
        )
    )

    # Fake DB resource (template-like content)
    fake_resource = MagicMock()
    fake_resource.id = "res1"
    fake_resource.uri = "file:///data/x.txt"
    fake_resource.enabled = True
    fake_resource.content = ResourceContent(
        type="resource",
        id="res1",
        uri="file:///data/x.txt",
        text="file:///data/x.txt",  # Simulate template URI in content
    )

    fake_db = MagicMock()
    fake_db.get.return_value = fake_resource
    fake_db.execute.return_value.scalar_one_or_none.return_value = fake_resource

    service = ResourceService()

    # Mock gateway resolution
    service.invoke_resource = AsyncMock(return_value="actual file content")

    # Minimal fake plugin manager
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

    # Execute
    result = await service.read_resource(
        db=fake_db,
        resource_id="res1",
        resource_uri="file:///data/x.txt",
    )

    # Assertions

    # Plugin must have been called
    assert "text" in captured

    # Plugin must NOT see template URI
    assert captured["text"] != "file:///data/x.txt"

    # Plugin MUST see resolved gateway content
    assert captured["text"] == "actual file content"

    # Returned ResourceContent must also be resolved
    assert result.text == "actual file content"


@pytest.mark.parametrize(
    "use_rust",
    [
        pytest.param(False, id="python"),
        pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"), id="rust"),
    ],
)
class TestAwsSecretPattern:
    """Test AWS secret access key pattern for correctness with both implementations."""

    def test_matches_standard_format(self, use_rust):
        """Pattern should match standard AWS secret key format."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        text = "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
        assert count >= 1
        assert any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_matches_with_separators(self, use_rust):
        """Pattern should match with various separators."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()

        for text in [
            "aws_secret_key=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "aws-access-key=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "AWS_SECRET=FAKESecretAccessKeyForTestingEXAMPLE0000",
        ]:
            count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
            assert count >= 1, f"Failed to detect secret in: {text}"

    def test_case_insensitive(self, use_rust):
        """Pattern should be case-insensitive for the prefix."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()

        for text in [
            "aws_secret=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "AWS_SECRET=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "Aws_Secret=FAKESecretAccessKeyForTestingEXAMPLE0000",
        ]:
            count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
            assert count >= 1, f"Failed to detect secret in: {text}"

    def test_no_match_short_secret(self, use_rust):
        """Pattern should not match secrets shorter than 40 chars."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        text = "aws_secret=FAKESecretKeyThatIsTooShortToMatch"  # Too short

        count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
        # Should not match aws_secret_access_key pattern (too short)
        assert not any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_no_match_missing_equals(self, use_rust):
        """Pattern should not match without = sign."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        text = "aws_secret FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
        # Should not match aws_secret_access_key pattern (no equals sign)
        assert not any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_no_match_unrelated_text(self, use_rust):
        """Pattern should not match unrelated text."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()

        for text in [
            "This is just some random text",
            "aws is a cloud provider",
        ]:
            count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
            assert count == 0, f"False positive in: {text}"

    def test_captures_secret_value(self, use_rust):
        """Pattern should capture the secret value."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        text = "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config, use_rust=use_rust)
        assert count >= 1
        # Check that the finding contains a preview of the secret
        aws_findings = [f for f in findings if f.get("type") == "aws_secret_access_key"]
        assert len(aws_findings) >= 1
        assert aws_findings[0].get("match") is not None


# Parametrized tests that run with both Python and Rust implementations
@pytest.mark.parametrize(
    "use_rust",
    [
        pytest.param(False, id="python"),
        pytest.param(True, marks=pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust not available"), id="rust"),
    ],
)
class TestSecretsDetectionBothImplementations:
    """Test secrets detection with both Python and Rust implementations.

    These tests run twice - once with use_rust=False (Python) and once with use_rust=True (Rust).
    This ensures both implementations produce correct results.
    """

    def test_detects_aws_access_key(self, use_rust):
        """Should detect AWS access keys."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "aws_access_key_id" for f in findings)

    def test_detects_aws_secret_key(self, use_rust):
        """Should detect AWS secret keys."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_detects_slack_token(self, use_rust):
        """Should detect Slack tokens."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "slack_token" for f in findings)

    def test_detects_google_api_key(self, use_rust):
        """Should detect Google API keys."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "google_api_key" for f in findings)

    def test_redaction_works(self, use_rust):
        """Should redact secrets when enabled."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig(redact=True, redaction_text="[REDACTED]")
        data = "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"

        count, redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 1
        assert "[REDACTED]" in redacted
        assert "AKIAFAKE12345EXAMPLE" not in redacted

    def test_handles_nested_structures(self, use_rust):
        """Should handle nested dicts and lists."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"users": [{"name": "Alice", "key": "AKIAFAKE12345EXAMPLE"}, {"name": "Bob", "token": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}]}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 2
        assert len(findings) >= 2

    def test_no_secrets_returns_zero(self, use_rust):
        """Should return zero findings for clean text."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "This is just normal text without any secrets"}

        count, redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count == 0
        assert len(findings) == 0
        assert redacted == data

    def test_empty_string(self, use_rust):
        """Should handle empty strings."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": ""}

        count, redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count == 0
        assert len(findings) == 0
        assert redacted == data

    def test_multiple_secrets(self, use_rust):
        """Should detect multiple secrets in one message."""
        from plugins.secrets_detection.secrets_detection import SecretsDetectionConfig, _scan_container

        config = SecretsDetectionConfig()
        data = {"message": "AWS_KEY=AKIAFAKE12345EXAMPLE and Slack token xoxr-fake-000000000-fake000000000-fakefakefakefake"}

        count, _redacted, findings = _scan_container(data, config, use_rust=use_rust)

        assert count >= 2
        assert len(findings) >= 2


def test_implementation_info():
    """Report which implementations are available for testing."""
    print("\n" + "=" * 60)
    print("Secrets Detection Test Configuration")
    print("=" * 60)
    print("Python implementation: ✓ Available")
    print(f"Rust implementation: {'✓ Available' if RUST_AVAILABLE else '✗ Not available'}")

    if RUST_AVAILABLE:
        print("\n✓ Tests will run with BOTH Python and Rust implementations")
    else:
        print("\n⚠ Tests will run with Python implementation only")
        print("  To enable Rust tests, build the Rust plugin:")
        print("  cd plugins_rust/secrets_detection && maturin develop --release")

    print("=" * 60)
