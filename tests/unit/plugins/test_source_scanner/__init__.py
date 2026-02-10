#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/__init__.py
Copyright: 2025
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for MCP Source Scanner Plugin.

This package contains comprehensive unit tests for the SourceScannerPlugin,
covering:
- Language detection (test_language_detector.py)
- Git operations (test_git_manager.py)
- Semgrep scanner integration (test_semgrep_scanner.py)
- Bandit scanner integration (test_bandit_scanner.py)
- Finding parsing and validation (test_finding_parser.py)
- Finding deduplication (test_finding_deduplication.py)
- Severity filtering (test_severity_filtering.py)
- Plugin integration and hooks (test_source_scanner_plugin.py)
- Cache management (test_cache_manager.py)

Test Structure:
- conftest.py: Shared pytest fixtures and configuration
- test_*.py: Individual test modules (one per component)

Running Tests locally:
    pytest tests/unit/plugins/test_source_scanner/ -v
    pytest tests/unit/plugins/test_source_scanner/ --cov=mcpgateway.plugins.source_scanner
"""
