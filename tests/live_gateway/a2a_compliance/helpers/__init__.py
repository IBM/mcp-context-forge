# -*- coding: utf-8 -*-
"""Shared test helpers for the A2A compliance harness.

Location: ./tests/live_gateway/a2a_compliance/helpers/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Mirrors ``tests/live_gateway/protocol_compliance/helpers`` in spirit:

* ``compliance.py`` — ``current_target`` + ``xfail_on`` for tracking
  documented compliance gaps without stalling the suite.
* ``drift.py`` — cross-target payload normalization for drift detection
  once gateway targets become testable.
"""
