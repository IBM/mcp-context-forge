#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate requirements.txt from pyproject.toml runtime dependencies.

Copyright 2025 Mihai Criveti
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extracts [project].dependencies from pyproject.toml (excluding dev and
optional extras) and writes a sorted requirements.txt for compatibility
with legacy security scanners and CI pipelines.

Usage:
    python scripts/generate_requirements.py                     # generate
    python scripts/generate_requirements.py --check             # verify in sync
    python scripts/generate_requirements.py --dry-run           # preview
    python scripts/generate_requirements.py --mode uv           # full resolved tree via uv export
    python scripts/generate_requirements.py --mode direct       # direct deps only (default)
"""

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HEADER_DIRECT = """\
# Auto-generated from pyproject.toml [project].dependencies
# Direct dependencies only (no transitive deps)
# DO NOT EDIT — regenerate with: make requirements
"""

HEADER_UV = """\
# Auto-generated via uv export (full resolved dependency tree)
# DO NOT EDIT — regenerate with: make requirements MODE=uv
"""


def normalize_name(name: str) -> str:
    """Normalize package name per PEP 503 (lowercase, hyphens to hyphens)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def extract_direct_deps(pyproject_path: Path) -> list[str]:
    """Extract and sort [project].dependencies from pyproject.toml."""
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    if not deps:
        print("Warning: No dependencies found in pyproject.toml", file=sys.stderr)
        return []

    return sorted(deps, key=lambda d: normalize_name(d.split("[")[0].split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("~")[0]))


def generate_direct(pyproject_path: Path) -> str:
    """Generate requirements.txt content from direct dependencies."""
    deps = extract_direct_deps(pyproject_path)
    return HEADER_DIRECT + "\n".join(deps) + "\n"


def generate_uv(pyproject_path: Path) -> str:
    """Generate requirements.txt content via uv export (full resolved tree)."""
    result = subprocess.run(
        ["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project"],
        capture_output=True,
        text=True,
        cwd=pyproject_path.parent,
    )
    if result.returncode != 0:
        print(f"Error: uv export failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # uv export includes its own header comments; replace with ours
    lines = [line for line in result.stdout.splitlines() if not line.startswith("#")]
    return HEADER_UV + "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate requirements.txt from pyproject.toml")
    parser.add_argument("-i", "--input", default="pyproject.toml", help="Path to pyproject.toml (default: pyproject.toml)")
    parser.add_argument("-o", "--output", default="requirements.txt", help="Output path (default: requirements.txt)")
    parser.add_argument("--mode", choices=["direct", "uv"], default="direct", help="Generation mode: 'direct' extracts declared deps, 'uv' resolves full tree (default: direct)")
    parser.add_argument("--check", action="store_true", help="Verify requirements.txt is in sync (exit 1 if not)")
    parser.add_argument("--dry-run", action="store_true", help="Print generated content without writing")
    args = parser.parse_args()

    pyproject_path = Path(args.input)
    output_path = Path(args.output)

    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found", file=sys.stderr)
        return 1

    # Generate content
    if args.mode == "uv":
        content = generate_uv(pyproject_path)
    else:
        content = generate_direct(pyproject_path)

    # Dry-run: just print
    if args.dry_run:
        print(content, end="")
        return 0

    # Check mode: compare with existing file
    if args.check:
        if not output_path.exists():
            print(f"Error: {output_path} does not exist. Run 'make requirements' to generate it.", file=sys.stderr)
            return 1

        existing = output_path.read_text()
        if existing == content:
            print(f"{output_path} is up to date.")
            return 0
        else:
            print(f"Error: {output_path} is out of sync with {pyproject_path}.", file=sys.stderr)
            print(f"Run 'make requirements' to regenerate it.", file=sys.stderr)
            return 1

    # Write mode
    output_path.write_text(content)
    dep_count = len([line for line in content.splitlines() if line and not line.startswith("#")])
    print(f"Generated {output_path} with {dep_count} dependencies (mode: {args.mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
