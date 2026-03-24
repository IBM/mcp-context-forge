# -*- coding: utf-8 -*-
"""Output Length Guard Plugin.

Location: ./plugins/output_length_guard/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Guards tool outputs by enforcing minimum/maximum character lengths.
Supports truncate or block strategies.

Version: 1.0.0
- Comprehensive exception handling (8 functions with try-except blocks)
- Extensive logging (28 log statements across all severity levels)
- Fail-safe design (never crashes, always returns safe defaults)
- Fixed all 8 bugs from GitHub issue #3747
- Added MCP content array format support
- Enhanced configuration validation
"""

from .output_length_guard import (
    OutputLengthGuardPlugin,
    OutputLengthGuardConfig,
)

__all__ = [
    "OutputLengthGuardPlugin",
    "OutputLengthGuardConfig",
]
__version__ = "1.0.0"
