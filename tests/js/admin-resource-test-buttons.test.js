/**
 * Regression tests for resource test modal buttons.
 *
 * Verifies that dynamically created buttons inside runResourceTest()
 * have explicit type="button" to prevent unintended form submission
 * when rendered inside <form id="resource-test-form">.
 *
 * See: https://github.com/ContextForge/mcp-context-forge/issues/3606
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

beforeEach(() => {
    doc.body.textContent = "";
});

// ---------------------------------------------------------------------------
// Helper: mock fetch response for resource test
// ---------------------------------------------------------------------------
function mockResourceResponse(content = { text: '{"key": "value"}' }) {
    return {
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: vi.fn().mockResolvedValue({ content }),
        text: vi.fn().mockResolvedValue(JSON.stringify({ content })),
        clone() {
            return mockResourceResponse(content);
        },
    };
}

// ---------------------------------------------------------------------------
// Helper: set up DOM elements required by runResourceTest()
// ---------------------------------------------------------------------------
function setupResourceTestDOM() {
    const form = doc.createElement("form");
    form.id = "resource-test-form";

    const fieldsContainer = doc.createElement("div");
    fieldsContainer.id = "resource-test-form-fields";
    form.appendChild(fieldsContainer);

    const resultBox = doc.createElement("div");
    resultBox.id = "resource-test-result";
    form.appendChild(resultBox);

    doc.body.appendChild(form);

    return { form, fieldsContainer, resultBox };
}

// ---------------------------------------------------------------------------
// runResourceTest – button type="button" regression
// ---------------------------------------------------------------------------
describe("runResourceTest button types", () => {
    test("Copy, Fullscreen, Download buttons have type='button'", async () => {
        const { resultBox } = setupResourceTestDOM();

        win.ROOT_PATH = "";
        win.CurrentResourceUnderTest = { uri: "test://example", name: "Test" };
        win.fetch = vi.fn().mockResolvedValue(mockResourceResponse());

        await win.runResourceTest();

        const buttons = resultBox.querySelectorAll("button");
        expect(buttons.length).toBeGreaterThanOrEqual(3);

        const copyBtn = Array.from(buttons).find(
            (b) => b.textContent === "Copy",
        );
        const fullscreenBtn = Array.from(buttons).find(
            (b) => b.textContent === "Fullscreen",
        );
        const downloadBtn = Array.from(buttons).find(
            (b) => b.textContent === "Download",
        );

        expect(copyBtn).toBeDefined();
        expect(copyBtn.type).toBe("button");

        expect(fullscreenBtn).toBeDefined();
        expect(fullscreenBtn.type).toBe("button");

        expect(downloadBtn).toBeDefined();
        expect(downloadBtn.type).toBe("button");
    });

    test("Fullscreen overlay Close button has type='button'", async () => {
        const { resultBox } = setupResourceTestDOM();

        win.ROOT_PATH = "";
        win.CurrentResourceUnderTest = { uri: "test://example", name: "Test" };
        win.fetch = vi.fn().mockResolvedValue(mockResourceResponse());

        await win.runResourceTest();

        // Click the Fullscreen button to create the overlay
        const fullscreenBtn = Array.from(
            resultBox.querySelectorAll("button"),
        ).find((b) => b.textContent === "Fullscreen");
        expect(fullscreenBtn).toBeDefined();
        fullscreenBtn.click();

        // The overlay is appended to document.body
        const closeBtn = Array.from(doc.body.querySelectorAll("button")).find(
            (b) => b.textContent === "Close",
        );
        expect(closeBtn).toBeDefined();
        expect(closeBtn.type).toBe("button");
    });
});
