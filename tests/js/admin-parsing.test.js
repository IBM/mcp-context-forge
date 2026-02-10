/**
 * Unit tests for admin.js parsing and data extraction functions.
 */

import { describe, test, expect, beforeAll, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;

beforeAll(() => {
    win = loadAdminJs();
});

afterAll(() => {
    cleanupAdminJs();
});

// ---------------------------------------------------------------------------
// parseUriTemplate
// ---------------------------------------------------------------------------
describe("parseUriTemplate", () => {
    const f = () => win.parseUriTemplate;

    test("extracts single template variable", () => {
        expect(f()("/users/{id}")).toEqual(["id"]);
    });

    test("extracts multiple template variables", () => {
        expect(f()("/users/{userId}/posts/{postId}")).toEqual([
            "userId",
            "postId",
        ]);
    });

    test("returns empty array when no variables", () => {
        expect(f()("/users/list")).toEqual([]);
    });

    test("returns empty array for empty string", () => {
        expect(f()("")).toEqual([]);
    });

    test("handles adjacent variables", () => {
        expect(f()("{a}{b}")).toEqual(["a", "b"]);
    });

    test("handles variable with underscores", () => {
        expect(f()("/api/{user_name}")).toEqual(["user_name"]);
    });
});

// ---------------------------------------------------------------------------
// parseThinkTags
// ---------------------------------------------------------------------------
describe("parseThinkTags", () => {
    const f = () => win.parseThinkTags;

    test("parses single think block", () => {
        const result = f()("<think>reasoning here</think>The answer");
        expect(result.thinkingSteps).toHaveLength(1);
        expect(result.thinkingSteps[0].content).toBe("reasoning here");
        expect(result.finalAnswer).toBe("The answer");
    });

    test("parses multiple think blocks", () => {
        const input =
            "<think>step 1</think>middle<think>step 2</think>final answer";
        const result = f()(input);
        expect(result.thinkingSteps).toHaveLength(2);
        expect(result.thinkingSteps[0].content).toBe("step 1");
        expect(result.thinkingSteps[1].content).toBe("step 2");
        expect(result.finalAnswer).toBe("middlefinal answer");
    });

    test("returns empty thinkingSteps when no think tags", () => {
        const result = f()("just a normal response");
        expect(result.thinkingSteps).toHaveLength(0);
        expect(result.finalAnswer).toBe("just a normal response");
    });

    test("preserves rawContent", () => {
        const input = "<think>thought</think>answer";
        const result = f()(input);
        expect(result.rawContent).toBe(input);
    });

    test("skips empty think blocks", () => {
        const result = f()("<think></think>answer");
        expect(result.thinkingSteps).toHaveLength(0);
        expect(result.finalAnswer).toBe("answer");
    });

    test("skips whitespace-only think blocks", () => {
        const result = f()("<think>   \n  </think>answer");
        expect(result.thinkingSteps).toHaveLength(0);
    });

    test("handles multiline think content", () => {
        const input = "<think>line1\nline2\nline3</think>answer";
        const result = f()(input);
        expect(result.thinkingSteps[0].content).toContain("line1");
        expect(result.thinkingSteps[0].content).toContain("line3");
    });

    test("trims final answer whitespace", () => {
        const result = f()("<think>thought</think>  answer  ");
        expect(result.finalAnswer).toBe("answer");
    });
});

// ---------------------------------------------------------------------------
// parseCertificateInfo
// ---------------------------------------------------------------------------
describe("parseCertificateInfo", () => {
    const f = () => win.parseCertificateInfo;

    test("identifies root cert (subject === issuer)", () => {
        const content = "Subject: CN=Root CA\nIssuer: CN=Root CA\n";
        const result = f()(content);
        expect(result.isRoot).toBe(true);
        expect(result.subject).toBe("CN=Root CA");
        expect(result.issuer).toBe("CN=Root CA");
    });

    test("identifies non-root cert (subject !== issuer)", () => {
        const content = "Subject: CN=Server\nIssuer: CN=Root CA\n";
        const result = f()(content);
        expect(result.isRoot).toBe(false);
        expect(result.subject).toBe("CN=Server");
        expect(result.issuer).toBe("CN=Root CA");
    });

    test("returns isRoot=false when Subject is missing", () => {
        const content = "Issuer: CN=Root CA\n";
        expect(f()(content).isRoot).toBe(false);
    });

    test("returns isRoot=false when Issuer is missing", () => {
        const content = "Subject: CN=Root CA\n";
        expect(f()(content).isRoot).toBe(false);
    });

    test("returns isRoot=false for empty string", () => {
        expect(f()("").isRoot).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// orderCertificateChain
// ---------------------------------------------------------------------------
describe("orderCertificateChain", () => {
    const f = () => win.orderCertificateChain;

    test("puts root certs first", () => {
        const certs = [
            { certInfo: { isRoot: false }, name: "leaf" },
            { certInfo: { isRoot: true }, name: "root" },
            { certInfo: { isRoot: false }, name: "intermediate" },
        ];
        const ordered = f()(certs);
        expect(ordered[0].name).toBe("root");
        expect(ordered).toHaveLength(3);
    });

    test("handles all roots", () => {
        const certs = [
            { certInfo: { isRoot: true }, name: "root1" },
            { certInfo: { isRoot: true }, name: "root2" },
        ];
        const ordered = f()(certs);
        expect(ordered).toHaveLength(2);
    });

    test("handles no roots", () => {
        const certs = [
            { certInfo: { isRoot: false }, name: "leaf1" },
            { certInfo: { isRoot: false }, name: "leaf2" },
        ];
        const ordered = f()(certs);
        expect(ordered).toHaveLength(2);
    });

    test("handles empty array", () => {
        expect(f()([])).toEqual([]);
    });

    test("filters out entries without certInfo", () => {
        const certs = [
            { certInfo: { isRoot: true }, name: "root" },
            { name: "no-cert-info" },
        ];
        const ordered = f()(certs);
        expect(ordered).toHaveLength(1);
    });
});

// ---------------------------------------------------------------------------
// extractTeamId
// ---------------------------------------------------------------------------
describe("extractTeamId", () => {
    const f = () => win.extractTeamId;

    test("extracts team ID from element ID", () => {
        expect(f()("team-row-", "team-row-abc123")).toBe("abc123");
    });

    test("returns null when elementId is null", () => {
        expect(f()("prefix-", null)).toBeNull();
    });

    test("returns null when elementId does not start with prefix", () => {
        expect(f()("team-row-", "other-abc123")).toBeNull();
    });

    test("returns empty string when ID equals prefix", () => {
        expect(f()("prefix-", "prefix-")).toBe("");
    });

    test("handles empty prefix", () => {
        expect(f()("", "anything")).toBe("anything");
    });
});

// ---------------------------------------------------------------------------
// extractApiError
// ---------------------------------------------------------------------------
describe("extractApiError", () => {
    const f = () => win.extractApiError;

    test("returns fallback for null error", () => {
        expect(f()(null)).toBe("An error occurred");
    });

    test("returns fallback for undefined error", () => {
        expect(f()(undefined)).toBe("An error occurred");
    });

    test("returns fallback for error without detail or message", () => {
        expect(f()({})).toBe("An error occurred");
    });

    test("uses custom fallback", () => {
        expect(f()(null, "Custom error")).toBe("Custom error");
    });

    test("extracts message property", () => {
        expect(f()({ message: "Something failed" })).toBe("Something failed");
    });

    test("extracts string detail", () => {
        expect(f()({ detail: "Not found" })).toBe("Not found");
    });

    test("prefers message over detail", () => {
        expect(f()({ message: "msg", detail: "det" })).toBe("msg");
    });

    test("formats Pydantic validation errors (array detail)", () => {
        const error = {
            detail: [
                { msg: "field required" },
                { msg: "invalid value" },
            ],
        };
        const result = f()(error);
        expect(result).toContain("field required");
        expect(result).toContain("invalid value");
        expect(result).toContain("; ");
    });

    test("JSON-stringifies array detail items without msg", () => {
        const error = {
            detail: [{ loc: ["body", "name"], type: "missing" }],
        };
        const result = f()(error);
        expect(result).toContain("loc");
    });
});

// ---------------------------------------------------------------------------
// extractKPIData
// ---------------------------------------------------------------------------
describe("extractKPIData", () => {
    const f = () => win.extractKPIData;

    test("extracts KPIs from standard format", () => {
        const data = {
            tools: {
                "Total Executions": 100,
                "Successful Executions": 90,
                "Failed Executions": 10,
                "Average Response Time": 1.5,
            },
        };
        const result = f()(data);
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
        const result = f()(data);
        expect(result.totalExecutions).toBe(100);
        expect(result.successRate).toBe(85);
        expect(result.errorRate).toBe(15);
    });

    test("returns zeros for empty data", () => {
        const result = f()({});
        expect(result.totalExecutions).toBe(0);
        expect(result.successRate).toBe(0);
        expect(result.errorRate).toBe(0);
        expect(result.avgResponseTime).toBeNull();
    });

    test("returns zeros for null data", () => {
        const result = f()(null);
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
        const result = f()(data);
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
        const result = f()(data);
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
        const result = f()(data);
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
        const result = f()(data);
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
        const result = f()(data);
        expect(result.avgResponseTime).toBeNull();
    });
});
