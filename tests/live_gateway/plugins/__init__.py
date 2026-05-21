# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Live-gateway tests for the plugin runtime (binding lifecycle, runtime
management, mode propagation, etc.). These exercise the full HTTP →
gateway plugin manager → plugin → Redis path against a running docker
stack and are gated on a reachable gateway via _is_gateway_running().
"""
