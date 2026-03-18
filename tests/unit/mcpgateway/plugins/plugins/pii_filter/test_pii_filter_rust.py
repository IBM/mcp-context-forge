# -*- coding: utf-8 -*-
"""Rust-specific unit tests for the Rust-backed PII Filter plugin."""

# Standard
import tempfile
from pathlib import Path

# Third-Party
import pytest
import yaml

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginManager,
    PluginMode,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from plugins.pii_filter_rust import pii_filter_rust as rust_plugin_module
from plugins.pii_filter_rust.pii_filter_rust import RustPIIFilterPlugin


def _require_rust() -> None:
    if not rust_plugin_module.RUST_AVAILABLE:
        pytest.skip("Rust implementation not available")


def _rust_plugin_config(**config_overrides) -> PluginConfig:
    config = {
        "detect_ssn": True,
        "detect_bsn": True,
        "detect_credit_card": True,
        "detect_email": True,
        "detect_phone": True,
        "detect_ip_address": True,
        "detect_date_of_birth": True,
        "detect_passport": True,
        "detect_driver_license": True,
        "detect_bank_account": True,
        "detect_medical_record": True,
        "detect_full_name": True,
        "detect_street_address": True,
        "detect_us_aba_routing_number": True,
        "detect_us_zip_code": True,
        "detect_us_ein": True,
        "detect_us_itin": True,
        "default_mask_strategy": "partial",
        "redaction_text": "[PII_REDACTED]",
        "block_on_detection": False,
        "log_detections": True,
        "include_detection_details": True,
        "whitelist_patterns": ["test@example.com", "555-555-5555"],
    }
    config.update(config_overrides)
    return PluginConfig(
        name="TestRustPIIFilter",
        description="Test Rust PII Filter",
        author="Test",
        kind="plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin",
        version="1.0",
        hooks=[
            PromptHookType.PROMPT_PRE_FETCH,
            PromptHookType.PROMPT_POST_FETCH,
            ToolHookType.TOOL_PRE_INVOKE,
            ToolHookType.TOOL_POST_INVOKE,
        ],
        tags=["test", "pii", "rust"],
        mode=PluginMode.ENFORCE,
        priority=10,
        config=config,
    )


def _load_shipped_plugin_config() -> PluginConfig:
    config_path = Path("plugins/config.yaml")
    config_dict = yaml.safe_load(config_path.read_text())
    plugin_entry = next(plugin for plugin in config_dict["plugins"] if plugin["name"] == "RustPIIFilterPlugin")
    return PluginConfig.model_validate(plugin_entry)


class TestRustPIIFilterPluginConfig:
    def test_plugins_config_yaml_ships_dedicated_rust_entry(self):
        plugin = _load_shipped_plugin_config()

        assert plugin.name == "RustPIIFilterPlugin"
        assert plugin.kind == "plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin"
        assert plugin.config["detect_driver_license"] is True
        assert plugin.config["detect_full_name"] is True
        assert plugin.config["detect_street_address"] is True
        assert plugin.config["detect_us_aba_routing_number"] is True
        assert plugin.config["detect_us_zip_code"] is True
        assert plugin.config["detect_us_ein"] is True
        assert plugin.config["detect_us_itin"] is True
        assert plugin.config["default_mask_strategy"] == "partial"
        assert plugin.config["redaction_text"] == "[PII_REDACTED]"

    def test_raw_rust_only_flags_survive_adapter_boundary(self):
        _require_rust()
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_full_name=False, detect_us_ein=False))

        assert plugin.rust_config["detect_full_name"] is False
        assert plugin.rust_config["detect_us_ein"] is False

    def test_invalid_plugin_config_shape_is_rejected(self):
        invalid_config = _rust_plugin_config()
        invalid_config.config = "not-a-mapping"

        with pytest.raises(TypeError, match="config must be a mapping"):
            RustPIIFilterPlugin(invalid_config)

    def test_rust_plugin_fails_fast_when_rust_unavailable(self, monkeypatch):
        monkeypatch.setattr(rust_plugin_module, "RUST_AVAILABLE", False)
        monkeypatch.setattr(rust_plugin_module, "RustPIIDetector", None)

        with pytest.raises(ImportError, match="requires the `pii_filter_rust` package"):
            RustPIIFilterPlugin(_rust_plugin_config())


