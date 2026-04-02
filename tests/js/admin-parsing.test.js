/**
 * Unit tests for admin.js parsing and data extraction functions.
 */

import { describe, test, expect } from "vitest";
import { parseUriTemplate } from "../../mcpgateway/admin_ui/utils.js";
import { parseThinkTags } from "../../mcpgateway/admin_ui/llmChat.js";
import { orderCertificateChain, parseCertificateInfo } from "../../mcpgateway/admin_ui/caCertificate.js";
import { extractTeamId } from "../../mcpgateway/admin_ui/teams.js";
import { extractApiError } from "../../mcpgateway/admin_ui/security.js";
import { extractKPIData } from "../../mcpgateway/admin_ui/metrics.js";


// ---------------------------------------------------------------------------
// parseUriTemplate
// ---------------------------------------------------------------------------
describe("parseUriTemplate", () => {
  test("extracts single template variable", () => {
    expect(parseUriTemplate("/users/{id}")).toEqual(["id"]);
  });

  test("extracts multiple template variables", () => {
    expect(parseUriTemplate("/users/{userId}/posts/{postId}")).toEqual(["userId", "postId"]);
  });

  test("returns empty array when no variables", () => {
    expect(parseUriTemplate("/users/list")).toEqual([]);
  });

  test("returns empty array for empty string", () => {
    expect(parseUriTemplate("")).toEqual([]);
  });

  test("handles adjacent variables", () => {
    expect(parseUriTemplate("{a}{b}")).toEqual(["a", "b"]);
  });

  test("handles variable with underscores", () => {
    expect(parseUriTemplate("/api/{user_name}")).toEqual(["user_name"]);
  });
});

// ---------------------------------------------------------------------------
// parseThinkTags
// ---------------------------------------------------------------------------
describe("parseThinkTags", () => {
  test("parses single think block", () => {
    const result = parseThinkTags("<think>reasoning here</think>The answer");
    expect(result.thinkingSteps).toHaveLength(1);
    expect(result.thinkingSteps[0].content).toBe("reasoning here");
    expect(result.finalAnswer).toBe("The answer");
  });

  test("parses multiple think blocks", () => {
    const input =
      "<think>step 1</think>middle<think>step 2</think>final answer";
    const result = parseThinkTags(input);
    expect(result.thinkingSteps).toHaveLength(2);
    expect(result.thinkingSteps[0].content).toBe("step 1");
    expect(result.thinkingSteps[1].content).toBe("step 2");
    expect(result.finalAnswer).toBe("middlefinal answer");
  });

  test("returns empty thinkingSteps when no think tags", () => {
    const result = parseThinkTags("just a normal response");
    expect(result.thinkingSteps).toHaveLength(0);
    expect(result.finalAnswer).toBe("just a normal response");
  });

  test("preserves rawContent", () => {
    const input = "<think>thought</think>answer";
    const result = parseThinkTags(input);
    expect(result.rawContent).toBe(input);
  });

  test("skips empty think blocks", () => {
    const result = parseThinkTags("<think></think>answer");
    expect(result.thinkingSteps).toHaveLength(0);
    expect(result.finalAnswer).toBe("answer");
  });

  test("skips whitespace-only think blocks", () => {
    const result = parseThinkTags("<think>   \n  </think>answer");
    expect(result.thinkingSteps).toHaveLength(0);
  });

  test("handles multiline think content", () => {
    const input = "<think>line1\nline2\nline3</think>answer";
    const result = parseThinkTags(input);
    expect(result.thinkingSteps[0].content).toContain("line1");
    expect(result.thinkingSteps[0].content).toContain("line3");
  });

  test("trims final answer whitespace", () => {
    const result = parseThinkTags("<think>thought</think>  answer  ");
    expect(result.finalAnswer).toBe("answer");
  });
});

