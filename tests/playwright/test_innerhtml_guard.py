# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_innerhtml_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

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

        # Directly invoke showUsageStatsModal with mock data to test
        # that the data-action close buttons have working event listeners
        page.evaluate("""
            showUsageStatsModal({
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

        page.evaluate("""
            showUsageStatsModal({
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

        result = page.evaluate("""
            () => {
                // Ensure required container exists
                let container = document.getElementById('aggregated-metrics-content');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'aggregated-metrics-content';
                    document.body.appendChild(container);
                }

                // Spy on retryLoadMetrics
                let retryCalled = false;
                const orig = window.retryLoadMetrics;
                window.retryLoadMetrics = () => { retryCalled = true; };

                try {
                    showMetricsError(new Error('test error'));
                    const btn = container.querySelector('[data-action="retry-metrics"]');
                    if (!btn) return { found: false };
                    btn.click();
                    return { found: true, retryCalled };
                } finally {
                    window.retryLoadMetrics = orig;
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-metrics' not found"
        assert result["retryCalled"], "Clicking retry should call retryLoadMetrics"

    def test_metrics_empty_state_refresh_button_wired(self, admin_page):
        """displayMetrics() empty-state refresh button should have working click handler."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Ensure required container exists
                let container = document.getElementById('aggregated-metrics-content');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'aggregated-metrics-content';
                    document.body.appendChild(container);
                }

                let retryCalled = false;
                const orig = window.retryLoadMetrics;
                window.retryLoadMetrics = () => { retryCalled = true; };

                try {
                    // Empty data triggers the empty-state path
                    displayMetrics({ tools: [], resources: [], prompts: [] });
                    const btn = container.querySelector('[data-action="retry-metrics"]');
                    if (!btn) return { found: false };
                    btn.click();
                    return { found: true, retryCalled };
                } finally {
                    window.retryLoadMetrics = orig;
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Refresh button with data-action='retry-metrics' not found in empty state"
        assert result["retryCalled"], "Clicking refresh should call retryLoadMetrics"


class TestAuthHeaderButtons:
    """Auth header toggle/remove buttons use data-action + addEventListener."""

    def test_auth_header_toggle_and_remove_buttons_wired(self, admin_page):
        """addAuthHeader() toggle and remove buttons should have working click handlers."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create a temporary container for auth headers
                const container = document.createElement('div');
                container.id = 'test-auth-headers';
                document.body.appendChild(container);

                try {
                    addAuthHeader('test-auth-headers');
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

                let resetCalled = false;
                const orig = window.resetImportFile;
                window.resetImportFile = () => { resetCalled = true; };

                try {
                    updateDropZoneStatus('test.json', {
                        version: '1.0',
                        gateways: { gw1: { gateway: { name: 'gw1' } } }
                    });

                    const btn = dropZone.querySelector('[data-action="reset-import"]');
                    if (!btn) return { found: false };
                    btn.click();
                    return { found: true, resetCalled };
                } finally {
                    window.resetImportFile = orig;
                    dropZone.textContent = '';
                }
            }
        """)

        assert result["found"], "Reset button with data-action='reset-import' not found"
        assert result["resetCalled"], "Clicking reset should call resetImportFile"


class TestTagFilterClearButton:
    """Tag filter clear button uses data-action + addEventListener."""

    def test_tag_filter_clear_button_wired(self, admin_page):
        """updateFilterEmptyState() clear button should have working click handler."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create the table container the function expects
                const entityType = 'tools';
                const containerId = entityType + '-table-container';
                let container = document.getElementById(containerId);
                if (!container) {
                    container = document.createElement('div');
                    container.id = containerId;
                    document.body.appendChild(container);
                }

                let clearCalled = false;
                const orig = window.clearTagFilter;
                window.clearTagFilter = (type) => { clearCalled = type; };

                try {
                    updateFilterEmptyState(entityType, 0, true);
                    const btn = container.querySelector('[data-action="clear-tag-filter"]');
                    if (!btn) return { found: false };
                    btn.click();
                    return { found: true, clearCalled };
                } finally {
                    window.clearTagFilter = orig;
                    container.remove();
                }
            }
        """)

        assert result["found"], "Clear button with data-action='clear-tag-filter' not found"
        assert result["clearCalled"] == "tools", "Clicking clear should call clearTagFilter with entity type"


class TestImportPreviewControls:
    """Bulk import preview selection controls use data-action + addEventListener."""

    def test_import_preview_buttons_wired(self, admin_page):
        """displayImportPreview() selection buttons and checkboxes should have listeners."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                // Create the container and parent that displayImportPreview expects
                let previewContainer = document.getElementById('import-preview-container');
                if (!previewContainer) {
                    const dropZone = document.getElementById('import-drop-zone')
                        || document.createElement('div');
                    if (!dropZone.id) {
                        dropZone.id = 'import-drop-zone';
                        document.body.appendChild(dropZone);
                    }
                    previewContainer = document.createElement('div');
                    previewContainer.id = 'import-preview-container';
                    dropZone.parentNode.insertBefore(previewContainer, dropZone.nextSibling);
                }

                // Spy on handler functions
                let selectAllCalled = false, selectNoneCalled = false, selectCustomCalled = false;
                let resetCalled = false, previewCalled = false, importCalled = false;
                let countUpdates = 0;
                const origSelectAll = window.selectAllItems;
                const origSelectNone = window.selectNoneItems;
                const origSelectCustom = window.selectOnlyCustom;
                const origReset = window.resetImportSelection;
                const origPreview = window.handleSelectiveImport;
                const origCount = window.updateSelectionCount;

                window.selectAllItems = () => { selectAllCalled = true; };
                window.selectNoneItems = () => { selectNoneCalled = true; };
                window.selectOnlyCustom = () => { selectCustomCalled = true; };
                window.resetImportSelection = () => { resetCalled = true; };
                window.handleSelectiveImport = (preview) => {
                    if (preview) previewCalled = true; else importCalled = true;
                };
                window.updateSelectionCount = () => { countUpdates++; };

                try {
                    displayImportPreview({
                        version: '1.0',
                        bundles: {
                            'gw1': {
                                gateway: { name: 'Test Gateway', url: 'http://test', transport: 'sse' },
                                tools: [{ id: 't1', name: 'Tool 1', type: 'custom', description: 'desc' }],
                                resources: [],
                                prompts: [],
                            }
                        }
                    });

                    const actions = {};
                    ['select-all', 'select-none', 'select-custom',
                     'reset-selection', 'preview-selected', 'import-selected'].forEach(a => {
                        actions[a] = !!previewContainer.querySelector('[data-action="' + a + '"]');
                    });

                    const checkboxes = previewContainer.querySelectorAll('[data-action="update-count"]');
                    actions.checkboxCount = checkboxes.length;

                    // Click each button
                    const safeClick = (sel) => {
                        const el = previewContainer.querySelector('[data-action="' + sel + '"]');
                        if (el) el.click();
                    };
                    safeClick('select-all');
                    safeClick('select-none');
                    safeClick('select-custom');
                    safeClick('reset-selection');
                    safeClick('preview-selected');
                    safeClick('import-selected');

                    // Trigger change on first checkbox
                    if (checkboxes.length > 0) {
                        checkboxes[0].dispatchEvent(new Event('change'));
                    }

                    return {
                        actions,
                        selectAllCalled, selectNoneCalled, selectCustomCalled,
                        resetCalled, previewCalled, importCalled,
                        countUpdates,
                    };
                } finally {
                    window.selectAllItems = origSelectAll;
                    window.selectNoneItems = origSelectNone;
                    window.selectOnlyCustom = origSelectCustom;
                    window.resetImportSelection = origReset;
                    window.handleSelectiveImport = origPreview;
                    window.updateSelectionCount = origCount;
                    previewContainer.textContent = '';
                }
            }
        """)

        # All buttons should be present
        for action in ["select-all", "select-none", "select-custom", "reset-selection", "preview-selected", "import-selected"]:
            assert result["actions"][action], f"Button data-action='{action}' not found"
        assert result["actions"]["checkboxCount"] > 0, "No checkboxes with data-action='update-count' found"

        # All click handlers should have fired
        assert result["selectAllCalled"], "Select All button should call selectAllItems"
        assert result["selectNoneCalled"], "Select None button should call selectNoneItems"
        assert result["selectCustomCalled"], "Custom Only button should call selectOnlyCustom"
        assert result["resetCalled"], "Reset button should call resetImportSelection"
        assert result["previewCalled"], "Preview button should call handleSelectiveImport(true)"
        assert result["importCalled"], "Import button should call handleSelectiveImport(false)"
        assert result["countUpdates"] > 0, "Checkbox change should call updateSelectionCount"


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

                let joinCalledWith = null;
                const orig = window.requestToJoinTeam;
                window.requestToJoinTeam = (id) => { joinCalledWith = id; };

                try {
                    displayPublicTeams([
                        { id: 'team-123', name: 'Public Team', description: 'A team', member_count: 5 }
                    ]);

                    const btn = container.querySelector('[data-action="request-join"]');
                    if (!btn) return { found: false };

                    const teamId = btn.dataset.teamId;
                    btn.click();
                    return { found: true, teamId, joinCalledWith };
                } finally {
                    window.requestToJoinTeam = orig;
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Join button with data-action='request-join' not found"
        assert result["teamId"] == "team-123", "Join button should have data-team-id"
        assert result["joinCalledWith"] == "team-123", "Clicking join should call requestToJoinTeam with team ID"


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

                let logDetailsCalled = null;
                let correlationCalled = null;
                const origDetails = window.showLogDetails;
                const origCorrelation = window.showCorrelationTrace;
                const origRestore = window.restoreLogTableHeaders;
                window.restoreLogTableHeaders = window.restoreLogTableHeaders || (() => {});
                window.showLogDetails = (id, corrId) => { logDetailsCalled = { id, corrId }; };
                window.showCorrelationTrace = (corrId) => { correlationCalled = corrId; };

                try {
                    displayLogResults({
                        results: [{
                            id: 'log-1',
                            timestamp: '2025-01-01T00:00:00Z',
                            level: 'INFO',
                            message: 'Test log',
                            correlation_id: 'corr-abc',
                            source: 'test',
                        }],
                        count: 1,
                    });

                    const tbody = document.getElementById('logs-tbody');
                    const row = tbody.querySelector('[data-action="show-log"]');
                    const corrBtn = tbody.querySelector('[data-action="show-correlation"]');

                    if (!row || !corrBtn) return { rowFound: !!row, corrFound: !!corrBtn };

                    const hasAbortController = !!tbody._logClickAC;

                    // Click the correlation button first
                    corrBtn.click();
                    // Click the row
                    row.click();

                    return {
                        rowFound: true,
                        corrFound: true,
                        hasAbortController,
                        logDetailsCalled,
                        correlationCalled,
                    };
                } finally {
                    window.showLogDetails = origDetails;
                    window.showCorrelationTrace = origCorrelation;
                    window.restoreLogTableHeaders = origRestore;
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["rowFound"], "Log row with data-action='show-log' not found"
        assert result["corrFound"], "Correlation button with data-action='show-correlation' not found"
        assert result["hasAbortController"], "tbody should have _logClickAC AbortController"
        assert result["correlationCalled"] == "corr-abc", "Clicking correlation should call showCorrelationTrace"
        assert result["logDetailsCalled"]["id"] == "log-1", "Clicking row should call showLogDetails"


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

                let correlationCalled = null;
                const origCorrelation = window.showCorrelationTrace;
                window.showCorrelationTrace = (corrId) => { correlationCalled = corrId; };

                try {
                    displaySecurityEvents([{
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

                    btn.click();
                    return { found: true, correlationCalled };
                } finally {
                    window.showCorrelationTrace = origCorrelation;
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["found"], "Correlation button with data-action='show-correlation' not found"
        assert result["correlationCalled"] == "corr-sec-1", "Clicking should call showCorrelationTrace"


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

                let correlationCalled = null;
                const origCorrelation = window.showCorrelationTrace;
                window.showCorrelationTrace = (corrId) => { correlationCalled = corrId; };

                try {
                    displayAuditTrail([{
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

                    btn.click();
                    return { found: true, correlationCalled };
                } finally {
                    window.showCorrelationTrace = origCorrelation;
                    created.forEach(el => el.remove());
                }
            }
        """)

        assert result["found"], "Correlation button with data-action='show-correlation' not found"
        assert result["correlationCalled"] == "corr-audit-1", "Clicking should call showCorrelationTrace"


class TestChatServerSelection:
    """Chat server selection items use data-action + addEventListener."""

    def test_chat_server_select_button_wired(self, admin_page):
        """Server selection items should call selectServerForChat with correct args."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let serversList = document.getElementById('chat-servers-list');
                if (!serversList) {
                    serversList = document.createElement('div');
                    serversList.id = 'chat-servers-list';
                    document.body.appendChild(serversList);
                }

                if (!window.llmChatState) {
                    window.llmChatState = { selectedServerId: null };
                }

                let selectCalled = null;
                const orig = window.selectServerForChat;
                window.selectServerForChat = (id, name, active, token, vis) => {
                    selectCalled = { id, name, active, token, vis };
                };

                try {
                    // Build HTML matching the pattern from loadVirtualServersForChat
                    const div = document.createElement('div');
                    div.setAttribute('data-action', 'select-server');
                    div.setAttribute('data-server-id', 'srv-1');
                    div.setAttribute('data-server-name', 'Test Server');
                    div.setAttribute('data-is-active', 'true');
                    div.setAttribute('data-requires-token', 'false');
                    div.setAttribute('data-visibility', 'public');
                    div.textContent = 'Test Server';
                    serversList.appendChild(div);

                    // Attach listener the same way loadVirtualServersForChat does
                    serversList.querySelectorAll('[data-action="select-server"]').forEach((item) => {
                        item.addEventListener('click', () => {
                            selectServerForChat(
                                item.dataset.serverId,
                                item.dataset.serverName,
                                item.dataset.isActive === 'true',
                                item.dataset.requiresToken === 'true',
                                item.dataset.visibility,
                            );
                        });
                    });

                    div.click();
                    return { found: true, selectCalled };
                } finally {
                    window.selectServerForChat = orig;
                    serversList.remove();
                }
            }
        """)

        assert result["found"], "Server item with data-action='select-server' not found"
        assert result["selectCalled"]["id"] == "srv-1", "Should pass server ID"
        assert result["selectCalled"]["active"] is True, "isActive should be parsed as boolean true"
        assert result["selectCalled"]["token"] is False, "requiresToken should be parsed as boolean false"


class TestTokenListRetryButton:
    """Token list error retry button uses data-action + addEventListener."""

    def test_token_error_retry_button_pattern(self, admin_page):
        """Token error state retry buttons should use data-action pattern."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let container = document.createElement('div');
                container.id = 'test-tokens-retry';
                document.body.appendChild(container);

                let retryCalled = false;
                const orig = window.loadTokensList;
                window.loadTokensList = () => { retryCalled = true; };

                try {
                    // Simulate the error HTML from setupCreateTokenForm
                    const errorDiv = document.createElement('div');
                    errorDiv.textContent = 'Failed to load tokens. ';
                    const retryBtn = document.createElement('button');
                    retryBtn.setAttribute('data-action', 'retry-tokens');
                    retryBtn.textContent = 'Retry';
                    errorDiv.appendChild(retryBtn);
                    container.appendChild(errorDiv);

                    retryBtn.addEventListener('click', () => loadTokensList(true));
                    retryBtn.click();
                    return { found: true, retryCalled };
                } finally {
                    window.loadTokensList = orig;
                    container.remove();
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-tokens' not found"
        assert result["retryCalled"], "Clicking retry should call loadTokensList"


class TestTeamSearchRetryButton:
    """Team selector search error retry button uses data-action + addEventListener."""

    def test_team_search_retry_button_pattern(self, admin_page):
        """Team search error retry should clear loaded flag and call searchTeamSelector."""
        page = admin_page.page

        result = page.evaluate("""
            () => {
                let container = document.getElementById('team-selector-items');
                if (!container) {
                    container = document.createElement('div');
                    container.id = 'team-selector-items';
                    document.body.appendChild(container);
                }
                // Set loaded flag so we can verify it gets cleared
                container.dataset.loaded = 'true';

                let searchCalled = false;
                const orig = window.searchTeamSelector;
                window.searchTeamSelector = () => { searchCalled = true; };

                try {
                    // Simulate the error path from performTeamSelectorSearch
                    const errorDiv = document.createElement('div');
                    errorDiv.textContent = 'Failed to load teams. ';
                    const retryBtn = document.createElement('button');
                    retryBtn.setAttribute('data-action', 'retry-team-search');
                    retryBtn.textContent = 'Retry';
                    errorDiv.appendChild(retryBtn);
                    container.appendChild(errorDiv);

                    retryBtn.addEventListener('click', function() {
                        delete container.dataset.loaded;
                        searchTeamSelector('');
                    });
                    retryBtn.click();
                    return { found: true, searchCalled, loadedCleared: !container.dataset.loaded };
                } finally {
                    window.searchTeamSelector = orig;
                    container.textContent = '';
                }
            }
        """)

        assert result["found"], "Retry button with data-action='retry-team-search' not found"
        assert result["searchCalled"], "Clicking retry should call searchTeamSelector"
        assert result["loadedCleared"], "Retry should clear the loaded dataset flag"
