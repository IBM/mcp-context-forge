# -*- coding: utf-8 -*-
"""Rate Limiter Plugin.

Location: ./plugins/rate_limiter/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Enforces simple in-memory rate limits by user, tenant, and/or tool.
Uses a fixed window keyed by second for simplicity and determinism.
"""
