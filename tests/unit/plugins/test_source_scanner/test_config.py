#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_config.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# First-Party
from plugins.source_scanner.config import BanditConfig, SemgrepConfig, SourceScannerConfig


def test_semgrep_config_defaults() -> None:
    """Test SemgrepConfig uses correct default values."""
    config = SemgrepConfig()

    assert config.enabled is True
    assert config.rulesets == ["p/security-audit", "p/owasp-top-ten", "p/python", "p/javascript"]
    assert config.extra_args == []


def test_semgrep_config_custom_values() -> None:
    """Test SemgrepConfig with custom values."""
    config = SemgrepConfig(enabled=False, rulesets=["p/python"], extra_args=["--strict"])

    assert config.enabled is False
    assert config.rulesets == ["p/python"]
    assert config.extra_args == ["--strict"]


def test_bandit_config_defaults() -> None:
    """Test BanditConfig uses correct default values."""
    config = BanditConfig()

    assert config.enabled is True
    assert config.severity == "medium"
    assert config.confidence == "medium"


def test_bandit_config_custom_values() -> None:
    """Test BanditConfig with custom values."""
    config = BanditConfig(enabled=False, severity="high", confidence="low")

    assert config.enabled is False
    assert config.severity == "high"
    assert config.confidence == "low"


def test_source_scanner_config_defaults() -> None:
    """Test SourceScannerConfig uses correct default values."""
    config = SourceScannerConfig()

    assert isinstance(config.semgrep, SemgrepConfig)
    assert isinstance(config.bandit, BanditConfig)
    assert config.severity_threshold == "WARNING"
    assert config.fail_on_critical is True
    assert config.clone_timeout_seconds == 120
    assert config.scan_timeout_seconds == 600
    assert config.max_repo_size_mb == 500
    assert config.github_token_env == "GITHUB_TOKEN"
    assert config.cache_by_commit is True
    assert config.cache_ttl_hours == 168


def test_source_scanner_config_custom_values() -> None:
    """Test SourceScannerConfig with custom configuration values."""
    config = SourceScannerConfig(
        semgrep=SemgrepConfig(enabled=False, rulesets=["p/python"]),
        bandit=BanditConfig(enabled=False, severity="low"),
        severity_threshold="ERROR",
        fail_on_critical=False,
        clone_timeout_seconds=60,
        scan_timeout_seconds=300,
        max_repo_size_mb=1000,
        github_token_env="CUSTOM_TOKEN",
        cache_by_commit=False,
        cache_ttl_hours=24,
    )

    assert config.semgrep.enabled is False
    assert config.semgrep.rulesets == ["p/python"]
    assert config.bandit.enabled is False
    assert config.bandit.severity == "low"
    assert config.severity_threshold == "ERROR"
    assert config.fail_on_critical is False
    assert config.clone_timeout_seconds == 60
    assert config.scan_timeout_seconds == 300
    assert config.max_repo_size_mb == 1000
    assert config.github_token_env == "CUSTOM_TOKEN"
    assert config.cache_by_commit is False
    assert config.cache_ttl_hours == 24


def test_source_scanner_config_inherits_scanner_configs() -> None:
    """Test that nested scanner configs work independently."""
    semgrep_cfg = SemgrepConfig(enabled=True, rulesets=["p/security-audit"])
    bandit_cfg = BanditConfig(enabled=True, severity="high")

    config = SourceScannerConfig(
        semgrep=semgrep_cfg,
        bandit=bandit_cfg,
    )

    assert config.semgrep is semgrep_cfg
    assert config.bandit is bandit_cfg
    assert config.semgrep.rulesets == ["p/security-audit"]
    assert config.bandit.severity == "high"