@pytest.mark.skipif(not rust_plugin_module.RUST_AVAILABLE, reason="Rust implementation not available")
class TestRustPIIFilterPluginHooks:
    @pytest.fixture
    def plugin(self) -> RustPIIFilterPlugin:
        return RustPIIFilterPlugin(_rust_plugin_config())

    @pytest.fixture
    def context(self) -> PluginContext:
        return PluginContext(global_context=GlobalContext(request_id="rust-pii-test"))

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_masks_and_records_metadata(self, plugin, context):
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: john@example.com SSN: 123-45-6789"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert "john@example.com" not in result.modified_payload.args["input"]
        assert "123-45-6789" not in result.modified_payload.args["input"]
        assert context.metadata["pii_detections"]["pre_fetch"]["detected"] is True
        assert sorted(context.metadata["pii_detections"]["pre_fetch"]["types"]) == ["email", "ssn"]

    @pytest.mark.asyncio
    async def test_prompt_post_fetch_blocks_when_fail_closed(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(block_on_detection=True))
        payload = PromptPosthookPayload(
            prompt_id="test_prompt",
            result=PromptResult(messages=[Message(role=Role.USER, content=TextContent(type="text", text="Contact john@example.com"))]),
        )

        result = await plugin.prompt_post_fetch(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PII_DETECTED"
        assert "email" in result.violation.details["types"]

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_masks_nested_args(self, plugin, context):
        payload = ToolPreInvokePayload(
            name="test_tool",
            args={"customer": {"ssn": "123-45-6789", "email": "john@example.com"}, "safe": "ok"},
        )

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.modified_payload is not None
        modified_args = result.modified_payload.args
        assert modified_args["customer"]["ssn"] != "123-45-6789"
        assert modified_args["customer"]["email"] != "john@example.com"
        assert modified_args["safe"] == "ok"
        assert context.metadata["pii_detections"]["tool_pre_invoke"]["detected"] is True

    @pytest.mark.asyncio
    async def test_tool_pre_invoke_blocks_with_violation_when_fail_closed(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(block_on_detection=True))
        payload = ToolPreInvokePayload(name="test_tool", args={"customer": {"ssn": "123-45-6789"}})

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PII_DETECTED_IN_TOOL_ARGS"
        assert "ssn" in result.violation.details["types"]

    @pytest.mark.asyncio
    async def test_tool_post_invoke_masks_string_and_dict_results(self, plugin, context):
        string_payload = ToolPostInvokePayload(name="test_tool", result="SSN: 123-45-6789")
        string_result = await plugin.tool_post_invoke(string_payload, context)
        assert string_result.modified_payload is not None
        assert "123-45-6789" not in string_result.modified_payload.result

        dict_payload = ToolPostInvokePayload(
            name="test_tool",
            result={"contact": {"email": "john@example.com"}, "message": "safe"},
        )
        dict_result = await plugin.tool_post_invoke(dict_payload, context)
        assert dict_result.modified_payload is not None
        assert dict_result.modified_payload.result["contact"]["email"] != "john@example.com"
        assert dict_result.modified_payload.result["message"] == "safe"

    @pytest.mark.asyncio
    async def test_tool_post_invoke_blocks_with_violation_when_fail_closed(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(block_on_detection=True))
        payload = ToolPostInvokePayload(name="test_tool", result={"contact": {"email": "john@example.com"}})

        result = await plugin.tool_post_invoke(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PII_DETECTED_IN_TOOL_RESULT"
        assert "email" in result.violation.details["types"]

    @pytest.mark.asyncio
    async def test_default_mask_strategy_partial_on_rust_plugin(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(default_mask_strategy="partial"))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: john@example.com"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        masked = result.modified_payload.args["input"]
        assert "john@example.com" not in masked
        assert "@example.com" in masked

    @pytest.mark.asyncio
    async def test_default_mask_strategy_redact_on_rust_plugin(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(default_mask_strategy="redact"))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: john@example.com"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        masked = result.modified_payload.args["input"]
        assert "john@example.com" not in masked
        assert "[PII_REDACTED]" in masked

    @pytest.mark.asyncio
    async def test_default_mask_strategy_auto_on_rust_plugin(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(default_mask_strategy="auto"))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "SSN: 123-45-6789 DOB: 01/15/1990"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        masked = result.modified_payload.args["input"]
        assert "***-**-6789" in masked
        assert "01/15/1990" not in masked
        assert "[PII_REDACTED]" in masked

    @pytest.mark.asyncio
    async def test_phone_detection_uses_libphonenumber_validation(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_phone=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Call +442083661177 or office (650) 253-0000"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        masked = result.modified_payload.args["input"]
        assert "+442083661177" not in masked
        assert "(650) 253-0000" not in masked
        assert "phone" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    async def test_invalid_phone_candidate_is_not_masked(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_phone=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Order number: 111-111-1111"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is None
        assert "pii_detections" not in context.metadata

    @pytest.mark.asyncio
    async def test_iban_detection_without_label_requires_valid_checksum(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_bank_account=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Wire funds to DE89370400440532013000"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert "DE89370400440532013000" not in result.modified_payload.args["input"]
        assert "bank_account" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    async def test_aba_routing_detection_without_label_requires_valid_checksum(self, context):
        plugin = RustPIIFilterPlugin(
            _rust_plugin_config(detect_us_aba_routing_number=True, detect_bank_account=False)
        )
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "021000021"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert "021000021" not in result.modified_payload.args["input"]
        assert "us_aba_routing_number" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    async def test_compressed_ipv6_detection_masks_value(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_ip_address=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Host: 2001:db8::1"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert "2001:db8::1" not in result.modified_payload.args["input"]
        assert "ip_address" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    async def test_safe_logging_never_emits_raw_pii(self, caplog, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(block_on_detection=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: john@example.com SSN: 123-45-6789"})

        with caplog.at_level("WARNING"):
            result = await plugin.prompt_pre_fetch(payload, context)

        assert result.continue_processing is False
        logs = "\n".join(record.getMessage() for record in caplog.records)
        assert "john@example.com" not in logs
        assert "123-45-6789" not in logs
        assert "pii_types=email,ssn" in logs or "pii_types=ssn,email" in logs

    @pytest.mark.asyncio
    async def test_rust_only_detector_flag_can_disable_detection(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_full_name=False))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "full name: John Doe"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is None
        assert "pii_detections" not in context.metadata

    @pytest.mark.asyncio
    async def test_rust_only_detector_flag_can_enable_detection(self, context):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_full_name=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "full name: John Doe"})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert result.modified_payload.args["input"] != "full name: John Doe"
        assert "full_name" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("text", "license_value"),
        [
            ("CA Driver License: A1234567", "A1234567"),
            ("Texas DL: 12345678", "12345678"),
            ("Driver License Florida: F123456789012", "F123456789012"),
            ("NY License: 123456789", "123456789"),
            ("CA A1234567", "A1234567"),
            ("Texas 12345678", "12345678"),
            ("Florida F123456789012", "F123456789012"),
            ("NY 123456789", "123456789"),
        ],
    )
    async def test_driver_license_detection_for_top_state_formats(self, context, text, license_value):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_driver_license=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": text})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert license_value not in result.modified_payload.args["input"]
        assert "driver_license" in context.metadata["pii_detections"]["pre_fetch"]["types"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("text", "passport_value"),
        [
            ("passport number: 123456789", "123456789"),
            ("passport no: AB1234567", "AB1234567"),
            ("US 123456789", "123456789"),
            ("EU AB1234567", "AB1234567"),
        ],
    )
    async def test_passport_detection_for_supported_us_and_eu_formats(self, context, text, passport_value):
        plugin = RustPIIFilterPlugin(_rust_plugin_config(detect_passport=True))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": text})

        result = await plugin.prompt_pre_fetch(payload, context)

        assert result.modified_payload is not None
        assert passport_value not in result.modified_payload.args["input"]
        assert "passport" in context.metadata["pii_detections"]["pre_fetch"]["types"]


@pytest.mark.skipif(not rust_plugin_module.RUST_AVAILABLE, reason="Rust implementation not available")
class TestRustPIIFilterPluginManager:
    @staticmethod
    def _manager_config() -> dict:
        return {
            "plugins": [
                {
                    "name": "RustPIIFilterPlugin",
                    "kind": "plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin",
                    "description": "Rust PII Filter",
                    "author": "Test",
                    "version": "1.0",
                    "hooks": ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"],
                    "tags": ["security", "pii", "rust"],
                    "mode": "enforce",
                    "priority": 10,
                    "conditions": [{"prompts": ["test_prompt"], "server_ids": [], "tenant_ids": []}],
                    "config": _rust_plugin_config().config,
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

    @pytest.mark.asyncio
    async def test_manager_registers_and_invokes_rust_plugin(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(self._manager_config(), handle)
            config_path = handle.name

        manager = PluginManager(config_path)
        try:
            await manager.initialize()

            global_context = GlobalContext(request_id="rust-plugin-manager")

            prompt_payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: john@example.com"})
            prompt_result, prompt_contexts = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt_payload, global_context)
            assert prompt_result.modified_payload is not None
            assert "john@example.com" not in prompt_result.modified_payload.args["input"]

            tool_pre_payload = ToolPreInvokePayload(name="test_tool", args={"nested": {"ssn": "123-45-6789"}})
            tool_pre_result, tool_contexts = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_pre_payload, global_context)
            assert tool_pre_result.modified_payload is not None
            assert tool_pre_result.modified_payload.args["nested"]["ssn"] != "123-45-6789"

            tool_post_payload = ToolPostInvokePayload(name="test_tool", result={"email": "john@example.com"})
            tool_post_result, _ = await manager.invoke_hook(
                ToolHookType.TOOL_POST_INVOKE,
                tool_post_payload,
                global_context,
                local_contexts=tool_contexts,
            )
            assert tool_post_result.modified_payload is not None
            assert tool_post_result.modified_payload.result["email"] != "john@example.com"
            assert prompt_contexts
        finally:
            await manager.shutdown()
            Path(config_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_manager_ignores_disabled_rust_plugin_without_loading_it(self, monkeypatch):
        config = self._manager_config()
        config["plugins"][0]["mode"] = "disabled"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
            yaml.safe_dump(config, handle)
            config_path = handle.name

        init_calls: list[str] = []

        def _boom(*args, **kwargs):
            init_calls.append("called")
            raise AssertionError("RustPIIFilterPlugin should not be instantiated when disabled")

        monkeypatch.setattr(rust_plugin_module, "RustPIIDetector", _boom)

        manager = PluginManager(config_path)
        try:
            await manager.initialize()
            assert init_calls == []
        finally:
            await manager.shutdown()
            Path(config_path).unlink(missing_ok=True)
