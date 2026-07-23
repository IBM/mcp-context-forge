#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Public API for the container_scanner plugin.
"""

from __future__ import annotations

from .config import RegistryConfig, ScannerConfig
from .types import ScanResult, Vulnerability

__all__ = [
    "Vulnerability",
    "ScanResult",
    "ScannerConfig",
    "RegistryConfig",
]
