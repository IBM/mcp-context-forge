#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/utils/purl_generator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Package URL (PURL) generation utilities.
Spec: https://github.com/package-url/purl-spec
"""

# Local
from ..models import PackageEcosystem

# Maps PackageEcosystem enum values to their PURL type strings
_ECOSYSTEM_TO_PURL_TYPE: dict[PackageEcosystem, str] = {
    PackageEcosystem.PYTHON: "pypi",
    PackageEcosystem.NPM: "npm",
    PackageEcosystem.GO: "golang",
    PackageEcosystem.RUST: "cargo",
    PackageEcosystem.GENERIC: "generic",
}


def get_purl_type(ecosystem: PackageEcosystem) -> str:
    """Return the PURL type string for a given PackageEcosystem.

    Args:
        ecosystem: The package ecosystem enum value.

    Returns:
        PURL type string (e.g. ``"pypi"``, ``"npm"``).

    Examples:
        >>> get_purl_type(PackageEcosystem.PYTHON)
        'pypi'
        >>> get_purl_type(PackageEcosystem.NPM)
        'npm'
        >>> get_purl_type(PackageEcosystem.GENERIC)
        'generic'
    """
    return _ECOSYSTEM_TO_PURL_TYPE.get(ecosystem, "generic")


def build_purl(
    name: str,
    version: str,
    ecosystem: PackageEcosystem,
    namespace: str | None = None,
) -> str:
    """Construct a well-formed PURL string.

    Args:
        name: Package name (e.g. ``"requests"``).
        version: Package version string (e.g. ``"2.28.0"``).
        ecosystem: The package ecosystem.
        namespace: Optional namespace component. Required for Go modules
            (the module path prefix, e.g. ``"github.com/gin-gonic"``) and
            Maven group IDs. Ignored for most other ecosystems.

    Returns:
        A PURL string conforming to the purl-spec.

    Raises:
        ValueError: If ``name`` or ``version`` are empty.

    Examples:
        >>> build_purl("requests", "2.28.0", PackageEcosystem.PYTHON)
        'pkg:pypi/requests@2.28.0'
        >>> build_purl("lodash", "4.17.21", PackageEcosystem.NPM)
        'pkg:npm/lodash@4.17.21'
        >>> build_purl("gin", "v1.9.1", PackageEcosystem.GO, namespace="github.com/gin-gonic")
        'pkg:golang/github.com/gin-gonic/gin@v1.9.1'
    """
    if not name:
        raise ValueError("Package name must not be empty")
    if not version:
        raise ValueError("Package version must not be empty")

    purl_type = get_purl_type(ecosystem)

    if namespace:
        return f"pkg:{purl_type}/{namespace}/{name}@{version}"
    return f"pkg:{purl_type}/{name}@{version}"


def is_valid_purl(purl: str) -> bool:
    """Return True if *purl* has the minimum expected PURL structure.

    Performs a lightweight structural check only — does not validate the
    type against the official PURL type registry.

    Args:
        purl: The PURL string to validate.

    Returns:
        True if structurally valid, False otherwise.

    Examples:
        >>> is_valid_purl("pkg:pypi/requests@2.28.0")
        True
        >>> is_valid_purl("pkg:golang/github.com/gin-gonic/gin@v1.9.1")
        True
        >>> is_valid_purl("not-a-purl")
        False
        >>> is_valid_purl("pkg:pypi/requests")
        False
        >>> is_valid_purl("")
        False
    """
    if not purl or not purl.startswith("pkg:"):
        return False
    # Must have a type (after "pkg:"), a name, and a version (after "@")
    rest = purl[4:]
    if "/" not in rest or "@" not in rest:
        return False
    return True


def parse_purl(purl: str) -> dict[str, str | None]:
    """Parse a PURL string into its constituent parts.

    Args:
        purl: A valid PURL string.

    Returns:
        Dict with keys ``type``, ``namespace``, ``name``, ``version``.
        ``namespace`` is ``None`` if not present.

    Raises:
        ValueError: If *purl* is not a valid PURL string.

    Examples:
        >>> parse_purl("pkg:pypi/requests@2.28.0")
        {'type': 'pypi', 'namespace': None, 'name': 'requests', 'version': '2.28.0'}
        >>> parse_purl("pkg:golang/github.com/gin-gonic/gin@v1.9.1")
        {'type': 'golang', 'namespace': 'github.com/gin-gonic', 'name': 'gin', 'version': 'v1.9.1'}
    """
    if not is_valid_purl(purl):
        raise ValueError(f"Invalid PURL: {purl!r}")

    # Strip "pkg:"
    rest = purl[4:]

    # Split off the type
    purl_type, rest = rest.split("/", 1)

    # Split off the version
    path, version = rest.rsplit("@", 1)

    # Remaining path: optional namespace + name
    if "/" in path:
        namespace, name = path.rsplit("/", 1)
    else:
        namespace = None
        name = path

    return {
        "type": purl_type,
        "namespace": namespace,
        "name": name,
        "version": version,
    }
