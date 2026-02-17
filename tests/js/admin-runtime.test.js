/**
 * Unit tests for runtime-specific admin.js behavior.
 */

import {
    afterAll,
    beforeAll,
    beforeEach,
    describe,
    expect,
    test,
    vi,
} from "vitest";
import { cleanupAdminJs, loadAdminJs } from "./helpers/admin-env.js";

let win;
let doc;

function addElement(tagName, id, options = {}) {
    const el = doc.createElement(tagName);
    if (id) {
        el.id = id;
    }
    if (options.type) {
        el.type = options.type;
    }
    if (options.value !== undefined) {
        el.value = options.value;
    }
    if (options.checked !== undefined) {
        el.checked = options.checked;
    }
    if (options.className) {
        el.className = options.className;
    }
    if (options.textContent !== undefined) {
        el.textContent = options.textContent;
    }
    doc.body.appendChild(el);
    return el;
}

function addSelect(id, values = [], selectedValue = "") {
    const select = addElement("select", id);
    values.forEach((value) => {
        const option = doc.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
    });
    if (selectedValue) {
        select.value = selectedValue;
    }
    return select;
}

function addRuntimeDeployElements() {
    addElement("input", "runtime-deploy-name", { value: "runtime-one" });
    addSelect(
        "runtime-deploy-backend",
        ["docker", "ibm_code_engine"],
        "docker",
    );
    addSelect(
        "runtime-deploy-source-type",
        ["docker", "github", "compose", "catalog"],
        "docker",
    );
    addSelect(
        "runtime-deploy-guardrails-profile",
        ["standard", "unrestricted"],
        "standard",
    );
    addElement("input", "runtime-deploy-register-gateway", {
        type: "checkbox",
        checked: true,
    });
    addSelect(
        "runtime-deploy-visibility",
        ["public", "team", "private"],
        "public",
    );
    addElement("input", "runtime-deploy-team-id", { value: "" });
    addElement("input", "runtime-deploy-gateway-name", { value: "" });
    addSelect(
        "runtime-deploy-gateway-transport",
        ["", "SSE", "STREAMABLEHTTP"],
        "",
    );
    addElement("input", "runtime-deploy-tags", {
        value: "runtime, fast-time ,production",
    });
    addElement("textarea", "runtime-deploy-environment-json", {
        value: '{"TZ":"UTC"}',
    });
    addElement("textarea", "runtime-deploy-metadata-json", {
        value: '{"owner":"platform"}',
    });
    addElement("input", "runtime-deploy-cpu", { value: "0.5" });
    addElement("input", "runtime-deploy-memory", { value: "512m" });
    addElement("input", "runtime-deploy-timeout", { value: "45" });

    addElement("input", "runtime-source-image", {
        value: "ghcr.io/ibm/fast-time-server:0.8.0",
    });
    addElement("input", "runtime-source-repo", {
        value: "https://github.com/org/repo",
    });
    addElement("input", "runtime-source-branch", { value: "main" });
    addElement("input", "runtime-source-dockerfile", { value: "Dockerfile" });
    addElement("input", "runtime-source-push-to-registry", {
        type: "checkbox",
        checked: true,
    });
    addElement("input", "runtime-source-registry", { value: "ghcr.io/acme" });
    addElement("input", "runtime-source-compose-file", {
        value: "compose.yml",
    });
    addElement("input", "runtime-source-main-service", { value: "mcp-server" });
    addElement("input", "runtime-source-catalog-id", {
        value: "fast-time-server",
    });
}

