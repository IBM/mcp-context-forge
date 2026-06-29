# -*- coding: utf-8 -*-
"""Location: ./mcp_reverse_proxy/__main__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Entry point for running reverse proxy as a module.
Allows: python -m mcpgateway.mcp_reverse_proxy
"""

# First-Party
from mcp_reverse_proxy.cli import run

if __name__ == "__main__":
    run()

# Made with Bob
