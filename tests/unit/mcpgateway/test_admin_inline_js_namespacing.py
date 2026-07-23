# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_inline_js_namespacing.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Forterro

Regression tests ensuring inline <script> blocks in admin.html reference
shared helpers through the ``Admin`` namespace instead of as bare globals.

Inline scripts in ``admin.html`` are NOT part of the bundled JS module, so
functions that are only exposed on ``window.Admin`` (e.g. ``getPaginationParams``)
are out of scope when called bare. Calling them bare throws a synchronous
``ReferenceError``.

Concretely this guards against the "My Teams" tab infinite "Loading teams..."
loop: ``initializeTeamManagement()`` used to call the bare global
``getPaginationParams('teams')``. The ReferenceError fired before the HTMX
request to ``/admin/teams/partial`` was issued, so the ``#teams-loading``
spinner was never replaced.
"""

# Standard
from pathlib import Path
import re
from typing import List

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "mcpgateway" / "templates"
ADMIN_TEMPLATE = TEMPLATES_DIR / "admin.html"

# Helpers that are exposed exclusively on the ``Admin`` namespace (admin.js)
# and therefore must never be called as bare globals inside inline scripts.
ADMIN_ONLY_HELPERS = ("getPaginationParams",)


def _inline_script_blocks(html: str) -> List[str]:
    """Return the contents of inline ``<script>`` blocks (those without a ``src``).

    External ``<script src=...>`` tags (the bundle) carry no inline body and are
    skipped — only template-authored inline JS is returned.
    """
    blocks: List[str] = []
    for match in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE):
        attrs, body = match.group(1), match.group(2)
        if "src=" in attrs.lower():
            continue
        blocks.append(body)
    return blocks


class TestAdminInlineJsNamespacing:
    """Inline admin scripts must call Admin-only helpers via the Admin namespace."""

    def test_no_bare_calls_to_admin_only_helpers(self) -> None:
        """No inline script may call an Admin-only helper as a bare global."""
        html = ADMIN_TEMPLATE.read_text(encoding="utf-8")
        offenders: List[str] = []

        for body in _inline_script_blocks(html):
            for helper in ADMIN_ONLY_HELPERS:
                # A bare call is ``helper(`` not preceded by ``.`` (which would
                # make it ``Admin.helper(`` or ``window.Admin.helper(``) and not
                # part of a longer identifier.
                pattern = r"(?<![.\w])" + re.escape(helper) + r"\s*\("
                for hit in re.finditer(pattern, body):
                    line = body.count("\n", 0, hit.start()) + 1
                    offenders.append(f"{helper}( called bare in inline script (script-relative line {line})")

        assert not offenders, "Inline scripts must use the Admin namespace for these helpers:\n  " + "\n  ".join(offenders)

    def test_team_management_init_uses_admin_namespace(self) -> None:
        """initializeTeamManagement() must reference Admin.getPaginationParams."""
        html = ADMIN_TEMPLATE.read_text(encoding="utf-8")

        match = re.search(r"function\s+initializeTeamManagement\s*\(\s*\)\s*\{", html)
        assert match is not None, "initializeTeamManagement() not found in admin.html"

        # Inspect the function body up to the HTMX call that loads the partial.
        body = html[match.end() : match.end() + 4000]
        assert "Admin.getPaginationParams('teams')" in body, "initializeTeamManagement() must call Admin.getPaginationParams('teams')"
        assert not re.search(r"(?<![.\w])getPaginationParams\s*\(", body), "initializeTeamManagement() must not call the bare global getPaginationParams()"
