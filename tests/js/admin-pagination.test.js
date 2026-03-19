/**
 * Unit tests for admin.js pagination state management functions.
 *
 * Covers getTeamsCurrentPaginationState, handleAdminTeamAction pagination
 * preservation, getPaginationParams/buildTableUrl namespace isolation (#3244),
 * and pagination component boundary behavior.
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
} from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

beforeAll(() => {
    // Inject getPaginationParams and buildTableUrl before admin.js loads,
    // mirroring the inline <script> in admin.html that defines them.
    // admin.js references these as globals (/* global ... getPaginationParams, buildTableUrl */).
    win = loadAdminJs({
        beforeEval: (window) => {
            window.getPaginationParams = function getPaginationParams(
                tableName,
            ) {
                const urlParams = new URLSearchParams(window.location.search);
                const prefix = tableName + "_";
                return {
                    page: Math.max(
                        1,
                        parseInt(urlParams.get(prefix + "page"), 10) || 1,
                    ),
                    perPage: Math.max(
                        1,
                        parseInt(urlParams.get(prefix + "size"), 10) || 10,
                    ),
                    includeInactive: urlParams.get(prefix + "inactive"),
                };
            };

            window.buildTableUrl = function buildTableUrl(
                tableName,
                baseUrl,
                additionalParams,
            ) {
                if (additionalParams === undefined) additionalParams = {};
                const params = window.getPaginationParams(tableName);
                const urlParams = new URLSearchParams(window.location.search);
                const prefix = tableName + "_";
                const url = new URL(baseUrl, window.location.origin);
                url.searchParams.set("page", params.page);
                url.searchParams.set("per_page", params.perPage);

                for (const [key, value] of Object.entries(additionalParams)) {
                    if (
                        key === "include_inactive" &&
                        params.includeInactive !== null
                    ) {
                        url.searchParams.set(
                            "include_inactive",
                            params.includeInactive,
                        );
                    } else if (
                        value !== null &&
                        value !== undefined &&
                        value !== ""
                    ) {
                        url.searchParams.set(key, value);
                    }
                }

                if (
                    !Object.prototype.hasOwnProperty.call(
                        additionalParams,
                        "include_inactive",
                    ) &&
                    params.includeInactive !== null
                ) {
                    url.searchParams.set(
                        "include_inactive",
                        params.includeInactive,
                    );
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
                } catch (_e) {
                    /* ignore in test env */
                }
            };
        },
    });
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
    // Reset URL to clean state
    win.history.replaceState({}, "", "/admin");
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
            perPage: 10,
        });
    });

    test("returns page from teams_page URL parameter", () => {
        win.history.replaceState({}, "", "/admin?teams_page=3&teams_size=10");
        const state = getPaginationState()();
        expect(state.page).toBe(3);
        expect(state.perPage).toBe(10);
    });

    test("returns perPage from teams_size URL parameter", () => {
        win.history.replaceState({}, "", "/admin?teams_page=1&teams_size=25");
        const state = getPaginationState()();
        expect(state.page).toBe(1);
        expect(state.perPage).toBe(25);
    });

    test("returns both page and perPage from URL parameters", () => {
        win.history.replaceState({}, "", "/admin?teams_page=5&teams_size=50");
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 5,
            perPage: 50,
        });
    });

    test("returns defaults when only teams_page is present", () => {
        win.history.replaceState({}, "", "/admin?teams_page=2");
        const state = getPaginationState()();
        expect(state.page).toBe(2);
        expect(state.perPage).toBe(10);
    });

    test("returns defaults when only teams_size is present", () => {
        win.history.replaceState({}, "", "/admin?teams_size=20");
        const state = getPaginationState()();
        expect(state.page).toBe(1);
        expect(state.perPage).toBe(20);
    });

    test("ignores other URL parameters", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=4&teams_size=15&other=value&foo=bar",
        );
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 4,
            perPage: 15,
        });
    });

    test("handles URL with hash fragment", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=2&teams_size=20#teams",
        );
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 2,
            perPage: 20,
        });
    });

    test("handles empty string values in URL params", () => {
        win.history.replaceState({}, "", "/admin?teams_page=&teams_size=");
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 1,
            perPage: 10,
        });
    });

    test("handles non-numeric values in URL params", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=abc&teams_size=xyz",
        );
        const state = getPaginationState()();
        expect(state).toEqual({
            page: 1,
            perPage: 10,
        });
    });

    test("clamps negative page to 1", () => {
        win.history.replaceState({}, "", "/admin?teams_page=-1&teams_size=10");
        const state = getPaginationState()();
        expect(state.page).toBe(1);
    });

    test("clamps negative perPage to 1", () => {
        win.history.replaceState({}, "", "/admin?teams_page=1&teams_size=-5");
        const state = getPaginationState()();
        expect(state.perPage).toBe(1);
    });

    test("clamps zero page to 1", () => {
        win.history.replaceState({}, "", "/admin?teams_page=0&teams_size=10");
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
        const unifiedList = doc.createElement("div");
        unifiedList.id = "unified-teams-list";
        doc.body.appendChild(unifiedList);

        const searchInput = doc.createElement("input");
        searchInput.id = "team-search";
        searchInput.value = "";
        doc.body.appendChild(searchInput);

        // Mock htmx.ajax
        win.htmx = {
            ajax: (method, url, options) => {
                // Store the called URL for verification
                win._lastHtmxUrl = url;
                return Promise.resolve();
            },
        };
    });

    test("preserves pagination state when refreshing teams list", async () => {
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=3&teams_size=25#teams",
        );

        const event = new win.CustomEvent("adminTeamAction", {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0,
            },
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise((resolve) => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain("page=3");
        expect(win._lastHtmxUrl).toContain("per_page=25");
    });

    test("uses default pagination when URL params are missing", async () => {
        win.history.replaceState({}, "", "/admin#teams");

        const event = new win.CustomEvent("adminTeamAction", {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0,
            },
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise((resolve) => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain("page=1");
        expect(win._lastHtmxUrl).toContain("per_page=10");
    });

    test("preserves search query along with pagination", async () => {
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=2&teams_size=20#teams",
        );
        const searchInput = doc.getElementById("team-search");
        searchInput.value = "test team query";

        const event = new win.CustomEvent("adminTeamAction", {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0,
            },
        });

        win.handleAdminTeamAction(event);

        // Wait for setTimeout to complete
        await new Promise((resolve) => setTimeout(resolve, 10));

        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain("page=2");
        expect(win._lastHtmxUrl).toContain("per_page=20");
        // Accept both URL encodings for space: %20 or +
        expect(win._lastHtmxUrl).toMatch(/q=test(\+|%20)team(\+|%20)query/);
    });

    test("uses page 1 after search resets pagination, not stale URL state", async () => {
        // Simulate: user was on page 3, then searched (which resets to page 1),
        // then triggers a CRUD action. The CRUD refresh should use page 1, not
        // the stale teams_page=3 from the URL.
        win.history.replaceState(
            {},
            "",
            "/admin?teams_page=3&teams_size=25#teams",
        );

        // Simulate performTeamSearch syncing URL to page 1
        if (typeof win.performTeamSearch === "function") {
            await win.performTeamSearch("test query");
        }

        // Verify URL was synced to page 1
        const urlAfterSearch = new URL(win.location.href);
        expect(urlAfterSearch.searchParams.get("teams_page")).toBe("1");

        // Now trigger a CRUD action
        const event = new win.CustomEvent("adminTeamAction", {
            detail: {
                refreshUnifiedTeamsList: true,
                delayMs: 0,
            },
        });

        win.handleAdminTeamAction(event);

        await new Promise((resolve) => setTimeout(resolve, 10));

        // CRUD refresh should use page 1, not stale page 3
        expect(win._lastHtmxUrl).toBeDefined();
        expect(win._lastHtmxUrl).toContain("page=1");
        expect(win._lastHtmxUrl).not.toContain("page=3");
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
            "/admin?servers_page=3&servers_size=50&tools_page=1&tools_size=25",
        );

        const servers = win.getPaginationParams("servers");
        const tools = win.getPaginationParams("tools");

        expect(servers.page).toBe(3);
        expect(servers.perPage).toBe(50);
        expect(tools.page).toBe(1);
        expect(tools.perPage).toBe(25);
    });

    test("missing params for one table do not leak from another", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?servers_page=5&servers_size=100",
        );

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
                "&agents_page=5&agents_size=200",
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
            "/admin?servers_page=5&servers_size=100&tools_page=2&tools_size=25",
        );

        const serversUrl = win.buildTableUrl(
            "servers",
            "/admin/servers/partial",
        );
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
            "/admin?servers_q=myserver&tools_q=mytool&servers_page=1&servers_size=10&tools_page=1&tools_size=10",
        );

        const serversUrl = win.buildTableUrl(
            "servers",
            "/admin/servers/partial",
        );
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
    function createPaginationComponent(opts) {
        const pages = [];
        const component = {
            currentPage: opts.currentPage || 1,
            perPage: opts.perPage || 50,
            totalItems: opts.totalItems || 0,
            totalPages: opts.totalPages || 0,
            hasNext: opts.hasNext || false,
            hasPrev: opts.hasPrev || false,
            _loadedPages: pages,

            goToPage(page) {
                if (
                    page >= 1 &&
                    page <= this.totalPages &&
                    page !== this.currentPage
                ) {
                    this.currentPage = page;
                    pages.push(page);
                }
            },

            prevPage() {
                if (this.hasPrev) {
                    this.goToPage(this.currentPage - 1);
                }
            },

            nextPage() {
                if (this.hasNext) {
                    this.goToPage(this.currentPage + 1);
                }
            },

            changePageSize(size) {
                this.perPage = parseInt(size, 10);
                this.currentPage = 1;
                pages.push(1);
            },
        };
        return component;
    }

    test("goToPage is a no-op when totalPages is 0 (cascade poison scenario)", () => {
        const component = createPaginationComponent({
            currentPage: 1,
            totalItems: 0,
            totalPages: 0,
            hasNext: false,
            hasPrev: false,
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
            hasPrev: false,
        });

        component.goToPage(2);

        expect(component._loadedPages).toEqual([2]);
        expect(component.currentPage).toBe(2);
    });

    test("navigation buttons hidden when totalPages is 0", () => {
        // Mirrors: <template x-if="totalPages > 0"> in pagination_controls.html
        const component = createPaginationComponent({
            totalItems: 0,
            totalPages: 0,
        });

        const navigationVisible = component.totalPages > 0;
        expect(navigationVisible).toBe(false);
    });

    test("navigation buttons shown when totalPages > 0", () => {
        const component = createPaginationComponent({
            totalItems: 75,
            totalPages: 2,
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
            hasPrev: false,
        });

        const tools = createPaginationComponent({
            currentPage: 1,
            totalItems: 75,
            totalPages: 2,
            hasNext: true,
            hasPrev: false,
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
            hasPrev: false,
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

// ---------------------------------------------------------------------------
// pagination_controls: data-extra-params safe handling
//
// The pagination_controls.html template stores extra query params (team_id, q,
// gateway_id, etc.) in a `data-extra-params` JSON attribute rather than
// inlining them inside the x-data JS string. This prevents Alpine.js parse
// errors when values contain double-quotes or other special characters.
//
// These tests verify the equivalent runtime logic: JSON.parse of the attribute
// value, forwarding to URLSearchParams, filtering, and team_id fallback.
// ---------------------------------------------------------------------------
describe("pagination_controls data-extra-params handling", () => {
    /**
     * Replicates the loadPage() extraParams block from pagination_controls.html.
     * Reads a JSON string (as produced by Jinja's `tojson | forceescape` and then
     * decoded by the browser), builds URL search params, and applies the team_id
     * fallback from the browser URL.
     */
    function buildUrlWithExtraParams(
        baseUrl,
        extraParamsJson,
        currentSearch = "",
    ) {
        const url = new URL(baseUrl, "http://localhost");
        const extraParams = JSON.parse(extraParamsJson || "{}");
        Object.entries(extraParams).forEach(([k, v]) => {
            if (k !== "include_inactive" && v !== null && v !== undefined) {
                url.searchParams.set(k, String(v));
            }
        });
        // team_id fallback: pick from browser URL when not already in extraParams
        const currentUrlParams = new URLSearchParams(currentSearch);
        const teamIdFromUrl = currentUrlParams.get("team_id");
        if (teamIdFromUrl && !extraParams.team_id) {
            url.searchParams.set("team_id", teamIdFromUrl);
        }
        return url;
    }

    test("forwards extra params to URL", () => {
        const json = JSON.stringify({ q: "hello", gateway_id: "42" });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe("hello");
        expect(url.searchParams.get("gateway_id")).toBe("42");
    });

    test("filters out include_inactive from extra params", () => {
        const json = JSON.stringify({ q: "test", include_inactive: "true" });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe("test");
        expect(url.searchParams.has("include_inactive")).toBe(false);
    });

    test("filters out null values from extra params", () => {
        const json = JSON.stringify({ q: null, gateway_id: "5" });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.has("q")).toBe(false);
        expect(url.searchParams.get("gateway_id")).toBe("5");
    });

    test("picks up team_id from browser URL when not in extra params", () => {
        const url = buildUrlWithExtraParams(
            "/admin/servers",
            "{}",
            "?team_id=abc123",
        );
        expect(url.searchParams.get("team_id")).toBe("abc123");
    });

    test("extra params team_id takes precedence over URL team_id", () => {
        const json = JSON.stringify({ team_id: "from-params" });
        const url = buildUrlWithExtraParams(
            "/admin/servers",
            json,
            "?team_id=from-url",
        );
        expect(url.searchParams.get("team_id")).toBe("from-params");
    });

    test("handles values with double quotes via JSON.parse without XSS", () => {
        // Jinja tojson encodes " as \u0022 inside the JSON string; when the browser
        // parses the data attribute the value is the literal JSON text, and
        // JSON.parse recovers the original string with the " character intact.
        // URLSearchParams then percent-encodes it, so it never appears raw in the URL.
        const json = JSON.stringify({ q: 'foo"bar' });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe('foo"bar');
        // Must be percent-encoded (%22) in the serialised URL, never a raw "
        expect(url.toString()).toContain("%22");
        expect(url.toString()).not.toMatch(/q=foo"bar/);
    });

    test("handles values with single quotes safely", () => {
        const json = JSON.stringify({ q: "it's a test" });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe("it's a test");
    });

    test("handles values with script tags safely", () => {
        const json = JSON.stringify({ q: "<script>alert(1)</script>" });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe("<script>alert(1)</script>");
        // The URL string must percent-encode < and >, not contain raw HTML
        expect(url.toString()).not.toContain("<script>");
    });

    test("handles empty extra params string as empty object", () => {
        const url = buildUrlWithExtraParams("/admin/servers", "");
        // No extra params added, no 'undefined' leaking into URL
        expect(url.search).toBe("");
        expect(url.toString()).not.toContain("undefined");
    });

    test("handles empty extra params JSON object with no team_id in URL", () => {
        const url = buildUrlWithExtraParams("/admin/servers", "{}", "");
        expect(url.search).toBe("");
    });

    test("all extra param keys are forwarded when none are filtered", () => {
        const json = JSON.stringify({
            q: "search term",
            gateway_id: "7",
            tags: "alpha,beta",
            relationship: "linked",
            visibility: "public",
        });
        const url = buildUrlWithExtraParams("/admin/servers", json);
        expect(url.searchParams.get("q")).toBe("search term");
        expect(url.searchParams.get("gateway_id")).toBe("7");
        expect(url.searchParams.get("tags")).toBe("alpha,beta");
        expect(url.searchParams.get("relationship")).toBe("linked");
        expect(url.searchParams.get("visibility")).toBe("public");
    });
});

// ---------------------------------------------------------------------------
// pagination_controls: dynamic search input reading (#3128)
//
// When paginating, loadPage() reads the current search and tag filter input
// values from the DOM. This ensures the user's active search filter is
// preserved across pages even if the input changed after the last server
// render (which would make data-extra-params stale).
// ---------------------------------------------------------------------------
describe("pagination_controls dynamic search input reading (#3128)", () => {
    /**
     * Replicates the full loadPage() URL-building logic from
     * pagination_controls.html, including extraParams AND the dynamic
     * input-reading block added in #3128.
     */
    function buildUrlWithInputs(
        baseUrl,
        extraParamsJson,
        tableName,
        inputs = {},
    ) {
        const url = new URL(baseUrl, "http://localhost");
        url.searchParams.set("page", "1");
        url.searchParams.set("per_page", "50");

        // Step 1: extraParams from server-rendered data attribute
        const extraParams = JSON.parse(extraParamsJson || "{}");
        Object.entries(extraParams).forEach(([k, v]) => {
            if (k !== "include_inactive" && v !== null && v !== undefined) {
                url.searchParams.set(k, String(v));
            }
        });

        // Step 2: dynamic input reading (mirrors #3128 fix)
        if (tableName) {
            if (inputs.search !== undefined) {
                const trimmedQuery = inputs.search.trim();
                if (trimmedQuery) {
                    url.searchParams.set("q", trimmedQuery);
                } else {
                    url.searchParams.delete("q");
                }
            }
            if (inputs.tags !== undefined) {
                const trimmedTags = inputs.tags.trim();
                if (trimmedTags) {
                    url.searchParams.set("tags", trimmedTags);
                } else {
                    url.searchParams.delete("tags");
                }
            }
        }

        return url;
    }

    test("search input value is used for q param", () => {
        const url = buildUrlWithInputs("/admin/tools/partial", "{}", "tools", {
            search: "my query",
        });
        expect(url.searchParams.get("q")).toBe("my query");
    });

    test("tag input value is used for tags param", () => {
        const url = buildUrlWithInputs("/admin/tools/partial", "{}", "tools", {
            tags: "prod,staging",
        });
        expect(url.searchParams.get("tags")).toBe("prod,staging");
    });

    test("input values override stale extraParams q and tags", () => {
        const json = JSON.stringify({ q: "old query", tags: "old-tag" });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "tools", {
            search: "new query",
            tags: "new-tag",
        });
        expect(url.searchParams.get("q")).toBe("new query");
        expect(url.searchParams.get("tags")).toBe("new-tag");
    });

    test("empty input clears stale extraParams q", () => {
        const json = JSON.stringify({ q: "stale search" });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "tools", {
            search: "",
        });
        expect(url.searchParams.has("q")).toBe(false);
    });

    test("empty input clears stale extraParams tags", () => {
        const json = JSON.stringify({ tags: "stale-tag" });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "tools", {
            tags: "",
        });
        expect(url.searchParams.has("tags")).toBe(false);
    });

    test("whitespace-only input clears q", () => {
        const json = JSON.stringify({ q: "stale" });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "tools", {
            search: "   ",
        });
        expect(url.searchParams.has("q")).toBe(false);
    });

    test("input values are trimmed", () => {
        const url = buildUrlWithInputs("/admin/tools/partial", "{}", "tools", {
            search: "  hello  ",
            tags: "  alpha  ",
        });
        expect(url.searchParams.get("q")).toBe("hello");
        expect(url.searchParams.get("tags")).toBe("alpha");
    });

    test("other extraParams are preserved when input overrides q", () => {
        const json = JSON.stringify({
            q: "old",
            gateway_id: "42",
            team_id: "t1",
        });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "tools", {
            search: "new",
        });
        expect(url.searchParams.get("q")).toBe("new");
        expect(url.searchParams.get("gateway_id")).toBe("42");
        expect(url.searchParams.get("team_id")).toBe("t1");
    });

    test("skips input reading when tableName is empty", () => {
        const json = JSON.stringify({ q: "from-server" });
        const url = buildUrlWithInputs("/admin/tools/partial", json, "", {
            search: "from-input",
        });
        // Without tableName, input reading is skipped; extraParams value stands
        expect(url.searchParams.get("q")).toBe("from-server");
    });
});

