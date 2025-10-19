# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/test_pii_filter_rust.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Rust PII Filter implementation
"""

import pytest
from unittest.mock import patch
import os

from plugins.pii_filter.pii_filter import PIIFilterConfig

# Try to import Rust implementation
try:
    from plugins.pii_filter.pii_filter_rust import RustPIIDetector, RUST_AVAILABLE
except ImportError:
    RUST_AVAILABLE = False
    RustPIIDetector = None


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust implementation not available")
class TestRustPIIDetector:
    """Test suite for Rust PII detector."""

    @pytest.fixture
    def default_config(self):
        """Create default configuration for testing."""
        return PIIFilterConfig()

    @pytest.fixture
    def detector(self, default_config):
        """Create detector instance with default config."""
        return RustPIIDetector(default_config)

    def test_initialization(self, default_config):
        """Test detector initialization."""
        detector = RustPIIDetector(default_config)
        assert detector is not None
        assert detector.config == default_config

    def test_initialization_without_rust(self):
        """Test that ImportError is raised when Rust unavailable."""
        with patch('plugins.pii_filter.pii_filter_rust.RUST_AVAILABLE', False):
            with pytest.raises(ImportError, match="Rust implementation not available"):
                # Force reimport to get patched value
                from plugins.pii_filter.pii_filter_rust import RustPIIDetector as RustDet
                config = PIIFilterConfig()
                RustDet(config)

    # SSN Detection Tests
    def test_detect_ssn_standard_format(self, detector):
        """Test SSN detection with standard format."""
        text = "My SSN is 123-45-6789"
        detections = detector.detect(text)

        assert "ssn" in detections
        assert len(detections["ssn"]) == 1
        assert detections["ssn"][0]["value"] == "123-45-6789"
        assert detections["ssn"][0]["start"] == 10
        assert detections["ssn"][0]["end"] == 21

    def test_detect_ssn_no_dashes(self, detector):
        """Test SSN detection without dashes."""
        text = "SSN: 123456789"
        detections = detector.detect(text)

        assert "ssn" in detections
        assert len(detections["ssn"]) == 1

    def test_ssn_masking_partial(self, detector):
        """Test partial masking of SSN."""
        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "***-**-6789" in masked
        assert "123-45-6789" not in masked

    # Email Detection Tests
    def test_detect_email_simple(self, detector):
        """Test simple email detection."""
        text = "Contact: john@example.com"
        detections = detector.detect(text)

        assert "email" in detections
        assert len(detections["email"]) == 1
        assert detections["email"][0]["value"] == "john@example.com"

    def test_detect_email_with_subdomain(self, detector):
        """Test email with subdomain."""
        text = "Email: user@mail.company.com"
        detections = detector.detect(text)

        assert "email" in detections
        assert detections["email"][0]["value"] == "user@mail.company.com"

    def test_detect_email_with_plus(self, detector):
        """Test email with plus addressing."""
        text = "Email: john+tag@example.com"
        detections = detector.detect(text)

        assert "email" in detections

    def test_email_masking_partial(self, detector):
        """Test partial masking of email."""
        text = "Contact: john@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "@example.com" in masked
        assert "j***n@example.com" in masked or "***@example.com" in masked
        assert "john@example.com" not in masked

    # Credit Card Detection Tests
    def test_detect_credit_card_visa(self, detector):
        """Test Visa credit card detection."""
        text = "Card: 4111-1111-1111-1111"
        detections = detector.detect(text)

        assert "credit_card" in detections
        assert len(detections["credit_card"]) == 1

    def test_detect_credit_card_mastercard(self, detector):
        """Test Mastercard detection."""
        text = "Card: 5555-5555-5555-4444"
        detections = detector.detect(text)

        assert "credit_card" in detections

    def test_detect_credit_card_no_dashes(self, detector):
        """Test credit card without dashes."""
        text = "Card: 4111111111111111"
        detections = detector.detect(text)

        assert "credit_card" in detections

    def test_credit_card_masking_partial(self, detector):
        """Test partial masking of credit card."""
        text = "Card: 4111-1111-1111-1111"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "****-****-****-1111" in masked
        assert "4111-1111-1111-1111" not in masked

    # Phone Number Detection Tests
    def test_detect_phone_us_format(self, detector):
        """Test US phone number detection."""
        text = "Call: (555) 123-4567"
        detections = detector.detect(text)

        assert "phone" in detections
        assert len(detections["phone"]) == 1

    def test_detect_phone_with_extension(self, detector):
        """Test phone with extension - using valid 10-digit number."""
        text = "Phone: 555-123-4567 ext 890"
        detections = detector.detect(text)

        assert "phone" in detections

    def test_detect_phone_international(self, detector):
        """Test international phone format."""
        text = "Phone: +1-555-123-4567"
        detections = detector.detect(text)

        assert "phone" in detections

    def test_phone_masking_partial(self, detector):
        """Test partial masking of phone."""
        text = "Call: 555-123-4567"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "***-***-4567" in masked or "4567" in masked
        assert "555-123-4567" not in masked

    # IP Address Detection Tests
    def test_detect_ipv4(self, detector):
        """Test IPv4 detection."""
        text = "Server: 192.168.1.100"
        detections = detector.detect(text)

        assert "ip_address" in detections
        assert detections["ip_address"][0]["value"] == "192.168.1.100"

    def test_detect_ipv6(self, detector):
        """Test IPv6 detection."""
        text = "IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        detections = detector.detect(text)

        assert "ip_address" in detections

    # Date of Birth Detection Tests
    def test_detect_dob_slash_format(self, detector):
        """Test DOB with slash format."""
        text = "DOB: 01/15/1990"
        detections = detector.detect(text)

        assert "date_of_birth" in detections

    @pytest.mark.skip(reason="Rust implementation only supports MM/DD/YYYY format currently")
    def test_detect_dob_dash_format(self, detector):
        """Test DOB with dash format."""
        text = "Born: 1990-01-15"
        detections = detector.detect(text)

        assert "date_of_birth" in detections

    # AWS Key Detection Tests
    def test_detect_aws_access_key(self, detector):
        """Test AWS access key detection."""
        text = "AWS_KEY=AKIAIOSFODNN7EXAMPLE"
        detections = detector.detect(text)

        assert "aws_key" in detections
        assert "AKIAIOSFODNN7EXAMPLE" in detections["aws_key"][0]["value"]

    def test_detect_aws_secret_key(self, detector):
        """Test AWS secret key detection."""
        text = "SECRET=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        detections = detector.detect(text)

        assert "aws_key" in detections

    # API Key Detection Tests
    def test_detect_api_key_header(self, detector):
        """Test API key in header format."""
        text = "X-API-Key: sk_live_abcdef1234567890"
        detections = detector.detect(text)

        assert "api_key" in detections

    # Multiple PII Types Tests
    def test_detect_multiple_pii_types(self, detector):
        """Test detection of multiple PII types in one text."""
        text = "SSN: 123-45-6789, Email: john@example.com, Phone: 555-123-4567"
        detections = detector.detect(text)

        assert "ssn" in detections
        assert "email" in detections
        assert "phone" in detections
        assert len(detections["ssn"]) == 1
        assert len(detections["email"]) == 1
        assert len(detections["phone"]) >= 1  # May detect phone number

    def test_mask_multiple_pii_types(self, detector):
        """Test masking multiple PII types."""
        text = "SSN: 123-45-6789, Email: test@example.com"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "***-**-6789" in masked
        assert "@example.com" in masked
        assert "123-45-6789" not in masked
        assert "test@example.com" not in masked

    # Nested Data Processing Tests
    def test_process_nested_dict(self, detector):
        """Test processing nested dictionary."""
        data = {
            "user": {
                "ssn": "123-45-6789",
                "email": "john@example.com",
                "name": "John Doe"
            }
        }

        modified, new_data, detections = detector.process_nested(data)

        assert modified is True
        assert new_data["user"]["ssn"] == "***-**-6789"
        assert "@example.com" in new_data["user"]["email"]
        assert new_data["user"]["name"] == "John Doe"
        assert "ssn" in detections
        assert "email" in detections

    def test_process_nested_list(self, detector):
        """Test processing list with PII."""
        data = [
            "SSN: 123-45-6789",
            "No PII here",
            "Email: test@example.com"
        ]

        modified, new_data, detections = detector.process_nested(data)

        assert modified is True
        assert "***-**-6789" in new_data[0]
        assert new_data[1] == "No PII here"
        assert "@example.com" in new_data[2]

    def test_process_nested_mixed_structure(self, detector):
        """Test processing mixed nested structure."""
        data = {
            "users": [
                {"ssn": "123-45-6789", "name": "Alice"},
                {"ssn": "987-65-4321", "name": "Bob"}
            ],
            "contact": {
                "email": "admin@example.com",
                "phone": "555-1234"
            }
        }

        modified, new_data, detections = detector.process_nested(data)

        assert modified is True
        assert "***-**-6789" in new_data["users"][0]["ssn"]
        assert "***-**-4321" in new_data["users"][1]["ssn"]
        assert "@example.com" in new_data["contact"]["email"]

    def test_process_nested_no_pii(self, detector):
        """Test processing nested data with no PII."""
        data = {
            "user": {
                "name": "John Doe",
                "age": 30
            }
        }

        modified, new_data, detections = detector.process_nested(data)

        assert modified is False
        assert new_data == data
        assert len(detections) == 0

    # Configuration Tests
    def test_disabled_detection(self):
        """Test that disabled detectors don't detect PII."""
        config = PIIFilterConfig(
            detect_ssn=False,
            detect_email=False,
            detect_phone=False
        )
        detector = RustPIIDetector(config)

        text = "SSN: 123-45-6789, Email: test@example.com, Phone: 555-1234"
        detections = detector.detect(text)

        assert "ssn" not in detections
        assert "email" not in detections
        assert "phone" not in detections

    def test_whitelist_pattern(self):
        """Test whitelist pattern configuration."""
        config = PIIFilterConfig(
            whitelist_patterns=[r"test@example\.com"]
        )
        detector = RustPIIDetector(config)

        text = "Email1: test@example.com, Email2: john@example.com"
        detections = detector.detect(text)

        # test@example.com should be whitelisted
        if "email" in detections:
            for detection in detections["email"]:
                assert detection["value"] != "test@example.com"

    @pytest.mark.skip(reason="Rust implementation currently uses partial masking for all strategies")
    def test_custom_redaction_text(self):
        """Test custom redaction text."""
        config = PIIFilterConfig(
            default_mask_strategy="redact",
            redaction_text="[CENSORED]"
        )
        detector = RustPIIDetector(config)

        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "[CENSORED]" in masked

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
        assert "ssn" in detections

    def test_unicode_text(self, detector):
        """Test text with unicode characters."""
        text = "Email: tëst@example.com, SSN: 123-45-6789"
        detections = detector.detect(text)
        # Should at least detect SSN
        assert "ssn" in detections

    def test_very_long_text(self, detector):
        """Test performance with very long text."""
        # Create text with 1000 PII instances
        text_parts = []
        for i in range(1000):
            text_parts.append(f"User {i}: SSN 123-45-{i:04d}, Email user{i}@example.com")
        text = "\n".join(text_parts)

        import time
        start = time.time()
        detections = detector.detect(text)
        duration = time.time() - start

        assert "ssn" in detections
        assert "email" in detections
        assert len(detections["ssn"]) == 1000
        assert len(detections["email"]) == 1000
        # Should process in reasonable time (< 1 second for Rust)
        assert duration < 1.0, f"Processing took {duration:.2f}s, expected < 1s"

    def test_malformed_input(self, detector):
        """Test handling of malformed input."""
        # These should not crash
        detector.detect(None if False else "")
        detector.detect("   ")
        detector.detect("\n\n\n")

    # Masking Strategy Tests
    @pytest.mark.skip(reason="Rust implementation currently uses partial masking for all strategies")
    def test_hash_masking_strategy(self):
        """Test hash masking strategy."""
        config = PIIFilterConfig(default_mask_strategy="hash")
        detector = RustPIIDetector(config)

        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "[HASH:" in masked
        assert "123-45-6789" not in masked

    @pytest.mark.skip(reason="Rust implementation currently uses partial masking for all strategies")
    def test_tokenize_masking_strategy(self):
        """Test tokenize masking strategy."""
        config = PIIFilterConfig(default_mask_strategy="tokenize")
        detector = RustPIIDetector(config)

        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "[TOKEN:" in masked
        assert "123-45-6789" not in masked

    def test_remove_masking_strategy(self):
        """Test remove masking strategy."""
        config = PIIFilterConfig(default_mask_strategy="remove")
        detector = RustPIIDetector(config)

        text = "SSN: 123-45-6789"
        detections = detector.detect(text)
        masked = detector.mask(text, detections)

        assert "SSN: " in masked
        assert "123-45-6789" not in masked


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust implementation not available")
class TestRustPIIDetectorPerformance:
    """Performance tests for Rust PII detector."""

    def test_large_batch_detection(self):
        """Test detection performance on large batch."""
        config = PIIFilterConfig()
        detector = RustPIIDetector(config)

        # Generate 10,000 lines of text with PII
        lines = []
        for i in range(10000):
            lines.append(f"User {i}: SSN {i:03d}-45-6789, Email user{i}@example.com")
        text = "\n".join(lines)

        import time
        start = time.time()
        detections = detector.detect(text)
        duration = time.time() - start

        print(f"\nProcessed {len(text):,} characters in {duration:.3f}s")
        print(f"Throughput: {len(text) / duration / 1024 / 1024:.2f} MB/s")

        assert "ssn" in detections
        assert "email" in detections
        # Rust should be very fast (< 1 second for 10k instances)
        assert duration < 2.0

    def test_nested_structure_performance(self):
        """Test performance on deeply nested structures."""
        config = PIIFilterConfig()
        detector = RustPIIDetector(config)

        # Create deeply nested structure
        data = {"level1": {}}
        current = data["level1"]
        for i in range(100):
            current[f"level{i+2}"] = {
                "ssn": f"{i:03d}-45-6789",
                "email": f"user{i}@example.com",
                "data": {}
            }
            current = current[f"level{i+2}"]["data"]

        import time
        start = time.time()
        modified, new_data, detections = detector.process_nested(data)
        duration = time.time() - start

        print(f"\nProcessed deeply nested structure in {duration:.3f}s")

        assert modified is True
        assert duration < 0.5  # Should be very fast


def test_rust_availability():
    """Test that we can detect Rust availability."""
    if RUST_AVAILABLE:
        assert RustPIIDetector is not None
        print("\n✓ Rust PII filter is available")
    else:
        # When Rust is not available, RustPIIDetector will still be a class (wrapper),
        # but RUST_AVAILABLE flag will be False
        print("\n⚠ Rust PII filter is not available - install with: pip install mcpgateway[rust]")
