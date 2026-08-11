"""Deterministic Git inventory helpers for the Task 20 scope verifier."""

from __future__ import annotations

from pathlib import Path


_EXCLUDED_UNTRACKED_PREFIXES = (".omo/", ".slim/", "certs/", "secrets/")


def parse_changed_inventory(tracked: str, untracked: str) -> tuple[Path, ...]:
    """Parse NUL-delimited tracked and untracked Git output into one inventory."""
    tracked_fields = tracked.split("\0")
    paths: set[Path] = set()
    index = 0
    while index < len(tracked_fields) and tracked_fields[index]:
        status = tracked_fields[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        for _ in range(path_count):
            if index >= len(tracked_fields) or not tracked_fields[index]:
                break
            paths.add(Path(tracked_fields[index]))
            index += 1
    paths.update(
        Path(value)
        for value in untracked.split("\0")
        if value and not value.startswith(_EXCLUDED_UNTRACKED_PREFIXES)
    )
    return tuple(sorted(paths, key=Path.as_posix))


def added_lines_from_patch(patch: str) -> tuple[tuple[Path, str], ...]:
    """Parse added lines from one zero-context Git patch."""
    current: Path | None = None
    added: list[tuple[Path, str]] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = Path(line[6:])
        elif line.startswith("+++ /dev/null"):
            current = None
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            added.append((current, line[1:]))
    return tuple(added)


def added_lines_for_untracked(root: Path, paths: tuple[Path, ...]) -> tuple[tuple[Path, str], ...]:
    """Treat every UTF-8 line in a nonignored untracked file as newly added."""
    added: list[tuple[Path, str]] = []
    for path in paths:
        absolute = root / path
        if absolute.is_file():
            added.extend((path, line) for line in absolute.read_text(encoding="utf-8").splitlines())
    return tuple(added)


__all__ = ("added_lines_for_untracked", "added_lines_from_patch", "parse_changed_inventory")
