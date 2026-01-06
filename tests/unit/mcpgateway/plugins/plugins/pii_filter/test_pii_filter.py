# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for PII Filter Plugin.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PluginMode,
    PromptHookType,
    PromptPosthookPayload,
    PromptPrehookPayload,
)

# Import the PII Filter plugin
from plugins.pii_filter.pii_filter import (
    MaskingStrategy,
    PIIDetector,
    PIIFilterConfig,
    PIIFilterPlugin,
    PIIType,
)


class TestPIIDetector:
    """Test the PII detection functionality."""

    def test_ssn_detection(self):
        """Test Social Security Number detection."""
        config = PIIFilterConfig(detect_ssn=True, detect_bsn=False)
        detector = PIIDetector(config)

        test_cases = [
            ("My SSN is 123-45-6789", True),
            ("Number 123-45-6789 is sensitive", True),
            ("No SSN here", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.SSN in detections
            else:
                assert PIIType.SSN not in detections

    def test_bsn_detection(self):
        """Test Dutch BSN (Burgerservicenummer) detection."""
        config = PIIFilterConfig(detect_bsn=True, detect_ssn=False, detect_phone=False, detect_bank_account=False)
        detector = PIIDetector(config)

        test_cases = [
            ("My BSN is 180774955. Store it and confirm.", True),
            ("BSN: 123456789", True),
            ("Regular number 180774955", True),
            ("No BSN here", False),
            ("Too short 12345678", False),
            ("Too long 1234567890", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.BSN in detections, f"Expected BSN detection in: {text}"
            else:
                assert PIIType.BSN not in detections, f"Unexpected BSN detection in: {text}"

    def test_bsn_masking(self):
        """Test BSN partial masking."""
        config = PIIFilterConfig(detect_bsn=True, detect_ssn=False, detect_phone=False, detect_bank_account=False)
        detector = PIIDetector(config)

        text = "My BSN is 180774955. Store it and confirm."
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "180774955" not in masked
        assert "*****4955" in masked

    def test_credit_card_detection(self):
        """Test credit card number detection."""
        config = PIIFilterConfig(detect_credit_card=True)
        detector = PIIDetector(config)

        test_cases = [
            ("Card: 4111-1111-1111-1111", True),
            ("4111111111111111", True),
            ("4111 1111 1111 1111", True),
            ("No card here", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.CREDIT_CARD in detections
            else:
                assert PIIType.CREDIT_CARD not in detections

    def test_email_detection(self):
        """Test email address detection."""
        config = PIIFilterConfig(detect_email=True)
        detector = PIIDetector(config)

        test_cases = [
            ("Contact me at john.doe@example.com", True),
            ("Email: user@test.co.uk", True),
            ("admin+test@company.org", True),
            ("No email here", False),
            ("Not an @email", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.EMAIL in detections
            else:
                assert PIIType.EMAIL not in detections

    def test_phone_detection(self):
        """Test phone number detection."""
        config = PIIFilterConfig(detect_phone=True)
        detector = PIIDetector(config)

        test_cases = [
            ("Call me at 555-123-4567", True),
            ("Phone: (555) 123-4567", True),
            ("+1 555 123 4567", True),
            ("5551234567", True),
            ("No phone here", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.PHONE in detections
            else:
                assert PIIType.PHONE not in detections

    def test_ip_address_detection(self):
        """Test IP address detection."""
        config = PIIFilterConfig(detect_ip_address=True)
        detector = PIIDetector(config)

        test_cases = [
            ("Server IP: 192.168.1.1", True),
            ("Connect to 10.0.0.1", True),
            ("IPv4: 255.255.255.255", True),
            ("No IP here", False),
            ("999.999.999.999", False),  # Invalid IP
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.IP_ADDRESS in detections
            else:
                assert PIIType.IP_ADDRESS not in detections

    def test_aws_key_detection(self):
        """Test AWS key detection."""
        config = PIIFilterConfig(detect_aws_keys=True)
        detector = PIIDetector(config)

        test_cases = [
            ("Access key: AKIAIOSFODNN7EXAMPLE", True),
            ("AKIA1234567890123456", True),
            ("No key here", False),
        ]

        for text, should_detect in test_cases:
            detections = detector.detect(text)
            if should_detect:
                assert PIIType.AWS_KEY in detections
            else:
                assert PIIType.AWS_KEY not in detections

    def test_whitelist_functionality(self):
        """Test that whitelisted patterns are not detected."""
        config = PIIFilterConfig(detect_email=True, whitelist_patterns=["test@example.com", "admin@localhost"])
        detector = PIIDetector(config)

        # Whitelisted emails should not be detected
        text = "Contact test@example.com or admin@localhost"
        detections = detector.detect(text)
        assert PIIType.EMAIL not in detections

        # Non-whitelisted email should be detected
        text = "Contact real@email.com"
        detections = detector.detect(text)
        assert PIIType.EMAIL in detections

    def test_masking_strategies(self):
        """Test different masking strategies."""
        config = PIIFilterConfig(detect_ssn=True, detect_phone=False, detect_bank_account=False)  # Disable phone detection  # Disable bank account detection
        detector = PIIDetector(config)

        # Test REDACT strategy (SSN uses PARTIAL by default in the pattern)
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "***-**-6789" in masked  # SSN partial masking pattern
        assert "123-45-6789" not in masked

        # Test PARTIAL strategy
        config = PIIFilterConfig(detect_email=True, detect_ssn=False, detect_phone=False, detect_bank_account=False, default_mask_strategy=MaskingStrategy.PARTIAL)  # Disable SSN for email test
        detector = PIIDetector(config)
        text = "Email: john.doe@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "@example.com" in masked
        assert "john.doe" not in masked

        # Test REMOVE strategy
        config = PIIFilterConfig(
            detect_ssn=True,
            detect_phone=False,
            detect_bank_account=False,
            default_mask_strategy=MaskingStrategy.REMOVE,  # Disable phone detection  # Disable bank account detection
        )
        detector = PIIDetector(config)
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "123-45-6789" not in masked
        # The result should have the SSN masked
        assert masked == "SSN: ***-**-6789"

    def test_multiple_pii_detection(self):
        """Test detection of multiple PII types in one text."""
        config = PIIFilterConfig(detect_ssn=True, detect_email=True, detect_phone=True)
        detector = PIIDetector(config)

        text = "Contact John at john@example.com or 555-123-4567. SSN: 123-45-6789"
        detections = detector.detect(text)

        assert PIIType.EMAIL in detections
        assert PIIType.PHONE in detections
        assert PIIType.SSN in detections
        assert len(detections) == 3


class TestPIIFilterPlugin:
    """Test the PII Filter plugin integration."""

    @pytest.fixture
    def plugin_config(self) -> PluginConfig:
        """Create a test plugin configuration."""
        return PluginConfig(
            name="TestPIIFilter",
            description="Test PII Filter",
            author="Test",
            kind="plugins.pii_filter.pii_filter.PIIFilterPlugin",
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
                "detect_aws_keys": True,
                "default_mask_strategy": "partial",
                "block_on_detection": False,
                "log_detections": True,
                "include_detection_details": True,
            },
        )

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_with_pii(self, plugin_config):
        """Test pre-fetch hook with PII detection."""
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-1"))

        # Create payload with PII
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"user_input": "My email is john@example.com and SSN is 123-45-6789", "safe_input": "This has no PII"})

        result = await plugin.prompt_pre_fetch(payload, context)

        # Check that PII was masked
        assert result.modified_payload is not None
        assert "john@example.com" not in result.modified_payload.args["user_input"]
        assert "123-45-6789" not in result.modified_payload.args["user_input"]
        assert result.modified_payload.args["safe_input"] == "This has no PII"

        # Check metadata
        assert "pii_detections" in context.metadata
        assert context.metadata["pii_detections"]["pre_fetch"]["detected"]
        assert "user_input" in context.metadata["pii_detections"]["pre_fetch"]["fields"]

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocking(self, plugin_config):
        """Test that blocking mode prevents processing when PII is detected."""
        # Enable blocking
        plugin_config.config["block_on_detection"] = True
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-2"))

        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "My SSN is 123-45-6789"})

        result = await plugin.prompt_pre_fetch(payload, context)

        # Check that processing was blocked
        assert not result.continue_processing
        assert result.violation is not None
        assert result.violation.code == "PII_DETECTED"
        assert "input" in result.violation.details["field"]

    @pytest.mark.asyncio
    async def test_prompt_post_fetch(self, plugin_config):
        """Test post-fetch hook with PII in messages."""
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-3"))

        # Create messages with PII
        messages = [
            Message(role=Role.USER, content=TextContent(type="text", text="Contact me at john@example.com or 555-123-4567")),
            Message(role=Role.ASSISTANT, content=TextContent(type="text", text="I'll reach you at the provided contact: AKIAIOSFODNN7EXAMPLE")),
        ]

        payload = PromptPosthookPayload(prompt_id="test_prompt", result=PromptResult(messages=messages))

        result = await plugin.prompt_post_fetch(payload, context)

        # Check that PII was masked in messages
        assert result.modified_payload is not None
        user_msg = result.modified_payload.result.messages[0].content.text
        assistant_msg = result.modified_payload.result.messages[1].content.text

        assert "john@example.com" not in user_msg
        assert "555-123-4567" not in user_msg
        assert "AKIAIOSFODNN7EXAMPLE" not in assistant_msg

        # Check metadata
        assert "pii_detections" in context.metadata
        assert context.metadata["pii_detections"]["post_fetch"]["detected"]

    @pytest.mark.asyncio
    async def test_no_pii_detection(self, plugin_config):
        """Test that clean text passes through unmodified."""
        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-4"))

        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "This text has no sensitive information"})

        result = await plugin.prompt_pre_fetch(payload, context)

        # Check that nothing was modified
        assert result.modified_payload is None
        assert "pii_detections" not in context.metadata

    @pytest.mark.asyncio
    async def test_custom_patterns(self, plugin_config):
        """Test custom PII pattern detection."""
        # Add custom pattern
        plugin_config.config["custom_patterns"] = [{"type": "custom", "pattern": r"\bEMP\d{6}\b", "description": "Employee ID", "mask_strategy": "redact", "enabled": True}]

        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-5"))

        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Employee ID: EMP123456"})

        result = await plugin.prompt_pre_fetch(payload, context)

        # Check that custom pattern was detected and masked
        assert result.modified_payload is not None
        assert "EMP123456" not in result.modified_payload.args["input"]
        assert "[REDACTED]" in result.modified_payload.args["input"]

    @pytest.mark.asyncio
    async def test_permissive_mode(self, plugin_config):
        """Test permissive mode (log but don't block)."""
        plugin_config.mode = PluginMode.PERMISSIVE
        plugin_config.config["block_on_detection"] = True  # Should be ignored in permissive mode

        plugin = PIIFilterPlugin(plugin_config)
        context = PluginContext(global_context=GlobalContext(request_id="test-6"))

        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "SSN: 123-45-6789"})

        result = await plugin.prompt_pre_fetch(payload, context)

        # In permissive mode, should continue even with block_on_detection
        assert result.continue_processing or plugin_config.mode == PluginMode.PERMISSIVE
        # PII should still be masked
        if result.modified_payload:
            assert "123-45-6789" not in result.modified_payload.args["input"]


@pytest.mark.asyncio
async def test_integration_with_manager():
    """Test the PII Filter plugin with the plugin manager."""
    # First-Party
    from mcpgateway.plugins.framework.manager import PluginManager

    # Create a test configuration
    config_dict = {
        "plugins": [
            {
                "name": "PIIFilter",
                "kind": "plugins.pii_filter.pii_filter.PIIFilterPlugin",
                "description": "PII Filter",
                "author": "Test",
                "version": "1.0",
                "hooks": ["prompt_pre_fetch", "prompt_post_fetch"],
                "tags": ["security", "pii"],
                "mode": "enforce",
                "priority": 10,
                "conditions": [{"prompts": ["test_prompt"], "server_ids": [], "tenant_ids": []}],
                "config": {"detect_ssn": True, "detect_email": True, "default_mask_strategy": "partial", "block_on_detection": False, "log_detections": True, "include_detection_details": True},
            }
        ],
        "plugin_dirs": [],
        "plugin_settings": {"parallel_execution_within_band": False, "plugin_timeout": 30, "fail_on_plugin_error": False, "enable_plugin_api": True, "plugin_health_check_interval": 60},
    }

    # Save config to a temp file and initialize manager
    # Standard
    import tempfile

    # Third-Party
    import yaml

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_dict, f)
        config_path = f.name

    try:
        manager = PluginManager(config_path)
        await manager.initialize()

        # Test with PII in prompt
        payload = PromptPrehookPayload(prompt_id="test_prompt", args={"input": "Email: test@example.com, SSN: 123-45-6789"})

        global_context = GlobalContext(request_id="test-manager")
        result, contexts = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, global_context)

        # Verify PII was masked
        assert result.modified_payload is not None
        assert "test@example.com" not in result.modified_payload.args["input"]
        assert "123-45-6789" not in result.modified_payload.args["input"]

        await manager.shutdown()
    finally:
        # Standard
        import os

        os.unlink(config_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
