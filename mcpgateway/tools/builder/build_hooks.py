# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/tools/builder/build_hooks.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Custom setuptools build hook to generate UI assets before packaging.

This hook runs during `python -m build` to ensure bundle-*.js and tailwind.min.css
are generated and included in the wheel/sdist, without requiring them to be committed to git.
"""

import logging
import subprocess
import sys
from pathlib import Path

from setuptools.command.build_py import build_py

logger = logging.getLogger(__name__)


class BuildPyWithUI(build_py):
    """Custom build_py that generates UI assets before building the package."""

    def run(self):
        """Run UI build before standard build_py."""
        import os

        # Only run npm build when explicitly requested via BUILD_UI_ASSETS=true.
        # uv sync, pip install, and pre-commit hooks all trigger build_py via PEP 517,
        # so we cannot use the command chain to distinguish PyPI dist builds from
        # dependency installs. The env var is the only reliable discriminator.
        if os.getenv("BUILD_UI_ASSETS", "").lower() != "true":
            super().run()
            return

        logger.info("=" * 70)
        logger.info("Building UI assets (Vite bundle + Tailwind CSS)...")
        logger.info("=" * 70)

        # Walk up from this file to find the project root (contains pyproject.toml)
        _path = Path(__file__).resolve().parent
        project_root = _path
        _max_depth = 10
        for depth in range(_max_depth):
            if (project_root / "pyproject.toml").exists():
                break
            if project_root.parent == project_root:
                break
            project_root = project_root.parent

        if not (project_root / "pyproject.toml").exists():
            logger.info("ERROR: Could not locate project root (pyproject.toml not found).")
            sys.exit(1)

        project_root = project_root.resolve()
        if not project_root.is_absolute() or not project_root.is_dir():
            logger.info(f"ERROR: Resolved project root is invalid: {project_root}")
            sys.exit(1)

        # Clean old bundle files before building
        static_dir = (project_root / "mcpgateway" / "static").resolve()
        if not static_dir.is_dir():
            logger.info(f"ERROR: Static directory not found: {static_dir}")
            sys.exit(1)

        for old_bundle in static_dir.glob("bundle-*.js"):
            logger.info(f"Removing old bundle: {old_bundle.name}")
            old_bundle.unlink()

        # Check if npm is available
        try:
            subprocess.run(["npm", "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.info("ERROR: npm not found. Cannot build UI assets.")
            logger.info("Install Node.js and npm, then retry.")
            sys.exit(1)

        # Check if node_modules exists
        if not (project_root / "node_modules").exists():
            logger.info("Installing npm dependencies...")
            try:
                subprocess.run(["npm", "install"], cwd=project_root, check=True)
            except subprocess.CalledProcessError as e:
                logger.info(f"ERROR: npm install failed: {e}")
                sys.exit(1)

        # Build Vite bundle
        logger.info("\n[1/2] Building Vite bundle (bundle-*.js)...")
        try:
            subprocess.run(["npm", "run", "vite:build"], cwd=project_root, check=True)
        except subprocess.CalledProcessError as e:
            logger.info(f"ERROR: Vite build failed: {e}")
            sys.exit(1)

        # Build Tailwind CSS
        logger.info("\n[2/2] Building Tailwind CSS (tailwind.min.css)...")
        try:
            subprocess.run(["npm", "run", "build:css"], cwd=project_root, check=True)
        except subprocess.CalledProcessError as e:
            logger.info(f"ERROR: Tailwind CSS build failed: {e}")
            sys.exit(1)

        logger.info("\n" + "=" * 70)
        logger.info("UI assets built successfully!")
        logger.info("=" * 70 + "\n")

        # Continue with standard build_py
        super().run()
