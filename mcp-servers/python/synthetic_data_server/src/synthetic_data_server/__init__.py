# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/synthetic_data_server/src/synthetic_data_server/__init__.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Synthetic data FastMCP server package.
"""

from . import schemas
from .generators import SyntheticDataGenerator, build_presets
from .storage import DatasetStorage

__version__ = "2.0.0"
__all__ = ["schemas", "SyntheticDataGenerator", "build_presets", "DatasetStorage", "__version__"]
