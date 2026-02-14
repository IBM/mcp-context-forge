# -*- coding: utf-8 -*-
"""
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Differential testing: Ensure Rust and Python implementations produce identical results

NOTE: These tests compare the Rust and Python implementations to ensure they produce
identical detection results for all inputs.
"""

import pytest
from pathlib import Path
import sys

# Add plugins directory to path to import secrets_detection
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "plugins" / "secrets_detection"))

from secrets_detection import _scan_container, SecretsDetectionConfig

# Try to import Rust implementation
try:
    import secret_detection as rust_secret_detection
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    rust_secret_detection = None


@pytest.mark.skipif(not RUST_AVAILABLE, reason="Rust implementation not available")
class TestDifferentialSecretsDetection:
    """
    Differential tests comparing Rust vs Python implementations.

    These tests ensure that the Rust implementation produces EXACTLY
    the same results as the Python implementation for all inputs.
    """

    @pytest.fixture
    def config(self):
        """Create default config."""
        return SecretsDetectionConfig()

    def assert_detections_equal(self, python_result, rust_result, data):
        """
        Assert that detection results from Python and Rust are identical.

        Args:
            python_result: Tuple (count, redacted_container, all_findings) from Python
            rust_result: Tuple (count, redacted_container, all_findings) from Rust
            data: Original data (for error messages)
        """
        py_count, py_redacted, py_findings = python_result
        rust_count, rust_redacted, rust_findings = rust_result

        # Check same count
        assert py_count == rust_count, \
            f"Different secret counts.\nData: {data}\nPython: {py_count}\nRust: {rust_count}"

        # Check same number of findings
        assert len(py_findings) == len(rust_findings), \
            f"Different number of findings.\nData: {data}\nPython: {len(py_findings)}\nRust: {len(rust_findings)}"

        # Sort findings for comparison (by type and match preview)
        py_sorted = sorted(py_findings, key=lambda f: (f.get("type", ""), f.get("match", "")))
        rust_sorted = sorted(rust_findings, key=lambda f: (f.get("type", ""), f.get("match", "")))

        for i, (py_finding, rust_finding) in enumerate(zip(py_sorted, rust_sorted)):
            assert py_finding.get("type") == rust_finding.get("type"), \
                f"Finding {i} type mismatch.\nPython: {py_finding.get('type')}\nRust: {rust_finding.get('type')}"
            assert py_finding.get("match") == rust_finding.get("match"), \
                f"Finding {i} match mismatch.\nPython: {py_finding.get('match')}\nRust: {rust_finding.get('match')}"

        # Check redacted data matches
        assert py_redacted == rust_redacted, \
            f"Redacted data mismatch.\nPython: {py_redacted}\nRust: {rust_redacted}"

    # AWS Credentials Tests
    def test_aws_access_key(self, config):
        """Test AWS access key detection."""
        data = {"message": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_aws_secret_key(self, config):
        """Test AWS secret key detection."""
        data = {"message": "AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_aws_both_keys(self, config):
        """Test both AWS keys together."""
        data = {"message": "AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Slack Token Tests
    def test_slack_bot_token(self, config):
        """Test Slack bot token detection."""
        data = {"message": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_slack_user_token(self, config):
        """Test Slack user token detection."""
        data = {"message": "xoxq-fake000000-fake000000000-fakefakefakefake"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Google API Key Tests
    def test_google_api_key(self, config):
        """Test Google API key detection."""
        data = {"message": "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # JWT Token Tests
    def test_jwt_token(self, config):
        """Test JWT token detection."""
        data = {"message": "eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Generic Secret Tests
    def test_generic_secret_key(self, config):
        """Test generic secret key detection."""
        data = {"message": "secret_key=00face00dead00beef00cafe00fade0000000000000000000000000000000000"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_base64_secret(self, config):
        """Test base64 encoded secret detection."""
        data = {"message": "dGhpcyBpcyBhIGJhc2U2NCBlbmNvZGVkIHNlY3JldCBrZXkgZm9yIHRlc3RpbmcgcHVycG9zZXM="}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Multiple Secrets Tests
    def test_multiple_secrets(self, config):
        """Test multiple secrets in one message."""
        data = {
            "message": "AWS_KEY=AKIAFAKE12345EXAMPLE and Slack token xoxr-fake-000000000-fake000000000-fakefakefakefake"
        }
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Nested Data Tests
    def test_nested_dict(self, config):
        """Test nested dictionary processing."""
        data = {
            "user": {
                "credentials": {
                    "aws_key": "AKIAFAKE12345EXAMPLE",
                    "slack_token": "xoxr-fake-000000000-fake000000000-fakefakefakefake"
                }
            }
        }
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_nested_list(self, config):
        """Test nested list processing."""
        data = {
            "messages": [
                "AWS_KEY=AKIAFAKE12345EXAMPLE",
                "No secrets here",
                "Slack: xoxr-fake-000000000-fake000000000-fakefakefakefake"
            ]
        }
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_nested_mixed(self, config):
        """Test mixed nested structure."""
        data = {
            "users": [
                {"name": "Alice", "key": "AKIAFAKE12345EXAMPLE"},
                {"name": "Bob", "token": "xoxr-fake-000000000-fake000000000-fakefakefakefake"}
            ],
            "config": {
                "api_key": "AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345"
            }
        }
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Edge Cases
    def test_empty_string(self, config):
        """Test empty string."""
        data = {"message": ""}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_no_secrets(self, config):
        """Test text with no secrets."""
        data = {"message": "This is just normal text without any sensitive information."}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    def test_special_characters(self, config):
        """Test special characters."""
        data = {"message": "AWS_KEY=AKIAFAKE12345EXAMPLE !@#$%^&*()"}
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Conversation Format Tests
    def test_conversation_format(self, config):
        """Test realistic conversation format."""
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": "I'm setting up AWS. What are best practices?",
                    "timestamp": "2024-01-01T00:00:00Z"
                },
                {
                    "role": "assistant",
                    "content": "Here are my credentials: AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE",
                    "timestamp": "2024-01-01T00:00:01Z"
                }
            ]
        }
        py_result = _scan_container(data, config, use_rust=False)
        rust_result = rust_secret_detection.py_scan_container(data, config)
        self.assert_detections_equal(py_result, rust_result, data)

    # Stress Tests
    @pytest.mark.slow
    def test_large_data(self, config):
        """Test with large data (performance comparison)."""
        # Generate large data with 100 secrets
        messages = []
        for i in range(100):
            messages.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"AWS_KEY_{i}=AKIAFAKE12345EXAMPLE and token xoxr-fake-{i:09d}-fake000000000-fakefake"
            })
        data = {"messages": messages}

        import time

        # Python detection
        py_start = time.time()
        py_result = _scan_container(data, config, use_rust=False)
        py_duration = time.time() - py_start

        # Rust detection
        rust_start = time.time()
        rust_result = rust_secret_detection.py_scan_container(data, config)
        rust_duration = time.time() - rust_start

        # Verify results match
        self.assert_detections_equal(py_result, rust_result, "large data")

        # Report speedup
        speedup = py_duration / rust_duration if rust_duration > 0 else 0
        print(f"\n{'=' * 60}")
        print("Performance Comparison: 100 messages with secrets")
        print(f"{'=' * 60}")
        print(f"Python: {py_duration:.3f}s")
        print(f"Rust:   {rust_duration:.3f}s")
        print(f"Speedup: {speedup:.1f}x")
        print(f"{'=' * 60}")

        # Rust should be faster
        assert speedup >= 1.0, f"Rust should be faster, got {speedup:.1f}x"

    @pytest.mark.slow
    def test_deeply_nested_structure(self, config):
        """Test deeply nested structure (performance comparison)."""
        # Create deeply nested structure
        data = {"level1": {}}
        current = data["level1"]
        for i in range(50):
            current[f"level{i + 2}"] = {
                "aws_key": f"AKIAFAKE12345EXAMPLE{i:03d}",
                "slack_token": f"xoxr-fake-{i:09d}-fake000000000-fakefake",
                "data": {}
            }
            current = current[f"level{i + 2}"]["data"]

        import time

        # Python processing
        py_start = time.time()
        py_result = _scan_container(data, config, use_rust=False)
        py_duration = time.time() - py_start

        # Rust processing
        rust_start = time.time()
        rust_result = rust_secret_detection.py_scan_container(data, config)
        rust_duration = time.time() - rust_start

        # Verify results match
        self.assert_detections_equal(py_result, rust_result, "deeply nested")

        # Report speedup
        speedup = py_duration / rust_duration if rust_duration > 0 else 0
        print(f"\n{'=' * 60}")
        print("Nested Structure Performance: 50 levels deep")
        print(f"{'=' * 60}")
        print(f"Python: {py_duration:.3f}s")
        print(f"Rust:   {rust_duration:.3f}s")
        print(f"Speedup: {speedup:.1f}x")
        print(f"{'=' * 60}")


def test_rust_python_compatibility():
    """
    Meta-test to ensure both implementations are available for comparison.
    """
    if not RUST_AVAILABLE:
        pytest.skip("Rust implementation not available - build with: cd plugins_rust/secrets_detection && maturin develop --release")

    # Verify both implementations can be called
    config = SecretsDetectionConfig()
    data = {"message": "test"}

    py_result = _scan_container(data, config, use_rust=False)
    rust_result = rust_secret_detection.py_scan_container(data, config)

    assert py_result is not None
    assert rust_result is not None

    print("\n✓ Both Python and Rust implementations available for differential testing")
