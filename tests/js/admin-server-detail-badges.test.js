/**
 * Tests for the "+N more" badge click-to-expand functionality in the
 * server details modal (viewServer).
 *
 * Covers:
 *  - Tools "+N more" badge renders with cursor-pointer and correct count
 *  - Clicking tools badge expands full list inline
 *  - Resources "+N more" badge renders and expands on click
 *  - Prompts "+N more" badge renders and expands on click
 *  - Expanded list shows all items with correct display names and IDs
 *  - Sections with <= maxToShow items do not render a "+N more" badge
 *  - Window mapping lookups fall back to raw IDs when mappings are absent
 */

import {
    describe,
    test,
    expect,
    beforeAll,
    beforeEach,
    afterAll,
    vi,
} from "vitest";
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeServerDetailsContainer() {
    const div = doc.createElement("div");
    div.id = "server-details";
    doc.body.appendChild(div);
    return div;
}

function makeServerModal() {
    const modal = doc.createElement("div");
    modal.id = "server-modal";
    modal.classList.add("hidden");
    doc.body.appendChild(modal);
    return modal;
}

function mockFetch(serverData) {
    const body = JSON.stringify(serverData);
    const makeResponse = () => ({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: {
            get: (name) => {
                if (name.toLowerCase() === "content-length") {
                    return String(body.length);
                }
                return null;
            },
        },
        json: () => Promise.resolve(serverData),
        text: () => Promise.resolve(body),
        clone: function () {
            return makeResponse();
        },
    });
    win.fetch = vi.fn().mockResolvedValue(makeResponse());
}

function buildServer(overrides = {}) {
    return {
        id: "srv-1",
        name: "Test Server",
        description: "A test server",
        enabled: true,
        visibility: "private",
        tags: [],
        associatedTools: [],
        associatedResources: [],
        associatedPrompts: [],
        associatedA2aAgents: [],
        ...overrides,
    };
}

function findMoreBadge(container, colorClass) {
    const badges = container.querySelectorAll("span");
    for (const badge of badges) {
        if (
            badge.textContent.startsWith("+") &&
            badge.textContent.includes("more") &&
            badge.className.includes(colorClass)
        ) {
            return badge;
        }
    }
    return null;
}

function getItemBadges(container, colorClass) {
    const badges = container.querySelectorAll("span");
    return Array.from(badges).filter(
        (b) =>
            b.className.includes(colorClass) &&
            b.className.includes("inline-block") &&
            !b.textContent.startsWith("+"),
    );
}

beforeEach(() => {
    doc.body.textContent = "";
    win.ROOT_PATH = "";
    win.toolMapping = undefined;
    win.resourceMapping = undefined;
    win.promptMapping = undefined;
    // Reset modal state so openModal doesn't skip
    if (win.AppState && win.AppState.activeModals) {
        win.AppState.activeModals.clear();
    }
});

// ---------------------------------------------------------------------------
// Tools: "+N more" badge click-to-expand
// ---------------------------------------------------------------------------

describe("viewServer — tools +N more badge", () => {
    test("renders '+N more' badge when tools exceed maxToShow (3)", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4", "t5"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        expect(moreBadge).not.toBeNull();
        expect(moreBadge.textContent).toBe("+2 more");
    });

    test("'+N more' badge has cursor-pointer class", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        expect(moreBadge.className).toContain("cursor-pointer");
    });

    test("clicking tools badge expands to show all tools", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4", "t5"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");

        // Click the badge
        moreBadge.click();

        // After expansion, the "+N more" badge should be gone
        const moreBadgeAfter = findMoreBadge(container, "bg-green");
        expect(moreBadgeAfter).toBeNull();

        // All 5 tool badges should be present
        const toolBadges = getItemBadges(container, "bg-green");
        expect(toolBadges.length).toBe(5);
    });

    test("expanded tools show IDs in parentheses", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        moreBadge.click();

        // Check that ID spans are rendered
        const idSpans = container.querySelectorAll(
            "span.text-xs.text-gray-500",
        );
        const toolIdTexts = Array.from(idSpans)
            .map((s) => s.textContent)
            .filter((t) => t.match(/^\(t\d\)$/));
        expect(toolIdTexts).toContain("(t1)");
        expect(toolIdTexts).toContain("(t4)");
    });

    test("expanded tools use window.toolMapping for display names", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        win.toolMapping = { t1: "Tool Alpha", t4: "Tool Delta" };
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        moreBadge.click();

        const toolBadges = getItemBadges(container, "bg-green");
        const texts = toolBadges.map((b) => b.textContent);
        expect(texts).toContain("Tool Alpha");
        expect(texts).toContain("Tool Delta");
        // t2 has no mapping, should fall back to raw ID
        expect(texts).toContain("t2");
    });

    test("does not render badge when tools count equals maxToShow", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        expect(moreBadge).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Resources: "+N more" badge click-to-expand
// ---------------------------------------------------------------------------

describe("viewServer — resources +N more badge", () => {
    test("renders '+N more' badge for resources exceeding maxToShow", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedResources: ["r1", "r2", "r3", "r4", "r5", "r6"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-blue");
        expect(moreBadge).not.toBeNull();
        expect(moreBadge.textContent).toBe("+3 more");
    });

    test("clicking resources badge expands to show all resources", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedResources: ["r1", "r2", "r3", "r4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-blue");
        moreBadge.click();

        const moreBadgeAfter = findMoreBadge(container, "bg-blue");
        expect(moreBadgeAfter).toBeNull();

        const resourceBadges = getItemBadges(container, "bg-blue");
        // Note: tags also use bg-blue, so filter by the resource section
        // Resources use "Resource {id}" as fallback text
        const resourceTexts = resourceBadges
            .map((b) => b.textContent)
            .filter((t) => t.startsWith("Resource "));
        expect(resourceTexts.length).toBe(4);
    });

    test("expanded resources use window.resourceMapping for display names", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        win.resourceMapping = { r1: "My Resource", r4: "Config File" };
        const server = buildServer({
            associatedResources: ["r1", "r2", "r3", "r4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-blue");
        moreBadge.click();

        const resourceBadges = getItemBadges(container, "bg-blue");
        const texts = resourceBadges.map((b) => b.textContent);
        expect(texts).toContain("My Resource");
        expect(texts).toContain("Config File");
        expect(texts).toContain("Resource r2");
    });

    test("resources '+N more' badge has cursor-pointer class", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedResources: ["r1", "r2", "r3", "r4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-blue");
        expect(moreBadge.className).toContain("cursor-pointer");
    });
});

