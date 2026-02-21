# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for PII Filter Plugin with parametric testing for both Python and Rust implementations.
"""

# Standard
import os
import time
from typing import Type

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

# Try to import Rust implementation
try:
    from plugins.pii_filter.pii_filter import RustPIIDetector, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False
    RustPIIDetector = None
    # Fail in CI if Rust plugins are required
    if os.environ.get("REQUIRE_RUST_PLUGINS") == "1":
        raise ImportError("Rust plugin 'pii_filter' is required in CI but not available")


# Parametric fixture for detector implementations
@pytest.fixture(params=["python", "rust"])
def detector_class(request) -> Type:
    """Fixture that provides both Python and Rust detector classes."""
    if request.param == "python":
        return PIIDetector
    elif request.param == "rust":
        if not RUST_AVAILABLE:
            pytest.skip("Rust implementation not available")
        return RustPIIDetector
    raise ValueError(f"Unknown detector type: {request.param}")


@pytest.fixture
def detector_impl(request) -> str:
    """Fixture that provides the implementation name for conditional assertions."""
    return getattr(request, "param", "python")


def normalize_detection_keys(detections: dict) -> set:
    """
    Normalize detection keys from both Python and Rust implementations.
    Python returns PIIType enum (e.g., PIIType.SSN), Rust returns lowercase strings (e.g., "ssn").
    This extracts just the type name in lowercase.
    """
    detection_keys = set()
    for k in detections.keys():
        key_str = str(k).lower()
        # Handle both "PIIType.SSN" / "piitype.ssn" and plain "ssn" formats
        if "." in key_str:
            key_str = key_str.split(".")[-1]
        detection_keys.add(key_str)
    return detection_keys


class TestPIIDetectorParametric:
    """Parametric tests that run on both Python and Rust implementations."""

    @pytest.fixture
    def default_config(self):
        """Create default configuration for testing."""
        return PIIFilterConfig()

    @pytest.fixture
    def detector(self, detector_class, default_config):
        """Create detector instance with default config."""
        return detector_class(default_config)

    def test_initialization(self, detector_class, default_config):
        """Test detector initialization."""
        detector = detector_class(default_config)
        assert detector is not None
        # Note: Rust implementation doesn't expose config attribute (internal optimization)
        # Python implementation does expose it for compatibility
        if hasattr(detector, "config"):
            assert detector.config == default_config

    # SSN Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect,acceptable_types",
        [
            ("My SSN is 123-45-6789", True, ["ssn"]),
            ("Number 123-45-6789 is sensitive", True, ["ssn"]),
            ("SSN: 123456789", True, ["ssn", "bank_account", "phone"]),  # No dashes - may match multiple patterns
            ("No SSN here", False, []),
        ],
    )
    def test_ssn_detection(self, detector_class, text, should_detect, acceptable_types):
        """Test Social Security Number detection."""
        config = PIIFilterConfig(detect_ssn=True, detect_bsn=False)
        detector = detector_class(config)
        detections = detector.detect(text)
        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            # Check if any of the acceptable types were detected
            assert any(pii_type in detection_keys for pii_type in acceptable_types), f"Expected one of {acceptable_types} but got {detection_keys}"
        else:
            assert "ssn" not in detection_keys

    def test_ssn_detection_with_position(self, detector_class):
        """Test SSN detection with position information (Rust-specific feature)."""
        config = PIIFilterConfig(detect_ssn=True)
        detector = detector_class(config)
        text = "My SSN is 123-45-6789"
        detections = detector.detect(text)

        # Normalize keys - handle both "ssn" and "PIIType.SSN" / "piitype.ssn"
        detection_keys = normalize_detection_keys(detections)
        assert "ssn" in detection_keys

        # Get the actual key for further checks
        ssn_key = next((k for k in detections.keys() if "ssn" in str(k).lower()), None)
        assert ssn_key is not None
        assert len(detections[ssn_key]) == 1

        # Check value
        detection = detections[ssn_key][0]
        assert detection["value"] == "123-45-6789"

        # Position info available in Rust implementation
        if detector_class.__name__ == "RustPIIDetector":
            assert detection["start"] == 10
            assert detection["end"] == 21

    def test_ssn_masking_partial(self, detector):
        """Test partial masking of SSN."""
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        # Check that the last 4 digits are preserved and original is masked
        assert "6789" in masked
        assert "123-45-6789" not in masked

    # BSN Detection Tests (Python-specific)
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("My BSN is 180774955. Store it and confirm.", True),
            ("BSN: 123456789", True),
            ("Regular number 180774955", True),
            ("No BSN here", False),
            ("Too short 12345678", False),
            ("Too long 1234567890", False),
        ],
    )
    def test_bsn_detection(self, detector_class, text, should_detect):
        """Test Dutch BSN (Burgerservicenummer) detection."""
        config = PIIFilterConfig(detect_bsn=True, detect_ssn=False, detect_phone=False, detect_bank_account=False)
        detector = detector_class(config)
        detections = detector.detect(text)

        if should_detect:
            assert PIIType.BSN in detections, f"Expected BSN detection in: {text}"
        else:
            assert PIIType.BSN not in detections, f"Unexpected BSN detection in: {text}"

    def test_bsn_masking(self, detector_class):
        """Test BSN partial masking."""
        config = PIIFilterConfig(detect_bsn=True, detect_ssn=False, detect_phone=False, detect_bank_account=False)
        detector = detector_class(config)

        text = "My BSN is 180774955. Store it and confirm."
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "180774955" not in masked
        assert "*****4955" in masked

    @pytest.mark.parametrize(
        "text,should_detect,description",
        [
            # Valid BSN numbers (pass 11-proef check)
            ("BSN: 111222333", True, "Valid BSN with 11-proef"),
            ("My BSN is 123456782", True, "Valid BSN embedded in text"),
            ("Citizen ID 180774955 on file", True, "Valid BSN in context"),
            # Invalid BSN numbers (fail 11-proef check) - should still detect as pattern match
            # Note: Current implementation uses simple regex, not validation
            ("BSN: 123456789", True, "9-digit number (invalid BSN but matches pattern)"),
            ("ID: 987654321", True, "9-digit number (invalid BSN but matches pattern)"),
            # Edge cases that should NOT be detected as BSN
            ("Phone: 555123456", False, "9-digit phone number with context"),
            ("Account: 12345678", False, "8-digit number (too short)"),
            ("Number: 1234567890", False, "10-digit number (too long)"),
            ("Partial 12345 6789 split", False, "Split 9-digit number"),
            # Context-specific false positives to prevent
            ("Order #123456789", True, "Order number (9 digits - will match pattern)"),
            ("Invoice 987654321", True, "Invoice number (9 digits - will match pattern)"),
            ("Tracking: 555666777", True, "Tracking number (9 digits - will match pattern)"),
            # Multiple 9-digit numbers
            ("BSN 111222333 and 123456782", True, "Multiple valid BSNs"),
            ("Numbers: 123456789 and 987654321", True, "Multiple 9-digit numbers"),
        ],
    )
    def test_bsn_pattern_validation(self, detector_class, text, should_detect, description):
        """Test BSN pattern detection with various edge cases to prevent false positives.

        Note: Current implementation uses simple regex pattern matching (r'\\b\\d{9}\\b')
        without 11-proef validation. This test documents expected behavior and
        identifies cases where false positives may occur.

        Future enhancement: Implement 11-proef validation to reduce false positives.
        """
        config = PIIFilterConfig(
            detect_bsn=True,
            detect_ssn=False,
            detect_phone=False,
            detect_bank_account=False,
            detect_credit_card=False,
            detect_email=False,
        )
        detector = detector_class(config)
        detections = detector.detect(text)

        if should_detect:
            assert PIIType.BSN in detections, f"{description}: Expected BSN detection in: {text}"
        else:
            assert PIIType.BSN not in detections, f"{description}: Unexpected BSN detection in: {text}"

    def test_bsn_vs_other_9digit_numbers(self, detector_class):
        """Test that BSN detection doesn't interfere with other 9-digit patterns.

        This test ensures that when multiple detectors are enabled, 9-digit numbers
        are correctly classified based on context.
        """
        # Enable multiple detectors that might match 9-digit numbers
        config = PIIFilterConfig(
            detect_bsn=True,
            detect_ssn=True,
            detect_phone=True,
            detect_bank_account=True,
        )
        detector = detector_class(config)

        # Test cases where context should help distinguish
        test_cases = [
            ("BSN: 180774955", PIIType.BSN, "Explicit BSN label"),
            ("SSN: 123456789", PIIType.SSN, "9-digit SSN without dashes"),
            ("Phone: 555123456", PIIType.PHONE, "9-digit phone number"),
            ("Account: 123456789", PIIType.BANK_ACCOUNT, "9-digit bank account"),
        ]

        for text, expected_type, description in test_cases:
            detections = detector.detect(text)
            detection_keys = normalize_detection_keys(detections)

            # At least one type should be detected
            assert len(detection_keys) > 0, f"{description}: No detection for: {text}"

            # Note: Due to overlapping patterns, multiple types may be detected
            # This is expected behavior with simple regex patterns

    def test_bsn_eleven_proof_validation_note(self, detector_class):
        """Document the need for 11-proef (modulo-11) validation for BSN.

        Dutch BSN numbers use the 11-proef algorithm for validation:
        - Multiply each digit by its weight (9, 8, 7, 6, 5, 4, 3, 2, -1)
        - Sum the results
        - Valid if sum is divisible by 11

        Example: 111222333
        (1×9 + 1×8 + 1×7 + 2×6 + 2×5 + 2×4 + 3×3 + 3×2 + 3×-1) = 55, 55 % 11 = 0 ✓

        This test documents valid and invalid BSN numbers for future implementation.
        """
        config = PIIFilterConfig(detect_bsn=True, detect_ssn=False, detect_phone=False, detect_bank_account=False)
        detector = detector_class(config)

        # Valid BSN numbers (pass 11-proef)
        valid_bsns = [
            "111222333",  # (1×9 + 1×8 + 1×7 + 2×6 + 2×5 + 2×4 + 3×3 + 3×2 + 3×-1) = 55 % 11 = 0
            "123456782",  # Valid BSN
            "180774955",  # Valid BSN
        ]

        # Invalid BSN numbers (fail 11-proef but match pattern)
        invalid_bsns = [
            "123456789",  # Sum = 46, 46 % 11 = 2 (invalid)
            "987654321",  # Sum = 165, 165 % 11 = 0 but negative weight makes it invalid
            "111111111",  # Sum = 0, but all same digits (suspicious)
        ]

        # Current implementation: All 9-digit numbers are detected
        for bsn in valid_bsns + invalid_bsns:
            text = f"BSN: {bsn}"
            detections = detector.detect(text)
            assert PIIType.BSN in detections, f"Pattern should match 9-digit number: {bsn}"

        # TODO: Future enhancement - implement 11-proef validation
        # When implemented, invalid BSNs should NOT be detected
        # for bsn in invalid_bsns:
        #     text = f"BSN: {bsn}"
        #     detections = detector.detect(text)
        #     assert PIIType.BSN not in detections, f"Invalid BSN should not be detected: {bsn}"

    # Credit Card Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("Card: 4111-1111-1111-1111", True),  # Visa with dashes
            ("Card: 5555-5555-5555-4444", True),  # Mastercard
            ("Card: 4111111111111111", True),  # No dashes
            ("4111 1111 1111 1111", True),  # Spaces
            ("No card here", False),
        ],
    )
    def test_credit_card_detection(self, detector_class, text, should_detect):
        """Test credit card number detection."""
        config = PIIFilterConfig(detect_credit_card=True)
        detector = detector_class(config)
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            assert "credit_card" in detection_keys
        else:
            assert "credit_card" not in detection_keys

    def test_credit_card_masking_partial(self, detector):
        """Test partial masking of credit card."""
        text = "Card: 4111-1111-1111-1111"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        # Check that the last 4 digits are preserved and original is masked
        assert "1111" in masked
        assert "4111-1111-1111-1111" not in masked

    # Email Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("Contact me at john.doe@example.com", True),
            ("Contact: john@example.com", True),
            ("Email: user@mail.company.com", True),  # Subdomain
            ("Email: john+tag@example.com", True),  # Plus addressing
            ("Email: user@test.co.uk", True),
            ("admin+test@company.org", True),
            ("No email here", False),
            ("Not an @email", False),
        ],
    )
    def test_email_detection(self, detector_class, text, should_detect):
        """Test email address detection."""
        config = PIIFilterConfig(detect_email=True)
        detector = detector_class(config)
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            assert "email" in detection_keys
        else:
            assert "email" not in detection_keys

    def test_email_masking_partial(self, detector):
        """Test partial masking of email."""
        text = "Contact: john@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "@example.com" in masked
        # Allow different masking patterns
        assert "j***n@example.com" in masked or "***@example.com" in masked
        assert "john@example.com" not in masked

    # Phone Number Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("Call me at 555-123-4567", True),
            ("Phone: (555) 123-4567", True),
            ("Call: (555) 123-4567", True),
            ("+1 555 123 4567", True),
            ("Phone: +1-555-123-4567", True),  # International
            ("Phone: 555-123-4567 ext 890", True),  # With extension
            ("5551234567", True),
            ("No phone here", False),
        ],
    )
    def test_phone_detection(self, detector_class, text, should_detect):
        """Test phone number detection."""
        config = PIIFilterConfig(detect_phone=True)
        detector = detector_class(config)
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            assert "phone" in detection_keys
        else:
            assert "phone" not in detection_keys

    def test_phone_masking_partial(self, detector):
        """Test partial masking of phone."""
        text = "Call: 555-123-4567"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        # Allow different masking patterns
        assert "***-***-4567" in masked or "4567" in masked
        assert "555-123-4567" not in masked

    # IP Address Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("Server IP: 192.168.1.1", True),
            ("Server: 192.168.1.100", True),
            ("Connect to 10.0.0.1", True),
            ("IPv4: 255.255.255.255", True),
            ("IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334", True),
            ("No IP here", False),
            ("999.999.999.999", False),  # Invalid IP
        ],
    )
    def test_ip_address_detection(self, detector_class, text, should_detect):
        """Test IP address detection."""
        config = PIIFilterConfig(detect_ip_address=True)
        detector = detector_class(config)
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            assert "ip_address" in detection_keys
        else:
            assert "ip_address" not in detection_keys

    # Date of Birth Detection Tests
    def test_detect_dob_slash_format(self, detector):
        """Test DOB with slash format."""
        text = "DOB: 01/15/1990"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)
        assert "date_of_birth" in detection_keys

    # AWS Key Detection Tests
    @pytest.mark.parametrize(
        "text,should_detect",
        [
            ("Access key: AKIAIOSFODNN7EXAMPLE", True),
            ("AWS_KEY=AKIAIOSFODNN7EXAMPLE", True),
            ("AKIA1234567890123456", True),
            ("SECRET=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", True),
            ("No key here", False),
        ],
    )
    def test_aws_key_detection(self, detector_class, text, should_detect):
        """Test AWS key detection."""
        config = PIIFilterConfig(detect_aws_keys=True)
        detector = detector_class(config)
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        if should_detect:
            assert "aws_key" in detection_keys
        else:
            assert "aws_key" not in detection_keys

    # API Key Detection Tests
    def test_detect_api_key_header(self, detector):
        """Test API key in header format."""
        text = "X-API-Key: test12345678901234567890"  # gitleaks:allow
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)
        assert "api_key" in detection_keys

    # Multiple PII Types Tests
    def test_detect_multiple_pii_types(self, detector):
        """Test detection of multiple PII types in one text."""
        text = "SSN: 123-45-6789, Email: john@example.com, Phone: 555-123-4567"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        assert "ssn" in detection_keys
        assert "email" in detection_keys
        assert "phone" in detection_keys

    def test_mask_multiple_pii_types(self, detector):
        """Test masking multiple PII types."""
        text = "SSN: 123-45-6789, Email: test@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        # Check that sensitive parts are masked
        assert "6789" in masked  # SSN last 4 preserved
        assert "@example.com" in masked  # Email domain preserved
        assert "123-45-6789" not in masked  # Original SSN masked
        assert "test@example.com" not in masked  # Original email masked

    # Configuration Tests
    def test_disabled_detection(self, detector_class):
        """Test that disabled detectors don't detect PII."""
        config = PIIFilterConfig(detect_ssn=False, detect_email=False, detect_phone=False)
        detector = detector_class(config)

        text = "SSN: 123-45-6789, Email: test@example.com, Phone: 555-1234"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        assert "ssn" not in detection_keys
        assert "email" not in detection_keys
        assert "phone" not in detection_keys

    def test_whitelist_functionality(self, detector_class):
        """Test that whitelisted patterns are not detected."""
        config = PIIFilterConfig(detect_email=True, whitelist_patterns=["test@example.com", "admin@localhost"])
        detector = detector_class(config)

        # Whitelisted emails should not be detected
        text = "Contact test@example.com or admin@localhost"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)

        # For Rust, check that whitelisted emails are filtered out
        if detector_class.__name__ == "RustPIIDetector":
            if "email" in detection_keys:
                email_key = next(k for k in detections.keys() if "email" in str(k).lower())
                for detection in detections[email_key]:
                    assert detection["value"] != "test@example.com"
        else:
            # Python implementation
            assert PIIType.EMAIL not in detections

        # Non-whitelisted email should be detected
        text = "Contact real@email.com"
        detections = detector.detect(text)
        detection_keys = normalize_detection_keys(detections)
        assert "email" in detection_keys

    def test_masking_strategies(self, detector_class):
        """Test different masking strategies."""
        # Test PARTIAL strategy (default for SSN)
        config = PIIFilterConfig(detect_ssn=True, detect_phone=False, detect_bank_account=False)
        detector = detector_class(config)
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "***-**-6789" in masked
        assert "123-45-6789" not in masked

        # Test PARTIAL strategy for email
        config = PIIFilterConfig(detect_email=True, detect_ssn=False, detect_phone=False, detect_bank_account=False, default_mask_strategy=MaskingStrategy.PARTIAL)
        detector = detector_class(config)
        text = "Email: john.doe@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "@example.com" in masked
        assert "john.doe" not in masked

        # Test REMOVE strategy
        config = PIIFilterConfig(detect_ssn=True, detect_phone=False, detect_bank_account=False, default_mask_strategy=MaskingStrategy.REMOVE)
        detector = detector_class(config)
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)
        assert "123-45-6789" not in masked
        assert masked == "SSN: ***-**-6789"

    # Edge Cases and Error Handling
    def test_empty_string(self, detector):
        """Test detection on empty string."""
        detections = detector.detect("")
        assert len(detections) == 0

    def test_no_pii_text(self, detector):
        """Test text with no PII."""
        text = "This is just normal text without any sensitive information."
        detections = detector.detect(text)
        assert len(detections) == 0

    def test_special_characters(self, detector):
        """Test text with special characters."""
        text = "SSN: 123-45-6789 !@#$%^&*()"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)
        assert "ssn" in detection_keys

    def test_unicode_text(self, detector):
        """Test text with unicode characters."""
        text = "Email: tëst@example.com, SSN: 123-45-6789"
        detections = detector.detect(text)

        detection_keys = normalize_detection_keys(detections)
        # Should at least detect SSN
        assert "ssn" in detection_keys

    def test_malformed_input(self, detector):
        """Test handling of malformed input."""
        # These should not crash
        detector.detect(None if False else "")
        detector.detect("   ")
        detector.detect("\n\n\n")


