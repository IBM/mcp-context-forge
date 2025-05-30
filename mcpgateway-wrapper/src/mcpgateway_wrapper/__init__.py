# -*- coding: utf-8 -*-
"""MCP Gateway Wrapper init file.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Keval Mahajan, Mihai Criveti, Madhav Kandukuri
"""

import asyncio
from . import server


def main():
    """Main entry point for the package."""
    asyncio.run(server.main())


# Optionally expose other important items at package level
__all__ = ["main", "server"]
