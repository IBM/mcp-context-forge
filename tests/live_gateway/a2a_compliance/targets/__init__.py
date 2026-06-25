# -*- coding: utf-8 -*-
"""A2A ComplianceTarget implementations.

Location: ./tests/live_gateway/a2a_compliance/targets/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

A target is a runnable A2A endpoint plus the logic to construct an
``a2a.client.Client`` bound to it over a given transport. The base ABC
in ``base.py`` enforces the (name, supported_transports, _open_client)
contract; ``conftest.py`` enumerates every ``(target, transport)`` pair
the harness should exercise.
"""