// ---------------------------------------------------------------------------
// Pagination swapStyle used by loadPage (#3396)
//
// Table-targeted pagination must use outerHTML swap to prevent nested <table>
// elements. When htmx.ajax receives swap: 'innerHTML' and the response body
// starts with <table>, the browser ejects the inner table as a sibling,
// leaving the visible table blank.
// ---------------------------------------------------------------------------
describe("pagination loadPage swapStyle (#3396)", () => {
    /**
     * Create a pagination component that records htmx.ajax calls
     * instead of actually performing them.
     */
    function createComponentWithAjaxSpy(swapStyle) {
        const ajaxCalls = [];
        const htmx = {
            ajax(method, url, opts) {
                ajaxCalls.push({ method, url, ...opts });
            },
        };
        const component = {
            currentPage: 1,
            perPage: 50,
            totalItems: 75,
            totalPages: 2,
            hasNext: true,
            hasPrev: false,
            targetSelector: "#tools-table",
            swapStyle,
            tableName: "tools",
            baseUrl: "/admin/tools/partial",
            $el: {
                dataset: { extraParams: "{}" },
            },

            updateBrowserUrl() {},

            loadPage(page) {
                const url = new URL(this.baseUrl, "http://localhost");
                url.searchParams.set("page", page);
                url.searchParams.set("per_page", this.perPage);

                htmx.ajax("GET", url.toString(), {
                    target: this.targetSelector,
                    swap: this.swapStyle,
                    indicator: "#tools-loading",
                });
            },
        };
        return { component, ajaxCalls };
    }

    test("outerHTML swapStyle is passed to htmx.ajax for table targets", () => {
        const { component, ajaxCalls } =
            createComponentWithAjaxSpy("outerHTML");
        component.loadPage(2);
        expect(ajaxCalls).toHaveLength(1);
        expect(ajaxCalls[0].swap).toBe("outerHTML");
        expect(ajaxCalls[0].target).toBe("#tools-table");
    });

    test("innerHTML swapStyle is passed to htmx.ajax for non-table targets", () => {
        const { component, ajaxCalls } =
            createComponentWithAjaxSpy("innerHTML");
        component.targetSelector = "#tokens-table";
        component.loadPage(2);
        expect(ajaxCalls).toHaveLength(1);
        expect(ajaxCalls[0].swap).toBe("innerHTML");
    });

    test("swapStyle defaults to innerHTML when not explicitly set", () => {
        // Mirrors pagination_controls.html: swapStyle: '{{ hx_swap|default('innerHTML') }}'
        const defaultSwap = undefined || "innerHTML";
        const { component, ajaxCalls } =
            createComponentWithAjaxSpy(defaultSwap);
        component.loadPage(2);
        expect(ajaxCalls[0].swap).toBe("innerHTML");
    });
});

