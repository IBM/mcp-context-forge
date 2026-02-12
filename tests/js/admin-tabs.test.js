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
    win.location.hash = "";
});

describe("showTab hidden tab fallback", () => {
    test("redirects hidden tab navigation to the default visible tab", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        createTab("overview");

        win.UI_HIDDEN_TABS = ["prompts"];

        win.showTab("prompts");

        expect(gatewaysPanel.classList.contains("hidden")).toBe(false);
        expect(promptsPanel.classList.contains("hidden")).toBe(true);
        expect(win.location.hash).toBe("#gateways");
    });
});

describe("initializeTabState hidden hash handling", () => {
    test("maps an initial hidden hash to a visible default tab", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        createTab("overview");
        win.UI_HIDDEN_TABS = ["prompts"];

        win.location.hash = "#prompts";
        win.initializeTabState();

        expect(win.location.hash).toBe("#gateways");
        expect(gatewaysPanel.classList.contains("hidden")).toBe(false);
        expect(promptsPanel.classList.contains("hidden")).toBe(true);
    });

    test("blocks hashchange navigation to hidden tabs", () => {
        const { panel: gatewaysPanel } = createTab("gateways");
        const { panel: promptsPanel } = createTab("prompts");
        createTab("overview");
        win.UI_HIDDEN_TABS = ["prompts"];

        win.location.hash = "#gateways";
        win.initializeTabState();
        expect(win.location.hash).toBe("#gateways");

        win.location.hash = "#prompts";
        win.dispatchEvent(new win.HashChangeEvent("hashchange"));

        expect(win.location.hash).toBe("#gateways");
        expect(gatewaysPanel.classList.contains("hidden")).toBe(false);
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
