# -*- coding: utf-8 -*-
"""Output Length Guard Plugin.

Location: ./plugins/output_length_guard/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Guards tool outputs by enforcing minimum/maximum character and token lengths.
Supports truncate or block strategies.

Version: 1.0.0
"""

# Local
from .config import LengthGuardPolicy, OutputLengthGuardConfig
from .output_length_guard import OutputLengthGuardPlugin

__all__ = [
    "LengthGuardPolicy",
    "OutputLengthGuardConfig",
    "OutputLengthGuardPlugin",
]
__version__ = "1.0.0"
