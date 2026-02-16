#!/usr/bin/env python3
# -- coding: utf-8 --
"""
Location: ./plugins/source_scanner/language_detector.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo

"""

# Standard
import logging
from pathlib import Path
from typing import List, Set

logger = logging.getLogger(__name__)


class LanguageDetector:
    """Detect programming languages in a repo"""

    EXTENSION_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".cs": "csharp",
    }

    def detect(self, repo_path: str) -> List[str]:
        """
        Detect languages in repository

        Args:
            repo_path: Path to repository

        Returns:
            List of detected language names (e.f., ["Python", "javascript"])
        """
        path = Path(repo_path)
        languages: Set[str] = set()

        for file_path in path.rglob("*"):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                if ext in self.EXTENSION_MAP:
                    languages.add(self.EXTENSION_MAP[ext])

        detected = sorted(list(languages))
        logger.info(f"Detected languages: {detected}")
        return detected
