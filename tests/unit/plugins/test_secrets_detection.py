# -*- coding: utf-8 -*-
"""Tests for the packaged secrets detection plugin."""

# Standard
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
from cpex_secrets_detection import py_scan_container
from cpex_secrets_detection.secrets_detection import SecretsDetectionPlugin


@pytest.mark.asyncio
async def test_resource_post_fetch_receives_resolved_content():
    """RESOURCE_POST_FETCH plugins should receive resolved gateway content."""
    captured = {}

    class CaptureSecretsPlugin(SecretsDetectionPlugin):
        async def resource_post_fetch(self, payload, context):
            captured["text"] = payload.content.text
            return await super().resource_post_fetch(payload, context)

    plugin = CaptureSecretsPlugin(PluginConfig(name="secrets_detection", kind="resource", config={}))

    fake_resource = MagicMock()
    fake_resource.id = "res1"
    fake_resource.uri = "file:///data/x.txt"
    fake_resource.enabled = True
    fake_resource.content = ResourceContent(type="resource", id="res1", uri="file:///data/x.txt", text="file:///data/x.txt")

    fake_db = MagicMock()
    fake_db.get.return_value = fake_resource
    fake_db.execute.return_value.scalar_one_or_none.return_value = fake_resource

    service = ResourceService()
    service.invoke_resource = AsyncMock(return_value="actual file content")

    pm = MagicMock()
    pm.has_hooks_for.return_value = True
    pm._initialized = True

    async def invoke_hook(hook_type, payload, global_ctx, local_contexts=None, violations_as_exceptions=True):
        if hook_type == ResourceHookType.RESOURCE_POST_FETCH:
            await plugin.resource_post_fetch(payload, global_ctx)
        return MagicMock(modified_payload=None), None

    pm.invoke_hook = invoke_hook
    service._get_plugin_manager = AsyncMock(return_value=pm)

    result = await service.read_resource(db=fake_db, resource_id="res1", resource_uri="file:///data/x.txt")

    assert captured["text"] == "actual file content"
    assert result.text == "actual file content"


@pytest.mark.asyncio
class TestSecretsDetectionHookDispatch:
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

    async def test_prompt_pre_fetch_blocks_without_redaction(self, tmp_path: Path):
        manager = await self._manager(tmp_path, {"block_on_detection": True, "redact": False})
        try:
            payload = PromptPrehookPayload(prompt_id="prompt-1", args={"input": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"})
            result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context=self._global_context())
            assert result.continue_processing is False
            assert result.violation.code == "SECRETS_DETECTED"
            assert result.modified_payload == payload
        finally:
            await manager.shutdown()


class TestSecretsDetectionRustAPI:
    def test_detects_aws_secret_access_key(self):
        count, _redacted, findings = py_scan_container("AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000", {})
        assert count >= 1
        assert any(f.get("type") == "aws_secret_access_key" for f in findings)

    def test_detects_slack_token(self):
        count, _redacted, findings = py_scan_container("xoxr-fake-000000000-fake000000000-fakefakefakefake", {})
        assert count >= 1
        assert any(f.get("type") == "slack_token" for f in findings)

    def test_redaction_works(self):
        count, redacted, findings = py_scan_container("AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE", {"redact": True, "redaction_text": "[REDACTED]"})
        assert count >= 1
        assert "[REDACTED]" in redacted
        assert findings

    def test_handles_nested_structures(self):
        data = {"users": [{"name": "Alice", "key": "AKIAFAKE12345EXAMPLE"}, {"name": "Bob", "token": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}]}
        count, _redacted, findings = py_scan_container(data, {})
        assert count >= 2
        assert len(findings) >= 2

    def test_generic_api_key_assignment_detection_is_opt_in(self):
        count, _redacted, findings = py_scan_container("X-API-Key: test12345678901234567890", {"enabled": {"generic_api_key_assignment": True}})
        assert count >= 1
        assert any(f.get("type") == "generic_api_key_assignment" for f in findings)

    def test_generic_api_key_assignment_ignores_short_or_prose_values(self):
        for text in ["api_key=short", "api key rotation is enabled", "The api_key field is documented below"]:
            count, _redacted, findings = py_scan_container(text, {"enabled": {"generic_api_key_assignment": True}})
            assert not any(f.get("type") == "generic_api_key_assignment" for f in findings), text
            if count:
                assert all(f.get("type") != "generic_api_key_assignment" for f in findings)
