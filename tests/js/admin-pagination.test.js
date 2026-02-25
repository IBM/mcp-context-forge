/**
 * Unit tests for admin.js pagination state management functions.
 *
 * Covers getTeamsCurrentPaginationState, handleAdminTeamAction pagination
 * preservation, getPaginationParams/buildTableUrl namespace isolation (#3244),
 * and pagination component boundary behavior.
 */

import { describe, test, expect, beforeAll, beforeEach, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    // Inject getPaginationParams and buildTableUrl before admin.js loads,
    // mirroring the inline <script> in admin.html that defines them.
    // admin.js references these as globals (/* global ... getPaginationParams, buildTableUrl */).
    win = loadAdminJs({
        beforeEval: (window) => {
            window.getPaginationParams = function getPaginationParams (tableName) {
                const urlParams = new URLSearchParams(window.location.search);
                const prefix = tableName + "_";
                return {
                    page: Math.max(1, parseInt(urlParams.get(prefix + "page"), 10) || 1),
                    perPage: Math.max(1, parseInt(urlParams.get(prefix + "size"), 10) || 10),
                    includeInactive: urlParams.get(prefix + "inactive")
                };
            };

            window.buildTableUrl = function buildTableUrl (tableName, baseUrl, additionalParams) {
                if (additionalParams === undefined) additionalParams = {};
                const params = window.getPaginationParams(tableName);
                const urlParams = new URLSearchParams(window.location.search);
                const prefix = tableName + "_";
                const url = new URL(baseUrl, window.location.origin);
                url.searchParams.set("page", params.page);
                url.searchParams.set("per_page", params.perPage);

                for (const [key, value] of Object.entries(additionalParams)) {
                    if (key === "include_inactive" && params.includeInactive !== null) {
                        url.searchParams.set("include_inactive", params.includeInactive);
                    } else if (value !== null && value !== undefined && value !== "") {
                        url.searchParams.set(key, value);
                    }
                }

                if (!additionalParams.hasOwnProperty("include_inactive") && params.includeInactive !== null) {
                    url.searchParams.set("include_inactive", params.includeInactive);
                }

                const namespacedQuery = urlParams.get(prefix + "q");
                const namespacedTags = urlParams.get(prefix + "tags");
                if (namespacedQuery) {
                    url.searchParams.set("q", namespacedQuery);
                }
                if (namespacedTags) {
                    url.searchParams.set("tags", namespacedTags);
                }

                return url.pathname + url.search;
            };

            // Provide safeReplaceState before admin.js loads (it uses ||= pattern)
            window.safeReplaceState = function (data, title, url) {
                try {
                    window.history.replaceState(data, title, url);
                } catch (_e) { /* ignore in test env */ }
            };
        }
    });
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

// ---------------------------------------------------------------------------
// getPaginationParams namespace isolation (#3244)
// ---------------------------------------------------------------------------
describe("getPaginationParams namespace isolation", () => {
    test("each table reads only its own namespaced URL params", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?servers_page=3&servers_size=50&tools_page=1&tools_size=25"
        );

        const servers = win.getPaginationParams("servers");
        const tools = win.getPaginationParams("tools");

        expect(servers.page).toBe(3);
        expect(servers.perPage).toBe(50);
        expect(tools.page).toBe(1);
        expect(tools.perPage).toBe(25);
    });

    test("missing params for one table do not leak from another", () => {
        win.history.replaceState({}, "", "/admin?servers_page=5&servers_size=100");

        const servers = win.getPaginationParams("servers");
        const tools = win.getPaginationParams("tools");

        expect(servers.page).toBe(5);
        expect(servers.perPage).toBe(100);
        // Tools should get defaults, not servers' values
        expect(tools.page).toBe(1);
        expect(tools.perPage).toBe(10);
    });

    test("all five section namespaces are independent", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?servers_page=1&servers_size=10" +
                "&tools_page=2&tools_size=25" +
                "&gateways_page=3&gateways_size=50" +
                "&tokens_page=4&tokens_size=100" +
                "&agents_page=5&agents_size=200"
        );

        const sections = ["servers", "tools", "gateways", "tokens", "agents"];
        const expectedPages = [1, 2, 3, 4, 5];
        const expectedSizes = [10, 25, 50, 100, 200];

        sections.forEach((name, i) => {
            const state = win.getPaginationParams(name);
            expect(state.page).toBe(expectedPages[i]);
            expect(state.perPage).toBe(expectedSizes[i]);
        });
    });
});