// ---------------------------------------------------------------------------
// _navigateAdmin: pagination state preservation (#3389)
//
// _navigateAdmin is the single function all edit/save/toggle handlers use to
// redirect after a successful operation. The fix copies namespaced pagination
// params (*_page, *_size, *_inactive, *_q, *_tags) from the current URL into
// the outgoing searchParams so editing an item on page 3 returns to page 3.
//
// Testing strategy: the function mutates the passed URLSearchParams before
// attempting navigation (which throws "Not implemented" in JSDOM). We inspect
// the URLSearchParams object after catching the error to verify the mutation.
// ---------------------------------------------------------------------------
describe("_navigateAdmin pagination state preservation (#3389)", () => {
    /**
     * Call _navigateAdmin and swallow the JSDOM navigation error.
     * Returns the searchParams object after mutation.
     */
    function callNavigateAdmin(fragment, searchParams) {
        try {
            win._navigateAdmin(fragment, searchParams);
        } catch (_) {
            // JSDOM throws "Not implemented: navigation" — expected
        }
        return searchParams;
    }

    test("preserves *_page and *_size params from current URL", () => {
        win.history.replaceState({}, "", "/admin?tools_page=3&tools_size=25");
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.get("tools_page")).toBe("3");
        expect(params.get("tools_size")).toBe("25");
    });

    test("preserves *_q and *_tags params from current URL", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?tools_q=search&tools_tags=alpha,beta",
        );
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.get("tools_q")).toBe("search");
        expect(params.get("tools_tags")).toBe("alpha,beta");
    });

    test("preserves namespaced *_inactive params (e.g. tools_inactive)", () => {
        win.history.replaceState({}, "", "/admin?tools_inactive=true");
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.get("tools_inactive")).toBe("true");
    });

    test("does NOT preserve bare include_inactive param", () => {
        win.history.replaceState({}, "", "/admin?include_inactive=true");
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.has("include_inactive")).toBe(false);
    });

    test("does NOT preserve non-pagination params (e.g. team_id, random)", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?team_id=abc&random=42&tools_page=2",
        );
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.has("team_id")).toBe(false);
        expect(params.has("random")).toBe(false);
        expect(params.get("tools_page")).toBe("2");
    });

    test("caller-set params take precedence over URL params", () => {
        win.history.replaceState({}, "", "/admin?tools_page=5&tools_size=50");
        const params = new win.URLSearchParams();
        params.set("tools_page", "1");
        callNavigateAdmin("tools", params);
        expect(params.get("tools_page")).toBe("1");
        expect(params.get("tools_size")).toBe("50");
    });

    test("preserves params across multiple table namespaces", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?tools_page=3&gateways_page=2&servers_size=50&agents_q=bot",
        );
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.get("tools_page")).toBe("3");
        expect(params.get("gateways_page")).toBe("2");
        expect(params.get("servers_size")).toBe("50");
        expect(params.get("agents_q")).toBe("bot");
    });

    test("handles null searchParams without TypeError", () => {
        win.history.replaceState({}, "", "/admin?tools_page=4");
        let typeError = false;
        try {
            win._navigateAdmin("tools", null);
        } catch (e) {
            if (e.message && e.message.includes("Cannot read properties")) {
                typeError = true;
            }
        }
        expect(typeError).toBe(false);
    });

    test("handles undefined searchParams without TypeError", () => {
        win.history.replaceState({}, "", "/admin?tools_page=4");
        let typeError = false;
        try {
            win._navigateAdmin("tools");
        } catch (e) {
            if (e.message && e.message.includes("Cannot read properties")) {
                typeError = true;
            }
        }
        expect(typeError).toBe(false);
    });

    test("preserves all five pagination suffixes simultaneously", () => {
        win.history.replaceState(
            {},
            "",
            "/admin?tools_page=3&tools_size=25&tools_inactive=true&tools_q=search&tools_tags=v1,v2",
        );
        const params = new win.URLSearchParams();
        callNavigateAdmin("tools", params);
        expect(params.get("tools_page")).toBe("3");
        expect(params.get("tools_size")).toBe("25");
        expect(params.get("tools_inactive")).toBe("true");
        expect(params.get("tools_q")).toBe("search");
        expect(params.get("tools_tags")).toBe("v1,v2");
    });

    test("does not overwrite caller include_inactive with URL's bare include_inactive", () => {
        win.history.replaceState({}, "", "/admin?include_inactive=true");
        const params = new win.URLSearchParams();
        params.set("include_inactive", "false");
        callNavigateAdmin("tools", params);
        expect(params.get("include_inactive")).toBe("false");
    });
});

