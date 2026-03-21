#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""__init__.py for integration tests

Location: tests/integration/test_image_signing/__init__.py
Copyright 2026
Authors: Xinyi
"""

"""
Integration tests for the image_signing plugin.

Tests the full verification pipeline: cosign verify → signer matching →
policy evaluation → DB persistence. Cosign CLI is mocked; all other
components (matcher, evaluator, repository) use real implementations.
"""