async function nextTick() {
    await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeAll(() => {
    win = loadAdminJs();
    doc = win.document;
});

afterAll(() => {
    cleanupAdminJs();
});

beforeEach(() => {
    vi.restoreAllMocks();
    doc.body.textContent = "";
    win.ROOT_PATH = "";
    win.RUNTIME_DEFAULT_BACKEND = "docker";
    win.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT = 1;
});

describe("runtime utility helpers", () => {
    test("builds runtime API base from root path", () => {
        win.ROOT_PATH = "/api";
        expect(win.getRuntimeApiBase()).toBe("/api/runtimes");
    });

    test("shortens runtime identifiers", () => {
        expect(win.runtimeShortId("abcdef123456", 6)).toBe("abcdef...");
        expect(win.runtimeShortId("abc", 6)).toBe("abc");
        expect(win.runtimeShortId("")).toBe("-");
    });

    test("renders deploy messages with type-specific classes", () => {
        const message = addElement("span", "runtime-deploy-message");
        win.runtimeSetDeployMessage("ok", "success");
        expect(message.textContent).toBe("ok");
        expect(message.className).toContain("text-green-600");

        win.runtimeSetDeployMessage("bad", "error");
        expect(message.className).toContain("text-red-600");

        win.runtimeSetDeployMessage("");
        expect(message.textContent).toBe("");
        expect(message.className).toContain("text-gray-600");
    });

    test("renders runtime logs and empty states", () => {
        const output = addElement("pre", "runtime-logs-output");
        win.runtimeSetLogs(["line1", "line2"], "rt-1");
        expect(output.textContent).toBe("line1\nline2");

        win.runtimeSetLogs([], "rt-1");
        expect(output.textContent).toContain("No logs returned");

        win.runtimeSetLogs([]);
        expect(output.textContent).toContain("No logs loaded");
    });

    test("creates status badge HTML for known and unknown values", () => {
        const running = win.runtimeStatusBadge("running");
        const weird = win.runtimeStatusBadge("weird_state");
        expect(running).toContain("bg-green-100");
        expect(running).toContain(">running<");
        expect(weird).toContain(">weird_state<");
        expect(weird).toContain("bg-gray-100");
    });

    test("validates docker image references", () => {
        expect(
            win.runtimeIsValidDockerImageReference(
                "ghcr.io/ibm/fast-time-server:0.8.0",
            ),
        ).toBe(true);
        expect(
            win.runtimeIsValidDockerImageReference(
                "docker.io/library/alpine:3.20",
            ),
        ).toBe(true);
        expect(win.runtimeIsValidDockerImageReference("bad image ref")).toBe(
            false,
        );
        expect(
            win.runtimeIsValidDockerImageReference(
                "https://ghcr.io/ibm/fast-time-server:0.8.0",
            ),
        ).toBe(false);
    });
});

describe("runtime panel data loading and rendering", () => {
    test("loads backend capabilities and populates selects/tables", async () => {
        addSelect("runtime-deploy-backend");
        addSelect("runtime-compat-backend");
        addSelect("runtime-filter-backend");
        addElement("tbody", "runtime-backends-table-body");
        vi.spyOn(win, "runtimeApiRequest").mockResolvedValue({
            backends: [
                {
                    backend: "docker",
                    supports_compose: true,
                    supports_github_build: true,
                },
                {
                    backend: "ibm_code_engine",
                    supports_compose: false,
                    supports_github_build: true,
                },
            ],
        });

        await win.runtimeLoadBackends();

        expect(doc.getElementById("runtime-deploy-backend").value).toBe(
            "docker",
        );
        expect(
            doc.getElementById("runtime-filter-backend").innerHTML,
        ).toContain("All backends");
        expect(
            doc.getElementById("runtime-backends-table-body").innerHTML,
        ).toContain("ibm_code_engine");
    });

    test("loads guardrails and populates selects/tables", async () => {
        addSelect("runtime-deploy-guardrails-profile");
        addSelect("runtime-compat-profile");
        addElement("tbody", "runtime-guardrails-table-body");
        vi.spyOn(win, "runtimeApiRequest").mockResolvedValue([
            { name: "standard", built_in: true },
            { name: "strict", built_in: false },
        ]);

        await win.runtimeLoadGuardrails();

        expect(
            doc.getElementById("runtime-deploy-guardrails-profile").value,
        ).toBe("standard");
        expect(
            doc.getElementById("runtime-guardrails-table-body").innerHTML,
        ).toContain("strict");
    });

    test("loads runtimes and applies filters", async () => {
        addSelect("runtime-filter-backend", ["", "docker"], "docker");
        addSelect("runtime-filter-status", ["", "running"], "running");
        addElement("tbody", "runtime-runtimes-table-body");
        const runtimeApiSpy = vi
            .spyOn(win, "runtimeApiRequest")
            .mockResolvedValue({
                runtimes: [
                    {
                        id: "runtime-12345678",
                        name: "fast-time",
                        backend: "docker",
                        source_type: "docker",
                        status: "running",
                        approval_status: "approved",
                    },
                ],
            });

        await win.runtimeLoadRuntimes();

        expect(runtimeApiSpy).toHaveBeenCalledWith(
            expect.stringContaining("backend=docker"),
        );
        expect(runtimeApiSpy).toHaveBeenCalledWith(
            expect.stringContaining("status_filter=running"),
        );
        expect(
            doc.getElementById("runtime-runtimes-table-body").innerHTML,
        ).toContain("fast-time");
        expect(
            doc.getElementById("runtime-runtimes-table-body").innerHTML,
        ).toContain('data-runtime-action="start"');
    });

    test("loads approvals with status filtering and pending actions", async () => {
        addSelect(
            "runtime-approval-filter-status",
            ["pending", "all"],
            "pending",
        );
        addElement("tbody", "runtime-approvals-table-body");
        const runtimeApiSpy = vi
            .spyOn(win, "runtimeApiRequest")
            .mockResolvedValue({
                approvals: [
                    {
                        id: "approval-1",
                        runtime_deployment_id: "runtime-1",
                        requested_by: "dev@example.com",
                        status: "pending",
                    },
                    {
                        id: "approval-2",
                        runtime_deployment_id: "runtime-2",
                        requested_by: "dev@example.com",
                        status: "approved",
                    },
                ],
            });

        await win.runtimeLoadApprovals();

        expect(runtimeApiSpy).toHaveBeenCalledWith(
            expect.stringContaining("status_filter=pending"),
        );
        expect(
            doc.getElementById("runtime-approvals-table-body").innerHTML,
        ).toContain('data-approval-action="approve"');
        expect(
            doc.getElementById("runtime-approvals-table-body").innerHTML,
        ).toContain(">n/a<");
    });
});

describe("runtime source and payload building", () => {
    test("toggles source sections by selected source type", () => {
        addSelect(
            "runtime-deploy-source-type",
            ["docker", "github", "compose", "catalog"],
            "github",
        );
        const dockerFields = addElement("div", "runtime-source-docker-fields", {
            className: "hidden",
        });
        const githubFields = addElement("div", "runtime-source-github-fields", {
            className: "hidden",
        });
        const composeFields = addElement(
            "div",
            "runtime-source-compose-fields",
            {
                className: "hidden",
            },
        );
        const catalogFields = addElement(
            "div",
            "runtime-source-catalog-fields",
            {
                className: "hidden",
            },
        );

        win.runtimeHandleSourceTypeChange();

        expect(githubFields.classList.contains("hidden")).toBe(false);
        expect(dockerFields.classList.contains("hidden")).toBe(true);
        expect(composeFields.classList.contains("hidden")).toBe(true);
        expect(catalogFields.classList.contains("hidden")).toBe(true);
    });

    test("builds docker deploy payload", () => {
        addRuntimeDeployElements();
        const payload = win.runtimeBuildDeployPayload();

        expect(payload.name).toBe("runtime-one");
        expect(payload.backend).toBe("docker");
        expect(payload.source).toEqual({
            type: "docker",
            image: "ghcr.io/ibm/fast-time-server:0.8.0",
        });
        expect(payload.environment).toEqual({ TZ: "UTC" });
        expect(payload.metadata).toEqual({ owner: "platform" });
        expect(payload.tags).toEqual(["runtime", "fast-time", "production"]);
        expect(payload.resources).toEqual({
            cpu: "0.5",
            memory: "512m",
            timeout_seconds: 45,
        });
    });

    test("builds github deploy payload with optional registry", () => {
        addRuntimeDeployElements();
        doc.getElementById("runtime-deploy-source-type").value = "github";

        const payload = win.runtimeBuildDeployPayload();

        expect(payload.source.type).toBe("github");
        expect(payload.source.repo).toBe("https://github.com/org/repo");
        expect(payload.source.registry).toBe("ghcr.io/acme");
        expect(payload.source.push_to_registry).toBe(true);
    });

    test("builds compose deploy payload", () => {
        addRuntimeDeployElements();
        doc.getElementById("runtime-deploy-source-type").value = "compose";

        const payload = win.runtimeBuildDeployPayload();

        expect(payload.source).toEqual({
            type: "compose",
            compose_file: "compose.yml",
            main_service: "mcp-server",
        });
    });

    test("builds catalog deploy payload without source object", () => {
        addRuntimeDeployElements();
        doc.getElementById("runtime-deploy-source-type").value = "catalog";

        const payload = win.runtimeBuildDeployPayload();

        expect(payload.catalog_server_id).toBe("fast-time-server");
        expect(payload.source).toBeUndefined();
    });

    test("validates required fields and input errors", () => {
        addRuntimeDeployElements();
        doc.getElementById("runtime-deploy-name").value = "";
        expect(() => win.runtimeBuildDeployPayload()).toThrow(
            "Runtime name is required",
        );

        doc.getElementById("runtime-deploy-name").value = "runtime-one";
        doc.getElementById("runtime-deploy-visibility").value = "team";
        doc.getElementById("runtime-deploy-team-id").value = "";
        expect(() => win.runtimeBuildDeployPayload()).toThrow(
            "Team ID is required when visibility is set to team",
        );

        doc.getElementById("runtime-deploy-visibility").value = "public";
        doc.getElementById("runtime-deploy-timeout").value = "0";
        expect(() => win.runtimeBuildDeployPayload()).toThrow(
            "Timeout must be a positive integer",
        );

        doc.getElementById("runtime-deploy-timeout").value = "30";
        doc.getElementById("runtime-deploy-environment-json").value = "{bad";
        expect(() => win.runtimeBuildDeployPayload()).toThrow();

        doc.getElementById("runtime-deploy-environment-json").value = "{}";
        doc.getElementById("runtime-source-image").value =
            "https://bad/image:1";
        expect(() => win.runtimeBuildDeployPayload()).toThrow(
            "Docker image must be a valid container reference",
        );
    });
});

describe("runtime API helpers and actions", () => {
    test("builds runtime API requests and handles 204", async () => {
        win.ROOT_PATH = "/root";
        const fetchSpy = vi.spyOn(win, "fetchWithTimeout").mockResolvedValue({
            status: 200,
            ok: true,
        });
        const parseSpy = vi
            .spyOn(win, "safeParseJsonResponse")
            .mockResolvedValue({ ok: true });

        await win.runtimeApiRequest("/deploy", {
            method: "POST",
            body: { name: "runtime" },
        });

        expect(fetchSpy).toHaveBeenCalledWith(
            "/root/runtimes/deploy",
            expect.objectContaining({
                method: "POST",
                credentials: "same-origin",
                headers: expect.objectContaining({
                    Accept: "application/json",
                    "Content-Type": "application/json",
                }),
                body: JSON.stringify({ name: "runtime" }),
            }),
        );
        expect(parseSpy).toHaveBeenCalled();

        parseSpy.mockClear();
        fetchSpy.mockResolvedValueOnce({ status: 204, ok: true });
        const result = await win.runtimeApiRequest("/noop");
        expect(result).toBeNull();
        expect(parseSpy).not.toHaveBeenCalled();
    });

    test("checks compatibility and renders result states", async () => {
        addSelect("runtime-compat-profile", ["standard"], "standard");
        addSelect("runtime-compat-backend", ["docker"], "docker");
        addElement("div", "runtime-compat-result");
        const runtimeApiSpy = vi.spyOn(win, "runtimeApiRequest");

        runtimeApiSpy.mockResolvedValueOnce({ compatible: true, warnings: [] });
        await win.runtimeCheckCompatibility();
        expect(doc.getElementById("runtime-compat-result").innerHTML).toContain(
            "Compatible with no warnings",
        );

        runtimeApiSpy.mockResolvedValueOnce({
            compatible: false,
            warnings: [{ field: "network.allowed_hosts", message: "ignored" }],
        });
        await win.runtimeCheckCompatibility();
        expect(doc.getElementById("runtime-compat-result").innerHTML).toContain(
            "Compatibility warnings",
        );
    });

    test("validates runtime logs loading", async () => {
        addElement("pre", "runtime-logs-output");
        const runtimeApiSpy = vi
            .spyOn(win, "runtimeApiRequest")
            .mockResolvedValue({
                logs: ["one", "two"],
            });

        await win.runtimeLoadLogs("runtime-xyz");
        expect(runtimeApiSpy).toHaveBeenCalledWith(
            "/runtime-xyz/logs?tail=200",
        );
        expect(doc.getElementById("runtime-logs-output").textContent).toBe(
            "one\ntwo",
        );

        await expect(win.runtimeLoadLogs("")).rejects.toThrow(
            "Runtime ID is required for logs",
        );
    });

    test("handles runtime action branches", async () => {
        const button = addElement("button", "runtime-action-btn");
        const runtimeApiSpy = vi
            .spyOn(win, "runtimeApiRequest")
            .mockResolvedValue({ message: "done" });
        const loadLogsSpy = vi
            .spyOn(win, "runtimeLoadLogs")
            .mockResolvedValue(undefined);
        const loadRuntimesSpy = vi
            .spyOn(win, "runtimeLoadRuntimes")
            .mockResolvedValue(undefined);
        const setLogsSpy = vi.spyOn(win, "runtimeSetLogs");
        const notifySpy = vi.spyOn(win, "showNotification");
        vi.spyOn(win, "confirm").mockReturnValue(true);

        await win.runtimeExecuteRuntimeAction("runtime-1", "logs");
        expect(loadLogsSpy).toHaveBeenCalledWith("runtime-1");

        await win.runtimeExecuteRuntimeAction("runtime-1", "refresh");
        expect(runtimeApiSpy).toHaveBeenCalledWith("/runtime-1?refresh=true");
        expect(loadRuntimesSpy).toHaveBeenCalled();
        expect(notifySpy).toHaveBeenCalledWith(
            expect.stringContaining("refreshed"),
            "success",
        );

        await win.runtimeExecuteRuntimeAction("runtime-1", "start", button);
        expect(runtimeApiSpy).toHaveBeenCalledWith("/runtime-1/start", {
            method: "POST",
        });
        expect(button.disabled).toBe(false);

        await win.runtimeExecuteRuntimeAction("runtime-1", "delete", button);
        expect(runtimeApiSpy).toHaveBeenCalledWith("/runtime-1", {
            method: "DELETE",
        });
        expect(setLogsSpy).toHaveBeenCalledWith([], "");

        await expect(
            win.runtimeExecuteRuntimeAction("runtime-1", "unsupported"),
        ).rejects.toThrow("Unsupported runtime action: unsupported");
    });

    test("skips delete action when confirmation is canceled", async () => {
        vi.spyOn(win, "confirm").mockReturnValue(false);
        const runtimeApiSpy = vi.spyOn(win, "runtimeApiRequest");
        await win.runtimeExecuteRuntimeAction("runtime-1", "delete");
        expect(runtimeApiSpy).not.toHaveBeenCalled();
    });

    test("handles approval action branches", async () => {
        const button = addElement("button", "runtime-approval-btn");
        const runtimeApiSpy = vi
            .spyOn(win, "runtimeApiRequest")
            .mockResolvedValue({ message: "approved" });
        const loadApprovalsSpy = vi
            .spyOn(win, "runtimeLoadApprovals")
            .mockResolvedValue(undefined);
        const loadRuntimesSpy = vi
            .spyOn(win, "runtimeLoadRuntimes")
            .mockResolvedValue(undefined);
        const notifySpy = vi.spyOn(win, "showNotification");

        vi.spyOn(win, "prompt").mockReturnValue("looks good");
        await win.runtimeExecuteApprovalAction("approval-1", "approve", button);
        expect(runtimeApiSpy).toHaveBeenCalledWith(
            "/approvals/approval-1/approve",
            {
                method: "POST",
                body: { reason: "looks good" },
            },
        );
        expect(loadApprovalsSpy).toHaveBeenCalled();
        expect(loadRuntimesSpy).toHaveBeenCalled();
        expect(notifySpy).toHaveBeenCalledWith("approved", "success");
        expect(button.disabled).toBe(false);

        vi.spyOn(win, "prompt").mockReturnValue(null);
        runtimeApiSpy.mockClear();
        await win.runtimeExecuteApprovalAction("approval-1", "reject", button);
        expect(runtimeApiSpy).not.toHaveBeenCalled();
    });
});

describe("runtime deploy submit, bindings, and panel loading", () => {
    test("submits deploy requests and handles failures", async () => {
        const submitButton = addElement("button", "runtime-deploy-submit");
        addElement("span", "runtime-deploy-message");
        const event = { preventDefault: vi.fn() };
        vi.spyOn(win, "runtimeBuildDeployPayload").mockReturnValue({
            name: "runtime-one",
        });
        vi.spyOn(win, "runtimeApiRequest").mockResolvedValue({
            message: "submitted",
        });
        vi.spyOn(win, "runtimeLoadRuntimes").mockResolvedValue(undefined);
        vi.spyOn(win, "runtimeLoadApprovals").mockResolvedValue(undefined);
        const notifySpy = vi.spyOn(win, "showNotification");

        await win.runtimeHandleDeploySubmit(event);
        expect(event.preventDefault).toHaveBeenCalled();
        expect(submitButton.disabled).toBe(false);
        expect(doc.getElementById("runtime-deploy-message").textContent).toBe(
            "submitted",
        );
        expect(notifySpy).toHaveBeenCalledWith("submitted", "success");

        vi.spyOn(win, "runtimeBuildDeployPayload").mockImplementation(() => {
            throw new Error("invalid payload");
        });
        await win.runtimeHandleDeploySubmit(event);
        expect(doc.getElementById("runtime-deploy-message").textContent).toBe(
            "invalid payload",
        );
        expect(notifySpy).toHaveBeenCalledWith(
            "Runtime deploy failed: invalid payload",
            "error",
        );
    });

    test("binds runtime panel events once and dispatches handlers", async () => {
        addElement("div", "runtime-panel");
        addSelect(
            "runtime-deploy-source-type",
            ["docker", "github", "compose", "catalog"],
            "docker",
        );
        const deployForm = addElement("form", "runtime-deploy-form");
        addElement("button", "runtime-deploy-submit");
        addElement("button", "runtime-deploy-reset");
        addElement("button", "runtime-refresh-all-btn");
        addElement("button", "runtime-refresh-runtimes-btn");
        addElement("button", "runtime-refresh-approvals-btn");
        addElement("tbody", "runtime-runtimes-table-body");
        addElement("tbody", "runtime-approvals-table-body");
        addSelect("runtime-filter-backend", ["", "docker"], "");
        addSelect("runtime-filter-status", ["", "running"], "");
        addSelect(
            "runtime-approval-filter-status",
            ["pending", "all"],
            "pending",
        );
        addElement("button", "runtime-compat-check-btn");
        addElement("button", "runtime-clear-logs-btn");
        addElement("pre", "runtime-logs-output", { textContent: "log data" });
        addElement("span", "runtime-deploy-message", { textContent: "old" });

        const sourceChangeSpy = vi
            .spyOn(win, "runtimeHandleSourceTypeChange")
            .mockImplementation(() => {});
        const deploySubmitSpy = vi
            .spyOn(win, "runtimeHandleDeploySubmit")
            .mockResolvedValue(undefined);
        const refreshAllSpy = vi
            .spyOn(win, "runtimeRefreshAll")
            .mockResolvedValue(undefined);
        const refreshRuntimesSpy = vi
            .spyOn(win, "runtimeLoadRuntimes")
            .mockResolvedValue(undefined);
        const refreshApprovalsSpy = vi
            .spyOn(win, "runtimeLoadApprovals")
            .mockResolvedValue(undefined);
        const runtimeActionSpy = vi
            .spyOn(win, "runtimeExecuteRuntimeAction")
            .mockResolvedValue(undefined);
        const approvalActionSpy = vi
            .spyOn(win, "runtimeExecuteApprovalAction")
            .mockResolvedValue(undefined);
        const compatibilitySpy = vi
            .spyOn(win, "runtimeCheckCompatibility")
            .mockResolvedValue(undefined);
        const setLogsSpy = vi.spyOn(win, "runtimeSetLogs");

        win.bindRuntimePanelEventHandlers();
        win.bindRuntimePanelEventHandlers();

        doc.getElementById("runtime-deploy-source-type").dispatchEvent(
            new win.Event("change", { bubbles: true }),
        );
        expect(sourceChangeSpy).toHaveBeenCalled();

        deployForm.dispatchEvent(
            new win.Event("submit", { bubbles: true, cancelable: true }),
        );
        await nextTick();
        expect(deploySubmitSpy).toHaveBeenCalled();

        doc.getElementById("runtime-deploy-reset").click();
        expect(sourceChangeSpy).toHaveBeenCalledTimes(2);
        expect(doc.getElementById("runtime-deploy-message").textContent).toBe(
            "",
        );

        doc.getElementById("runtime-refresh-all-btn").click();
        await nextTick();
        expect(refreshAllSpy).toHaveBeenCalledTimes(1);

        doc.getElementById("runtime-refresh-runtimes-btn").click();
        doc.getElementById("runtime-filter-backend").dispatchEvent(
            new win.Event("change"),
        );
        doc.getElementById("runtime-filter-status").dispatchEvent(
            new win.Event("change"),
        );
        await nextTick();
        expect(refreshRuntimesSpy).toHaveBeenCalled();

        doc.getElementById("runtime-refresh-approvals-btn").click();
        doc.getElementById("runtime-approval-filter-status").dispatchEvent(
            new win.Event("change"),
        );
        await nextTick();
        expect(refreshApprovalsSpy).toHaveBeenCalled();

        doc.getElementById("runtime-runtimes-table-body").innerHTML =
            '<tr><td><button data-runtime-action="start" data-runtime-id="runtime-1"></button></td></tr>';
        doc.getElementById("runtime-runtimes-table-body")
            .querySelector("button")
            .dispatchEvent(new win.Event("click", { bubbles: true }));
        await nextTick();
        const runtimeActionArgs = runtimeActionSpy.mock.calls.at(-1);
        expect(runtimeActionArgs[0]).toBe("runtime-1");
        expect(runtimeActionArgs[1]).toBe("start");
        expect(runtimeActionArgs[2].dataset.runtimeId).toBe("runtime-1");

        doc.getElementById("runtime-approvals-table-body").innerHTML =
            '<tr><td><button data-approval-action="approve" data-approval-id="approval-1"></button></td></tr>';
        doc.getElementById("runtime-approvals-table-body")
            .querySelector("button")
            .dispatchEvent(new win.Event("click", { bubbles: true }));
        await nextTick();
        const approvalActionArgs = approvalActionSpy.mock.calls.at(-1);
        expect(approvalActionArgs[0]).toBe("approval-1");
        expect(approvalActionArgs[1]).toBe("approve");
        expect(approvalActionArgs[2].dataset.approvalId).toBe("approval-1");

        doc.getElementById("runtime-compat-check-btn").click();
        await nextTick();
        expect(compatibilitySpy).toHaveBeenCalled();

        doc.getElementById("runtime-clear-logs-btn").click();
        expect(setLogsSpy).toHaveBeenCalledWith([], "");
    });

    test("loads runtime panel for success, cached mode, and errors", async () => {
        const panel = addElement("div", "runtime-panel");
        const initializeSpy = vi
            .spyOn(win, "initializeRuntimePanel")
            .mockResolvedValue(undefined);
        const fetchSpy = vi.spyOn(win, "fetchWithTimeout");
        const notifySpy = vi.spyOn(win, "showNotification");
        win.ROOT_PATH = "/root";

        fetchSpy.mockResolvedValueOnce({
            ok: true,
            status: 200,
            statusText: "OK",
            text: vi
                .fn()
                .mockResolvedValue('<form id="runtime-deploy-form"></form>'),
        });
        await win.loadRuntimePanel();
        expect(fetchSpy).toHaveBeenCalledWith(
            "/root/admin/runtime/partial",
            expect.any(Object),
            1,
        );
        expect(panel.dataset.loaded).toBe("true");
        expect(initializeSpy).toHaveBeenCalled();

        panel.dataset.loaded = "true";
        panel.innerHTML = "<div>already loaded</div>";
        fetchSpy.mockClear();
        initializeSpy.mockClear();
        await win.loadRuntimePanel();
        expect(fetchSpy).not.toHaveBeenCalled();
        expect(initializeSpy).toHaveBeenCalledTimes(1);

        initializeSpy.mockRejectedValueOnce(new Error("refresh failed"));
        await win.loadRuntimePanel();
        expect(notifySpy).toHaveBeenCalledWith(
            "Failed to refresh runtime data: refresh failed",
            "error",
        );

        panel.dataset.loaded = "";
        panel.innerHTML = "";
        fetchSpy.mockResolvedValueOnce({
            ok: false,
            status: 403,
            statusText: "Forbidden",
            text: vi.fn().mockResolvedValue(""),
        });
        await win.loadRuntimePanel(true);
        expect(panel.innerHTML).toContain(
            "Platform administrator access required",
        );

        fetchSpy.mockResolvedValueOnce({
            ok: false,
            status: 404,
            statusText: "Not Found",
            text: vi.fn().mockResolvedValue(""),
        });
        await win.loadRuntimePanel(true);
        expect(panel.innerHTML).toContain("Runtime feature is disabled");
    });
});
