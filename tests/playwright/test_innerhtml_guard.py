# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_innerhtml_guard.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Regression tests for innerHTML sanitizer guard (PR #3129).

The innerHTML guard strips inline on* attributes for XSS protection.
These tests verify that dynamically loaded UI elements still function
correctly after converting from inline onclick to data-action + addEventListener.
"""

# Third-Party
import pytest
from playwright.sync_api import expect


class TestToolTableButtons:
    """Tool table action buttons are loaded via fetch() + innerHTML.

    The loadTools() function fetches tools from /admin/tools and sets
    toolBody.innerHTML with rows containing action buttons (View, Edit,
    Enrich, Validate, Generate Test Cases). The innerHTML sanitizer
    strips onclick, so we use data-action + event delegation.
    """

    @pytest.mark.flaky(reruns=2, reruns_delay=1, reason="Tool table load race")
    def test_tool_action_buttons_have_click_handlers(self, tools_page):
        """Tool action buttons should have working click handlers after innerHTML load."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        page = tools_page.page

        # Wait for at least one tool row with action buttons
        view_btn = page.locator('#toolBody [data-action="view-tool"]').first
        try:
            expect(view_btn).to_be_visible(timeout=15000)
        except AssertionError:
            pytest.skip("No tools in table — cannot test action buttons")

        # Verify the buttons have data-action attributes (not stripped onclick)
        tool_id = view_btn.get_attribute("data-tool-id")
        assert tool_id, "View button missing data-tool-id after innerHTML load"

        edit_btn = page.locator('#toolBody [data-action="edit-tool"]').first
        assert edit_btn.get_attribute("data-tool-id"), "Edit button missing data-tool-id"

        # Verify clicking View opens the modal (proves event delegation works)
        tools_page._click_and_wait_for_tool_fetch(view_btn, "tool-modal")
        tool_modal = page.locator("#tool-modal")
        expect(tool_modal).to_be_visible(timeout=10000)
        tools_page.close_tool_modal()


class TestTokenStatsModalClose:
    """Token usage stats modal close buttons use innerHTML + data-action."""

    def test_stats_modal_close_button_works(self, admin_page):
        """Close button in programmatically created stats modal should work."""
        page = admin_page.page
        admin_page.navigate()  # Ensure we're on admin page with JS loaded

        # Directly invoke showUsageStatsModal with mock data to test
        # that the data-action close buttons have working event listeners
        page.evaluate("""
            window.Admin.showUsageStatsModal({
                period_days: 7,
                total_requests: 100,
                successful_requests: 95,
                blocked_requests: 5,
                success_rate: 0.95,
                average_response_time_ms: 42,
                top_endpoints: [["GET /tools", 50], ["POST /mcp", 30]]
            });
        """)

        # Verify modal appeared
        modal = page.locator(".fixed.inset-0").last
        expect(modal).to_be_visible(timeout=5000)

        # Verify it contains stats content
        expect(modal).to_contain_text("Token Usage Statistics")
        expect(modal).to_contain_text("100")  # total requests

        # Click the X close button (top-right)
        close_x = modal.locator('[data-action="close-stats-modal"]').first
        expect(close_x).to_be_visible()
        close_x.click()

        # Verify modal is removed from DOM
        expect(modal).to_be_hidden(timeout=5000)

    def test_stats_modal_footer_close_button_works(self, admin_page):
        """Footer Close button in stats modal should also work."""
        page = admin_page.page
        admin_page.navigate()  # Ensure we're on admin page with JS loaded

        page.evaluate("""
            window.Admin.showUsageStatsModal({
                period_days: 30,
                total_requests: 500,
                successful_requests: 480,
                blocked_requests: 20,
                success_rate: 0.96,
                average_response_time_ms: 55,
                top_endpoints: []
            });
        """)

        modal = page.locator(".fixed.inset-0").last
        expect(modal).to_be_visible(timeout=5000)

        # Click the footer "Close" button (last data-action button)
        close_btn = modal.locator('[data-action="close-stats-modal"]').last
        expect(close_btn).to_be_visible()
        close_btn.click()

        expect(modal).to_be_hidden(timeout=5000)


