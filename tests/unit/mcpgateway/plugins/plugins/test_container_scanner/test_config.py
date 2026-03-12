#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_config.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for ScannerConfig, RegistryConfig, and _parse_registry_host.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from plugins.container_scanner.config import RegistryConfig, ScannerConfig, _parse_registry_host


class TestParseRegistryHost:
    def test_docker_hub_image(self):
        assert _parse_registry_host("python:3.12-slim") == "docker.io"

    def test_ghcr_image(self):
        assert _parse_registry_host("ghcr.io/org/app:v1") == "ghcr.io"

    def test_gcr_image(self):
        assert _parse_registry_host("gcr.io/myproject/app:latest") == "gcr.io"

    def test_localhost_registry(self):
        assert _parse_registry_host("localhost:5000/app:v1") == "localhost:5000"

    def test_registry_with_port(self):
        assert _parse_registry_host("registry.example.com:443/app:v1") == "registry.example.com:443"


class TestRegistryConfigValidation:
    def test_token_auth_requires_token_env(self):
        with pytest.raises(ValidationError, match="token_env"):
            RegistryConfig(url="ghcr.io", auth_type="token")

    def test_token_auth_valid(self):
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        assert reg.token_env == "GHCR_TOKEN"

    def test_basic_auth_requires_username_and_password(self):
        with pytest.raises(ValidationError):
            RegistryConfig(url="registry.example.com", auth_type="basic", username_env="USER")

    def test_basic_auth_missing_username(self):
        with pytest.raises(ValidationError):
            RegistryConfig(url="registry.example.com", auth_type="basic", password_env="PASS")

    def test_basic_auth_valid(self):
        reg = RegistryConfig(url="registry.example.com", auth_type="basic", username_env="USER", password_env="PASS")
        assert reg.username_env == "USER"
        assert reg.password_env == "PASS"


class TestScannerConfigDefaults:
    def test_default_scanner_is_trivy(self):
        cfg = ScannerConfig()
        assert cfg.scanner == "trivy"

    def test_default_mode_is_enforce(self):
        cfg = ScannerConfig()
        assert cfg.mode == "enforce"

    def test_default_severity_threshold_is_high(self):
        cfg = ScannerConfig()
        assert cfg.severity_threshold == "HIGH"

    def test_default_fail_on_unfixed_is_false(self):
        cfg = ScannerConfig()
        assert cfg.fail_on_unfixed is False

    def test_default_cache_enabled_is_true(self):
        cfg = ScannerConfig()
        assert cfg.cache_enabled is True

    def test_default_on_scan_error_is_fail_closed(self):
        cfg = ScannerConfig()
        assert cfg.on_scan_error == "fail_closed"

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            ScannerConfig(timeout_seconds=0)


class TestScannerConfigRegistryFor:
    def test_returns_matching_registry(self):
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        cfg = ScannerConfig(registries=[reg])
        assert cfg.registry_for("ghcr.io/org/app:v1") is reg

    def test_returns_none_for_unmatched_registry(self):
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        cfg = ScannerConfig(registries=[reg])
        assert cfg.registry_for("gcr.io/project/app:latest") is None

    def test_returns_none_for_public_image(self):
        cfg = ScannerConfig()
        assert cfg.registry_for("python:3.12") is None
