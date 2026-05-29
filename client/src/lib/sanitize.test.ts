import { describe, it, expect } from "vitest";
import {
  removeControlCharacters,
  sanitizeString,
  sanitizeUrl,
  sanitizePassword,
  sanitizeToken,
  sanitizeQueryParam,
  sanitizeCertificate,
} from "./sanitize";

describe("removeControlCharacters", () => {
  it("removes CRLF characters", () => {
    expect(removeControlCharacters("hello\r\nworld")).toBe("helloworld");
  });

  it("removes control characters", () => {
    expect(removeControlCharacters("hello\x00world")).toBe("helloworld");
    expect(removeControlCharacters("test\x1Fvalue")).toBe("testvalue");
  });

  it("removes URL-encoded control characters", () => {
    expect(removeControlCharacters("test%0Avalue")).toBe("testvalue");
    expect(removeControlCharacters("test%1Bvalue")).toBe("testvalue");
  });

  it("preserves normal strings", () => {
    expect(removeControlCharacters("hello world")).toBe("hello world");
  });

  it("returns empty value as-is", () => {
    expect(removeControlCharacters("")).toBe("");
  });
});

describe("sanitizeString", () => {
  it("removes control characters and trims", () => {
    expect(sanitizeString("  hello\r\n  ")).toBe("hello");
  });

  it("truncates to maxLength", () => {
    expect(sanitizeString("abcdef", 3)).toBe("abc");
  });

  it("uses default maxLength of 1000", () => {
    const long = "a".repeat(1100);
    expect(sanitizeString(long).length).toBe(1000);
  });

  it("returns empty string as-is", () => {
    expect(sanitizeString("")).toBe("");
  });
});

describe("sanitizeUrl", () => {
  it("removes control characters from URL", () => {
    expect(sanitizeUrl("https://example.com\r\n/path")).toBe("https://example.com/path");
  });

  it("truncates to maxLength", () => {
    const long = "https://example.com/" + "a".repeat(2100);
    expect(sanitizeUrl(long).length).toBe(2000);
  });

  it("returns empty string as-is", () => {
    expect(sanitizeUrl("")).toBe("");
  });

  it("preserves valid URL", () => {
    expect(sanitizeUrl("https://example.com/path?q=1")).toBe("https://example.com/path?q=1");
  });
});

describe("sanitizePassword", () => {
  it("removes control characters", () => {
    expect(sanitizePassword("pass\x00word")).toBe("password");
  });

  it("preserves spaces in password", () => {
    expect(sanitizePassword("my password 123")).toBe("my password 123");
  });

  it("truncates to maxLength", () => {
    const long = "a".repeat(1100);
    expect(sanitizePassword(long).length).toBe(1000);
  });

  it("returns empty string as-is", () => {
    expect(sanitizePassword("")).toBe("");
  });
});

describe("sanitizeToken", () => {
  it("keeps only printable ASCII", () => {
    expect(sanitizeToken("Bearer\x00token")).toBe("Bearertoken");
  });

  it("removes non-ASCII characters", () => {
    expect(sanitizeToken("token\x80value")).toBe("tokenvalue");
  });

  it("truncates to maxLength", () => {
    const long = "a".repeat(2100);
    expect(sanitizeToken(long).length).toBe(2000);
  });

  it("returns empty string as-is", () => {
    expect(sanitizeToken("")).toBe("");
  });

  it("preserves valid token", () => {
    expect(sanitizeToken("Bearer abc123")).toBe("Bearer abc123");
  });
});

describe("sanitizeQueryParam", () => {
  it("removes control characters", () => {
    expect(sanitizeQueryParam("value\r\ninjected")).toBe("valueinjected");
  });

  it("truncates to maxLength", () => {
    const long = "a".repeat(600);
    expect(sanitizeQueryParam(long).length).toBe(500);
  });

  it("returns empty string as-is", () => {
    expect(sanitizeQueryParam("")).toBe("");
  });

  it("preserves normal query param", () => {
    expect(sanitizeQueryParam("search term")).toBe("search term");
  });
});

describe("sanitizeCertificate", () => {
  it("preserves newlines in PEM format", () => {
    const pem = "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n";
    expect(sanitizeCertificate(pem)).toContain("\n");
  });

  it("removes control characters except newlines", () => {
    expect(sanitizeCertificate("cert\x00data")).toBe("certdata");
  });

  it("removes URL-encoded control characters", () => {
    expect(sanitizeCertificate("cert%0Adata")).toBe("certdata");
  });

  it("truncates to maxLength", () => {
    const long = "a".repeat(11000);
    expect(sanitizeCertificate(long).length).toBe(10000);
  });

  it("returns empty string as-is", () => {
    expect(sanitizeCertificate("")).toBe("");
  });
});