// ---------------------------------------------------------------------------
// Alpine.js reinit on OOB-swapped pagination controls (#3039)
//
// After HTMX settles an OOB swap of a pagination-controls div, Alpine.js
// may not automatically detect and initialise the new x-data component
// (race with MutationObserver). The htmx:afterSettle listener in
// initializeTabState() calls Alpine.initTree() on any uninitialized
// pagination controls.
// ---------------------------------------------------------------------------
describe("Alpine.js reinit on OOB-swapped pagination controls (#3039)", () => {
    /** Dispatch a synthetic htmx:afterSettle event on document.body. */
    function fireAfterSettle() {
        const event = new win.Event("htmx:afterSettle", { bubbles: true });
        doc.body.dispatchEvent(event);
    }

    /** Create a pagination-controls div with an x-data child, optionally pre-initialized. */
    function createPaginationDiv(id, { initialized = false } = {}) {
        const container = doc.createElement("div");
        container.id = id;
        const xDataEl = doc.createElement("div");
        xDataEl.setAttribute("x-data", "{ currentPage: 1 }");
        if (initialized) {
            xDataEl._x_dataStack = [{ currentPage: 1 }];
        }
        container.appendChild(xDataEl);
        doc.body.appendChild(container);
        return container;
    }

    beforeEach(() => {
        // Clear any previous Alpine mock
        delete win.Alpine;
    });

    test("calls Alpine.initTree on uninitialized pagination controls", () => {
        const initTreeCalls = [];
        win.Alpine = {
            initTree: (el) => initTreeCalls.push(el),
        };

        const div = createPaginationDiv("tools-pagination-controls");

        fireAfterSettle();

        expect(initTreeCalls).toHaveLength(1);
        expect(initTreeCalls[0]).toBe(div);
    });

    test("skips already-initialized pagination controls", () => {
        const initTreeCalls = [];
        win.Alpine = {
            initTree: (el) => initTreeCalls.push(el),
        };

        createPaginationDiv("tools-pagination-controls", {
            initialized: true,
        });

        fireAfterSettle();

        expect(initTreeCalls).toHaveLength(0);
    });

    test("handles multiple pagination controls, only inits uninitialized ones", () => {
        const initTreeCalls = [];
        win.Alpine = {
            initTree: (el) => initTreeCalls.push(el),
        };

        createPaginationDiv("servers-pagination-controls", {
            initialized: true,
        });
        const uninitDiv = createPaginationDiv("tools-pagination-controls");
        createPaginationDiv("gateways-pagination-controls", {
            initialized: true,
        });

        fireAfterSettle();

        expect(initTreeCalls).toHaveLength(1);
        expect(initTreeCalls[0]).toBe(uninitDiv);
    });

    test("does not error when Alpine is not loaded", () => {
        // Alpine is undefined (deleted in beforeEach)
        createPaginationDiv("tools-pagination-controls");

        expect(() => fireAfterSettle()).not.toThrow();
    });

    test("does not error when Alpine.initTree is not a function", () => {
        win.Alpine = { version: "3.x" }; // no initTree

        createPaginationDiv("tools-pagination-controls");

        expect(() => fireAfterSettle()).not.toThrow();
    });

    test("does not call initTree when pagination div has no x-data child", () => {
        const initTreeCalls = [];
        win.Alpine = {
            initTree: (el) => initTreeCalls.push(el),
        };

        // Create a div with the right ID but no x-data child
        const container = doc.createElement("div");
        container.id = "tools-pagination-controls";
        doc.body.appendChild(container);

        fireAfterSettle();

        expect(initTreeCalls).toHaveLength(0);
    });

    test("matches metrics top-performers pagination-controls-visible IDs", () => {
        const initTreeCalls = [];
        win.Alpine = {
            initTree: (el) => initTreeCalls.push(el),
        };

        // Metrics partials use IDs like "top-tools-pagination-controls-visible"
        // which contain "-pagination-controls" but don't end with it.
        const metricsDiv = createPaginationDiv(
            "top-tools-pagination-controls-visible",
        );

        fireAfterSettle();

        expect(initTreeCalls).toHaveLength(1);
        expect(initTreeCalls[0]).toBe(metricsDiv);
    });

    test("still enables disabled toggles alongside Alpine reinit", () => {
        win.Alpine = { initTree: () => {} };

        // Create a target element for the toggle
        const target = doc.createElement("div");
        target.id = "tools-table";
        doc.body.appendChild(target);

        // Create a disabled toggle
        const toggle = doc.createElement("input");
        toggle.type = "checkbox";
        toggle.className = "show-inactive-toggle";
        toggle.disabled = true;
        toggle.setAttribute("hx-target", "#tools-table");
        doc.body.appendChild(toggle);

        createPaginationDiv("tools-pagination-controls");

        fireAfterSettle();

        expect(toggle.disabled).toBe(false);
    });
});
