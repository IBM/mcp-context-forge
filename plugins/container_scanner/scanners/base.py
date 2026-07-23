#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/container_scanner/scanners/base.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Abstract base class for container scanner runners.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from plugins.container_scanner.types import Vulnerability


class ScannerRunner(ABC):
    @abstractmethod
    async def run(self, image_ref: str, auth_env: Dict[str, str]) -> List[Vulnerability]:
        pass
