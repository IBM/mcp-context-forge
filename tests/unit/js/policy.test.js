/**
 * Unit tests for policy.js module
 * Tests: openAddRuleModal, closeAddRuleModal, splitTrim, submitAddRule,
 *        deleteRule, runPolicyTest, reloadPolicyPartial
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  openAddRuleModal,
  closeAddRuleModal,
  splitTrim,
  submitAddRule,
  deleteRule,
  runPolicyTest,
  reloadPolicyPartial,
} from "../../../mcpgateway/admin_ui/policy.js";

vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

function buildDOM() {
  document.body.innerHTML = `
    <div id="add-rule-modal" class="hidden"></div>
    <span id="rule-error" class="hidden"></span>
    <input id="rule-id" value="" />
    <input id="rule-roles" value="" />
    <input id="rule-actions" value="" />
    <input id="rule-resource-types" value="" />
    <input id="rule-resource-ids" value="" />
    <input id="rule-reason" value="" />
    <div id="policy-panel"></div>
    <input id="test-email" value="" />
    <input id="test-roles" value="" />
    <input id="test-action" value="" />
    <input id="test-resource-type" value="" />
    <input id="test-resource-id" value="" />
    <input id="test-ip" value="" />
    <div id="policy-test-result" class="hidden"></div>
    <div id="policy-test-verdict"></div>
    <div id="policy-test-reason"></div>
    <div id="policy-test-policies"></div>
    <div id="policy-test-timing"></div>
  `;
}

beforeEach(() => {
  buildDOM();
  window.ROOT_PATH = "";
  global.alert = vi.fn();
  global.confirm = vi.fn(() => true);
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(""),
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  delete window.ROOT_PATH;
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// splitTrim
// ---------------------------------------------------------------------------
describe("splitTrim", () => {
  test("splits on comma and trims whitespace", () => {
    expect(splitTrim("admin, viewer, developer")).toEqual(["admin", "viewer", "developer"]);
  });

  test("filters out empty segments", () => {
    expect(splitTrim("admin,,viewer")).toEqual(["admin", "viewer"]);
  });

  test("trims leading and trailing whitespace from each segment", () => {
    expect(splitTrim("  admin  ,  viewer  ")).toEqual(["admin", "viewer"]);
  });

  test("returns empty array for blank string", () => {
    expect(splitTrim("")).toEqual([]);
  });

  test("handles single value without comma", () => {
    expect(splitTrim("admin")).toEqual(["admin"]);
  });
});

// ---------------------------------------------------------------------------
// openAddRuleModal
// ---------------------------------------------------------------------------
describe("openAddRuleModal", () => {
  test("removes hidden class from the modal", () => {
    openAddRuleModal();
    expect(document.getElementById("add-rule-modal").classList.contains("hidden")).toBe(false);
  });

  test("hides the rule-error element", () => {
    document.getElementById("rule-error").classList.remove("hidden");
    openAddRuleModal();
    expect(document.getElementById("rule-error").classList.contains("hidden")).toBe(true);
  });

  test("clears all rule form fields", () => {
    document.getElementById("rule-id").value = "existing-id";
    document.getElementById("rule-roles").value = "admin";
    document.getElementById("rule-actions").value = "read";
    document.getElementById("rule-resource-types").value = "tool";
    document.getElementById("rule-resource-ids").value = "tool-1";
    document.getElementById("rule-reason").value = "some reason";

    openAddRuleModal();

    for (const id of ["rule-id", "rule-roles", "rule-actions", "rule-resource-types", "rule-resource-ids", "rule-reason"]) {
      expect(document.getElementById(id).value).toBe("");
    }
  });
});

// ---------------------------------------------------------------------------
// closeAddRuleModal
// ---------------------------------------------------------------------------
describe("closeAddRuleModal", () => {
  test("adds hidden class to the modal", () => {
    document.getElementById("add-rule-modal").classList.remove("hidden");
    closeAddRuleModal();
    expect(document.getElementById("add-rule-modal").classList.contains("hidden")).toBe(true);
  });

  test("is idempotent when modal is already hidden", () => {
    closeAddRuleModal();
    expect(document.getElementById("add-rule-modal").classList.contains("hidden")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// submitAddRule — validation
// ---------------------------------------------------------------------------
describe("submitAddRule — validation", () => {
  test("shows error and does not call fetch when rule-id is empty", async () => {
    document.getElementById("rule-id").value = "";
    await submitAddRule();
    const errEl = document.getElementById("rule-error");
    expect(errEl.classList.contains("hidden")).toBe(false);
    expect(errEl.textContent).toBe("Rule ID is required.");
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// submitAddRule — successful submit
// ---------------------------------------------------------------------------
describe("submitAddRule — successful submit", () => {
  test("calls POST /admin/policy/rules with correct payload", async () => {
    document.getElementById("rule-id").value = "rule-1";
    document.getElementById("rule-roles").value = "admin, viewer";
    document.getElementById("rule-actions").value = "read";
    document.getElementById("rule-resource-types").value = "tool";
    document.getElementById("rule-resource-ids").value = "tool-1";
    document.getElementById("rule-reason").value = "test reason";

    await submitAddRule();

    expect(global.fetch).toHaveBeenCalled();
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/admin/policy/rules");
    expect(opts.method).toBe("POST");
    const body = JSON.parse(opts.body);
    expect(body.id).toBe("rule-1");
    expect(body.roles).toEqual(["admin", "viewer"]);
    expect(body.actions).toEqual(["read"]);
    expect(body.resource_types).toEqual(["tool"]);
    expect(body.resource_ids).toEqual(["tool-1"]);
    expect(body.reason).toBe("test reason");
    expect(body.conditions).toEqual({});
  });

  test("sends empty array for roles/actions/resource_types/resource_ids when fields are blank", async () => {
    document.getElementById("rule-id").value = "rule-defaults";

    await submitAddRule();

    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.roles).toEqual([]);
    expect(body.actions).toEqual([]);
    expect(body.resource_types).toEqual([]);
    expect(body.resource_ids).toEqual([]);
  });

  test("uses ROOT_PATH prefix in fetch URL", async () => {
    window.ROOT_PATH = "/prefix";
    document.getElementById("rule-id").value = "rule-2";

    await submitAddRule();

    expect(global.fetch.mock.calls[0][0]).toBe("/prefix/admin/policy/rules");
  });

  test("includes same-origin credentials in the request", async () => {
    document.getElementById("rule-id").value = "rule-3";

    await submitAddRule();

    expect(global.fetch.mock.calls[0][1].credentials).toBe("same-origin");
  });

  test("closes the modal after success", async () => {
    document.getElementById("add-rule-modal").classList.remove("hidden");
    document.getElementById("rule-id").value = "rule-4";

    await submitAddRule();

    expect(document.getElementById("add-rule-modal").classList.contains("hidden")).toBe(true);
  });

  test("reloads the policy panel after success", async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ text: () => Promise.resolve("<p>updated</p>") });
    document.getElementById("rule-id").value = "rule-5";

    await submitAddRule();
    await vi.waitFor(() =>
      expect(document.getElementById("policy-panel").innerHTML).toBe("<p>updated</p>")
    );
  });
});

// ---------------------------------------------------------------------------
// submitAddRule — error handling
// ---------------------------------------------------------------------------
describe("submitAddRule — error handling", () => {
  test("shows detail from response body when not ok", async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "Permission denied" }),
    });
    document.getElementById("rule-id").value = "rule-err";

    await submitAddRule();

    const errEl = document.getElementById("rule-error");
    expect(errEl.classList.contains("hidden")).toBe(false);
    expect(errEl.textContent).toBe("Permission denied");
  });

  test("falls back to statusText when detail is absent", async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
      statusText: "Internal Server Error",
    });
    document.getElementById("rule-id").value = "rule-err2";

    await submitAddRule();

    expect(document.getElementById("rule-error").textContent).toBe("Internal Server Error");
  });

  test("shows network error in error element", async () => {
    global.fetch.mockRejectedValue(new Error("Network failure"));
    document.getElementById("rule-id").value = "rule-net";

    await submitAddRule();

    const errEl = document.getElementById("rule-error");
    expect(errEl.classList.contains("hidden")).toBe(false);
    expect(errEl.textContent).toBe("Network failure");
  });
});

// ---------------------------------------------------------------------------
// deleteRule
// ---------------------------------------------------------------------------
describe("deleteRule — confirm cancelled", () => {
  test("does not call fetch when confirm returns false", async () => {
    global.confirm.mockReturnValue(false);
    await deleteRule("rule-abc");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("prompts with the rule id in the confirm message", async () => {
    global.confirm.mockReturnValue(false);
    await deleteRule("my-rule");
    expect(global.confirm).toHaveBeenCalledWith(expect.stringContaining("my-rule"));
  });
});

describe("deleteRule — successful deletion", () => {
  test("calls DELETE with the correct URL-encoded rule id", async () => {
    await deleteRule("rule/abc");
    expect(global.fetch).toHaveBeenCalled();
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe("/admin/policy/rules/rule%2Fabc");
    expect(opts.method).toBe("DELETE");
  });

  test("uses ROOT_PATH in the delete URL", async () => {
    window.ROOT_PATH = "/app";
    await deleteRule("r1");
    expect(global.fetch.mock.calls[0][0]).toBe("/app/admin/policy/rules/r1");
  });

  test("includes same-origin credentials", async () => {
    await deleteRule("r2");
    expect(global.fetch.mock.calls[0][1].credentials).toBe("same-origin");
  });

  test("reloads the policy panel after successful delete", async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ text: () => Promise.resolve("<p>reloaded</p>") });
    await deleteRule("r3");
    await vi.waitFor(() =>
      expect(document.getElementById("policy-panel").innerHTML).toBe("<p>reloaded</p>")
    );
  });
});

describe("deleteRule — error handling", () => {
  test("shows alert when delete response is not ok", async () => {
    global.fetch.mockResolvedValue({ ok: false });
    await deleteRule("rule-fail");
    expect(global.alert).toHaveBeenCalledWith(expect.stringContaining("Failed to delete rule"));
  });

  test("shows alert on network error", async () => {
    global.fetch.mockRejectedValue(new Error("Network error"));
    await deleteRule("rule-net");
    expect(global.alert).toHaveBeenCalledWith(expect.stringContaining("Network error"));
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — validation
// ---------------------------------------------------------------------------
describe("runPolicyTest — validation", () => {
  test("alerts and returns early when all required fields are empty", async () => {
    await runPolicyTest();
    expect(global.alert).toHaveBeenCalledWith(
      expect.stringContaining("Email, Action, Resource Type and Resource ID")
    );
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("alerts when email is missing", async () => {
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";
    await runPolicyTest();
    expect(global.alert).toHaveBeenCalled();
  });

  test("alerts when action is missing", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";
    await runPolicyTest();
    expect(global.alert).toHaveBeenCalled();
  });

  test("alerts when resource-type is missing", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-id").value = "tool-1";
    await runPolicyTest();
    expect(global.alert).toHaveBeenCalled();
  });

  test("alerts when resource-id is missing", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    await runPolicyTest();
    expect(global.alert).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — allow decision
// ---------------------------------------------------------------------------
describe("runPolicyTest — allow decision", () => {
  beforeEach(() => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          decision: "allow",
          reason: "User has required role",
          matching_policies: ["policy-1", "policy-2"],
          duration_ms: 5,
          cached: false,
        }),
    });
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";
  });

  test("unhides result panel and applies green styling", async () => {
    await runPolicyTest();
    const resultEl = document.getElementById("policy-test-result");
    expect(resultEl.classList.contains("hidden")).toBe(false);
    expect(resultEl.classList.contains("bg-green-50")).toBe(true);
    expect(resultEl.classList.contains("border-green-200")).toBe(true);
  });

  test("shows ALLOWED verdict", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-verdict").innerHTML).toContain("ALLOWED");
  });

  test("displays the reason text", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-reason").textContent).toBe("User has required role");
  });

  test("lists matching policies", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-policies").textContent).toContain("policy-1");
    expect(document.getElementById("policy-test-policies").textContent).toContain("policy-2");
  });

  test("shows timing without cached indicator", async () => {
    await runPolicyTest();
    const timing = document.getElementById("policy-test-timing").textContent;
    expect(timing).toContain("5ms");
    expect(timing).not.toContain("cached");
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — deny decision
// ---------------------------------------------------------------------------
describe("runPolicyTest — deny decision", () => {
  beforeEach(() => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          decision: "deny",
          reason: "Insufficient permissions",
          matching_policies: [],
          duration_ms: 3,
          cached: true,
        }),
    });
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "write";
    document.getElementById("test-resource-type").value = "server";
    document.getElementById("test-resource-id").value = "server-1";
  });

  test("applies red styling to result panel", async () => {
    await runPolicyTest();
    const resultEl = document.getElementById("policy-test-result");
    expect(resultEl.classList.contains("bg-red-50")).toBe(true);
    expect(resultEl.classList.contains("border-red-200")).toBe(true);
  });

  test("shows DENIED verdict", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-verdict").innerHTML).toContain("DENIED");
  });

  test("shows no-matching-policies message", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-policies").textContent).toContain("No matching policies");
  });

  test("shows timing with cached indicator", async () => {
    await runPolicyTest();
    expect(document.getElementById("policy-test-timing").textContent).toContain("(cached)");
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — clears previous styling on re-run
// ---------------------------------------------------------------------------
describe("runPolicyTest — clears previous styling", () => {
  test("removes both green and red classes before applying new result", async () => {
    const resultEl = document.getElementById("policy-test-result");
    resultEl.classList.add("bg-green-50", "border-green-200");
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ decision: "deny", matching_policies: [], duration_ms: 1 }),
    });
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";

    await runPolicyTest();

    expect(resultEl.classList.contains("bg-green-50")).toBe(false);
    expect(resultEl.classList.contains("border-green-200")).toBe(false);
    expect(resultEl.classList.contains("bg-red-50")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — request payload
// ---------------------------------------------------------------------------
describe("runPolicyTest — request payload", () => {
  beforeEach(() => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ decision: "allow", matching_policies: [], duration_ms: 1 }),
    });
  });

  test("defaults ip to 127.0.0.1 when field is empty", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";
    document.getElementById("test-ip").value = "";

    await runPolicyTest();

    expect(JSON.parse(global.fetch.mock.calls[0][1].body).ip).toBe("127.0.0.1");
  });

  test("uses provided ip when set", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";
    document.getElementById("test-ip").value = "10.0.0.1";

    await runPolicyTest();

    expect(JSON.parse(global.fetch.mock.calls[0][1].body).ip).toBe("10.0.0.1");
  });

  test("sends subject_roles as a parsed array", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-roles").value = "admin, viewer";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";

    await runPolicyTest();

    expect(JSON.parse(global.fetch.mock.calls[0][1].body).subject_roles).toEqual(["admin", "viewer"]);
  });

  test("sends empty subject_roles array when roles field is blank", async () => {
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";

    await runPolicyTest();

    expect(JSON.parse(global.fetch.mock.calls[0][1].body).subject_roles).toEqual([]);
  });

  test("uses ROOT_PATH in the test URL", async () => {
    window.ROOT_PATH = "/myapp";
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";

    await runPolicyTest();

    expect(global.fetch.mock.calls[0][0]).toBe("/myapp/admin/policy/test");
  });
});

// ---------------------------------------------------------------------------
// runPolicyTest — error handling
// ---------------------------------------------------------------------------
describe("runPolicyTest — error handling", () => {
  test("shows alert on fetch error", async () => {
    global.fetch.mockRejectedValue(new Error("Network error"));
    document.getElementById("test-email").value = "user@example.com";
    document.getElementById("test-action").value = "read";
    document.getElementById("test-resource-type").value = "tool";
    document.getElementById("test-resource-id").value = "tool-1";

    await runPolicyTest();

    expect(global.alert).toHaveBeenCalledWith(expect.stringContaining("Network error"));
  });
});

// ---------------------------------------------------------------------------
// reloadPolicyPartial
// ---------------------------------------------------------------------------
describe("reloadPolicyPartial", () => {
  test("fetches partial HTML and injects it into policy-panel", async () => {
    global.fetch.mockResolvedValue({ text: () => Promise.resolve("<p>new content</p>") });

    reloadPolicyPartial();

    await vi.waitFor(() =>
      expect(document.getElementById("policy-panel").innerHTML).toBe("<p>new content</p>")
    );
  });

  test("calls the correct partial URL", async () => {
    global.fetch.mockResolvedValue({ text: () => Promise.resolve("") });

    reloadPolicyPartial();

    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(global.fetch.mock.calls[0][0]).toBe("/admin/policy/partial");
  });

  test("uses ROOT_PATH in the partial URL", async () => {
    window.ROOT_PATH = "/root";
    global.fetch.mockResolvedValue({ text: () => Promise.resolve("") });

    reloadPolicyPartial();

    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(global.fetch.mock.calls[0][0]).toBe("/root/admin/policy/partial");
  });

  test("sends same-origin credentials and Accept: text/html header", async () => {
    global.fetch.mockResolvedValue({ text: () => Promise.resolve("") });

    reloadPolicyPartial();

    await vi.waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const opts = global.fetch.mock.calls[0][1];
    expect(opts.credentials).toBe("same-origin");
    expect(opts.headers?.Accept).toBe("text/html");
  });

  test("does nothing when policy-panel element is absent", () => {
    document.getElementById("policy-panel").remove();
    reloadPolicyPartial();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
