# -*- coding: utf-8 -*-
"""Tests for secrets detection plugin regex patterns."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcpgateway.common.models import ResourceContent
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.plugins.framework import PluginConfig, ResourceHookType
from plugins.secrets_detection.secrets_detection import PATTERNS, SecretsDetectionPlugin


@pytest.mark.asyncio
async def test_resource_post_fetch_receives_resolved_content():
    """
    RESOURCE_POST_FETCH plugins should receive actual gateway content,
    not template URIs.
    """

    captured = {}

    # Subclass the real plugin to capture payload.content.text
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
        # Too short
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
