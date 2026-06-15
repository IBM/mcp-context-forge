"""
Custom setuptools build hook to generate UI assets before packaging.

This hook runs during `python -m build` to ensure bundle-*.js and tailwind.min.css
are generated and included in the wheel/sdist, without requiring them to be committed to git.
"""

import subprocess
import sys
from pathlib import Path

from setuptools.command.build_py import build_py


class BuildPyWithUI(build_py):
    """Custom build_py that generates UI assets before building the package."""

    def run(self):
        """Run UI build before standard build_py."""
        # Only run npm build during actual distribution builds (wheel/sdist).
        # During editable installs and uv sync, skip to avoid modifying package-lock.json.
        dist_commands = self.distribution.command_obj or {}
        if not any(cmd in dist_commands for cmd in ("bdist_wheel", "sdist")):
            super().run()
            return

        print("=" * 70)
        print("Building UI assets (Vite bundle + Tailwind CSS)...")
        print("=" * 70)

        # Walk up from this file to find the project root (contains pyproject.toml)
        _path = Path(__file__).resolve().parent
        project_root = _path
        while project_root.parent != project_root:
            if (project_root / "pyproject.toml").exists():
                break
            project_root = project_root.parent

        # Clean old bundle files before building
        static_dir = project_root / "mcpgateway" / "static"
        for old_bundle in static_dir.glob("bundle-*.js"):
            print(f"Removing old bundle: {old_bundle.name}")
            old_bundle.unlink()

        # Check if npm is available
        try:
            subprocess.run(["npm", "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("WARNING: npm not found. Skipping UI build.", file=sys.stderr)
            print("Install Node.js and npm to build UI assets.", file=sys.stderr)
            super().run()
            return

        # Check if node_modules exists
        if not (project_root / "node_modules").exists():
            print("Installing npm dependencies...")
            try:
                subprocess.run(["npm", "install"], cwd=project_root, check=True)
            except subprocess.CalledProcessError as e:
                print(f"ERROR: npm install failed: {e}", file=sys.stderr)
                sys.exit(1)

        # Build Vite bundle
        print("\n[1/2] Building Vite bundle (bundle-*.js)...")
        try:
            subprocess.run(["npm", "run", "vite:build"], cwd=project_root, check=True)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Vite build failed: {e}", file=sys.stderr)
            sys.exit(1)

        # Build Tailwind CSS
        print("\n[2/2] Building Tailwind CSS (tailwind.min.css)...")
        try:
            subprocess.run(["npm", "run", "build:css"], cwd=project_root, check=True)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Tailwind CSS build failed: {e}", file=sys.stderr)
            sys.exit(1)

        print("\n" + "=" * 70)
        print("UI assets built successfully!")
        print("=" * 70 + "\n")

        # Continue with standard build_py
        super().run()
