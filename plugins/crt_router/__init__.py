# -*- coding: utf-8 -*-
"""CRT Router Plugin for MCP Gateway.

This package provides CRT-based semantic tool routing capabilities for
the MCP Gateway, enabling dynamic tool selection based on relevance scoring.
"""

from .crt_router import CRTRouterPlugin, CRTRouterConfig
from .semantic_router import CRTRouter
from .models import (
    CalibrationArtifact,
    DifficultyBin,
    ToolCalibration,
    ToolRelevanceScore,
)

__all__ = [
    "CRTRouterPlugin",
    "CRTRouterConfig",
    "CRTRouter",
    "CalibrationArtifact",
    "DifficultyBin",
    "ToolCalibration",
    "ToolRelevanceScore",
]
