/**
 * Unit tests for admin.js validation functions.
 */

import { describe, test, expect, beforeAll, afterAll } from "vitest";
import { loadAdminJs, cleanupAdminJs } from "./helpers/admin-env.js";

let win;

beforeAll(() => {
    win = loadAdminJs();
    // Set MAX_NAME_LENGTH used by validateInputName
    win.MAX_NAME_LENGTH = 200;
});

afterAll(() => {
    cleanupAdminJs();
});

// ---------------------------------------------------------------------------
// validatePassthroughHeader
// ---------------------------------------------------------------------------
describe("validatePassthroughHeader", () => {
    const v = () => win.validatePassthroughHeader;

    test("accepts valid header name and value", () => {
        expect(v()("Content-Type", "application/json")).toEqual({
            valid: true,
        });
    });

    test("accepts header with empty value", () => {
        expect(v()("X-Custom", "")).toEqual({ valid: true });
    });

    test("rejects header name with spaces", () => {
        const result = v()("Bad Header", "value");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/invalid characters/);
    });

    test("rejects header name with underscore", () => {
        const result = v()("bad_header", "value");
        expect(result.valid).toBe(false);
    });

    test("rejects header name with colon", () => {
        const result = v()("Host:", "value");
        expect(result.valid).toBe(false);
    });

    test("rejects value with newline (CRLF injection)", () => {
        const result = v()("X-Custom", "val\r\nEvil: injected");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/newline/);
    });

    test("rejects value with bare newline", () => {
        const result = v()("X-Custom", "val\nEvil");
        expect(result.valid).toBe(false);
    });

    test("rejects value with bare carriage return", () => {
        const result = v()("X-Custom", "val\rEvil");
        expect(result.valid).toBe(false);
    });

    test("rejects value exceeding max length", () => {
        const longValue = "x".repeat(5000);
        const result = v()("X-Custom", longValue);
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/too long/);
    });

    test("accepts value at exactly max length (4096)", () => {
        const exactValue = "x".repeat(4096);
        expect(v()("X-Custom", exactValue)).toEqual({ valid: true });
    });

    test("rejects value with control characters (NUL)", () => {
        const result = v()("X-Custom", "val\x00ue");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/control characters/);
    });

    test("allows tab in value", () => {
        expect(v()("X-Custom", "val\tue")).toEqual({ valid: true });
    });

    test("accepts numeric header name", () => {
        expect(v()("123", "value")).toEqual({ valid: true });
    });
});

// ---------------------------------------------------------------------------
// validateInputName
// ---------------------------------------------------------------------------
describe("validateInputName", () => {
    const v = () => win.validateInputName;

    test("accepts simple name", () => {
        const result = v()("my-tool");
        expect(result.valid).toBe(true);
        expect(result.value).toBe("my-tool");
    });

    test("rejects null", () => {
        const result = v()(null);
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/required/);
    });

    test("rejects undefined", () => {
        const result = v()(undefined);
        expect(result.valid).toBe(false);
    });

    test("rejects empty string", () => {
        const result = v()("");
        expect(result.valid).toBe(false);
    });

    test("rejects non-string (number)", () => {
        const result = v()(123);
        expect(result.valid).toBe(false);
    });

    test("strips HTML tags and validates cleaned result", () => {
        const result = v()("my<b>tool</b>");
        expect(result.valid).toBe(true);
        expect(result.value).toBe("mytool");
    });

    test("rejects script tag injection", () => {
        const result = v()('<script>alert("xss")</script>');
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/invalid characters/);
    });

    test("rejects javascript: protocol", () => {
        const result = v()("javascript:alert(1)");
        expect(result.valid).toBe(false);
    });

    test("rejects event handler injection", () => {
        const result = v()('onerror=alert("xss")');
        expect(result.valid).toBe(false);
    });

    test("rejects data:text/html", () => {
        const result = v()("data:text/html,<h1>hi</h1>");
        expect(result.valid).toBe(false);
    });

    test("rejects vbscript:", () => {
        const result = v()("vbscript:MsgBox");
        expect(result.valid).toBe(false);
    });

    test("uses custom type label in error messages", () => {
        const result = v()(null, "Server name");
        expect(result.error).toMatch(/Server name/);
    });

    test("rejects name exceeding MAX_NAME_LENGTH", () => {
        const long = "a".repeat(201);
        const result = v()(long);
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/200 characters or less/);
    });

    test("accepts name at exactly MAX_NAME_LENGTH", () => {
        const exact = "a".repeat(200);
        const result = v()(exact);
        expect(result.valid).toBe(true);
    });

    test("prompt type rejects special characters", () => {
        const result = v()("my.prompt!", "prompt");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/letters, numbers/);
    });

    test("prompt type accepts valid prompt name", () => {
        const result = v()("my-prompt_v2", "prompt");
        expect(result.valid).toBe(true);
    });

    test("prompt type allows spaces", () => {
        const result = v()("My Prompt Name", "prompt");
        expect(result.valid).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// validateUrl
// ---------------------------------------------------------------------------
describe("validateUrl", () => {
    const v = () => win.validateUrl;

    test("accepts valid HTTP URL", () => {
        const result = v()("http://example.com");
        expect(result.valid).toBe(true);
        expect(result.value).toBe("http://example.com");
    });

    test("accepts valid HTTPS URL", () => {
        const result = v()("https://example.com/path?q=1");
        expect(result.valid).toBe(true);
    });

    test("rejects null", () => {
        const result = v()(null);
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/required/);
    });

    test("rejects empty string", () => {
        const result = v()("");
        expect(result.valid).toBe(false);
    });

    test("rejects non-string", () => {
        const result = v()(123);
        expect(result.valid).toBe(false);
    });

    test("rejects ftp:// protocol", () => {
        const result = v()("ftp://example.com");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/HTTP and HTTPS/);
    });

    test("rejects javascript: protocol", () => {
        const result = v()("javascript:alert(1)");
        expect(result.valid).toBe(false);
    });

    test("rejects malformed URL", () => {
        const result = v()("not a url");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/Invalid URL/);
    });

    test("uses custom label in error", () => {
        const result = v()(null, "Gateway URL");
        expect(result.error).toMatch(/Gateway URL/);
    });

    test("uses default 'URL' label when no label given", () => {
        const result = v()(null);
        expect(result.error).toMatch(/URL/);
    });
});

