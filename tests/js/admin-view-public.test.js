/**
 * Tests for the toggleViewPublic function and View Public checkbox behaviour.
 *
 * Covers:
 *  - Checking the box keeps team_id and adds include_public=true to selector hx-get URLs
 *  - Unchecking removes include_public and keeps team_id
 *  - Round-trip: check → uncheck → check
 *  - team_id is not duplicated when unchecking with it already present
 *  - HTMX process + trigger are called per container per toggle
 *  - Multiple containers updated in a single call
 *  - Early-return guards (missing checkbox, missing teamId, missing container)
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
    win.htmx = { process: vi.fn(), trigger: vi.fn() };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCheckbox(id) {
    const cb = doc.createElement("input");
    cb.type = "checkbox";
    cb.id = id;
    doc.body.appendChild(cb);
    return cb;
}

function makeHtmxContainer(id, url) {
    const div = doc.createElement("div");
    div.id = id;
    div.setAttribute("hx-get", url);
    doc.body.appendChild(div);
    return div;
}

// ---------------------------------------------------------------------------
// URL mutation
// ---------------------------------------------------------------------------

describe("toggleViewPublic — URL mutation", () => {
    test("checking the box keeps team_id and adds include_public=true", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
    });

    test("unchecking the box removes include_public and keeps team_id", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc&include_public=true",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = false;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).not.toContain("include_public");
    });

    test("round-trip check → uncheck → check keeps team_id throughout and toggles include_public", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");

        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        cb.checked = false;
        cb.dispatchEvent(new win.Event("change"));

        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
    });

    test("unchecking does not add team_id a second time when it is already present", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = false;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect((url.match(/team_id=/g) || []).length).toBe(1);
    });

    test("team_id value is URI-encoded in the appended param", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team with spaces",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = false;
        cb.dispatchEvent(new win.Event("change"));

        expect(container.getAttribute("hx-get")).toContain(
            "team_id=team%20with%20spaces",
        );
    });

    test("checking adds include_public even when team_id was not initially in URL", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
    });

    test("include_public is not duplicated on repeated checks", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect((url.match(/include_public=/g) || []).length).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// HTMX side-effects
// ---------------------------------------------------------------------------

describe("toggleViewPublic — HTMX side-effects", () => {
    test("htmx.process and htmx.trigger are called once per toggle", () => {
        makeCheckbox("add-server-view-public");
        makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        expect(win.htmx.process).toHaveBeenCalledTimes(1);
        expect(win.htmx.trigger).toHaveBeenCalledTimes(1);
    });

    test("htmx.trigger is called with the container element and 'load'", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        expect(win.htmx.trigger).toHaveBeenCalledWith(container, "load");
    });

    test("htmx is called once per container when multiple containers are passed", () => {
        makeCheckbox("add-server-view-public");
        ["associatedTools", "associatedResources", "associatedPrompts"].forEach(
            (id) =>
                makeHtmxContainer(
                    id,
                    `/admin/${id}/partial?render=selector&team_id=team-abc`,
                ),
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools", "associatedResources", "associatedPrompts"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        expect(win.htmx.process).toHaveBeenCalledTimes(3);
        expect(win.htmx.trigger).toHaveBeenCalledTimes(3);
    });

    test("all containers have include_public=true added when checking with multiple containers", () => {
        makeCheckbox("add-server-view-public");
        const containers = [
            "associatedTools",
            "associatedResources",
            "associatedPrompts",
        ].map((id) =>
            makeHtmxContainer(
                id,
                `/admin/${id}/partial?render=selector&team_id=team-abc`,
            ),
        );

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools", "associatedResources", "associatedPrompts"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        containers.forEach((c) => {
            const url = c.getAttribute("hx-get");
            expect(url).toContain("team_id=team-abc");
            expect(url).toContain("include_public=true");
        });
    });
});

// ---------------------------------------------------------------------------
// Guard / early-return behaviour
// ---------------------------------------------------------------------------

describe("toggleViewPublic — early-return guards", () => {
    test("does not throw when the checkbox does not exist in the DOM", () => {
        expect(() => {
            win.toggleViewPublic(
                "nonexistent-checkbox",
                ["associatedTools"],
                "team-abc",
            );
        }).not.toThrow();
    });

    test("does not throw when teamId is an empty string", () => {
        makeCheckbox("add-server-view-public");
        expect(() => {
            win.toggleViewPublic(
                "add-server-view-public",
                ["associatedTools"],
                "",
            );
        }).not.toThrow();
    });

    test("skips containers that are not in the DOM, processes those that are", () => {
        makeCheckbox("add-server-view-public");
        const present = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?render=selector&team_id=team-abc",
        );
        // "associatedMissing" does not exist in the DOM

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools", "associatedMissing"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        // Present container updated, no error for missing one
        const url = present.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
        expect(win.htmx.process).toHaveBeenCalledTimes(1);
    });

    test("skips a container that has no hx-get attribute", () => {
        makeCheckbox("add-server-view-public");
        const noAttr = doc.createElement("div");
        noAttr.id = "associatedTools";
        doc.body.appendChild(noAttr); // no hx-get set

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        expect(win.htmx.process).not.toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// toggleViewPublic — gateway_id preservation
// ---------------------------------------------------------------------------

describe("toggleViewPublic — gateway_id preservation", () => {
    test("preserves team_id and adds include_public when toggling (no active gateway selection)", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&gateway_id=gw-1&team_id=team-abc",
        );

        // No getSelectedGatewayIds available — falls back to empty
        win.getSelectedGatewayIds = undefined;

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        // team_id preserved, include_public added, gateway_id stripped (no active selection)
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
        expect(url).not.toContain("gateway_id");
    });

    test("injects current gateway selection into hx-get on toggle", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        // Simulate selected gateways
        win.getSelectedGatewayIds = () => ["gw-1", "gw-2"];

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("include_public=true");
        expect(url).toContain("gateway_id=gw-1%2Cgw-2");
    });

    test("round-trip preserves gateway_id when unchecking", () => {
        makeCheckbox("add-server-view-public");
        const container = makeHtmxContainer(
            "associatedTools",
            "/admin/tools/partial?page=1&render=selector&team_id=team-abc",
        );

        win.getSelectedGatewayIds = () => ["gw-1"];

        win.toggleViewPublic(
            "add-server-view-public",
            ["associatedTools"],
            "team-abc",
        );

        const cb = doc.getElementById("add-server-view-public");

        // check
        cb.checked = true;
        cb.dispatchEvent(new win.Event("change"));

        // uncheck
        cb.checked = false;
        cb.dispatchEvent(new win.Event("change"));

        const url = container.getAttribute("hx-get");
        expect(url).toContain("team_id=team-abc");
        expect(url).toContain("gateway_id=gw-1");
        expect(url).not.toContain("include_public");
    });
});

// ---------------------------------------------------------------------------
// initGatewaySelect — edit-modal Select All reads correct View Public checkbox
// ---------------------------------------------------------------------------

describe("initGatewaySelect — edit-modal Select All checkbox lookup", () => {
    function makeGatewayEditDom() {
        const container = doc.createElement("div");
        container.id = "associatedEditGateways";
        doc.body.appendChild(container);

        const pills = doc.createElement("div");
        pills.id = "selectedEditGatewayPills";
        doc.body.appendChild(pills);

        const warn = doc.createElement("div");
        warn.id = "selectedEditGatewayWarning";
        doc.body.appendChild(warn);

        const selectBtn = doc.createElement("button");
        selectBtn.id = "selectAllEditGatewayBtn";
        doc.body.appendChild(selectBtn);

        const clearBtn = doc.createElement("button");
        clearBtn.id = "clearAllEditGatewayBtn";
        doc.body.appendChild(clearBtn);
    }

    test("edit-modal Select All includes team_id and include_public when edit View Public is checked", async () => {
        // Both checkboxes exist in DOM (as on a team-scoped page)
        const addCb = makeCheckbox("add-server-view-public");
        addCb.checked = false; // add-modal unchecked
        const editCb = makeCheckbox("edit-server-view-public");
        editCb.checked = true; // edit-modal checked

        makeGatewayEditDom();

        // Stubs
        win.getCurrentTeamId = () => "team-abc";
        win.ROOT_PATH = "";
        let fetchedUrl = null;
        win.fetch = vi.fn().mockImplementation((url) => {
            fetchedUrl = url;
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ gateway_ids: [] }),
            });
        });

        // Init with edit selectId
        win.initGatewaySelect(
            "associatedEditGateways",
            "selectedEditGatewayPills",
            "selectedEditGatewayWarning",
            12,
            "selectAllEditGatewayBtn",
            "clearAllEditGatewayBtn",
            "searchEditGateways",
        );

        // Click the replaced Select All button
        const btn = doc.getElementById("selectAllEditGatewayBtn");
        btn.click();
        // Let the async handler run
        await new Promise((resolve) => setTimeout(resolve, 50));

        // Should contain team_id AND include_public because edit checkbox is checked
        expect(fetchedUrl).not.toBeNull();
        expect(fetchedUrl).toContain("team_id=team-abc");
        expect(fetchedUrl).toContain("include_public=true");
    });

    test("edit-modal Select All includes team_id without include_public when edit View Public is unchecked", async () => {
        const addCb = makeCheckbox("add-server-view-public");
        addCb.checked = true; // add-modal checked (should be ignored)
        const editCb = makeCheckbox("edit-server-view-public");
        editCb.checked = false; // edit-modal unchecked

        makeGatewayEditDom();

        win.getCurrentTeamId = () => "team-abc";
        win.ROOT_PATH = "";
        let fetchedUrl = null;
        win.fetch = vi.fn().mockImplementation((url) => {
            fetchedUrl = url;
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ gateway_ids: [] }),
            });
        });

        win.initGatewaySelect(
            "associatedEditGateways",
            "selectedEditGatewayPills",
            "selectedEditGatewayWarning",
            12,
            "selectAllEditGatewayBtn",
            "clearAllEditGatewayBtn",
            "searchEditGateways",
        );

        const btn = doc.getElementById("selectAllEditGatewayBtn");
        btn.click();
        await new Promise((resolve) => setTimeout(resolve, 50));

        expect(fetchedUrl).not.toBeNull();
        expect(fetchedUrl).toContain("team_id=team-abc");
        expect(fetchedUrl).not.toContain("include_public");
    });
});
