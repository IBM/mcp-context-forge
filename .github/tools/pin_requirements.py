#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract dependencies from pyproject.toml and pin versions.

Copyright 2025 Mihai Criveti
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This script reads the dependencies from pyproject.toml and converts
version specifiers from >= to == for reproducible builds.
"""

# Standard
import re
import sys
import tomllib


def pin_requirements(pyproject_path="pyproject.toml", output_path="requirements.txt"):
    """
    Extract dependencies from pyproject.toml and pin versions.

    Args:
        pyproject_path: Path to pyproject.toml file
        output_path: Path to output requirements.txt file
    """
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        print(f"Error: {pyproject_path} not found!", file=sys.stderr)
        sys.exit(1)
    except tomllib.TOMLDecodeError as e:
        print(f"Error parsing TOML: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract dependencies
    dependencies = data.get("project", {}).get("dependencies", [])
    if not dependencies:
        print("Warning: No dependencies found in pyproject.toml", file=sys.stderr)
        return

    pinned_deps = []
    converted_count = 0

    for dep in dependencies:
        # Match package name with optional extras and version
        # Pattern: package_name[optional_extras]>=version
        match = re.match(r"^([a-zA-Z0-9_-]+)(?:\[.*\])?>=(.+)", dep)

        if match:
            name, version = match.groups()
            pinned_deps.append(f"{name}=={version}")
            converted_count += 1
        else:
            # Keep as-is if not in expected format
            pinned_deps.append(dep)
            print(f"Info: Keeping '{dep}' as-is (no >= pattern found)")

    # Sort dependencies for consistency
    pinned_deps.sort(key=lambda x: x.lower())

    # Write to requirements.txt
    with open(output_path, "w") as f:
        for dep in pinned_deps:
            f.write(f"{dep}\n")

    print(f"✓ Generated {output_path} with {len(pinned_deps)} dependencies")
    print(f"✓ Converted {converted_count} dependencies from >= to ==")

    # Show first few dependencies as preview
    if pinned_deps:
        print("\nPreview of pinned dependencies:")
        for dep in pinned_deps[:5]:
            print(f"  - {dep}")
        if len(pinned_deps) > 5:
            print(f"  ... and {len(pinned_deps) - 5} more")


def main():
    """Main entry point."""
    # Standard
    import argparse

    parser = argparse.ArgumentParser(description="Extract and pin dependencies from pyproject.toml")
    parser.add_argument("-i", "--input", default="pyproject.toml", help="Path to pyproject.toml file (default: pyproject.toml)")
    parser.add_argument("-o", "--output", default="requirements.txt", help="Path to output requirements file (default: requirements.txt)")
    parser.add_argument("--dry-run", action="store_true", help="Print dependencies without writing to file")

    args = parser.parse_args()

    if args.dry_run:
        # Dry run mode - just print what would be written
        try:
            with open(args.input, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            print(f"Error: {args.input} not found!", file=sys.stderr)
            sys.exit(1)

        dependencies = data.get("project", {}).get("dependencies", [])
        print("Would generate the following pinned dependencies:\n")

        for dep in sorted(dependencies, key=lambda x: x.lower()):
            match = re.match(r"^([a-zA-Z0-9_-]+)(?:\[.*\])?>=(.+)", dep)
            if match:
                name, version = match.groups()
                print(f"{name}=={version}")
            else:
                print(dep)
    else:
        pin_requirements(args.input, args.output)


if __name__ == "__main__":
    main()