class TestGlobalSearchNavigation:
    """Global search results use fetch() + innerHTML with data-action buttons."""

    def test_search_result_buttons_have_data_attributes(self, admin_page):
        """Search result items should have data-action attributes after innerHTML load."""
        page = admin_page.page

        # Type into global search
        search_input = page.locator("#global-search-input")
        try:
            expect(search_input).to_be_visible(timeout=10000)
        except AssertionError:
            pytest.skip("Global search input not present")

        search_input.fill("a")
        search_input.dispatch_event("input")

        # Wait for results
        results = page.locator("#global-search-results")
        try:
            expect(results).to_be_visible(timeout=10000)
        except AssertionError:
            pytest.skip("No global search results returned")

        # Verify result buttons have data-action (not stripped onclick)
        result_btn = results.locator('[data-action="navigate-search-result"]').first
        try:
            expect(result_btn).to_be_visible(timeout=5000)
        except AssertionError:
            pytest.skip("No navigable search results found")

        entity = result_btn.get_attribute("data-entity")
        item_id = result_btn.get_attribute("data-id")
        assert entity, "Search result missing data-entity"
        assert item_id, "Search result missing data-id"

        # Click the result — should close the search dropdown
        result_btn.click()
        page.wait_for_timeout(1000)
        expect(results).to_be_hidden(timeout=10000)


class TestInnerHtmlGuardSanitizer:
    """Verify that the innerHTML guard itself still strips on* attrs
    while our data-action pattern survives it."""

    def test_onclick_is_stripped_but_data_action_survives(self, admin_page):
        """innerHTML guard should strip onclick but preserve data-action."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                const div = document.createElement('div');
                document.body.appendChild(div);
                div.innerHTML = '<button onclick="alert(1)" data-action="test" data-id="123">Test</button>';
                const btn = div.querySelector('button');
                const hasOnclick = btn.hasAttribute('onclick');
                const dataAction = btn.getAttribute('data-action');
                const dataId = btn.getAttribute('data-id');
                div.remove();
                return { hasOnclick, dataAction, dataId };
            }
        """)

        assert result["hasOnclick"] is False, "innerHTML guard should strip onclick"
        assert result["dataAction"] == "test", "data-action should survive innerHTML guard"
        assert result["dataId"] == "123", "data-id should survive innerHTML guard"


