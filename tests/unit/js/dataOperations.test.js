/**
 * Unit tests for dataOperations.js grpc Tool Sync Preview wiring
 * Tests: initializeDataOperations -> setupGrpcOperations, the schema-upload
 *        handler that stores a candidate artifact id, and the preview
 *        toggle/close/render flow that calls the preview endpoint.
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import { initializeDataOperations } from "../../../mcpgateway/admin_ui/dataOperations.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  getCookie: vi.fn(() => "test-csrf"),
}));

const html = (serviceId, candidateId) => `
  <form class="grpc-schema-upload" data-service-id="${serviceId}">
    <input type="file" name="artifact" />
    <label><input type="checkbox" name="activate" checked /> Activate</label>
    <button type="submit">Import Schema</button>
  </form>
  <div class="grpc-sync-preview" data-service-id="${serviceId}"${
    candidateId ? ` data-candidate-id="${candidateId}"` : ""
  }>
    <button type="button" class="grpc-sync-preview-toggle">Preview Tool Sync</button>
    <div class="grpc-sync-preview-panel hidden">
      <button type="button" class="grpc-sync-preview-close">✕</button>
      <div class="grpc-sync-preview-body">Loading…</div>
    </div>
  </div>
`;

const setup = ({ candidateId } = {}) => {
  window.ROOT_PATH = "";
  document.body.innerHTML = html("svc-1", candidateId);
  initializeDataOperations();
};

const lineageHtml = () => `
  <select id="grpc-lineage-service"><option value="svc-1" selected>Demo</option></select>
  <input id="grpc-lineage-search" />
  <input id="grpc-lineage-include-unbound" type="checkbox" checked />
  <button id="grpc-lineage-refresh" type="button">Refresh</button>
  <div id="grpc-lineage-summary"></div>
  <div id="grpc-lineage-list"></div>
  <div id="grpc-lineage-semantics"></div>
`;

const mockFetchJson = (payload, status = 200) => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(payload),
  });
};

beforeEach(() => {
  global.fetch = undefined;
  window.ROOT_PATH = "";
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
});

describe("grpc schema upload handler", () => {
  test("forwards activate=false explicitly and stores the candidate id", async () => {
    setup();
    const form = document.querySelector(".grpc-schema-upload");
    const activate = form.querySelector('input[name="activate"]');
    activate.checked = false;
    mockFetchJson({ id: "art-1", version: 3, is_active: false });

    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/admin/grpc/svc-1/schemas/import");
    const fd = opts.body;
    expect(fd.get("activate")).toBe("false");

    const box = document.querySelector(".grpc-sync-preview");
    await vi.waitFor(() => expect(box.dataset.candidateId).toBe("art-1"));
    const toggle = box.querySelector(".grpc-sync-preview-toggle");
    expect(toggle.classList.contains("hidden")).toBe(false);
  });

  test("reloads the page after an activating import", async () => {
    setup();
    mockFetchJson({ id: "art-1", version: 2, is_active: true });
    const reload = vi
      .spyOn(window, "setTimeout")
      .mockImplementation((fn) => {
        fn();
        return 1;
      });

    document
      .querySelector(".grpc-schema-upload")
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(reload).toHaveBeenCalled());

    reload.mockRestore();
  });
});

describe("grpc Tool Sync Preview rendering", () => {
  test("toggle reveals the panel and renders the four lists", async () => {
    setup({ candidateId: "art-1" });
    const box = document.querySelector(".grpc-sync-preview");
    const panel = box.querySelector(".grpc-sync-preview-panel");
    const body = box.querySelector(".grpc-sync-preview-body");
    mockFetchJson({
      service_id: "svc-1",
      candidate_artifact_id: "art-1",
      added_tools: ["testpkg.TestService.CreateItem"],
      modified_tools: ["testpkg.TestService.GetItem"],
      disabled_tools: ["testpkg.TestService.OldMethod"],
      methods_needing_reapproval: ["testpkg.TestService.Update"],
      warning: null,
    });

    box.querySelector(".grpc-sync-preview-toggle").click();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));

    expect(global.fetch.mock.calls[0][0]).toBe(
      "/admin/grpc/svc-1/schemas/art-1/preview"
    );
    expect(panel.classList.contains("hidden")).toBe(false);
    await vi.waitFor(() =>
      expect(body.textContent).toContain("testpkg.TestService.CreateItem")
    );
    expect(body.textContent).toContain("testpkg.TestService.OldMethod");
    expect(body.textContent).toContain("testpkg.TestService.Update");
  });

  test("close button hides the panel", async () => {
    setup({ candidateId: "art-1" });
    const box = document.querySelector(".grpc-sync-preview");
    const panel = box.querySelector(".grpc-sync-preview-panel");
    mockFetchJson({
      service_id: "svc-1",
      candidate_artifact_id: "art-1",
      added_tools: [],
      modified_tools: [],
      disabled_tools: [],
      methods_needing_reapproval: [],
      warning: null,
    });

    box.querySelector(".grpc-sync-preview-toggle").click();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    box.querySelector(".grpc-sync-preview-close").click();
    expect(panel.classList.contains("hidden")).toBe(true);
  });

  test("renders the empty-candidate warning", async () => {
    setup({ candidateId: "art-1" });
    mockFetchJson({
      service_id: "svc-1",
      candidate_artifact_id: "art-1",
      added_tools: [],
      modified_tools: [],
      disabled_tools: [],
      methods_needing_reapproval: [],
      warning: "Candidate schema defines no methods; activating it would disable 3 existing tools.",
    });

    document.querySelector(".grpc-sync-preview-toggle").click();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const body = document.querySelector(".grpc-sync-preview-body");
    await vi.waitFor(() => expect(body.textContent).toContain("would disable 3 existing tools"));
  });

  test("shows an error when the preview request fails", async () => {
    setup({ candidateId: "art-1" });
    mockFetchJson({ detail: "Schema artifact not found for this service" }, 404);

    document.querySelector(".grpc-sync-preview-toggle").click();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    await vi.waitFor(() =>
      expect(
        document.querySelector(".grpc-sync-preview-body").textContent
      ).toContain("Preview failed")
    );
  });
});

describe("gRPC API to data lineage rendering", () => {
  test("renders a left-to-right path and applies the method filter", async () => {
    document.body.innerHTML = lineageHtml();
    mockFetchJson({
      paths: [
        {
          id: "path-1",
          method_name: "demo.Greeter.SayHello",
          has_mcp_exposure: true,
          has_data_binding: true,
          stages: [
            { kind: "grpc_service", label: "Greeter", detail: "localhost:50051", state: "active", attributes: {} },
            { kind: "grpc_method", label: "demo.Greeter.SayHello", detail: "Request → Reply", state: "active", attributes: {} },
            { kind: "mcp_tool", label: "Say Hello", detail: "demo.Greeter.SayHello", state: "active", attributes: {} },
            { kind: "mcp_server", label: "Demo MCP", detail: "/servers/server-1/mcp", state: "active", attributes: {} },
            { kind: "data_binding", label: "read (manual)", detail: "Catalog/impact relationship", state: "active", attributes: {} },
            { kind: "sql_source", label: "Customer DB", detail: "postgresql", state: "active", attributes: {} },
            { kind: "sql_table", label: "public.customers", detail: "table", state: "active", attributes: {} },
          ],
        },
      ],
      summary: {
        service_count: 1,
        method_count: 1,
        tool_count: 1,
        mcp_exposed_tool_count: 1,
        data_bound_tool_count: 1,
        path_count: 1,
      },
      truncated: false,
      relationship_semantics: "Catalog relationship only.",
    });

    initializeDataOperations();
    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(global.fetch.mock.calls[0][0]).toBe(
      "/admin/grpc/lineage?service_id=svc-1&include_unbound=true"
    );
    await vi.waitFor(() =>
      expect(document.querySelector("#grpc-lineage-list").textContent).toContain(
        "public.customers"
      )
    );
    expect(document.querySelectorAll("[data-kind]")).toHaveLength(7);
    expect(document.querySelector("#grpc-lineage-summary").textContent).toContain(
      "1 shown / 1 paths"
    );

    const filter = document.querySelector("#grpc-lineage-search");
    filter.value = "not-present";
    filter.dispatchEvent(new Event("input", { bubbles: true }));
    expect(document.querySelector("#grpc-lineage-list").textContent).toContain(
      "No lineage paths match"
    );
  });
});