// ---------------------------------------------------------------------------
// validateJson
// ---------------------------------------------------------------------------
describe("validateJson", () => {
    const v = () => win.validateJson;

    test("parses valid JSON object", () => {
        const result = v()('{"key": "value"}');
        expect(result.valid).toBe(true);
        expect(result.value).toEqual({ key: "value" });
    });

    test("parses valid JSON array", () => {
        const result = v()("[1, 2, 3]");
        expect(result.valid).toBe(true);
        expect(result.value).toEqual([1, 2, 3]);
    });

    test("returns empty object for null input", () => {
        const result = v()(null);
        expect(result.valid).toBe(true);
        expect(result.value).toEqual({});
    });

    test("returns empty object for empty string", () => {
        const result = v()("");
        expect(result.valid).toBe(true);
        expect(result.value).toEqual({});
    });

    test("returns empty object for whitespace-only string", () => {
        const result = v()("   ");
        expect(result.valid).toBe(true);
        expect(result.value).toEqual({});
    });

    test("rejects invalid JSON", () => {
        const result = v()("{invalid}");
        expect(result.valid).toBe(false);
        expect(result.error).toMatch(/Invalid JSON format/);
    });

    test("uses custom field name in error", () => {
        const result = v()("{bad}", "Headers");
        expect(result.error).toMatch(/Headers/);
    });

    test("handles nested JSON", () => {
        const result = v()('{"a": {"b": [1, 2]}}');
        expect(result.valid).toBe(true);
        expect(result.value.a.b).toEqual([1, 2]);
    });
});

