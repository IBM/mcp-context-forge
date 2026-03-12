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

    # Directories to skip during scanning
    SKIP_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
        "target",
        "bin",
        "obj",
    }

    def detect(self, repo_path: str) -> List[str]:
        """
        Detect languages in repository

        Args:
            repo_path: Path to repository

        Returns:
            List of detected language names (e.g., ["python", "javascript"])
        """
        path = Path(repo_path)
        languages: Set[str] = set()

        for file_path in path.rglob("*"):
            if any(part.startswith(".") or part in self.SKIP_DIRS for part in file_path.parts):
                continue
            if file_path.is_file():
                ext = file_path.suffix.lower()
                if ext in self.EXTENSION_MAP:
                    languages.add(self.EXTENSION_MAP[ext])

        detected = sorted(list(languages))
        logger.info(f"Detected languages: {detected}")
        return detected
