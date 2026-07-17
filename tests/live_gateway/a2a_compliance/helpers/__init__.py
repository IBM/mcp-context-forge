# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/helpers/__init__.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared test helpers for the A2A compliance harness.
Mirrors ``tests/live_gateway/protocol_compliance/helpers`` in spirit:

* ``compliance.py`` — ``current_target`` + ``xfail_on`` for tracking
  documented compliance gaps without stalling the suite.
* ``drift.py`` — cross-target payload normalization for drift detection
  once gateway targets become testable.
"""
