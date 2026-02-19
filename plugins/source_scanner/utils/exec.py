#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/utils/exec.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Re-exports run_command and ExecResult from mcpgateway.utils.exec for backwards compatibility.
"""

from mcpgateway.utils.exec import run_command, ExecResult

__all__ = ["run_command", "ExecResult"]