# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Live-gateway tests for the plugin runtime (binding lifecycle, runtime
management, mode propagation, etc.). These exercise the full HTTP →
gateway plugin manager → plugin → Redis path against a running docker
stack, and are intentionally skipped by default — each test file declares
its own opt-in env var. See the file-level docstrings for run commands.
"""
