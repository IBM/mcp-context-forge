#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_container_scanner/test_auth_resolver.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Unit tests for AuthResolver.
"""

from __future__ import annotations

import pytest

from plugins.container_scanner.auth.auth_resolver import AuthResolver
from plugins.container_scanner.config import RegistryConfig, ScannerConfig


def make_config(registries=None) -> ScannerConfig:
    return ScannerConfig(registries=registries or [])


class TestAuthResolverPublicRegistry:
    def test_public_image_returns_empty_dict(self):
        resolver = AuthResolver(make_config())
        result = resolver.resolve("python:3.12-slim")
        assert result == {}

    def test_no_matching_registry_returns_empty_dict(self):
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        resolver = AuthResolver(make_config(registries=[reg]))
        # gcr.io doesn't match ghcr.io
        result = resolver.resolve("gcr.io/myproject/app:latest")
        assert result == {}


class TestAuthResolverTokenAuth:
    def test_token_auth_sets_all_scanner_vars(self, monkeypatch):
        monkeypatch.setenv("GHCR_TOKEN", "secret-token")
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        resolver = AuthResolver(make_config(registries=[reg]))
        result = resolver.resolve("ghcr.io/org/app:v1")
        assert result["TRIVY_USERNAME"] == ""
        assert result["TRIVY_PASSWORD"] == "secret-token"
        assert result["GRYPE_REGISTRY_AUTH_USERNAME"] == ""
        assert result["GRYPE_REGISTRY_AUTH_PASSWORD"] == "secret-token"

    def test_token_auth_raises_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("GHCR_TOKEN", raising=False)
        reg = RegistryConfig(url="ghcr.io", auth_type="token", token_env="GHCR_TOKEN")
        resolver = AuthResolver(make_config(registries=[reg]))
        with pytest.raises(EnvironmentError, match="GHCR_TOKEN"):
            resolver.resolve("ghcr.io/org/app:v1")


class TestAuthResolverBasicAuth:
    def test_basic_auth_sets_credentials(self, monkeypatch):
        monkeypatch.setenv("REG_USER", "myuser")
        monkeypatch.setenv("REG_PASS", "mypass")
        reg = RegistryConfig(url="registry.example.com", auth_type="basic", username_env="REG_USER", password_env="REG_PASS")
        resolver = AuthResolver(make_config(registries=[reg]))
        result = resolver.resolve("registry.example.com/app:latest")
        assert result["TRIVY_USERNAME"] == "myuser"
        assert result["TRIVY_PASSWORD"] == "mypass"
        assert result["GRYPE_REGISTRY_AUTH_USERNAME"] == "myuser"
        assert result["GRYPE_REGISTRY_AUTH_PASSWORD"] == "mypass"

    def test_basic_auth_raises_when_username_missing(self, monkeypatch):
        monkeypatch.delenv("REG_USER", raising=False)
        monkeypatch.setenv("REG_PASS", "mypass")
        reg = RegistryConfig(url="registry.example.com", auth_type="basic", username_env="REG_USER", password_env="REG_PASS")
        resolver = AuthResolver(make_config(registries=[reg]))
        with pytest.raises(EnvironmentError, match="REG_USER"):
            resolver.resolve("registry.example.com/app:latest")

    def test_basic_auth_raises_when_password_missing(self, monkeypatch):
        monkeypatch.setenv("REG_USER", "myuser")
        monkeypatch.delenv("REG_PASS", raising=False)
        reg = RegistryConfig(url="registry.example.com", auth_type="basic", username_env="REG_USER", password_env="REG_PASS")
        resolver = AuthResolver(make_config(registries=[reg]))
        with pytest.raises(EnvironmentError, match="REG_PASS"):
            resolver.resolve("registry.example.com/app:latest")


class TestAuthResolverMatchingLogic:
    def test_first_matching_registry_wins(self, monkeypatch):
        monkeypatch.setenv("TOKEN_A", "tokenA")
        reg_a = RegistryConfig(url="ghcr.io", auth_type="token", token_env="TOKEN_A")
        monkeypatch.setenv("TOKEN_B", "tokenB")
        reg_b = RegistryConfig(url="ghcr.io", auth_type="token", token_env="TOKEN_B")
        resolver = AuthResolver(make_config(registries=[reg_a, reg_b]))
        result = resolver.resolve("ghcr.io/org/app:v1")
        assert result["TRIVY_PASSWORD"] == "tokenA"
