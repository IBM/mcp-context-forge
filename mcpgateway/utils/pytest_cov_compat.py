# -*- coding: utf-8 -*-
"""Pytest compatibility plugin for environments without pytest-cov.

This keeps repository-level `--cov=...` addopts parseable when pytest-cov is
not installed, while preserving normal pytest-cov behavior when it is present.
"""

# Future
from __future__ import annotations

# Standard
import warnings


def _pytest_cov_available() -> bool:
    """Return whether ``pytest-cov`` is importable in the current environment.

    Returns:
        ``True`` when ``pytest-cov`` can be imported, else ``False``.
    """
    try:
        # Third-Party
        import pytest_cov.plugin  # noqa: F401  # pylint: disable=unused-import,import-outside-toplevel

        return True
    except Exception:
        return False


def pytest_addoption(parser) -> None:
    """Register no-op coverage options when ``pytest-cov`` is unavailable.

    Args:
        parser: Pytest parser used to register command-line options.
    """
    if _pytest_cov_available():
        return

    warnings.warn(
        "pytest-cov is not installed; coverage CLI options are accepted but ignored.",
        RuntimeWarning,
        stacklevel=2,
    )

    group = parser.getgroup("covcompat")
    group.addoption("--cov", action="append", default=[], help="No-op fallback when pytest-cov is unavailable")
    group.addoption("--cov-report", action="append", default=[], help="No-op fallback when pytest-cov is unavailable")
    group.addoption("--cov-append", action="store_true", default=False, help="No-op fallback when pytest-cov is unavailable")
    group.addoption("--cov-fail-under", action="store", default=None, help="No-op fallback when pytest-cov is unavailable")