// ---------------------------------------------------------------------------
// Prompts: "+N more" badge click-to-expand
// ---------------------------------------------------------------------------

describe("viewServer — prompts +N more badge", () => {
    test("renders '+N more' badge for prompts exceeding maxToShow", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedPrompts: ["p1", "p2", "p3", "p4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-purple");
        expect(moreBadge).not.toBeNull();
        expect(moreBadge.textContent).toBe("+1 more");
    });

    test("clicking prompts badge expands to show all prompts", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedPrompts: ["p1", "p2", "p3", "p4", "p5"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-purple");
        moreBadge.click();

        const moreBadgeAfter = findMoreBadge(container, "bg-purple");
        expect(moreBadgeAfter).toBeNull();

        const promptBadges = getItemBadges(container, "bg-purple");
        expect(promptBadges.length).toBe(5);
    });

    test("expanded prompts use window.promptMapping for display names", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        win.promptMapping = { p1: "Welcome Prompt", p5: "Farewell Prompt" };
        const server = buildServer({
            associatedPrompts: ["p1", "p2", "p3", "p4", "p5"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-purple");
        moreBadge.click();

        const promptBadges = getItemBadges(container, "bg-purple");
        const texts = promptBadges.map((b) => b.textContent);
        expect(texts).toContain("Welcome Prompt");
        expect(texts).toContain("Farewell Prompt");
        expect(texts).toContain("Prompt p2");
    });

    test("prompts '+N more' badge has cursor-pointer class", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedPrompts: ["p1", "p2", "p3", "p4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-purple");
        expect(moreBadge.className).toContain("cursor-pointer");
    });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe("viewServer — badge edge cases", () => {
    test("no badges shown when all sections have <= 3 items", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2"],
            associatedResources: ["r1"],
            associatedPrompts: ["p1", "p2", "p3"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        expect(findMoreBadge(container, "bg-green")).toBeNull();
        expect(findMoreBadge(container, "bg-purple")).toBeNull();
    });

    test("expanded tools list has correct green badge styling", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        moreBadge.click();

        const toolBadges = getItemBadges(container, "bg-green");
        for (const badge of toolBadges) {
            expect(badge.className).toContain("bg-green-100");
            expect(badge.className).toContain("text-green-800");
            expect(badge.className).toContain("rounded-full");
        }
    });

    test("badge shows correct count with exactly 4 items (maxToShow+1)", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const moreBadge = findMoreBadge(container, "bg-green");
        expect(moreBadge.textContent).toBe("+1 more");
    });

    test("multiple sections can each have their own +N more badge", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4", "t5"],
            associatedResources: ["r1", "r2", "r3", "r4"],
            associatedPrompts: ["p1", "p2", "p3", "p4", "p5", "p6"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");
        const toolsBadge = findMoreBadge(container, "bg-green");
        const promptsBadge = findMoreBadge(container, "bg-purple");
        expect(toolsBadge.textContent).toBe("+2 more");
        expect(promptsBadge.textContent).toBe("+3 more");
    });

    test("clicking one section badge does not affect other sections", async () => {
        makeServerDetailsContainer();
        makeServerModal();
        const server = buildServer({
            associatedTools: ["t1", "t2", "t3", "t4"],
            associatedPrompts: ["p1", "p2", "p3", "p4"],
        });
        mockFetch(server);

        await win.viewServer("srv-1");

        const container = doc.getElementById("server-details");

        // Click only the tools badge
        const toolsBadge = findMoreBadge(container, "bg-green");
        toolsBadge.click();

        // Tools badge should be gone
        expect(findMoreBadge(container, "bg-green")).toBeNull();
        // Prompts badge should still be present
        expect(findMoreBadge(container, "bg-purple")).not.toBeNull();
    });
});