// ---------------------------------------------------------------------------
// isValidIpOrCidr
// ---------------------------------------------------------------------------
describe("isValidIpOrCidr", () => {
    const v = () => win.isValidIpOrCidr;

    test("accepts valid IPv4 address", () => {
        expect(v()("192.168.1.1")).toBe(true);
    });

    test("accepts IPv4 with CIDR", () => {
        expect(v()("10.0.0.0/8")).toBe(true);
    });

    test("accepts IPv4 /32", () => {
        expect(v()("192.168.1.1/32")).toBe(true);
    });

    test("accepts IPv4 /0", () => {
        expect(v()("0.0.0.0/0")).toBe(true);
    });

    test("accepts 255.255.255.255", () => {
        expect(v()("255.255.255.255")).toBe(true);
    });

    test("rejects IPv4 octet > 255", () => {
        expect(v()("256.0.0.1")).toBe(false);
    });

    test("rejects IPv4 CIDR > 32", () => {
        expect(v()("10.0.0.0/33")).toBe(false);
    });

    test("accepts loopback", () => {
        expect(v()("127.0.0.1")).toBe(true);
    });

    test("accepts full IPv6", () => {
        expect(v()("2001:0db8:85a3:0000:0000:8a2e:0370:7334")).toBe(true);
    });

    test("accepts compressed IPv6", () => {
        expect(v()("::1")).toBe(true);
    });

    test("accepts :: (all zeros)", () => {
        expect(v()("::")).toBe(true);
    });

    test("accepts IPv6 with CIDR", () => {
        expect(v()("2001:db8::/32")).toBe(true);
    });

    test("rejects null", () => {
        expect(v()(null)).toBe(false);
    });

    test("rejects undefined", () => {
        expect(v()(undefined)).toBe(false);
    });

    test("rejects empty string", () => {
        expect(v()("")).toBe(false);
    });

    test("rejects non-string", () => {
        expect(v()(123)).toBe(false);
    });

    test("rejects random text", () => {
        expect(v()("not-an-ip")).toBe(false);
    });

    test("rejects incomplete IPv4", () => {
        expect(v()("192.168.1")).toBe(false);
    });

    test("trims whitespace", () => {
        expect(v()("  192.168.1.1  ")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// isValidPermission
// ---------------------------------------------------------------------------
describe("isValidPermission", () => {
    const v = () => win.isValidPermission;

    test("accepts wildcard *", () => {
        expect(v()("*")).toBe(true);
    });

    test("accepts tools.read", () => {
        expect(v()("tools.read")).toBe(true);
    });

    test("accepts resources.write", () => {
        expect(v()("resources.write")).toBe(true);
    });

    test("accepts prompts.execute", () => {
        expect(v()("prompts.execute")).toBe(true);
    });

    test("accepts permission with underscores", () => {
        expect(v()("my_resource.my_action")).toBe(true);
    });

    test("rejects null", () => {
        expect(v()(null)).toBe(false);
    });

    test("rejects empty string", () => {
        expect(v()("")).toBe(false);
    });

    test("rejects single word without dot", () => {
        expect(v()("tools")).toBe(false);
    });

    test("rejects triple dot format", () => {
        expect(v()("a.b.c")).toBe(false);
    });

    test("rejects leading number in resource", () => {
        expect(v()("1tools.read")).toBe(false);
    });

    test("rejects spaces", () => {
        expect(v()("tools .read")).toBe(false);
    });

    test("trims whitespace", () => {
        expect(v()("  tools.read  ")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// isValidBase64
// ---------------------------------------------------------------------------
describe("isValidBase64", () => {
    const v = () => win.isValidBase64;

    test("accepts valid base64 string", () => {
        expect(v()("SGVsbG8gV29ybGQ=")).toBe(true);
    });

    test("accepts base64 without padding", () => {
        expect(v()("SGVsbG8")).toBe(true);
    });

    test("accepts base64 with double padding", () => {
        expect(v()("SGVsbA==")).toBe(true);
    });

    test("rejects empty string", () => {
        expect(v()("")).toBe(false);
    });

    test("rejects string with spaces", () => {
        expect(v()("SGVs bG8=")).toBe(false);
    });

    test("rejects string with special characters", () => {
        expect(v()("SGVsbG8!")).toBe(false);
    });

    test("accepts base64 with + and /", () => {
        expect(v()("ab+cd/ef==")).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// isValidCertificate
// ---------------------------------------------------------------------------
describe("isValidCertificate", () => {
    const v = () => win.isValidCertificate;

    // A minimal valid-looking PEM certificate (long enough base64 content)
    const validCert = [
        "-----BEGIN CERTIFICATE-----",
        "MIIBkTCB+wIJALRiMLAh3nsoMA0GCSqGSIb3DQEBCwUAMBExDzANBgNVBAMMBnRl",
        "c3RjYTAeFw0yMzAxMDEwMDAwMDBaFw0yNDAxMDEwMDAwMDBaMBExDzANBgNVBAMM",
        "BnRlc3RjYTBcMA0GCSqGSIb3DQEBAQUAAEsASUFJQUlBSUFJQUlBSUFJQUlBSUFJ",
        "-----END CERTIFICATE-----",
    ].join("\n");

    test("accepts valid PEM certificate", () => {
        expect(v()(validCert)).toBe(true);
    });

    test("rejects string without BEGIN marker", () => {
        expect(v()("just some text")).toBe(false);
    });

    test("rejects string with only BEGIN marker", () => {
        expect(
            v()("-----BEGIN CERTIFICATE-----\ndata\n"),
        ).toBe(false);
    });

    test("rejects certificate with too-short base64 content", () => {
        const shortCert = [
            "-----BEGIN CERTIFICATE-----",
            "AQAB",
            "-----END CERTIFICATE-----",
        ].join("\n");
        expect(v()(shortCert)).toBe(false);
    });

    test("accepts multiple certificates in chain", () => {
        const chain = validCert + "\n" + validCert;
        expect(v()(chain)).toBe(true);
    });

    test("handles leading/trailing whitespace", () => {
        expect(v()("  \n" + validCert + "\n  ")).toBe(true);
    });
});
