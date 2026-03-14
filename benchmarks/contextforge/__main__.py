"""Module entrypoint for the self-contained benchmark bundle."""

from __future__ import annotations

from .runner import main


if __name__ == "__main__":
    raise SystemExit(main())
