# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_certifi_ca_bundle.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests: certifi CA bundle must not contain roots removed by Mozilla.

httpx resolves verify=True to certifi.where(), so any root present in the
bundle is trusted for all outbound gateway, tool, and OAuth calls.
Python and OpenSSL perform no CRL or OCSP checking; removing the anchor is
the only mitigation.

Note: certifi publishes root removals as they land in NSS/Mozilla. The
version floor below must be advanced each time a relevant removal is
released.  The per-root tests below will fail independently once a new
certifi release drops the affected roots, guiding that bump.
"""

# Standard
import re

# Third-Party
import certifi
import pytest

# Minimum certifi version known to pre-date the emSign removal.
# Advance this once certifi publishes a release that drops the emSign roots
# (currently in upstream main but not yet published to PyPI as of 2026-10-19).
_MINIMUM_CERTIFI_VERSION = (2026, 10, 19)

# Roots Mozilla has removed or is removing for key incidents.
# Each entry is (cn, released_in_certifi) where released_in_certifi is True
# once a certifi release that drops that root is available on PyPI.
# Roots with released_in_certifi=False trigger a skip with an advisory message
# rather than a hard failure, so CI stays green until the release lands.
_REMOVED_ROOTS = [
    ("emSign ECC Root CA - G3", False),
    ("emSign Root CA - C1", False),
    ("emSign ECC Root CA - C3", False),
    ("emSign Root CA - G1", False),
    ("eMudhra Root CA - G1", True),
    ("eMudhra Root CA - G2", True),
    ("eMudhra Root CA - G3", True),
]


def _subject_cns_in_bundle() -> set[str]:
    """Return the set of label/subject CN values present in the certifi bundle.

    Returns:
        Set of Common Name strings extracted from all certificate comment lines.
    """
    bundle_text = open(certifi.where(), encoding="utf-8").read()
    cns: set[str] = set()
    for line in bundle_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Label:"):
            # '# Label: "emSign Root CA - C1"'
            cns.add(stripped.split('"')[1] if '"' in stripped else stripped[9:].strip())
        elif stripped.startswith("# Subject:") and "CN=" in stripped:
            cns.add(stripped.split("CN=")[-1].split(" O=")[0].strip())
    return cns


@pytest.mark.parametrize("cn,released", _REMOVED_ROOTS)
def test_removed_root_absent_from_certifi_bundle(cn: str, released: bool) -> None:
    """Assert that a Mozilla-removed root is not trusted by certifi.

    Args:
        cn: Certificate subject Common Name to check.
        released: True when a certifi release dropping this root is on PyPI.
    """
    cns = _subject_cns_in_bundle()
    if cn in cns:
        if not released:
            pytest.skip(
                f"certifi {certifi.__version__} still contains '{cn}'. "
                "The emSign removal is in certifi upstream main but not yet "
                "published to PyPI. Advance certifi>= pin once released."
            )
        pytest.fail(
            f"certifi {certifi.__version__} still trusts '{cn}'. "
            "Bump certifi minimum in pyproject.toml and refresh uv.lock."
        )


def test_certifi_version_meets_minimum() -> None:
    """Assert certifi meets the minimum version floor."""
    version = certifi.__version__
    parts = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version)
    assert parts is not None, f"Unexpected certifi version format: {version}"
    year, month, day = int(parts[1]), int(parts[2]), int(parts[3])
    assert (year, month, day) >= _MINIMUM_CERTIFI_VERSION, (
        f"certifi {version} is below the minimum {_MINIMUM_CERTIFI_VERSION}. "
        "Bump certifi>= in pyproject.toml and refresh uv.lock."
    )