// ---------------------------------------------------------------------------
// buildTableUrl namespace isolation (#3244)
// ---------------------------------------------------------------------------
describe("buildTableUrl namespace isolation", () => {
    test("builds URL using only the specified table's params", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?servers_page=5&servers_size=100&tools_page=2&tools_size=25"
        );

        const serversUrl = win.buildTableUrl("servers", "/admin/servers/partial");
        const toolsUrl = win.buildTableUrl("tools", "/admin/tools/partial");

        expect(serversUrl).toContain("page=5");
        expect(serversUrl).toContain("per_page=100");
        expect(toolsUrl).toContain("page=2");
        expect(toolsUrl).toContain("per_page=25");
    });

    test("does not cross-contaminate search queries between tables", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?servers_q=myserver&tools_q=mytool&servers_page=1&servers_size=10&tools_page=1&tools_size=10"
        );

        const serversUrl = win.buildTableUrl("servers", "/admin/servers/partial");
        const toolsUrl = win.buildTableUrl("tools", "/admin/tools/partial");

        expect(serversUrl).toContain("q=myserver");
        expect(serversUrl).not.toContain("q=mytool");
        expect(toolsUrl).toContain("q=mytool");
        expect(toolsUrl).not.toContain("q=myserver");
    });
});

// ---------------------------------------------------------------------------
// Pagination component: goToPage boundary behavior (#3244)
// ---------------------------------------------------------------------------
describe("pagination component goToPage behavior", () => {
    /**
     * Simulate the Alpine.js pagination component's goToPage logic.
     * This mirrors pagination_controls.html x-data methods.
     */
    function createPaginationComponent (opts) {
        const pages = [];
        const component = {
            currentPage: opts.currentPage || 1,
            perPage: opts.perPage || 50,
            totalItems: opts.totalItems || 0,
            totalPages: opts.totalPages || 0,
            hasNext: opts.hasNext || false,
            hasPrev: opts.hasPrev || false,
            _loadedPages: pages,

            goToPage (page) {
                if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
                    this.currentPage = page;
                    pages.push(page);
                }
            },

            prevPage () {
                if (this.hasPrev) {
                    this.goToPage(this.currentPage - 1);
                }
            },

            nextPage () {
                if (this.hasNext) {
                    this.goToPage(this.currentPage + 1);
                }
            },

            changePageSize (size) {
                this.perPage = parseInt(size, 10);
                this.currentPage = 1;
                pages.push(1);
            }
        };
        return component;
    }

    test("goToPage is a no-op when totalPages is 0 (cascade poison scenario)", () => {
        const component = createPaginationComponent({
            currentPage: 1,
            totalItems: 0,
            totalPages: 0,
            hasNext: false,
            hasPrev: false
        });

        component.goToPage(1);
        component.goToPage(2);
        component.goToPage(3);

        expect(component._loadedPages).toHaveLength(0);
        expect(component.currentPage).toBe(1);
    });

    test("goToPage works when totalPages > 0 (correct pagination)", () => {
        const component = createPaginationComponent({
            currentPage: 1,
            totalItems: 75,
            totalPages: 2,
            hasNext: true,
            hasPrev: false
        });

        component.goToPage(2);

        expect(component._loadedPages).toEqual([2]);
        expect(component.currentPage).toBe(2);
    });

    test("navigation buttons hidden when totalPages is 0", () => {
        // Mirrors: <template x-if="totalPages > 0"> in pagination_controls.html
        const component = createPaginationComponent({
            totalItems: 0,
            totalPages: 0
        });

        const navigationVisible = component.totalPages > 0;
        expect(navigationVisible).toBe(false);
    });

    test("navigation buttons shown when totalPages > 0", () => {
        const component = createPaginationComponent({
            totalItems: 75,
            totalPages: 2
        });

        const navigationVisible = component.totalPages > 0;
        expect(navigationVisible).toBe(true);
    });

    test("two independent sections have independent pagination state", () => {
        const servers = createPaginationComponent({
            currentPage: 1,
            totalItems: 0,
            totalPages: 0,
            hasNext: false,
            hasPrev: false
        });

        const tools = createPaginationComponent({
            currentPage: 1,
            totalItems: 75,
            totalPages: 2,
            hasNext: true,
            hasPrev: false
        });

        servers.goToPage(2);
        expect(servers.currentPage).toBe(1);
        expect(servers.totalPages).toBe(0);

        tools.goToPage(2);
        expect(tools.currentPage).toBe(2);
        expect(tools.totalPages).toBe(2);

        // Verify they didn't affect each other
        expect(servers.currentPage).toBe(1);
        expect(servers.totalItems).toBe(0);
        expect(tools.totalItems).toBe(75);
    });

    test("prevPage and nextPage respect bounds", () => {
        const component = createPaginationComponent({
            currentPage: 1,
            totalItems: 150,
            totalPages: 3,
            hasNext: true,
            hasPrev: false
        });

        component.prevPage();
        expect(component.currentPage).toBe(1);

        component.hasNext = true;
        component.goToPage(2);
        expect(component.currentPage).toBe(2);

        component.goToPage(3);
        expect(component.currentPage).toBe(3);

        component.goToPage(4);
        expect(component.currentPage).toBe(3);
    });
});
