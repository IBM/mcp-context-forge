"""Compatibility shim for the self-contained benchmark CLI."""

from __future__ import annotations

from benchmarks.contextforge.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
