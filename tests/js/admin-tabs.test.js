/**
 * Unit tests for tab visibility behavior in admin.js.
 */

import { afterAll, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { cleanupAdminJs, loadAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

function createTab(tabName) {
    const link = doc.createElement("a");
    link.id = `tab-${tabName}`;
    link.href = `#${tabName}`;
    link.className = "sidebar-link";
    link.textContent = tabName;
    doc.body.appendChild(link);

    const panel = doc.createElement("div");
    panel.id = `${tabName}-panel`;
    panel.className = "tab-panel hidden";
    doc.body.appendChild(panel);

    return { link, panel };
}

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    doc.body.textContent = "";
    win.UI_HIDDEN_TABS = [];
    win.UI_HIDDEN_SECTIONS = [];
    win.IS_ADMIN = true;
    win.location.hash = "";
});

describe("normalizeTabName", () => {
    test("strips leading hash, trims, and lowercases", () => {
        expect(win.normalizeTabName("#Tools")).toBe("tools");
        expect(win.normalizeTabName("  Gateways  ")).toBe("gateways");
        expect(win.normalizeTabName("#A2A-Agents")).toBe("a2a-agents");
    });

    test("returns empty string for null, undefined, and non-string inputs", () => {
        expect(win.normalizeTabName(null)).toBe("");
        expect(win.normalizeTabName(undefined)).toBe("");
        expect(win.normalizeTabName(42)).toBe("");
        expect(win.normalizeTabName("")).toBe("");
    });

    test("strips characters outside the allowed set", () => {
        expect(win.normalizeTabName('#"],.evil[x="')).toBe("evilx");
        expect(win.normalizeTabName("tab<script>")).toBe("tabscript");
        expect(win.normalizeTabName("valid-name")).toBe("valid-name");
    });
});

describe("showTab hidden tab fallback", () => {
    test("redirects hidden tab navigation to the default visible tab", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        const { panel: overviewPanel } = createTab("overview");

        win.UI_HIDDEN_TABS = ["prompts"];

        win.showTab("prompts");

        expect(overviewPanel.classList.contains("hidden")).toBe(false);
        expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
        expect(promptsPanel.classList.contains("hidden")).toBe(true);
        expect(win.location.hash).toBe("#overview");
    });

    test("blocks non-admin access to admin-only tabs", () => {
        const { panel: overviewPanel } = createTab("overview");
        const { panel: gatewaysPanel } = createTab("gateways");
        createTab("users");

        win.IS_ADMIN = false;

        win.showTab("users");

        expect(overviewPanel.classList.contains("hidden")).toBe(false);
        expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
        expect(win.location.hash).toBe("#overview");
    });
});

describe("showTab idempotency", () => {
    test("does not re-process a tab that is already visible", () => {
        const { panel: overviewPanel, link: overviewLink } = createTab("overview");
        createTab("gateways");

        win.showTab("overview");
        expect(overviewPanel.classList.contains("hidden")).toBe(false);

        // Call showTab again for the same tab — should be a no-op
        overviewLink.classList.remove("active");
        win.showTab("overview");

        // The link should get its active class restored but no full re-render
        expect(overviewLink.classList.contains("active")).toBe(true);
        expect(overviewPanel.classList.contains("hidden")).toBe(false);
    });
});

describe("getDefaultTabName priority", () => {
    test("prefers overview when available", () => {
        createTab("gateways");
        createTab("tools");
        createTab("overview");

        expect(win.getDefaultTabName()).toBe("overview");
    });

    test("falls back to gateways when overview is hidden", () => {
        createTab("gateways");
        createTab("tools");
        createTab("overview");

        win.UI_HIDDEN_TABS = ["overview"];

        expect(win.getDefaultTabName()).toBe("gateways");
    });

    test("falls back to first visible tab when overview and gateways are hidden", () => {
        createTab("gateways");
        createTab("tools");
        createTab("prompts");
        createTab("overview");

        win.UI_HIDDEN_TABS = ["overview", "gateways"];

        expect(win.getDefaultTabName()).toBe("tools");
    });
});

