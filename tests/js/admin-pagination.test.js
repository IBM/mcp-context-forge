/**
 * Unit tests for admin.js pagination state management functions.
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
    // Reset URL to clean state
    win.history.replaceState({}, '', '/admin');
});

// ---------------------------------------------------------------------------
// getTeamsCurrentPaginationState
// ---------------------------------------------------------------------------
describe("getTeamsCurrentPaginationState", () => {
    const getPaginationState = () => win.getTeamsCurrentPaginationState;

    test("returns default values when URL params are missing", () => {
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 1,
            perPage: 10
        });
    });

    test("returns page from teams_page URL parameter", () => {
        win.history.replaceState({}, '', '/admin?teams_page=3&teams_size=10');
        const state = getPaginationState()();
        expect(state.page).toBe(3);
        expect(state.perPage).toBe(10);
    });

    test("returns perPage from teams_size URL parameter", () => {
        win.history.replaceState({}, '', '/admin?teams_page=1&teams_size=25');
        const state = getPaginationState()();
        expect(state.page).toBe(1);
        expect(state.perPage).toBe(25);
    });

    test("returns both page and perPage from URL parameters", () => {
        win.history.replaceState({}, '', '/admin?teams_page=5&teams_size=50');
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 5,
            perPage: 50
        });
    });

    test("returns defaults when only teams_page is present", () => {
        win.history.replaceState({}, '', '/admin?teams_page=2');
        const state = getPaginationState()();
        expect(state.page).toBe(2);
        expect(state.perPage).toBe(10);
    });

    test("returns defaults when only teams_size is present", () => {
        win.history.replaceState({}, '', '/admin?teams_size=20');
        const state = getPaginationState()();
        expect(state.page).toBe(1);
        expect(state.perPage).toBe(20);
    });

    test("ignores other URL parameters", () => {
        win.history.replaceState({}, '', '/admin?teams_page=4&teams_size=15&other=value&foo=bar');
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 4,
            perPage: 15
        });
    });

    test("handles URL with hash fragment", () => {
        win.history.replaceState({}, '', '/admin?teams_page=2&teams_size=20#teams');
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 2,
            perPage: 20
        });
    });

    test("handles empty string values in URL params", () => {
        win.history.replaceState({}, '', '/admin?teams_page=&teams_size=');
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 1,
            perPage: 10
        });
    });

    test("handles non-numeric values in URL params", () => {
        win.history.replaceState({}, '', '/admin?teams_page=abc&teams_size=xyz');
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 1,
            perPage: 10
        });
    });

    test("clamps negative page to 1", () => {
        win.history.replaceState({}, '', '/admin?teams_page=-1&teams_size=10');
        const state = getPaginationState()();
        expect(state.page).toBe(1);
    });

    test("clamps negative perPage to 1", () => {
        win.history.replaceState({}, '', '/admin?teams_page=1&teams_size=-5');
        const state = getPaginationState()();
        expect(state.perPage).toBe(1);
    });

    test("clamps zero page to 1", () => {
        win.history.replaceState({}, '', '/admin?teams_page=0&teams_size=10');
        const state = getPaginationState()();
        expect(state.page).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// Integration: handleAdminTeamAction with pagination preservation
// ---------------------------------------------------------------------------
describe("handleAdminTeamAction pagination preservation", () => {
    beforeEach(() => {
        // Set up DOM elements needed for team refresh
        const unifiedList = doc.createElement('div');
        unifiedList.id = 'unified-teams-list';
        doc.body.appendChild(unifiedList);

        const searchInput = doc.createElement('input');
        searchInput.id = 'team-search';
        searchInput.value = '';
        doc.body.appendChild(searchInput);

        // Mock htmx.ajax
        win.htmx = {
            ajax: (method, url, options) => {
                // Store the called URL for verification
                win._lastHtmxUrl = url;
                return Promise.resolve();
            }
        };
    });

    test("preserves pagination state when refreshing teams list", async () => {
        win.history.replaceState({}, '', '/admin?teams_page=3&teams_size=25#teams');

        const event = new win.CustomEvent('adminTeamAction', {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0
            }
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise(resolve => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain('page=3');
        expect(win._lastHtmxUrl).toContain('per_page=25');
    });

    test("uses default pagination when URL params are missing", async () => {
        win.history.replaceState({}, '', '/admin#teams');

        const event = new win.CustomEvent('adminTeamAction', {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0
            }
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise(resolve => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain('page=1');
        expect(win._lastHtmxUrl).toContain('per_page=10');
    });

    test("preserves search query along with pagination", async () => {
        win.history.replaceState({}, '', '/admin?teams_page=2&teams_size=20#teams');
        const searchInput = doc.getElementById('team-search');
        searchInput.value = 'test team query';

        const event = new win.CustomEvent('adminTeamAction', {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0
            }
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise(resolve => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain('page=2');
        expect(win._lastHtmxUrl).toContain('per_page=20');
        // Accept both URL encodings for space: %20 or +
        expect(win._lastHtmxUrl).toMatch(/q=test(\+|%20)team(\+|%20)query/);
    });

    test("uses page 1 after search resets pagination, not stale URL state", async () => {
        // Simulate: user was on page 3, then searched (which resets to page 1),
        // then triggers a CRUD action. The CRUD refresh should use page 1, not
        // the stale teams_page=3 from the URL.
        win.history.replaceState({}, '', '/admin?teams_page=3&teams_size=25#teams');

        // Simulate performTeamSearch syncing URL to page 1
        if (typeof win.performTeamSearch === 'function') {
            await win.performTeamSearch('test query');
        }

        // Verify URL was synced to page 1
        const urlAfterSearch = new URL(win.location.href);
        expect(urlAfterSearch.searchParams.get('teams_page')).toBe('1');

        // Now trigger a CRUD action
        const event = new win.CustomEvent('adminTeamAction', {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0
            }
        });

        win.handleAdminTeamAction(event);

        await new Promise(resolve => setTimeout(resolve, 10));

        // CRUD refresh should use page 1, not stale page 3
        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain('page=1');
        expect(win._lastHtmxUrl).not.toContain('page=3');
    });
});