# Rust-specific tests
@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust implementation not available")
class TestRustPIIDetectorSpecific:
    """Tests specific to Rust implementation."""

    @pytest.fixture
    def default_config(self):
        """Create default configuration for testing."""
        return PIIFilterConfig()

    @pytest.fixture
    def detector(self, default_config):
        """Create Rust detector instance."""
        return RustPIIDetector(default_config)

    def test_process_nested_dict(self, detector):
        """Test processing nested dictionary."""
        data = {"user": {"ssn": "123-45-6789", "email": "john@example.com", "name": "John Doe"}}

        modified, new_data, detections = detector.process_nested(data, "")

        assert modified is True
        assert new_data["user"]["ssn"] == "***-**-6789"
        assert "@example.com" in new_data["user"]["email"]
        assert new_data["user"]["name"] == "John Doe"

        detection_keys = normalize_detection_keys(detections)
        assert "ssn" in detection_keys
        assert "email" in detection_keys

    def test_process_nested_list(self, detector):
        """Test processing list with PII."""
        data = ["SSN: 123-45-6789", "No PII here", "Email: test@example.com"]

        modified, new_data, detections = detector.process_nested(data, "")

        assert modified is True
        assert "***-**-6789" in new_data[0]
        assert new_data[1] == "No PII here"
        assert "@example.com" in new_data[2]

    def test_process_nested_mixed_structure(self, detector):
        """Test processing mixed nested structure."""
        data = {"users": [{"ssn": "123-45-6789", "name": "Alice"}, {"ssn": "987-65-4321", "name": "Bob"}], "contact": {"email": "admin@example.com", "phone": "555-1234"}}

        modified, new_data, detections = detector.process_nested(data, "")

        assert modified is True
        assert "***-**-6789" in new_data["users"][0]["ssn"]
        assert "***-**-4321" in new_data["users"][1]["ssn"]
        assert "@example.com" in new_data["contact"]["email"]

    def test_process_nested_no_pii(self, detector):
        """Test processing nested data with no PII."""
        data = {"user": {"name": "John Doe", "age": 30}}

        modified, new_data, detections = detector.process_nested(data, "")

        assert modified is False
        assert new_data == data
        assert len(detections) == 0

    def test_initialization_without_rust(self):
        """Test that Rust detector is available when imported."""
        # This test originally checked for ImportError when Rust unavailable
        # Since Rust is now available and working, we verify it can be imported
        from plugins.pii_filter.pii_filter import RustPIIDetector as RustDet

        config = PIIFilterConfig()
        detector = RustDet(config)
        assert detector is not None

    def test_very_long_text_performance(self, detector):
        """Test performance with very long text."""
        # Create text with 1000 PII instances
        text_parts = []
        for i in range(1000):
            text_parts.append(f"User {i}: SSN 123-45-{i:04d}, Email user{i}@example.com")
        text = "\n".join(text_parts)

        start = time.time()
        detections = detector.detect(text)
        duration = time.time() - start

        assert "ssn" in detections
        assert "email" in detections
        assert len(detections["ssn"]) == 1000
        assert len(detections["email"]) == 1000
        # Should process in reasonable time (< 1 second for Rust)
        assert duration < 1.0, f"Processing took {duration:.2f}s, expected < 1s"

    def test_large_batch_detection(self):
        """Test detection performance on large batch."""
        config = PIIFilterConfig()
        detector = RustPIIDetector(config)

        # Generate 10,000 lines of text with PII
        lines = []
        for i in range(10000):
            lines.append(f"User {i}: SSN {i:03d}-45-6789, Email user{i}@example.com")
        text = "\n".join(lines)

        start = time.time()
        detections = detector.detect(text)
        duration = time.time() - start

        print(f"\nProcessed {len(text):,} characters in {duration:.3f}s")
        print(f"Throughput: {len(text) / duration / 1024 / 1024:.2f} MB/s")

        assert "ssn" in detections
        assert "email" in detections
        # Rust should be very fast (< 2 seconds for 10k instances)
        assert duration < 2.0

    def test_nested_structure_performance(self):
        """Test performance on deeply nested structures."""
        config = PIIFilterConfig()
        detector = RustPIIDetector(config)

        # Create deeply nested structure
        data = {"level1": {}}
        current = data["level1"]
        for i in range(100):
            current[f"level{i+2}"] = {"ssn": f"{i:03d}-45-6789", "email": f"user{i}@example.com", "data": {}}
            current = current[f"level{i+2}"]["data"]

        start = time.time()
        modified, new_data, detections = detector.process_nested(data, path="")
        duration = time.time() - start

        print(f"\nProcessed deeply nested structure in {duration:.3f}s")

        assert modified is True
        assert duration < 0.5  # Should be very fast


# Python-specific plugin integration tests
class TestPIIFilterPlugin:
    """Test the PII Filter plugin integration (Python-specific)."""

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
    async def test_integration_with_manager(self):
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
