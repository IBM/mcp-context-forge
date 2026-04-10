# -*- coding: utf-8 -*-
"""Tests for secrets detection plugin regex patterns."""

# Standard
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest
import yaml

# First-Party
from mcpgateway.common.models import ResourceContent
from mcpgateway.plugins.framework import PluginConfig, PluginManager, PluginMode, PromptHookType, PromptPrehookPayload, ResourceHookType, ResourcePostFetchPayload, ToolHookType, ToolPostInvokePayload
from mcpgateway.plugins.framework.models import GlobalContext
from mcpgateway.services.resource_service import ResourceService
import cpex_secrets_detection.secrets_detection as secrets_detection_module
from cpex_secrets_detection.secrets_detection import SecretsDetectionPlugin

if not all(hasattr(secrets_detection_module, name) for name in ("_scan_container", "SecretsDetectionConfig")):
    pytest.skip("cpex_secrets_detection does not expose the legacy in-tree helper API", allow_module_level=True)


@pytest.mark.asyncio
async def test_resource_post_fetch_receives_resolved_content():
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
    service._get_plugin_manager = AsyncMock(return_value=pm)

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


@pytest.mark.asyncio
class TestSecretsDetectionHookDispatch:
    """Regression tests for the manager-dispatch paths called out in issue #5."""

    @pytest.fixture(autouse=True)
    def reset_plugin_manager(self):
        PluginManager.reset()
        yield
        PluginManager.reset()

    @staticmethod
    def _global_context() -> GlobalContext:
        return GlobalContext(request_id="req-secrets", server_id="srv-secrets")

    async def _manager(self, tmp_path: Path, config: dict) -> PluginManager:
        config_path = tmp_path / "secrets_detection.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "plugins": [
                        {
                            "name": "SecretsDetection",
                            "kind": "cpex_secrets_detection.secrets_detection.SecretsDetectionPlugin",
                            "hooks": [
                                PromptHookType.PROMPT_PRE_FETCH.value,
                                ToolHookType.TOOL_POST_INVOKE.value,
                                ResourceHookType.RESOURCE_POST_FETCH.value,
                            ],
                            "mode": PluginMode.ENFORCE.value,
                            "priority": 100,
                            "config": config,
                        }
                    ],
                    "plugin_dirs": [],
                    "plugin_settings": {
                        "parallel_execution_within_band": False,
                        "plugin_timeout": 30,
                        "fail_on_plugin_error": False,
                        "enable_plugin_api": True,
                        "plugin_health_check_interval": 60,
                    },
                }
            ),
            encoding="utf-8",
        )

        manager = PluginManager(str(config_path))
        await manager.initialize()
        return manager

    async def test_prompt_pre_fetch_redacts_without_blocking(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": False, "redact": True, "redaction_text": "[REDACTED]"})
        try:
            payload = PromptPrehookPayload(prompt_id="prompt-1", args={"input": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"})
            result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context=self._global_context())

            assert result.continue_processing is True
            assert result.violation is None
            assert result.modified_payload is not None
            assert result.modified_payload.args["input"] == "AWS_ACCESS_KEY_ID=[REDACTED]"
            assert result.metadata["secrets_redacted"] is True
            assert result.metadata["count"] == 1
        finally:
            await manager.shutdown()

    async def test_prompt_pre_fetch_blocks_without_redaction(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": True, "redact": False})
        try:
            payload = PromptPrehookPayload(prompt_id="prompt-1", args={"input": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"})
            result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context=self._global_context())

            assert result.continue_processing is False
            assert result.violation is not None
            assert result.violation.code == "SECRETS_DETECTED"
            # Blocking plugins do not return a modified payload here; the manager
            # backfills the current payload into the aggregate result on block.
            assert result.modified_payload == payload
        finally:
            await manager.shutdown()

    async def test_tool_post_invoke_redacts_mcp_content_payload(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": False, "redact": True, "redaction_text": "[REDACTED]"})
        try:
            payload = ToolPostInvokePayload(
                name="writer",
                result={"content": [{"type": "text", "text": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"}], "isError": False},
            )
            result, _ = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, global_context=self._global_context())

            assert result.continue_processing is True
            assert result.violation is None
            assert result.modified_payload is not None
            assert result.modified_payload.result["content"][0]["text"] == "AWS_ACCESS_KEY_ID=[REDACTED]"
            assert result.modified_payload.result["isError"] is False
            assert result.metadata["secrets_redacted"] is True
            assert result.metadata["count"] == 1
        finally:
            await manager.shutdown()

    async def test_tool_post_invoke_blocks_without_redaction(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": True, "redact": False})
        try:
            payload = ToolPostInvokePayload(
                name="writer",
                result={"content": [{"type": "text", "text": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"}], "isError": False},
            )
            result, _ = await manager.invoke_hook(ToolHookType.TOOL_POST_INVOKE, payload, global_context=self._global_context())

            assert result.continue_processing is False
            assert result.violation is not None
            assert result.violation.code == "SECRETS_DETECTED"
            # Blocking plugins do not return a modified payload here; the manager
            # backfills the current payload into the aggregate result on block.
            assert result.modified_payload == payload
        finally:
            await manager.shutdown()

    async def test_resource_post_fetch_redacts_without_blocking(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": False, "redact": True, "redaction_text": "[REDACTED]"})
        try:
            payload = ResourcePostFetchPayload(
                uri="file:///secret.txt",
                content=ResourceContent(type="resource", id="res-1", uri="file:///secret.txt", text="AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"),
            )
            result, _ = await manager.invoke_hook(ResourceHookType.RESOURCE_POST_FETCH, payload, global_context=self._global_context())

            assert result.continue_processing is True
            assert result.violation is None
            assert result.modified_payload is not None
            assert result.modified_payload.content.text == "AWS_ACCESS_KEY_ID=[REDACTED]"
            assert result.metadata["secrets_redacted"] is True
            assert result.metadata["count"] == 1
        finally:
            await manager.shutdown()

    async def test_resource_post_fetch_blocks_without_redaction(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": True, "redact": False})
        try:
            payload = ResourcePostFetchPayload(
                uri="file:///secret.txt",
                content=ResourceContent(type="resource", id="res-1", uri="file:///secret.txt", text="AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"),
            )
            result, _ = await manager.invoke_hook(ResourceHookType.RESOURCE_POST_FETCH, payload, global_context=self._global_context())

            assert result.continue_processing is False
            assert result.violation is not None
            assert result.violation.code == "SECRETS_DETECTED"
            # Blocking plugins do not return a modified payload here; the manager
            # backfills the current payload into the aggregate result on block.
            assert result.modified_payload == payload
        finally:
            await manager.shutdown()


class TestAwsSecretPattern:
    """Test AWS secret access key pattern behavior."""

    def test_matches_standard_format(self):
        """Pattern should match standard AWS secret key format."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        text = "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config)
        assert count >= 1
        assert any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_matches_with_separators(self):
        """Pattern should match with various separators."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()

        for text in [
            "aws_secret_key=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "aws-access-key=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "AWS_SECRET=FAKESecretAccessKeyForTestingEXAMPLE0000",
        ]:
            count, _redacted, findings = _scan_container(text, config)
            assert count >= 1, f"Failed to detect secret in: {text}"

    def test_case_insensitive(self):
        """Pattern should be case-insensitive for the prefix."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()

        for text in [
            "aws_secret=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "AWS_SECRET=FAKESecretAccessKeyForTestingEXAMPLE0000",
            "Aws_Secret=FAKESecretAccessKeyForTestingEXAMPLE0000",
        ]:
            count, _redacted, findings = _scan_container(text, config)
            assert count >= 1, f"Failed to detect secret in: {text}"

    def test_no_match_short_secret(self):
        """Pattern should not match secrets shorter than 40 chars."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        text = "aws_secret=FAKESecretKeyThatIsTooShortToMatch"  # Too short

        count, _redacted, findings = _scan_container(text, config)
        # Should not match aws_secret_access_key pattern (too short)
        assert not any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_no_match_missing_equals(self):
        """Pattern should not match without = sign."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        text = "aws_secret FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config)
        # Should not match aws_secret_access_key pattern (no equals sign)
        assert not any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_no_match_unrelated_text(self):
        """Pattern should not match unrelated text."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()

        for text in [
            "This is just some random text",
            "aws is a cloud provider",
        ]:
            count, _redacted, findings = _scan_container(text, config)
            assert count == 0, f"False positive in: {text}"

    def test_captures_secret_value(self):
        """Pattern should capture the secret value."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        text = "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"

        count, _redacted, findings = _scan_container(text, config)
        assert count >= 1
        # Check that the finding contains a preview of the secret
        aws_findings = [f for f in findings if f.get("type") == "aws_secret_access_key"]
        assert len(aws_findings) >= 1
        assert aws_findings[0].get("match") is not None


class TestSecretsDetectionBehavior:
    """Test packaged secrets detection behavior."""

    def test_detects_aws_access_key(self):
        """Should detect AWS access keys."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "aws_access_key_id" for f in findings)

    def test_detects_aws_secret_key(self):
        """Should detect AWS secret keys."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_detects_slack_token(self):
        """Should detect Slack tokens."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "slack_token" for f in findings)

    def test_detects_google_api_key(self):
        """Should detect Google API keys."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert len(findings) >= 1
        assert any(f.get("type") == "google_api_key" for f in findings)

    def test_detects_github_token_without_label(self):
        """Should detect provider-specific GitHub tokens without relying on labels."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "Token value ghp_1234567890abcdefghijklmnopqrstuvwxyZ was pasted into the chat"}  # pragma: allowlist secret

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert any(f.get("type") == "github_token" for f in findings)

    def test_detects_github_fine_grained_pat_without_label(self):
        """Should detect GitHub fine-grained PATs from their intrinsic prefix."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        token = "github_pat_abcdefghijklmnopqrstuvwxyz_ABCDEFGHIJKLMNOPQRSTUVWXYZ12"  # pragma: allowlist secret
        data = {"message": f"{token} was pasted into the chat"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert any(f.get("type") == "github_token" for f in findings)

    def test_detects_stripe_secret_key_without_label(self):
        """Should detect Stripe secret keys from their intrinsic prefix."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        stripe_secret = "_".join(["sk", "live", "1234567890abcdefghijklmnop"])  # pragma: allowlist secret
        data = {"message": f"{stripe_secret} should never be committed"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert any(f.get("type") == "stripe_secret_key" for f in findings)

    def test_does_not_treat_publishable_stripe_key_as_secret(self):
        """Should avoid obvious Stripe false positives like publishable keys."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        publishable_key = "_".join(["pk", "live", "1234567890abcdefghijklmnop"])  # pragma: allowlist secret
        data = {"message": f"{publishable_key} is a publishable key example"}

        count, _redacted, findings = _scan_container(data, config)

        assert not any(f.get("type") == "stripe_secret_key" for f in findings)

    def test_redaction_works(self):
        """Should redact secrets when enabled."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig(redact=True, redaction_text="[REDACTED]")
        data = "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"

        count, redacted, findings = _scan_container(data, config)

        assert count >= 1
        assert "[REDACTED]" in redacted
        assert "AKIAFAKE12345EXAMPLE" not in redacted

    def test_handles_nested_structures(self):
        """Should handle nested dicts and lists."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"users": [{"name": "Alice", "key": "AKIAFAKE12345EXAMPLE"}, {"name": "Bob", "token": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}]}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 2
        assert len(findings) >= 2

    def test_no_secrets_returns_zero(self):
        """Should return zero findings for clean text."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "This is just normal text without any secrets"}

        count, redacted, findings = _scan_container(data, config)

        assert count == 0
        assert len(findings) == 0
        assert redacted == data

    def test_empty_string(self):
        """Should handle empty strings."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": ""}

        count, redacted, findings = _scan_container(data, config)

        assert count == 0
        assert len(findings) == 0
        assert redacted == data

    def test_multiple_secrets(self):
        """Should detect multiple secrets in one message."""
        # First-Party
        from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

        config = SecretsDetectionConfig()
        data = {"message": "AWS_KEY=AKIAFAKE12345EXAMPLE and Slack token xoxr-fake-000000000-fake000000000-fakefakefakefake"}

        count, _redacted, findings = _scan_container(data, config)

        assert count >= 2
        assert len(findings) >= 2


def test_default_config_disables_broad_generic_api_key_pattern():
    """Broad generic API-key assignment detection should stay opt-in."""
    # First-Party
    from cpex_secrets_detection.secrets_detection import SecretsDetectionConfig

    config = SecretsDetectionConfig()

    assert config.enabled["generic_api_key_assignment"] is False


def test_partial_enabled_config_preserves_safe_defaults():
    """Partial enabled maps should not silently enable broad heuristics."""
    # First-Party
    from cpex_secrets_detection.secrets_detection import SecretsDetectionConfig

    config = SecretsDetectionConfig(enabled={"aws_access_key_id": False})

    assert config.enabled["aws_access_key_id"] is False
    assert config.enabled["github_token"] is True
    assert config.enabled["stripe_secret_key"] is True
    assert config.enabled["generic_api_key_assignment"] is False


def test_generic_api_key_assignment_detection_is_opt_in():
    """Generic assignment-based API key detection should work when explicitly enabled."""
    # First-Party
    from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

    config = SecretsDetectionConfig(
        enabled={
            **SecretsDetectionConfig().enabled,
            "generic_api_key_assignment": True,
        }
    )
    text = "X-API-Key: test12345678901234567890"  # gitleaks:allow

    count, _redacted, findings = _scan_container(text, config)

    assert count >= 1
    assert any(f.get("type") == "generic_api_key_assignment" for f in findings)


def test_generic_api_key_assignment_ignores_short_or_prose_values():
    """The broad API-key pattern should avoid matching short values or prose."""
    # First-Party
    from cpex_secrets_detection.secrets_detection import _scan_container, SecretsDetectionConfig

    config = SecretsDetectionConfig(
        enabled={
            **SecretsDetectionConfig().enabled,
            "generic_api_key_assignment": True,
        }
    )

    for text in [
        "api_key=short",
        "api key rotation is enabled",
        "The api_key field is documented below",
    ]:
        count, _redacted, findings = _scan_container(text, config)
        assert not any(f.get("type") == "generic_api_key_assignment" for f in findings), text
        if count:
            assert all(f.get("type") != "generic_api_key_assignment" for f in findings)


def test_plugin_warns_when_broad_patterns_enabled(caplog):
    """Enabling broad heuristic API-key patterns should emit an operator warning."""
    # First-Party
    from cpex_secrets_detection.secrets_detection import SecretsDetectionPlugin

    caplog.set_level(logging.WARNING, logger="cpex_secrets_detection.secrets_detection")
    SecretsDetectionPlugin(
        PluginConfig(
            name="secrets_detection",
            kind="cpex_secrets_detection.secrets_detection.SecretsDetectionPlugin",
            config={
                "enabled": {
                    "aws_access_key_id": True,
                    "aws_secret_access_key": True,
                    "google_api_key": True,
                    "generic_api_key_assignment": True,
                    "slack_token": True,
                    "private_key_block": True,
                    "jwt_like": False,
                    "hex_secret_32": False,
                    "base64_24": False,
                }
            },
        )
    )

    assert "Broad secrets heuristics enabled" in caplog.text
    assert "generic_api_key_assignment" in caplog.text
