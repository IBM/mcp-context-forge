#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/extraction/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Abstract base class for all dependency extractors.
"""

# Future
from __future__ import annotations

# Standard
from abc import ABC, abstractmethod

# Local
from ..models import ExtractionResult


class BaseExtractor(ABC):
    """Abstract base class that all extractors must implement.

    Subclasses:
        - ContainerExtractor  — extracts from a container image
        - SourceExtractor     — extracts from a source directory
    """

    @abstractmethod
    async def extract(self, target: str) -> ExtractionResult:
        """Extract dependencies from *target*.

        Args:
            target: Image name (container) or directory path (source).

        Returns:
            An :class:`~plugins.sbom_generator.models.ExtractionResult`
            populated with all discovered components.

        Raises:
            ExtractionError: If extraction fails unrecoverably.
        """

    @abstractmethod
    def supports(self, target: str) -> bool:
        """Return ``True`` if this extractor can handle *target*.

        Used by the plugin to select the correct extractor at runtime
        without needing to instantiate every subclass.

        Args:
            target: Image name or directory path to test.

        Returns:
            ``True`` if this extractor is capable of processing *target*.
        """
