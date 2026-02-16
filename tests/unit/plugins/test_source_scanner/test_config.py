#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_config.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# First-Party
from plugins.source_scanner.config import BanditConfig, ScannersConfig, SemgrepConfig, SourceScannerConfig


def test_semgrep_config_defaults() -> None:
    config = SemgrepConfig()

    assert config.enabled is True
    assert config.rulesets == ["p/security-audit", "p/owasp-top-ten", "p/python", "p/javascript"]
    assert config.extra_args == []
    assert config.timeout_seconds == 600


def test_bandit_config_defaults() -> None:
    config = BanditConfig()

    assert config.enabled is True
    assert config.severity == "medium"
    assert config.confidence == "medium"


def test_scanners_config_defaults() -> None:
    config = ScannersConfig()

    assert isinstance(config.semgrep, SemgrepConfig)
    assert isinstance(config.bandit, BanditConfig)


def test_source_scanner_config_defaults() -> None:
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


def test_source_scanner_config_merges_scanners() -> None:
    scanners = ScannersConfig(
        semgrep=SemgrepConfig(enabled=False, rulesets=["p/python"], extra_args=["--strict"], timeout_seconds=123),
        bandit=BanditConfig(enabled=False, severity="low", confidence="high"),
    )
    config = SourceScannerConfig(
        scanners=scanners,
        semgrep=SemgrepConfig(enabled=True, rulesets=["p/security-audit"], extra_args=[], timeout_seconds=999),
        bandit=BanditConfig(enabled=True, severity="high", confidence="low"),
    )

    assert config.semgrep.enabled is False
    assert config.semgrep.rulesets == ["p/python"]
    assert config.semgrep.extra_args == ["--strict"]
    assert config.semgrep.timeout_seconds == 123
    assert config.bandit.enabled is False
    assert config.bandit.severity == "low"
    assert config.bandit.confidence == "high"