// ---------------------------------------------------------------------------
// parseCertificateInfo
// ---------------------------------------------------------------------------
describe("parseCertificateInfo", () => {
  test("identifies root cert (subject === issuer)", () => {
    const content = "Subject: CN=Root CA\nIssuer: CN=Root CA\n";
    const result = parseCertificateInfo(content);
    expect(result.isRoot).toBe(true);
    expect(result.subject).toBe("CN=Root CA");
    expect(result.issuer).toBe("CN=Root CA");
  });

  test("identifies non-root cert (subject !== issuer)", () => {
    const content = "Subject: CN=Server\nIssuer: CN=Root CA\n";
    const result = parseCertificateInfo(content);
    expect(result.isRoot).toBe(false);
    expect(result.subject).toBe("CN=Server");
    expect(result.issuer).toBe("CN=Root CA");
  });

  test("returns isRoot=false when Subject is missing", () => {
    const content = "Issuer: CN=Root CA\n";
    expect(parseCertificateInfo(content).isRoot).toBe(false);
  });

  test("returns isRoot=false when Issuer is missing", () => {
    const content = "Subject: CN=Root CA\n";
    expect(parseCertificateInfo(content).isRoot).toBe(false);
  });

  test("returns isRoot=false for empty string", () => {
    expect(parseCertificateInfo("").isRoot).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// orderCertificateChain
// ---------------------------------------------------------------------------
describe("orderCertificateChain", () => {
  test("puts root certs first", () => {
    const certs = [
      { certInfo: { isRoot: false }, name: "leaf" },
      { certInfo: { isRoot: true }, name: "root" },
      { certInfo: { isRoot: false }, name: "intermediate" },
    ];
    const ordered = orderCertificateChain(certs);
    expect(ordered[0].name).toBe("root");
    expect(ordered).toHaveLength(3);
  });

  test("handles all roots", () => {
    const certs = [
      { certInfo: { isRoot: true }, name: "root1" },
      { certInfo: { isRoot: true }, name: "root2" },
    ];
    const ordered = orderCertificateChain(certs);
    expect(ordered).toHaveLength(2);
  });

  test("handles no roots", () => {
    const certs = [
      { certInfo: { isRoot: false }, name: "leaf1" },
      { certInfo: { isRoot: false }, name: "leaf2" },
    ];
    const ordered = orderCertificateChain(certs);
    expect(ordered).toHaveLength(2);
  });

  test("handles empty array", () => {
    expect(orderCertificateChain([])).toEqual([]);
  });

  test("filters out entries without certInfo", () => {
    const certs = [
      { certInfo: { isRoot: true }, name: "root" },
      { name: "no-cert-info" },
    ];
    const ordered = orderCertificateChain(certs);
    expect(ordered).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// extractTeamId
// ---------------------------------------------------------------------------
describe("extractTeamId", () => {
  test("extracts team ID from element ID", () => {
    expect(extractTeamId("team-row-", "team-row-abc123")).toBe("abc123");
  });

  test("returns null when elementId is null", () => {
    expect(extractTeamId("prefix-", null)).toBeNull();
  });

  test("returns null when elementId does not start with prefix", () => {
    expect(extractTeamId("team-row-", "other-abc123")).toBeNull();
  });

  test("returns empty string when ID equals prefix", () => {
    expect(extractTeamId("prefix-", "prefix-")).toBe("");
  });

  test("handles empty prefix", () => {
    expect(extractTeamId("", "anything")).toBe("anything");
  });
});

// ---------------------------------------------------------------------------
// extractApiError
// ---------------------------------------------------------------------------
describe("extractApiError", () => {
  test("returns fallback for null error", () => {
    expect(extractApiError(null)).toBe("An error occurred");
  });

  test("returns fallback for undefined error", () => {
    expect(extractApiError(undefined)).toBe("An error occurred");
  });

  test("returns fallback for error without detail or message", () => {
    expect(extractApiError({})).toBe("An error occurred");
  });

  test("uses custom fallback", () => {
    expect(extractApiError(null, "Custom error")).toBe("Custom error");
  });

  test("extracts message property", () => {
    expect(extractApiError({ message: "Something failed" })).toBe("Something failed");
  });

  test("extracts string detail", () => {
    expect(extractApiError({ detail: "Not found" })).toBe("Not found");
  });

  test("prefers message over detail", () => {
    expect(extractApiError({ message: "msg", detail: "det" })).toBe("msg");
  });

  test("formats Pydantic validation errors (array detail)", () => {
    const error = {
      detail: [{ msg: "field required" }, { msg: "invalid value" }],
    };
    const result = extractApiError(error);
    expect(result).toContain("field required");
    expect(result).toContain("invalid value");
    expect(result).toContain("; ");
  });

  test("JSON-stringifies array detail items without msg", () => {
    const error = {
      detail: [{ loc: ["body", "name"], type: "missing" }],
    };
    const result = extractApiError(error);
    expect(result).toContain("loc");
  });
});

// ---------------------------------------------------------------------------
// extractKPIData
// ---------------------------------------------------------------------------
describe("extractKPIData", () => {
  test("extracts KPIs from standard format", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Successful Executions": 90,
        "Failed Executions": 10,
        "Average Response Time": 1.5,
      },
    };
    const result = extractKPIData(data);
    expect(result.totalExecutions).toBe(100);
    expect(result.successRate).toBe(90);
    expect(result.errorRate).toBe(10);
    expect(result.avgResponseTime).toBeCloseTo(1.5, 1);
  });

  test("aggregates across multiple categories", () => {
    const data = {
      tools: {
        "Total Executions": 50,
        "Successful Executions": 45,
        "Failed Executions": 5,
      },
      resources: {
        "Total Executions": 50,
        "Successful Executions": 40,
        "Failed Executions": 10,
      },
    };
    const result = extractKPIData(data);
    expect(result.totalExecutions).toBe(100);
    expect(result.successRate).toBe(85);
    expect(result.errorRate).toBe(15);
  });

  test("returns zeros for empty data", () => {
    const result = extractKPIData({});
    expect(result.totalExecutions).toBe(0);
    expect(result.successRate).toBe(0);
    expect(result.errorRate).toBe(0);
    expect(result.avgResponseTime).toBeNull();
  });

  test("returns zeros for null data", () => {
    const result = extractKPIData(null);
    expect(result.totalExecutions).toBe(0);
  });

  test("handles camelCase key aliases", () => {
    const data = {
      tools_metrics: {
        totalexecutions: 200,
        successfulexecutions: 180,
        failedexecutions: 20,
        avgresponsetime: 2.0,
      },
    };
    const result = extractKPIData(data);
    expect(result.totalExecutions).toBe(200);
    expect(result.successRate).toBe(90);
  });

  test("handles snake_case key aliases", () => {
    const data = {
      tools: {
        total_executions: 100,
        successful_executions: 80,
        failed_executions: 20,
      },
    };
    const result = extractKPIData(data);
    expect(result.totalExecutions).toBe(100);
  });

  test("returns null avgResponseTime when no executions", () => {
    const data = {
      tools: {
        "Total Executions": 0,
        "Successful Executions": 0,
        "Failed Executions": 0,
        "Average Response Time": 5.0,
      },
    };
    const result = extractKPIData(data);
    expect(result.avgResponseTime).toBeNull();
  });

  test("computes weighted average response time across categories", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Successful Executions": 100,
        "Failed Executions": 0,
        "Average Response Time": 2.0,
      },
      resources: {
        "Total Executions": 100,
        "Successful Executions": 100,
        "Failed Executions": 0,
        "Average Response Time": 4.0,
      },
    };
    const result = extractKPIData(data);
    // Weighted avg = (100*2.0 + 100*4.0) / 200 = 3.0
    expect(result.avgResponseTime).toBeCloseTo(3.0, 1);
  });

  test("ignores N/A response time values", () => {
    const data = {
      tools: {
        "Total Executions": 100,
        "Successful Executions": 100,
        "Failed Executions": 0,
        "Average Response Time": "N/A",
      },
    };
    const result = extractKPIData(data);
    expect(result.avgResponseTime).toBeNull();
  });
});
