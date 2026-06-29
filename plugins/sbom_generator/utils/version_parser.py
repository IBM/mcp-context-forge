#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/utils/version_parser.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Version parsing and comparison utilities used by the CVE correlation query
(query/cve_correlation.py) to identify vulnerable dependency versions.

Uses ``packaging.version.Version`` (PEP 440) as the primary comparison engine
since the gateway already depends on it.  Non-PEP-440 strings (e.g. Go
``v1.9.1``, Cargo semver) are normalised before comparison and fall back to
lexicographic ordering if normalisation fails.
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_V_PREFIX = re.compile(r"^v", re.IGNORECASE)


def normalise(version_str: str) -> str:
    """Strip a leading ``v``/``V`` prefix so PEP-440 parsing succeeds.

    Args:
        version_str: Raw version string from a package manifest or SBOM.

    Returns:
        Normalised version string suitable for ``packaging.version.Version``.

    Examples:
        >>> normalise("v1.9.1")
        '1.9.1'
        >>> normalise("V2.0.0")
        '2.0.0'
        >>> normalise("2.28.0")
        '2.28.0'
    """
    return _V_PREFIX.sub("", version_str.strip())


def _parse(version_str: str):
    """Return a comparable version object.

    Tries ``packaging.version.Version`` first; falls back to the normalised
    raw string so callers always get *something* comparable.

    Args:
        version_str: Version string to parse.

    Returns:
        A ``packaging.version.Version`` instance, or the normalised string.
    """
    normalised = normalise(version_str)
    try:
        # Third-Party
        from packaging.version import Version  # type: ignore[import-untyped]

        return Version(normalised)
    except Exception:
        return normalised


# ---------------------------------------------------------------------------
# Parsed version dataclass
# ---------------------------------------------------------------------------


class ParsedVersion(NamedTuple):
    """Decomposed version with its original and normalised representations.

    Attributes:
        original: The raw version string as supplied.
        normalised: The version string after stripping ``v``/``V`` prefix.
        major: Major version integer, or ``None`` if not parseable.
        minor: Minor version integer, or ``None`` if not parseable.
        patch: Patch version integer, or ``None`` if not parseable.
    """

    original: str
    normalised: str
    major: int | None
    minor: int | None
    patch: int | None


def parse_version(version_str: str) -> ParsedVersion:
    """Parse a version string into a ``ParsedVersion`` named tuple.

    Args:
        version_str: Raw version string (e.g. ``"v1.9.1"``, ``"2.28.0"``).

    Returns:
        A :class:`ParsedVersion` with major/minor/patch populated where
        possible, or ``None`` for parts that cannot be determined.

    Examples:
        >>> pv = parse_version("2.28.0")
        >>> pv.major, pv.minor, pv.patch
        (2, 28, 0)
        >>> pv = parse_version("v1.9.1")
        >>> pv.major, pv.minor, pv.patch
        (1, 9, 1)
        >>> pv = parse_version("nightly")
        >>> pv.major is None
        True
    """
    normalised = normalise(version_str)
    major = minor = patch = None

    try:
        # Third-Party
        from packaging.version import Version

        v = Version(normalised)
        parts = v.release
        major = parts[0] if len(parts) > 0 else None
        minor = parts[1] if len(parts) > 1 else None
        patch = parts[2] if len(parts) > 2 else None
    except Exception:
        # Try a simple numeric split as a best-effort fallback
        segments = normalised.split(".")
        try:
            major = int(segments[0]) if len(segments) > 0 else None
            minor = int(segments[1]) if len(segments) > 1 else None
            patch = int(segments[2]) if len(segments) > 2 else None
        except (ValueError, IndexError):
            pass

    return ParsedVersion(
        original=version_str,
        normalised=normalised,
        major=major,
        minor=minor,
        patch=patch,
    )


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def version_lt(a: str, b: str) -> bool:
    """Return ``True`` if version *a* is strictly less than version *b*.

    Args:
        a: Left-hand version string.
        b: Right-hand version string.

    Returns:
        ``True`` if ``a < b``.

    Examples:
        >>> version_lt("2.28.0", "2.31.0")
        True
        >>> version_lt("2.31.0", "2.28.0")
        False
        >>> version_lt("1.0.0", "1.0.0")
        False
    """
    try:
        return _parse(a) < _parse(b)
    except Exception:
        return normalise(a) < normalise(b)


def version_lte(a: str, b: str) -> bool:
    """Return ``True`` if version *a* is less than or equal to version *b*.

    Args:
        a: Left-hand version string.
        b: Right-hand version string.

    Returns:
        ``True`` if ``a <= b``.

    Examples:
        >>> version_lte("1.0.0", "1.0.0")
        True
        >>> version_lte("0.9.0", "1.0.0")
        True
        >>> version_lte("2.0.0", "1.0.0")
        False
    """
    try:
        return _parse(a) <= _parse(b)
    except Exception:
        return normalise(a) <= normalise(b)


def version_eq(a: str, b: str) -> bool:
    """Return ``True`` if version *a* is equal to version *b*.

    Args:
        a: Left-hand version string.
        b: Right-hand version string.

    Returns:
        ``True`` if ``a == b`` after normalisation.

    Examples:
        >>> version_eq("1.0.0", "1.0.0")
        True
        >>> version_eq("v1.0.0", "1.0.0")
        True
        >>> version_eq("1.0.0", "1.0.1")
        False
    """
    try:
        return _parse(a) == _parse(b)
    except Exception:
        return normalise(a) == normalise(b)


# ---------------------------------------------------------------------------
# CVE vulnerability range check
# ---------------------------------------------------------------------------


def is_vulnerable(
    component_version: str,
    version_lt_threshold: str | None = None,
    version_lte_threshold: str | None = None,
    version_eq_threshold: str | None = None,
) -> bool:
    """Check whether *component_version* falls within a vulnerable range.

    Exactly one threshold argument should be supplied per call.  If multiple
    are given, they are evaluated in priority order:
    ``version_lt`` → ``version_lte`` → ``version_eq``.

    Args:
        component_version: The installed package version to test.
        version_lt_threshold: Vulnerable if ``component_version < threshold``.
        version_lte_threshold: Vulnerable if ``component_version <= threshold``.
        version_eq_threshold: Vulnerable if ``component_version == threshold``.

    Returns:
        ``True`` if the component is in the vulnerable range, ``False``
        otherwise.  Also returns ``False`` if no threshold is provided.

    Examples:
        >>> is_vulnerable("2.28.0", version_lt_threshold="2.31.0")
        True
        >>> is_vulnerable("2.31.0", version_lt_threshold="2.31.0")
        False
        >>> is_vulnerable("2.31.0", version_lte_threshold="2.31.0")
        True
        >>> is_vulnerable("3.0.0", version_lt_threshold="2.31.0")
        False
        >>> is_vulnerable("1.2.3", version_eq_threshold="1.2.3")
        True
        >>> is_vulnerable("1.2.4", version_eq_threshold="1.2.3")
        False
        >>> is_vulnerable("1.0.0")
        False
    """
    if version_lt_threshold is not None:
        return version_lt(component_version, version_lt_threshold)
    if version_lte_threshold is not None:
        return version_lte(component_version, version_lte_threshold)
    if version_eq_threshold is not None:
        return version_eq(component_version, version_eq_threshold)
    return False
