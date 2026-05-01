# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_plugins_page.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Playwright E2E tests for the plugins page mode UI.

Verifies that unified mode labels, deduplicated filters, mode badges,
detail modal, and stats card render correctly in the browser.

Requires PLUGINS_ENABLED=true and at least one loaded plugin.

Examples:
    pytest tests/playwright/test_plugins_page.py -v
    pytest tests/playwright/test_plugins_page.py -v -k "test_mode_badges"
"""

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.plugins_page import PluginsPage, RAW_LEGACY_MODES, UNIFIED_MODE_LABELS


def _skip_if_no_plugins(plugins_page: PluginsPage) -> None:
    plugins_page.navigate_to_plugins()
    if plugins_page.plugin_cards.count() == 0:
        pytest.skip("No plugins loaded — PLUGINS_ENABLED may be false or no plugins configured")


class TestPluginsPageModeUI:
    """End-to-end tests for plugin mode display, filtering, and detail modal."""

    def test_plugins_tab_loads(self, plugins_page: PluginsPage):
        """Plugins tab shows the panel and plugin grid."""
        plugins_page.navigate_to_plugins()
        expect(plugins_page.plugins_panel).not_to_have_class("hidden")
        expect(plugins_page.plugin_grid).to_be_visible()

    def test_mode_badges_use_unified_labels(self, plugins_page: PluginsPage):
        """Every plugin card shows a unified mode label, not a raw legacy value."""
        _skip_if_no_plugins(plugins_page)

        cards = plugins_page.get_visible_cards()
        assert len(cards) > 0, "Expected at least one visible plugin card"

        for card in cards:
            mode_attr = card.get_attribute("data-mode")
            assert mode_attr is not None, "Plugin card missing data-mode attribute"
            assert mode_attr not in RAW_LEGACY_MODES, (
                f"Card data-mode='{mode_attr}' is a raw legacy value — "
                f"expected a unified label from {UNIFIED_MODE_LABELS}"
            )
            badge = card.locator("span.text-xs.font-medium.rounded")
            if badge.count() > 0:
                badge_text = badge.first.text_content().strip()
                assert badge_text in UNIFIED_MODE_LABELS, (
                    f"Badge text '{badge_text}' not in unified labels: {UNIFIED_MODE_LABELS}"
                )

    def test_mode_filter_dropdown_has_deduplicated_options(self, plugins_page: PluginsPage):
        """Mode filter dropdown has 'All Modes' first and no duplicate labels."""
        _skip_if_no_plugins(plugins_page)

        options = plugins_page.get_mode_filter_options()
        assert len(options) >= 2, f"Expected at least 2 filter options, got {len(options)}"
        assert options[0] == "All Modes", f"First option should be 'All Modes', got '{options[0]}'"

        mode_options = options[1:]
        assert len(mode_options) == len(set(mode_options)), (
            f"Duplicate mode options found: {mode_options}"
        )

    def test_mode_filter_filters_cards(self, plugins_page: PluginsPage):
        """Selecting a mode in the filter hides non-matching cards."""
        _skip_if_no_plugins(plugins_page)

        options = plugins_page.get_mode_filter_options()
        if len(options) < 2:
            pytest.skip("Need at least one mode option to test filtering")

        target_mode = options[1]
        plugins_page.mode_filter.select_option(label=target_mode)
        plugins_page.page.wait_for_timeout(500)

        all_cards = plugins_page.plugin_cards
        for i in range(all_cards.count()):
            card = all_cards.nth(i)
            card_mode = card.get_attribute("data-mode")
            if card.is_visible():
                assert card_mode == target_mode, (
                    f"Visible card has data-mode='{card_mode}', expected '{target_mode}'"
                )

        plugins_page.mode_filter.select_option(value="")

    def test_plugin_detail_modal_shows_unified_mode(self, plugins_page: PluginsPage):
        """The detail modal displays a unified mode label with appropriate color."""
        _skip_if_no_plugins(plugins_page)

        first_card = plugins_page.plugin_cards.first
        plugin_name = first_card.locator("[data-show-plugin]").get_attribute("data-show-plugin")
        assert plugin_name, "Could not find plugin name on first card"

        plugins_page.open_plugin_detail(plugin_name)

        expect(plugins_page.details_modal).not_to_have_class("hidden")
        modal_text = plugins_page.modal_content.text_content()

        found = any(label in modal_text for label in UNIFIED_MODE_LABELS)
        assert found, (
            f"Detail modal for '{plugin_name}' does not contain any unified mode label. "
            f"Modal text excerpt: {modal_text[:200]}"
        )

        plugins_page.close_detail_modal()

    def test_stats_card_shows_enforcing_count(self, plugins_page: PluginsPage):
        """The overview stats card shows an 'Enforcing' metric with a numeric count."""
        _skip_if_no_plugins(plugins_page)

        enforcing_label = plugins_page.page.locator("text=Enforcing")
        if enforcing_label.count() == 0:
            pytest.skip("No 'Enforcing' stat card found — may not be rendered in this config")

        stat_container = enforcing_label.locator("..")
        count_el = stat_container.locator(".text-3xl")
        count_text = count_el.text_content().strip()
        assert count_text.isdigit(), f"Enforcing count should be numeric, got '{count_text}'"