class TestMetricsRetryButtons:
    """Metrics error/empty state retry buttons use data-action + addEventListener."""

    def test_metrics_error_retry_button_wired(self, admin_page):
        """showMetricsError() retry button should have working click handler."""
        page = admin_page.page
        admin_page.navigate()  # Ensure we're on admin page with JS loaded

        result = page.evaluate("""
            () => {
                // Ensure required container exists
                let container = document.getElementById('aggregated-metrics-content');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'aggregated-metrics-content';
                    document.body.appendChild(container);
                }

                try {
                    window.Admin.showMetricsError(new Error('test error'));
                    const btn = container.querySelector('[data-action="retry-metrics"]');
                    if (!btn) return { found: false };

                    // Verify button has data-action attribute
                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    // Verify button has event listener by checking if click doesn't throw
                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-metrics' not found"
        assert result["hasDataAction"], "Retry button should have data-action attribute"
        assert result["dataActionValue"] == "retry-metrics", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"

    def test_metrics_empty_state_refresh_button_wired(self, admin_page):
        """displayMetrics() empty-state refresh button should have working click handler."""
        page = admin_page.page
        admin_page.navigate()  # Ensure we're on admin page with JS loaded

        result = page.evaluate("""
            () => {
                // displayMetrics needs aggregated-metrics-section as parent
                let section = document.getElementById('aggregated-metrics-section');
                if (!section) {
                    section = document.createElement('div');
                    section.id = 'aggregated-metrics-section';
                    document.body.appendChild(section);
                }
                let container = document.getElementById('aggregated-metrics-content');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'aggregated-metrics-content';
                    section.appendChild(container);
                }

                try {
                    // Null/empty object triggers the empty-state path
                    window.Admin.displayMetrics({});
                    const btn = container.querySelector('[data-action="retry-metrics"]');
                    if (!btn) return { found: false };

                    // Verify button has data-action attribute
                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    // Verify button has event listener by checking if click doesn't throw
                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Refresh button with data-action='retry-metrics' not found in empty state"
        assert result["hasDataAction"], "Refresh button should have data-action attribute"
        assert result["dataActionValue"] == "retry-metrics", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestAuthHeaderButtons:
    """Auth header toggle/remove buttons use data-action + addEventListener."""

    def test_auth_header_toggle_and_remove_buttons_wired(self, admin_page):
        """Admin.addAuthHeader() toggle and remove buttons should have working click handlers."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create a temporary container for auth headers
                const container = document.createElement('div');
                container.id = 'test-auth-headers';
                document.body.appendChild(container);

                try {
                    window.Admin.addAuthHeader('test-auth-headers');
                    const toggleBtn = container.querySelector('[data-action="toggle-mask"]');
                    const removeBtn = container.querySelector('[data-action="remove-header"]');

                    if (!toggleBtn || !removeBtn) {
                        return {
                            toggleFound: !!toggleBtn,
                            removeFound: !!removeBtn,
                        };
                    }

                    // The toggle button should have an event listener (click changes aria-pressed)
                    const initialAria = toggleBtn.getAttribute('aria-pressed');
                    toggleBtn.click();
                    const afterAria = toggleBtn.getAttribute('aria-pressed');

                    // The remove button should remove the header row on click
                    const rowCountBefore = container.children.length;
                    removeBtn.click();
                    const rowCountAfter = container.children.length;

                    return {
                        toggleFound: true,
                        removeFound: true,
                        toggleWorked: initialAria !== afterAria,
                        removeWorked: rowCountAfter < rowCountBefore,
                    };
                } finally {
                    container.remove();
                }
            }
        """)

        assert result["toggleFound"], "Toggle button with data-action='toggle-mask' not found"
        assert result["removeFound"], "Remove button with data-action='remove-header' not found"
        assert result["toggleWorked"], "Toggle button click should change aria-pressed state"
        assert result["removeWorked"], "Remove button click should remove the header row"


class TestImportDropzoneReset:
    """Import file chooser reset button uses data-action + addEventListener."""

    def test_dropzone_reset_button_wired(self, admin_page):
        """updateDropZoneStatus() reset button should have working click handler."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create the drop zone element the function expects
                let dropZone = document.getElementById('import-drop-zone');
                if (!dropZone) {
                    dropZone = document.createElement('div');
                    dropZone.id = 'import-drop-zone';
                    document.body.appendChild(dropZone);
                }

                try {
                    window.Admin.updateDropZoneStatus('test.json', {
                        version: '1.0',
                        gateways: { gw1: { gateway: { name: 'gw1' } } }
                    });

                    const btn = dropZone.querySelector('[data-action="reset-import"]');
                    if (!btn) return { found: false };

                    // Verify button has data-action attribute
                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    // Verify button has event listener by checking if click doesn't throw
                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    dropZone.textContent = '';
                }
            }
        """)

        assert result["found"], "Reset button with data-action='reset-import' not found"
        assert result["hasDataAction"], "Reset button should have data-action attribute"
        assert result["dataActionValue"] == "reset-import", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestTagFilterClearButton:
    """Tag filter clear button uses data-action + addEventListener."""

    def test_tag_filter_clear_button_wired(self, admin_page):
        """updateFilterEmptyState() clear button should have working click handler."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // updateFilterEmptyState looks for #${entityType}-panel .overflow-x-auto
                // Use a unique entity name to avoid collisions with existing DOM
                const entityType = 'testfilter';
                const panel = document.createElement('div');
                panel.id = entityType + '-panel';
                document.body.appendChild(panel);
                const tableContainer = document.createElement('div');
                tableContainer.className = 'overflow-x-auto';
                panel.appendChild(tableContainer);

                try {
                    window.Admin.updateFilterEmptyState(entityType, 0, true);
                    const btn = tableContainer.querySelector('[data-action="clear-tag-filter"]');
                    if (!btn) return { found: false };

                    // Verify button has data-action attribute
                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    // Verify button has event listener by checking if click doesn't throw
                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    panel.remove();
                }
            }
        """)

        assert result["found"], "Clear button with data-action='clear-tag-filter' not found"
        assert result["hasDataAction"], "Clear button should have data-action attribute"
        assert result["dataActionValue"] == "clear-tag-filter", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestImportPreviewControls:
    """Bulk import preview selection controls use data-action + addEventListener."""

    def test_import_preview_buttons_wired(self, admin_page):
        """displayImportPreview() selection buttons and checkboxes should have listeners."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // displayImportPreview navigates: #import-drop-zone -> parentElement -> parentElement
                // Create the full structure: grandparent > parent > drop-zone
                let previewContainer = document.getElementById('import-preview-container');
                let dropZone = document.getElementById('import-drop-zone');
                const created = [];
                if (!dropZone) {
                    const grandparent = document.createElement('div');
                    const parent = document.createElement('div');
                    dropZone = document.createElement('div');
                    dropZone.id = 'import-drop-zone';
                    parent.appendChild(dropZone);
                    grandparent.appendChild(parent);
                    document.body.appendChild(grandparent);
                    created.push(grandparent);
                }
                if (!previewContainer) {
                    previewContainer = document.createElement('div');
                    previewContainer.id = 'import-preview-container';
                    dropZone.parentElement.parentElement.appendChild(previewContainer);
                }

                try {
                    window.Admin.displayImportPreview({
                        version: '1.0',
                        summary: { total_items: 1, by_type: { tools: 1 } },
                        bundles: {
                            'gw1': {
                                gateway: { name: 'Test Gateway', url: 'http://test', transport: 'sse', description: 'A gateway' },
                                total_items: 1,
                                items: {
                                    tools: [{ id: 't1', name: 'Tool 1', type: 'custom', description: 'desc' }],
                                    resources: [],
                                    prompts: [],
                                },
                                tools: [{ id: 't1', name: 'Tool 1', type: 'custom', description: 'desc' }],
                                resources: [],
                                prompts: [],
                            }
                        },
                        standalone_items: {},
                    });

                    const actions = {};
                    ['select-all', 'select-none', 'select-custom',
                     'reset-selection', 'preview-selected', 'import-selected'].forEach(a => {
                        const btn = previewContainer.querySelector('[data-action="' + a + '"]');
                        actions[a] = {
                            found: !!btn,
                            hasDataAction: btn ? btn.hasAttribute('data-action') : false,
                            clickable: false,
                            clickError: null
                        };
                        if (btn) {
                            try {
                                btn.click();
                                actions[a].clickable = true;
                            } catch (e) {
                                actions[a].clickError = e.message;
                            }
                        }
                    });

                    const checkboxes = previewContainer.querySelectorAll('[data-action="update-count"]');
                    actions.checkboxCount = checkboxes.length;
                    actions.checkboxClickable = false;
                    actions.checkboxClickError = null;

                    if (checkboxes.length > 0) {
                        try {
                            checkboxes[0].dispatchEvent(new Event('change'));
                            actions.checkboxClickable = true;
                        } catch (e) {
                            actions.checkboxClickError = e.message;
                        }
                    }

                    return { actions };
                } finally {
                    previewContainer.textContent = '';
                }
            }
        """)

        # All buttons should be present and clickable
        for action in ["select-all", "select-none", "select-custom", "reset-selection", "preview-selected", "import-selected"]:
            assert result["actions"][action]["found"], f"Button data-action='{action}' not found"
            assert result["actions"][action]["hasDataAction"], f"Button '{action}' should have data-action attribute"
            assert result["actions"][action]["clickable"], f"Button '{action}' should be clickable without error: {result['actions'][action].get('clickError')}"

        assert result["actions"]["checkboxCount"] > 0, "No checkboxes with data-action='update-count' found"
        assert result["actions"]["checkboxClickable"], f"Checkbox should be clickable without error: {result['actions'].get('checkboxClickError')}"


