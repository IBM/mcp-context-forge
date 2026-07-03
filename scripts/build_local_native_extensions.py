#!/usr/bin/env python3
"""Build local native extension wheels from maturin-based crates.

Discovers all Cargo.toml files under /build/crates that have a corresponding
pyproject.toml with maturin as the build backend, then builds them as wheels
using maturin.

Usage:
    python3 build_local_native_extensions.py [crates_root] [wheel_dir]

Args:
    crates_root: Root directory containing crates (default: /build/crates)
    wheel_dir: Output directory for wheels (default: /build/native-extension-wheels)
"""

import pathlib
import subprocess
import sys
import tomllib


def main() -> None:
    """Build all maturin-based native extensions."""
    crates_root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/build/crates")
    wheel_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "/build/native-extension-wheels")

    for cargo_toml in sorted(crates_root.rglob("Cargo.toml")):
        pyproject_toml = cargo_toml.with_name("pyproject.toml")
        if not pyproject_toml.exists():
            continue

        pyproject = tomllib.loads(pyproject_toml.read_text(encoding="utf-8"))
        build_system = pyproject.get("build-system", {})
        backend = str(build_system.get("build-backend", ""))
        requires = [str(item) for item in build_system.get("requires", [])]

        if "maturin" not in backend and not any("maturin" in item for item in requires):
            continue

        crate_dir = cargo_toml.parent
        print(f"🦀 Building local native extension: {crate_dir.name}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "maturin",
                "build",
                "--release",
                "--manifest-path",
                str(cargo_toml),
                "--out",
                str(wheel_dir),
            ],
            check=True,
        )

    print("✅ Local native extensions built successfully")


if __name__ == "__main__":
    main()