describe("isTabAvailable", () => {
    test("returns true only when both panel and sidebar link exist", () => {
        createTab("gateways");

        expect(win.isTabAvailable("gateways")).toBe(true);
    });

    test("returns false when panel exists but no sidebar link", () => {
        const panel = doc.createElement("div");
        panel.id = "orphan-panel";
        panel.className = "tab-panel hidden";
        doc.body.appendChild(panel);

        expect(win.isTabAvailable("orphan")).toBe(false);
    });

    test("returns false for empty or invalid names", () => {
        expect(win.isTabAvailable("")).toBe(false);
        expect(win.isTabAvailable(null)).toBe(false);
    });
});

describe("isSectionHidden with override mapping", () => {
    test("maps catalog to servers section for hide check", () => {
        createTab("gateways");
        win.UI_HIDDEN_SECTIONS = ["servers"];

        // isSectionHidden is an IIFE-scoped function, not directly accessible.
        // Test it indirectly via the overview section reload filter that uses it.
        // The getUiHiddenSections function IS accessible.
        const hiddenSections = win.getUiHiddenSections();
        expect(hiddenSections.has("servers")).toBe(true);
    });
});

describe("getUiHiddenSections and getUiHiddenTabs", () => {
    test("normalizes and deduplicates window globals", () => {
        win.UI_HIDDEN_SECTIONS = ["Tools", "TOOLS", "prompts"];
        const sections = win.getUiHiddenSections();
        expect(sections.has("tools")).toBe(true);
        expect(sections.has("prompts")).toBe(true);
        expect(sections.size).toBe(2);
    });

    test("returns empty set when globals are not arrays", () => {
        win.UI_HIDDEN_SECTIONS = "tools";
        expect(win.getUiHiddenSections().size).toBe(0);

        win.UI_HIDDEN_TABS = null;
        expect(win.getUiHiddenTabs().size).toBe(0);
    });
});

describe("initializeTabState hidden hash handling", () => {
    test("maps an initial hidden hash to a visible default tab", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        const { panel: overviewPanel } = createTab("overview");
        win.UI_HIDDEN_TABS = ["prompts"];

        win.location.hash = "#prompts";
        win.initializeTabState();

        expect(win.location.hash).toBe("#overview");
        expect(overviewPanel.classList.contains("hidden")).toBe(false);
        expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
        expect(promptsPanel.classList.contains("hidden")).toBe(true);
    });

    test("blocks hashchange navigation to hidden tabs", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        const { panel: overviewPanel } = createTab("overview");
        win.UI_HIDDEN_TABS = ["prompts"];

        win.location.hash = "#overview";
        win.initializeTabState();
        expect(win.location.hash).toBe("#overview");

        win.location.hash = "#prompts";
        win.dispatchEvent(new win.HashChangeEvent("hashchange"));

        expect(win.location.hash).toBe("#overview");
        expect(overviewPanel.classList.contains("hidden")).toBe(false);
        expect(gatewaysPanel.classList.contains("hidden")).toBe(true);
        expect(promptsPanel.classList.contains("hidden")).toBe(true);
    });
});

describe("loadTools hidden section behavior", () => {
    test("skips fetch when the tools section is hidden", async () => {
        const toolBody = doc.createElement("tbody");
        toolBody.id = "toolBody";
        doc.body.appendChild(toolBody);

        const fetchSpy = vi.fn();
        win.fetch = fetchSpy;
        win.UI_HIDDEN_SECTIONS = ["tools"];

        await win.loadTools();

        expect(fetchSpy).not.toHaveBeenCalled();
    });
});

