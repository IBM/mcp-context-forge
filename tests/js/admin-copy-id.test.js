/**
 * Unit tests for makeCopyIdButton helper in admin.js.
 */

import {
    describe,
    test,
    expect,
    vi,
    beforeAll,
    beforeEach,
    afterAll,
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
    vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// makeCopyIdButton
// ---------------------------------------------------------------------------
describe("makeCopyIdButton", () => {
    const f = () => win.makeCopyIdButton;

    test("returns a button element", () => {
        const btn = f()("test-id-123");
        expect(btn.tagName).toBe("BUTTON");
        expect(btn.type).toBe("button");
    });

    test("button has correct title attribute", () => {
        const btn = f()("abc");
        expect(btn.title).toBe("Copy ID to clipboard");
    });

    test("button has expected CSS classes", () => {
        const btn = f()("abc");
        expect(btn.className).toContain("ml-2");
        expect(btn.className).toContain("inline-flex");
        expect(btn.className).toContain("items-center");
    });

    test("button has copy label text", () => {
        const btn = f()("abc");
        expect(btn.textContent).toContain("Copy");
    });

    test("coerces numeric id to string via String()", () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(win.navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });

        const btn = f()(42);
        btn.click();
        expect(writeText).toHaveBeenCalledWith("42");
    });

    test("copies string id to clipboard on click", () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(win.navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });

        const btn = f()("my-uuid-1234");
        btn.click();
        expect(writeText).toHaveBeenCalledWith("my-uuid-1234");
    });

    test("shows success feedback after copy", async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(win.navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });

        const btn = f()("id-1");
        btn.click();

        // Wait for the promise to resolve
        await vi.waitFor(() => {
            expect(btn.textContent).toContain("Copied!");
        });
    });

    test("shows failure feedback when clipboard write fails", async () => {
        const writeText = vi.fn().mockRejectedValue(new Error("denied"));
        Object.defineProperty(win.navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });

        const btn = f()("id-2");
        btn.click();

        await vi.waitFor(() => {
            expect(btn.textContent).toContain("Failed");
        });
    });

    test("falls back to execCommand when clipboard API is unavailable", () => {
        Object.defineProperty(win.navigator, "clipboard", {
            value: undefined,
            configurable: true,
        });
        doc.execCommand = vi.fn(() => true);

        const btn = f()("fallback-id");
        doc.body.appendChild(btn);
        btn.click();

        expect(doc.execCommand).toHaveBeenCalledWith("copy");
        expect(btn.textContent).toContain("Copied!");
    });

    test("shows failure when both clipboard API and execCommand fail", () => {
        Object.defineProperty(win.navigator, "clipboard", {
            value: undefined,
            configurable: true,
        });
        doc.execCommand = vi.fn(() => {
            throw new Error("not supported");
        });

        const btn = f()("fail-id");
        doc.body.appendChild(btn);
        btn.click();

        expect(btn.textContent).toContain("Failed");
    });
});
