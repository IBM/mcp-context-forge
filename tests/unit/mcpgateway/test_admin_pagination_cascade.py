# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_pagination_cascade.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for the pagination variable cascade bug in admin.html (#3244).

When multiple sections in admin.html compute pagination using a shared
``pagination`` variable, Jinja2 scoping causes later sections to inherit
stale values from earlier sections instead of computing from their own data.
"""

import pytest
from jinja2 import Environment


# ---------------------------------------------------------------------------
# This template mirrors the EXACT pattern used in admin.html for the
# servers (section 1) and tools (section 2) pagination blocks.
# See admin.html lines 2489-2503 and 3437-3451.
# ---------------------------------------------------------------------------

PAGINATION_TEMPLATE = """\
{# --- Section 1: Servers (may be hidden, may have 0 items) --- #}
{% if 'servers' not in hidden_sections %}
  {% set page = page if page is defined else 1 %}
  {% set per_page = per_page if per_page is defined else 50 %}
  {% set total_items = servers|length if servers is defined else 0 %}
  {% set total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 0 %}
  {% set has_prev = page > 1 %}
  {% set has_next = (page * per_page) < total_items %}

  {% set pagination = {
    'page': page,
    'per_page': per_page,
    'total_items': total_items,
    'total_pages': total_pages,
    'has_prev': has_prev,
    'has_next': has_next
  } %}
  SERVERS_TOTAL_ITEMS={{ pagination.total_items }}
  SERVERS_TOTAL_PAGES={{ pagination.total_pages }}
{% endif %}

{# --- Section 2: Tools (visible, has items) --- #}
{% if 'tools' not in hidden_sections %}
  {% set page = page if page is defined else 1 %}
  {% set per_page = per_page if per_page is defined else 50 %}
  {% set total_items = tools|length if tools is defined else 0 %}
  {% set total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 0 %}
  {% set has_prev = page > 1 %}
  {% set has_next = (page * per_page) < total_items %}

  {% set pagination = {
    'page': page,
    'per_page': per_page,
    'total_items': total_items,
    'total_pages': total_pages,
    'has_prev': has_prev,
    'has_next': has_next
  } %}
  TOOLS_TOTAL_ITEMS={{ pagination.total_items }}
  TOOLS_TOTAL_PAGES={{ pagination.total_pages }}
{% endif %}

{# --- Section 3: Gateways (visible, has items) --- #}
{% if 'gateways' not in hidden_sections %}
  {% set page = page if page is defined else 1 %}
  {% set per_page = per_page if per_page is defined else 50 %}
  {% set total_items = gateways|length if gateways is defined else 0 %}
  {% set total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 0 %}
  {% set has_prev = page > 1 %}
  {% set has_next = (page * per_page) < total_items %}

  {% set pagination = {
    'page': page,
    'per_page': per_page,
    'total_items': total_items,
    'total_pages': total_pages,
    'has_prev': has_prev,
    'has_next': has_next
  } %}
  GATEWAYS_TOTAL_ITEMS={{ pagination.total_items }}
  GATEWAYS_TOTAL_PAGES={{ pagination.total_pages }}
{% endif %}
"""


def _parse_output(rendered: str) -> dict[str, int]:
    """Parse KEY=VALUE pairs from rendered template output."""
    result = {}
    for line in rendered.strip().splitlines():
        line = line.strip()
        if "=" in line and line[0].isalpha():
            key, val = line.split("=", 1)
            result[key.strip()] = int(val.strip())
    return result


class TestPaginationVariableCascade:
    """Verify that each section computes pagination from its OWN data, not from a shared variable."""

    def test_tools_pagination_not_poisoned_by_empty_servers(self):
        """When servers has 0 items, tools section must still show correct pagination.

        This is the core bug: servers sets pagination.total_items=0 and
        pagination.total_pages=0. Because Jinja2 {% set %} inside {% if %}
        propagates to enclosing scope, the tools section reads the stale
        pagination dict instead of computing from tools|length.
        """
        env = Environment()
        template = env.from_string(PAGINATION_TEMPLATE)

        rendered = template.render(
            hidden_sections=set(),
            servers=[],  # 0 servers
            tools=[{"name": f"tool-{i}"} for i in range(75)],  # 75 tools
            gateways=[{"name": f"gw-{i}"} for i in range(30)],  # 30 gateways
        )

        values = _parse_output(rendered)

        # Servers should correctly show 0
        assert values["SERVERS_TOTAL_ITEMS"] == 0
        assert values["SERVERS_TOTAL_PAGES"] == 0

        # Tools must compute from its own data (75 items), NOT inherit 0 from servers
        assert values["TOOLS_TOTAL_ITEMS"] == 75, (
            f"Tools inherited stale total_items={values['TOOLS_TOTAL_ITEMS']} from servers "
            f"instead of computing 75 from its own tools list"
        )
        assert values["TOOLS_TOTAL_PAGES"] == 2, (
            f"Tools inherited stale total_pages={values['TOOLS_TOTAL_PAGES']} from servers "
            f"instead of computing 2 (ceil(75/50))"
        )

        # Gateways must compute from its own data (30 items), NOT inherit from tools or servers
        assert values["GATEWAYS_TOTAL_ITEMS"] == 30, (
            f"Gateways inherited stale total_items={values['GATEWAYS_TOTAL_ITEMS']} "
            f"instead of computing 30 from its own gateways list"
        )

    def test_tools_pagination_correct_when_servers_hidden(self):
        """When servers section is hidden, tools must not inherit stale pagination.

        Even when the servers section is hidden (not rendered), the tools
        section should compute its own pagination independently.
        """
        env = Environment()
        template = env.from_string(PAGINATION_TEMPLATE)

        rendered = template.render(
            hidden_sections={"servers"},  # servers hidden
            servers=[],
            tools=[{"name": f"tool-{i}"} for i in range(120)],  # 120 tools → 3 pages
            gateways=[{"name": f"gw-{i}"} for i in range(10)],
        )

        values = _parse_output(rendered)

        # Servers should not appear at all
        assert "SERVERS_TOTAL_ITEMS" not in values

        # Tools must compute from its own data
        assert values["TOOLS_TOTAL_ITEMS"] == 120
        assert values["TOOLS_TOTAL_PAGES"] == 3  # ceil(120/50)

    def test_later_section_not_poisoned_by_earlier_with_different_counts(self):
        """Each section must reflect its own item count, not an earlier section's."""
        env = Environment()
        template = env.from_string(PAGINATION_TEMPLATE)

        rendered = template.render(
            hidden_sections=set(),
            servers=[{"name": f"srv-{i}"} for i in range(200)],  # 200 servers → 4 pages
            tools=[{"name": f"tool-{i}"} for i in range(25)],  # 25 tools → 1 page
            gateways=[{"name": f"gw-{i}"} for i in range(150)],  # 150 gateways → 3 pages
        )

        values = _parse_output(rendered)

        assert values["SERVERS_TOTAL_ITEMS"] == 200
        assert values["SERVERS_TOTAL_PAGES"] == 4

        assert values["TOOLS_TOTAL_ITEMS"] == 25, (
            f"Tools shows {values['TOOLS_TOTAL_ITEMS']} items instead of 25 "
            f"(leaked from servers section)"
        )
        assert values["TOOLS_TOTAL_PAGES"] == 1

        assert values["GATEWAYS_TOTAL_ITEMS"] == 150, (
            f"Gateways shows {values['GATEWAYS_TOTAL_ITEMS']} items instead of 150 "
            f"(leaked from earlier section)"
        )
        assert values["GATEWAYS_TOTAL_PAGES"] == 3