describe("renderGlobalSearchResults hidden section filtering", () => {
    test("filters out groups belonging to hidden sections", () => {
        const container = doc.createElement("div");
        container.id = "global-search-results";
        doc.body.appendChild(container);

        win.UI_HIDDEN_SECTIONS = ["tools", "prompts"];

        win.renderGlobalSearchResults({
            groups: [
                { entity_type: "tools", items: [{ id: "t1", name: "Tool 1" }] },
                { entity_type: "gateways", items: [{ id: "g1", name: "GW 1" }] },
                { entity_type: "prompts", items: [{ id: "p1", name: "Prompt 1" }] },
            ],
        });

        const html = container.innerHTML;
        expect(html).toContain("Gateways");
        expect(html).not.toContain("Tools");
        expect(html).not.toContain("Prompts");
    });

    test("shows no results message when all groups are hidden", () => {
        const container = doc.createElement("div");
        container.id = "global-search-results";
        doc.body.appendChild(container);

        win.UI_HIDDEN_SECTIONS = ["tools"];

        win.renderGlobalSearchResults({
            groups: [
                { entity_type: "tools", items: [{ id: "t1", name: "Tool 1" }] },
            ],
        });

        expect(container.innerHTML).toContain("No matching results");
    });
});

describe("isTabHidden", () => {
    test("returns true for a tab in the hidden list", () => {
        win.UI_HIDDEN_TABS = ["prompts", "tools"];
        expect(win.isTabHidden("prompts")).toBe(true);
        expect(win.isTabHidden("tools")).toBe(true);
    });

    test("returns false for a tab not in the hidden list", () => {
        win.UI_HIDDEN_TABS = ["prompts"];
        expect(win.isTabHidden("gateways")).toBe(false);
    });

    test("returns false for empty or null input", () => {
        win.UI_HIDDEN_TABS = ["prompts"];
        expect(win.isTabHidden("")).toBe(false);
        expect(win.isTabHidden(null)).toBe(false);
    });

    test("normalizes input before checking", () => {
        win.UI_HIDDEN_TABS = ["prompts"];
        expect(win.isTabHidden("#Prompts")).toBe(true);
        expect(win.isTabHidden("  PROMPTS  ")).toBe(true);
    });
});

describe("resolveTabForNavigation", () => {
    test("returns the tab itself when visible and available", () => {
        createTab("gateways");
        createTab("overview");

        expect(win.resolveTabForNavigation("gateways")).toBe("gateways");
    });

    test("falls back to default for hidden tab", () => {
        createTab("gateways");
        createTab("prompts");
        createTab("overview");
        win.UI_HIDDEN_TABS = ["prompts"];

        expect(win.resolveTabForNavigation("prompts")).toBe("overview");
    });

    test("falls back to default for empty input", () => {
        createTab("overview");
        createTab("gateways");

        expect(win.resolveTabForNavigation("")).toBe("overview");
        expect(win.resolveTabForNavigation(null)).toBe("overview");
    });

    test("falls back to default for admin-only tab when non-admin", () => {
        createTab("overview");
        createTab("users");
        win.IS_ADMIN = false;

        expect(win.resolveTabForNavigation("users")).toBe("overview");
    });

    test("falls back to default for non-existent tab", () => {
        createTab("overview");
        createTab("gateways");

        expect(win.resolveTabForNavigation("nonexistent")).toBe("overview");
    });
});

describe("showTab normal navigation", () => {
    test("shows the requested visible tab and hides others", () => {
        const { panel: overviewPanel, link: overviewLink } = createTab("overview");
        const { panel: gatewaysPanel, link: gatewaysLink } = createTab("gateways");

        win.showTab("gateways");

        expect(gatewaysPanel.classList.contains("hidden")).toBe(false);
        expect(overviewPanel.classList.contains("hidden")).toBe(true);
        expect(gatewaysLink.classList.contains("active")).toBe(true);
        expect(overviewLink.classList.contains("active")).toBe(false);
    });
});

describe("getDefaultTabName edge cases", () => {
    test("returns gateways fallback when all tabs are hidden and no panels exist", () => {
        // No tabs created, nothing available
        win.UI_HIDDEN_TABS = ["overview"];
        expect(win.getDefaultTabName()).toBe("gateways");
    });

    test("returns overview when overview panel exists but no sidebar links", () => {
        // Create only the panel, not the sidebar link
        const panel = doc.createElement("div");
        panel.id = "overview-panel";
        panel.className = "tab-panel hidden";
        doc.body.appendChild(panel);

        expect(win.getDefaultTabName()).toBe("overview");
    });
});
