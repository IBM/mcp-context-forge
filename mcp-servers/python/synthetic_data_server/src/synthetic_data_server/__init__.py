"""Synthetic data FastMCP server package."""

from . import schemas
from .generators import SyntheticDataGenerator, build_presets
from .storage import DatasetStorage

__all__ = ["schemas", "SyntheticDataGenerator", "build_presets", "DatasetStorage"]
