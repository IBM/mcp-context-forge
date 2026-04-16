# -*- coding: utf-8 -*-
"""Smoke tests for the packaged secrets detection plugin."""

# Third-Party
import pytest

cpex_secrets_detection = pytest.importorskip("cpex_secrets_detection", reason="cpex-secrets-detection extra is not installed")
secrets_detection = pytest.importorskip("cpex_secrets_detection.secrets_detection", reason="cpex-secrets-detection extra is not installed")


def test_secrets_detection_package_exports_expected_symbols():
    assert callable(cpex_secrets_detection.py_scan_container)
    assert secrets_detection.SecretsDetectionPlugin.__name__ == "SecretsDetectionPlugin"
