# -*- coding: utf-8 -*-
"""Tests for the packaged PII filter plugin."""

# Standard
import logging

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import GlobalContext, PluginConfig, PluginContext, PluginMode, PromptHookType, PromptPosthookPayload, PromptPrehookPayload
from cpex_pii_filter import PIIDetectorRust
from cpex_pii_filter.pii_filter import PIIFilterPlugin


@pytest.fixture
def detector():
    return PIIDetectorRust({})


class TestPIIDetectorRust:
    def test_initialization(self):
        detector = PIIDetectorRust({})
        assert detector is not None

    def test_ssn_detection_with_position(self):
        detections = PIIDetectorRust({"detect_ssn": True}).detect("My SSN is 123-45-6789")
        assert "ssn" in detections
        entry = detections["ssn"][0]
        assert entry["value"] == "123-45-6789"
        assert entry["start"] == 10
        assert entry["end"] == 21

    def test_bsn_detection_for_labeled_number(self):
        detections = PIIDetectorRust({"detect_bsn": True, "detect_ssn": False, "detect_phone": False, "detect_bank_account": False}).detect("My BSN is 180774955. Store it and confirm.")
        assert "bsn" in detections

    def test_bsn_detection_for_bsn_prefix(self):
        detections = PIIDetectorRust({"detect_bsn": True, "detect_ssn": False, "detect_phone": False, "detect_bank_account": False}).detect("BSN: 123456789")
        assert "bsn" in detections

    def test_bsn_detection_skips_unlabeled_regular_number(self):
        detections = PIIDetectorRust({"detect_bsn": True, "detect_ssn": False, "detect_phone": False, "detect_bank_account": False}).detect("Regular number 180774955")
        assert "bsn" not in detections

    def test_bsn_detection_ignores_clean_text(self):
        detections = PIIDetectorRust({"detect_bsn": True, "detect_ssn": False, "detect_phone": False, "detect_bank_account": False}).detect("No BSN here")
        assert "bsn" not in detections

    def test_contextual_phone_case_stays_undetected(self):
        detections = PIIDetectorRust({"detect_bsn": True, "detect_ssn": True, "detect_phone": True, "detect_bank_account": True}).detect("Phone: 555123456")
        assert detections == {}

    def test_whitelist_functionality(self):
        detector = PIIDetectorRust({"detect_email": True, "whitelist_patterns": ["test@example.com", "admin@localhost"]})
        detections = detector.detect("Contact test@example.com or admin@localhost")
        assert "email" not in detections
        detections = detector.detect("Contact real@email.com")
        assert "email" in detections

    def test_mask_and_process_nested(self):
        detector = PIIDetectorRust({"detect_ssn": True, "detect_email": True})
        detections = detector.detect("SSN: 123-45-6789 Email: john@example.com")
        masked = detector.mask("SSN: 123-45-6789 Email: john@example.com", detections)
        assert "123-45-6789" not in masked
        assert "john@example.com" not in masked

        modified, new_data, nested = detector.process_nested({"user": {"ssn": "123-45-6789", "email": "john@example.com"}}, "")
        assert modified is True
        assert "ssn" in nested
        assert new_data["user"]["ssn"] != "123-45-6789"


class TestPIIFilterPlugin:
    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        return PluginConfig(
            name="TestPIIFilter",
            description="Test PII Filter",
            author="Test",
            kind="cpex_pii_filter.pii_filter.PIIFilterPlugin",
            version="1.0",
            hooks=[PromptHookType.PROMPT_PRE_FETCH, PromptHookType.PROMPT_POST_FETCH],
            tags=["test", "pii"],
            mode=PluginMode.ENFORCE,
            priority=10,
            config={
                "detect_ssn": True,
                "detect_credit_card": True,
                "detect_email": True,
                "detect_phone": True,
                "detect_ip_address": True,
                "default_mask_strategy": "partial",
                "block_on_detection": False,
                "log_detections": True,
                "include_detection_details": True,
            },
        )

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocks_with_pii(self, plugin_config):
        plugin_config.config["block_on_detection"] = True
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-1"))
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"user_input": "My email is john@example.com and SSN is 123-45-6789", "safe_input": "This has no PII"})
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.continue_processing is False
        assert result.violation is not None
        assert result.violation.code == "PII_DETECTED"

    @pytest.mark.asyncio
    async def test_prompt_post_fetch(self, plugin_config):
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-3"))
        messages = [
            Message(role=Role.USER, content=TextContent(type="text", text="Contact me at john@example.com or 555-123-4567")),
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="I'll reach you at jane.doe@example.com once the ticket is processed")),
        ]
        payload = PromptPosthookPayload(prompt_id="test_prompt", result=PromptResult(messages=messages))
        result = await plugin.prompt_post_fetch(payload, context)
        assert result.modified_payload is not None
        assert "john@example.com" not in result.modified_payload.result.messages[0].content.text
        assert "jane.doe@example.com" not in result.modified_payload.result.messages[1].content.text

    def test_plugin_uses_rust_core(self, plugin_config):
        plugin = PIIFilterPlugin(plugin_config)
        assert type(plugin._core).__name__ == "PIIFilterPluginCore"

    def test_python_detector_logs_deprecation_warning(self, plugin_config, monkeypatch, caplog):
        monkeypatch.setattr(PIIFilterPlugin, "_python_deprecation_warned", False, raising=False)
        caplog.set_level(logging.WARNING)
        PIIFilterPlugin(plugin_config)
        PIIFilterPlugin(plugin_config)
        warning_messages = [record.message for record in caplog.records if "legacy Python PII filter detector is deprecated" in record.message]
        assert len(warning_messages) <= 1
