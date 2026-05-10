#!/usr/bin/env python3
"""Verify local native extension wheels are importable after installation.

This script is used during container builds to validate that Rust-based
native extensions built in the rust-builder stage can be successfully
imported in the target virtual environment.

Usage:
    python3 verify-native-extensions.py /tmp/local-native-extension-wheels

Exit codes:
    0  All discovered top-level modules import successfully
    1  No importable modules were discovered or import failed
"""

import glob
import importlib
import sys
import zipfile


def main(wheel_dir: str) -> int:
    """Discover and import all top-level modules from wheels in wheel_dir."""
    modules: list[str] = []
    pattern = f"{wheel_dir}/*.whl"

    for wheel in glob.glob(pattern):
        with zipfile.ZipFile(wheel) as archive:
            top_level = next(
                (name for name in archive.namelist() if name.endswith(".dist-info/top_level.txt")),
                None,
            )
            if top_level:
                modules.extend(
                    line.strip()
                    for line in archive.read(top_level).decode("utf-8").splitlines()
                    if line.strip()
                )
                continue

            for name in archive.namelist():
                if "/" not in name and (name.endswith(".so") or name.endswith(".pyd")):
                    modules.append(name.split(".", 1)[0])
                    break
                if name.count("/") == 1 and name.endswith("/__init__.py"):
                    modules.append(name.split("/", 1)[0])
                    break

    modules = list(dict.fromkeys(modules))

    if not modules:
        print(
            "Local native extension wheels installed but no importable top-level modules were discovered",
            file=sys.stderr,
        )
        return 1

    for module in modules:
        importlib.import_module(module)
        print(f"✓ Local native extension import ok: {module}")

    return 0


if __name__ == "__main__":
    wheel_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/local-native-extension-wheels"
    sys.exit(main(wheel_dir))
