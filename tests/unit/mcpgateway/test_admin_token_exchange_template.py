# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_token_exchange_template.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The Admin UI renders the token-exchange grant option and field group for platform admins only.
"""

# Standard
from pathlib import Path
import re

# Third-Party
from jinja2 import Environment
import pytest

TEMPLATE = Path(__file__).resolve().parents[3] / "mcpgateway" / "templates" / "admin.html"


def _extract(source: str, start_marker: str, end_marker: str) -> str:
    """Return the template slice from the element holding ``start_marker`` through ``end_marker``."""
    start = source.rindex("<", 0, source.index(start_marker))
    end = source.index(end_marker, start) + len(end_marker)
    return source[start:end]


def _render(fragment: str, is_admin: bool) -> str:
    return Environment(autoescape=True).from_string(fragment).render(is_admin=is_admin)


@pytest.fixture(scope="module")
def fragments() -> dict[str, str]:
    source = TEMPLATE.read_text(encoding="utf-8")
    return {
        "add_select": _extract(source, 'id="oauth-grant-type-gw"', "</select>"),
        "edit_select": _extract(source, 'id="oauth-grant-type-gw-edit"', "</select>"),
        "add_group": source[source.rindex("{% if is_admin %}", 0, source.index('id="oauth-token-exchange-fields-gw"')) : source.index('<div id="oauth-auth-code-fields-gw">')],
        "edit_group": source[source.rindex("{% if is_admin %}", 0, source.index('id="oauth-token-exchange-fields-gw-edit"')) : source.index('id="oauth-auth-code-fields-gw-edit"')],
    }


@pytest.mark.parametrize("name", ["add_select", "edit_select"])
def test_token_exchange_option_rendered_for_admin(fragments, name):
    assert 'value="token-exchange"' in _render(fragments[name], is_admin=True)


@pytest.mark.parametrize("name", ["add_select", "edit_select"])
def test_token_exchange_option_hidden_for_non_admin(fragments, name):
    html = _render(fragments[name], is_admin=False)
    assert 'value="token-exchange"' not in html
    assert 'value="client_credentials"' in html


@pytest.mark.parametrize(("name", "suffix"), [("add_group", "gw"), ("edit_group", "gw-edit")])
def test_token_exchange_field_group(fragments, name, suffix):
    admin_html = _render(fragments[name], is_admin=True)
    for field in ("oauth_target_audience", "oauth_subject_token_type", "oauth_requested_token_type", "oauth_subject_token_source", "oauth_token_endpoint_auth_method"):
        assert f'name="{field}"' in admin_html
    assert f'id="oauth-token-exchange-fields-{suffix}"' in admin_html
    assert re.search(r'<option value="private_key_jwt" hidden disabled>', admin_html)
    assert "oauth_target_audience" not in _render(fragments[name], is_admin=False)
