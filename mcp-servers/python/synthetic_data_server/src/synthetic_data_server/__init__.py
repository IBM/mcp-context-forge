# -*- coding: utf-8 -*-
"""Synthetic data FastMCP server package."""

from . import schemas
from .generators import SyntheticDataGenerator, build_presets
from .storage import DatasetStorage

__version__ = "2.0.0"
__all__ = ["schemas", "SyntheticDataGenerator", "build_presets", "DatasetStorage", "__version__"]
