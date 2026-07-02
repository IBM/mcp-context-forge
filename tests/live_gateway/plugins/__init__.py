# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/plugins/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Live-gateway end-to-end suites for managed cpex plugins.

Each module under this package boots no code itself; it talks HTTP to a running
ContextForge gateway that was started with a dedicated, single-plugin enforce
config (``plugins/plugin_e2e_<slug>.yaml``). The tests never import the cpex
plugin package — the gateway loads it from config, so a broken wheel or Rust
extension surfaces as a failing E2E rather than a silently skipped import.
"""