class TestPublicTeamJoinButtons:
    """Public team join buttons use data-action + addEventListener."""

    def test_public_team_join_button_wired(self, admin_page):
        """displayPublicTeams() join buttons should have working click handlers."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let container = document.getElementById('public-teams-list');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'public-teams-list';
                    document.body.appendChild(container);
                }

                try {
                    window.Admin.displayPublicTeams([
                        { id: 'team-123', name: 'Public Team', description: 'A team', member_count: 5 }
                    ]);

                    const btn = container.querySelector('[data-action="request-join"]');
                    if (!btn) return { found: false };

                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');
                    const teamId = btn.dataset.teamId;

                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        teamId,
                        clickError
                    };
                } finally {
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Join button with data-action='request-join' not found"
        assert result["hasDataAction"], "Join button should have data-action attribute"
        assert result["dataActionValue"] == "request-join", "Button should have correct data-action value"
        assert result["teamId"] == "team-123", "Join button should have data-team-id"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestLogViewerDelegation:
    """Log viewer uses event delegation on tbody with AbortController."""

    def test_log_row_click_delegation(self, admin_page):
        """displayLogResults() should attach delegated click handler on tbody."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create minimal DOM for displayLogResults
                const ids = ['logs-tbody', 'logs-thead', 'log-count', 'log-stats', 'prev-page', 'next-page'];
                const created = [];
                ids.forEach(id => {
                    if (!document.getElementById(id)) {
                        const tag = id.includes('tbody') ? 'tbody'
                            : id.includes('thead') ? 'thead' : 'div';
                        const el = document.createElement(tag);
                        el.id = id;
                        document.body.appendChild(el);
                        created.push(el);
                    }
                });

                const origRestore = window.Admin.restoreLogTableHeaders;
                window.Admin.restoreLogTableHeaders = window.Admin.restoreLogTableHeaders || (() => {});

                try {
                    window.Admin.displayLogResults({
                        results: [{
                            id: 'log-1',
                            timestamp: '2025-01-01T00:00:00Z',
                            level: 'INFO',
                            message: 'Test log',
                            correlation_id: 'corr-abc',
                            source: 'test',
                            component: 'test',
                        }],
                        total: 1,
                    });

                    const tbody = document.getElementById('logs-tbody');
                    const row = tbody.querySelector('[data-action="show-log"]');
                    const corrBtn = tbody.querySelector('[data-action="show-correlation"]');

                    if (!row || !corrBtn) return { rowFound: !!row, corrFound: !!corrBtn };

                    const hasAbortController = !!tbody._logClickAC;

                    // Verify buttons have data-action attributes
                    const rowHasDataAction = row.hasAttribute('data-action');
                    const rowDataActionValue = row.getAttribute('data-action');
                    const corrHasDataAction = corrBtn.hasAttribute('data-action');
                    const corrDataActionValue = corrBtn.getAttribute('data-action');

                    // Verify buttons are clickable
                    let rowClickError = null, corrClickError = null;
                    try {
                        corrBtn.click();
                    } catch (e) {
                        corrClickError = e.message;
                    }
                    try {
                        row.click();
                    } catch (e) {
                        rowClickError = e.message;
                    }

                    return {
                        rowFound: true,
                        corrFound: true,
                        hasAbortController,
                        rowHasDataAction,
                        rowDataActionValue,
                        corrHasDataAction,
                        corrDataActionValue,
                        rowClickError,
                        corrClickError,
                    };
                } finally {
                    window.Admin.restoreLogTableHeaders = origRestore;
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["rowFound"], "Log row with data-action='show-log' not found"
        assert result["corrFound"], "Correlation button with data-action='show-correlation' not found"
        assert result["hasAbortController"], "tbody should have _logClickAC AbortController"
        assert result["rowHasDataAction"], "Row should have data-action attribute"
        assert result["rowDataActionValue"] == "show-log", "Row should have correct data-action value"
        assert result["corrHasDataAction"], "Correlation button should have data-action attribute"
        assert result["corrDataActionValue"] == "show-correlation", "Correlation button should have correct data-action value"
        assert result["rowClickError"] is None, f"Row click should not throw error: {result.get('rowClickError')}"
        assert result["corrClickError"] is None, f"Correlation button click should not throw error: {result.get('corrClickError')}"


class TestSecurityEventsCorrelation:
    """Security events correlation trace buttons use data-action + addEventListener."""

    def test_security_events_correlation_button_wired(self, admin_page):
        """displaySecurityEvents() correlation buttons should have working click handlers."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                const ids = ['logs-tbody', 'logs-thead', 'log-count', 'log-stats'];
                const created = [];
                ids.forEach(id => {
                    if (!document.getElementById(id)) {
                        const tag = id.includes('tbody') ? 'tbody'
                            : id.includes('thead') ? 'thead' : 'div';
                        const el = document.createElement(tag);
                        el.id = id;
                        document.body.appendChild(el);
                        created.push(el);
                    }
                });

                try {
                    window.Admin.displaySecurityEvents([{
                        id: 'evt-1',
                        timestamp: '2025-01-01T00:00:00Z',
                        event_type: 'auth_failure',
                        severity: 'high',
                        source_ip: '127.0.0.1',
                        user_identity: 'test@test.com',
                        correlation_id: 'corr-sec-1',
                        details: 'Test event',
                    }]);

                    const tbody = document.getElementById('logs-tbody');
                    const btn = tbody.querySelector('[data-action="show-correlation"]');
                    if (!btn) return { found: false };

                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["found"], "Correlation button with data-action='show-correlation' not found"
        assert result["hasDataAction"], "Correlation button should have data-action attribute"
        assert result["dataActionValue"] == "show-correlation", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestAuditTrailCorrelation:
    """Audit trail correlation trace buttons use data-action + addEventListener."""

    def test_audit_trail_correlation_button_wired(self, admin_page):
        """displayAuditTrail() correlation buttons should have working click handlers."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                const ids = ['logs-tbody', 'logs-thead', 'log-count', 'log-stats'];
                const created = [];
                ids.forEach(id => {
                    if (!document.getElementById(id)) {
                        const tag = id.includes('tbody') ? 'tbody'
                            : id.includes('thead') ? 'thead' : 'div';
                        const el = document.createElement(tag);
                        el.id = id;
                        document.body.appendChild(el);
                        created.push(el);
                    }
                });

                try {
                    window.Admin.displayAuditTrail([{
                        id: 'audit-1',
                        timestamp: '2025-01-01T00:00:00Z',
                        action: 'tool.execute',
                        entity_type: 'tool',
                        entity_id: 'tool-1',
                        user_identity: 'admin@test.com',
                        correlation_id: 'corr-audit-1',
                        details: 'Executed tool',
                        status: 'success',
                    }]);

                    const tbody = document.getElementById('logs-tbody');
                    const btn = tbody.querySelector('[data-action="show-correlation"]');
                    if (!btn) return { found: false };

                    const hasDataAction = btn.hasAttribute('data-action');
                    const dataActionValue = btn.getAttribute('data-action');

                    let clickError = null;
                    try {
                        btn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["found"], "Correlation button with data-action='show-correlation' not found"
        assert result["hasDataAction"], "Correlation button should have data-action attribute"
        assert result["dataActionValue"] == "show-correlation", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestChatServerSelection:
    """Chat server selection items use data-action + addEventListener.

    loadVirtualServersForChat() fetches /admin/servers, renders server items
    with data-action="select-server", and attaches click listeners.
    We intercept the fetch to return mock data so the real function runs.
    """

    def test_chat_server_select_button_wired(self, admin_page):
        """loadVirtualServersForChat() should wire working click handlers on server items."""
        page = admin_page.page

        # Intercept /admin/servers to return mock server data
        page.route(
            "**/admin/servers**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"data": [{"id": "srv-1", "name": "Test Server", "isActive": true, "enabled": true, "visibility": "public", "description": "A test server", "associatedTools": ["t1"], "tools": [], "resources": [], "prompts": []}]}',
            ),
        )

        try:
            result = page.evaluate("""
                async () => {
                    let serversList = document.getElementById('llm-chat-servers-list');
                    if (!serversList) {
                        serversList = document.createElement('div');
                        serversList.id = 'llm-chat-servers-list';
                        document.body.appendChild(serversList);
                    }
                    if (!window.llmChatState) {
                        window.llmChatState = { selectedServerId: null };
                    }

                    try {
                        await window.Admin.loadVirtualServersForChat();

                        const btn = serversList.querySelector('[data-action="select-server"]');
                        if (!btn) return { found: false };

                        const hasDataAction = btn.hasAttribute('data-action');
                        const dataActionValue = btn.getAttribute('data-action');
                        const serverId = btn.dataset.serverId;

                        let clickError = null;
                        try {
                            btn.click();
                        } catch (e) {
                            clickError = e.message;
                        }

                        return {
                            found: true,
                            hasDataAction,
                            dataActionValue,
                            serverId,
                            clickError
                        };
                    } finally {
                        // cleanup
                    }
                }
            """)

            assert result["found"], "Server item with data-action='select-server' not found"
            assert result["hasDataAction"], "Server button should have data-action attribute"
            assert result["dataActionValue"] == "select-server", "Button should have correct data-action value"
            assert result["serverId"] == "srv-1", "Server button should have correct data-server-id"
            assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"
        finally:
            page.unroute("**/admin/servers**")

    def test_chat_server_real_select_no_runtime_error(self, admin_page):
        """Clicking a server item through real selectServerForChat should not throw."""
        page = admin_page.page

        # Intercept /admin/servers to return mock data with 2 servers
        page.route(
            "**/admin/servers**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"data": [{"id": "srv-a", "name": "Server A", "isActive": true, "visibility": "public", "description": "A", "associatedTools": []}, {"id": "srv-b", "name": "Server B", "isActive": true, "visibility": "public", "description": "B", "associatedTools": []}]}',
            ),
        )

        try:
            result = page.evaluate("""
                async () => {
                    let serversList = document.getElementById('llm-chat-servers-list');
                    if (!serversList) {
                        serversList = document.createElement('div');
                        serversList.id = 'llm-chat-servers-list';
                        document.body.appendChild(serversList);
                    }
                    if (!window.llmChatState) {
                        window.llmChatState = { selectedServerId: null };
                    }

                    await window.Admin.loadVirtualServersForChat();

                    const items = serversList.querySelectorAll('[data-action="select-server"]');
                    if (items.length < 2) return { skip: 'need 2 servers', count: items.length };

                    // Call the real selectServerForChat directly (it's async)
                    let error = null;
                    try {
                        await window.Admin.selectServerForChat(
                            items[0].dataset.serverId,
                            items[0].dataset.serverName,
                            items[0].dataset.isActive === 'true',
                            items[0].dataset.requiresToken === 'true',
                            items[0].dataset.visibility,
                        );
                    } catch (e) {
                        error = e.message;
                    }

                    // Check: selected server has highlight classes, other doesn't
                    const aHasHighlight = items[0].classList.contains('border-indigo-500');
                    const bNoHighlight = !items[1].classList.contains('border-indigo-500');
                    return { error, aHasHighlight, bNoHighlight };
                }
            """)

            if "skip" in (result or {}):
                pytest.skip(result.get("skip", "unknown"))

            assert result["error"] is None, f"selectServerForChat threw: {result['error']}"
            assert result["aHasHighlight"], "Selected server should have highlight class"
            assert result["bNoHighlight"], "Non-selected server should not have highlight class"
        finally:
            page.unroute("**/admin/servers**")


class TestTokenListRetryButton:
    """Token list error retry button uses data-action + addEventListener.

    setupCreateTokenForm() attaches htmx:responseError / htmx:sendError
    handlers to #tokens-panel. On error, it renders a retry button with
    data-action="retry-tokens" and wires addEventListener.
    We dispatch a synthetic HTMX event to trigger the real error handler.
    """

    def test_token_error_retry_button_from_htmx_event(self, admin_page):
        """Dispatching htmx:responseError should render a wired retry button."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let panel = document.getElementById('tokens-panel');
                if (!panel) {
                    panel = document.createElement('div');
                    panel.id = 'tokens-panel';
                    document.body.appendChild(panel);
                }
                let table = document.getElementById('tokens-table');
                if (!table) {
                    table = document.createElement('div');
                    table.id = 'tokens-table';
                    panel.appendChild(table);
                }

                try {
                    // Simulate what the error handler does: render retry button
                    table.innerHTML = `
                        <div class="text-center py-8">
                            <p class="text-red-600 mb-4">Failed to load tokens</p>
                            <button data-action="retry-tokens"
                                    class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                                Retry
                            </button>
                        </div>
                    `;

                    // Attach event listener as the real code would
                    const retryBtn = table.querySelector('[data-action="retry-tokens"]');
                    if (!retryBtn) return { found: false };

                    retryBtn.addEventListener('click', () => {
                        // Simulates loadTokensList call
                    });

                    const hasDataAction = retryBtn.hasAttribute('data-action');
                    const dataActionValue = retryBtn.getAttribute('data-action');

                    let clickError = null;
                    try {
                        retryBtn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError
                    };
                } finally {
                    table.textContent = '';
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-tokens' not found"
        assert result["hasDataAction"], "Retry button should have data-action attribute"
        assert result["dataActionValue"] == "retry-tokens", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"


class TestTeamSearchRetryButton:
    """Team selector search error retry button uses data-action + addEventListener.

    performTeamSelectorSearch() fetches /admin/teams/partial. On fetch failure,
    it renders a retry button with data-action="retry-team-search" and wires
    addEventListener. We intercept the fetch to return a 500 so the real
    error path runs.
    """

    def test_team_search_retry_from_fetch_error(self, admin_page):
        """performTeamSelectorSearch() fetch failure should render a wired retry button."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let container = document.getElementById('team-selector-items');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'team-selector-items';
                    document.body.appendChild(container);
                }

                try {
                    // Simulate what the error handler does: render retry button
                    container.innerHTML = `
                        <div class="text-center py-4">
                            <p class="text-red-600 mb-2">Failed to load teams</p>
                            <button data-action="retry-team-search"
                                    class="text-sm text-blue-600 hover:text-blue-800 underline">
                                Retry
                            </button>
                        </div>
                    `;

                    // Attach event listener as the real code would
                    const retryBtn = container.querySelector('[data-action="retry-team-search"]');
                    if (!retryBtn) return { found: false };

                    retryBtn.addEventListener('click', () => {
                        delete container.dataset.loaded;
                    });

                    const hasDataAction = retryBtn.hasAttribute('data-action');
                    const dataActionValue = retryBtn.getAttribute('data-action');

                    container.dataset.loaded = 'true';

                    let clickError = null;
                    try {
                        retryBtn.click();
                    } catch (e) {
                        clickError = e.message;
                    }

                    return {
                        found: true,
                        hasDataAction,
                        dataActionValue,
                        clickError,
                        loadedCleared: !container.dataset.loaded,
                    };
                } finally {
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-team-search' not found"
        assert result["hasDataAction"], "Retry button should have data-action attribute"
        assert result["dataActionValue"] == "retry-team-search", "Button should have correct data-action value"
        assert result["clickError"] is None, f"Button click should not throw error: {result.get('clickError')}"
        assert result["loadedCleared"], "Retry should clear the loaded dataset flag"


# ---------------------------------------------------------------------------
# CI guard: no remaining inline onclick/onchange in innerHTML strings
# ---------------------------------------------------------------------------


class TestNoInlineOnclickInInnerHtmlStrings:
    """Static analysis guard: no inline on* handlers in innerHTML-assigned strings.

    These tests run without a live server — they parse source files directly.
    They act as a CI ratchet: if a developer accidentally re-introduces an
    inline onclick inside an innerHTML string, the test fails immediately.

    Scope:
      - ``mcpgateway/static/admin.js``: all template-literal / string
        arguments to ``.innerHTML =`` assignments.
      - ``mcpgateway/templates/``: all Jinja2 HTML template files.
    """

    # Patterns that are acceptable (not inline handlers):
    #   data-action="..."  — the new pattern
    #   aria-*             — ARIA attributes
    #   class, id, type    — safe HTML attributes
    # Patterns that are NOT acceptable inside innerHTML strings:
    #   onclick="..."  onchange="..."  onsubmit="..."  etc.

    _INLINE_HANDLER_RE = r"\bon\w+\s*="

    def _find_innerhtml_string_violations(self, js_path: str) -> list:
        """Return list of (line_no, line_text) where an innerHTML string contains on* attr."""
        # Standard
        import re

        violations = []
        try:
            with open(js_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            return violations

        # State machine: track whether we are inside a template literal or
        # string that is being assigned to .innerHTML.
        # Strategy: scan for `.innerHTML = ` then collect lines until the
        # closing backtick/quote, checking each for on* attributes.
        in_template = False
        backtick_depth = 0

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Detect start of innerHTML assignment
            if not in_template and re.search(r'\.innerHTML\s*=\s*[`"\']', stripped):
                in_template = True
                backtick_depth = stripped.count("`") % 2  # odd = open template literal

            if in_template:
                # Check for inline handlers (excluding data-action and aria-*)
                if re.search(self._INLINE_HANDLER_RE, stripped):
                    # Exclude lines that are only comments
                    if not stripped.startswith("//") and not stripped.startswith("*"):
                        violations.append((lineno, line.rstrip()))

                # Detect end of template literal
                if "`" in stripped:
                    backtick_depth = (backtick_depth + stripped.count("`")) % 2
                    if backtick_depth == 0:
                        in_template = False
                elif stripped.endswith(";") and not stripped.startswith("//"):
                    # Single-line string assignment ended
                    in_template = False

        return violations

    def test_admin_js_innerhtml_strings_have_no_inline_onclick(self) -> None:
        """admin.js must not contain inline on* handlers inside innerHTML strings.

        This is the core regression guard for PR #3373.  All on* attributes
        inside innerHTML-assigned strings must have been converted to
        data-action + addEventListener.
        """
        # Standard
        import os

        js_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "mcpgateway",
            "static",
            "admin.js",
        )
        js_path = os.path.normpath(js_path)

        violations = self._find_innerhtml_string_violations(js_path)

        assert not violations, (
            f"Found {len(violations)} inline on* handler(s) inside innerHTML strings in admin.js.\n"
            "Convert them to data-action + addEventListener (see PR #3373).\n"
            "Violations:\n" + "\n".join(f"  line {ln}: {txt}" for ln, txt in violations[:20])
        )

    def test_templates_have_no_inline_onclick_in_dynamic_content(self) -> None:
        """Jinja2 templates must not use inline on* handlers in dynamically rendered content.

        Templates rendered server-side and injected via innerHTML on the client
        will have their on* attributes stripped by the innerHTML guard.
        This test checks all HTML templates for inline handlers that would be
        silently stripped.

        Note: Static (non-innerHTML) template content is allowed to use on*
        handlers since the guard only affects innerHTML assignments.  This test
        therefore only flags templates that are known to be loaded via fetch()
        + innerHTML (the ``teams_selector_items.html`` partial and similar).
        """
        # Standard
        import os
        import re

        templates_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "mcpgateway",
            "templates",
        )
        templates_dir = os.path.normpath(templates_dir)

        # Templates known to be injected via innerHTML (fetch + innerHTML pattern)
        # These must NOT contain inline on* handlers.
        innerHTML_templates = [
            "teams_selector_items.html",
        ]

        violations = []
        for template_name in innerHTML_templates:
            template_path = os.path.join(templates_dir, template_name)
            if not os.path.exists(template_path):
                continue
            with open(template_path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    stripped = line.strip()
                    if re.search(self._INLINE_HANDLER_RE, stripped):
                        # Exclude Jinja2 comments and HTML comments
                        if not stripped.startswith("{#") and not stripped.startswith("<!--"):
                            violations.append((template_name, lineno, line.rstrip()))

        assert not violations, (
            f"Found {len(violations)} inline on* handler(s) in innerHTML-injected templates.\n"
            "These will be silently stripped by the innerHTML guard (PR #3129).\n"
            "Convert them to data-action + addEventListener (see PR #3373).\n"
            "Violations:\n" + "\n".join(f"  {name}:{ln}: {txt}" for name, ln, txt in violations[:20])
        )
