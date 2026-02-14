/**
 * Unit tests for caCertificate.js module
 * Tests: validateCACertFiles, parseCertificateInfo, updateBodyLabel, initializeCACertUpload
 * (orderCertificateChain, formatFileSize are already tested in tests/js/)
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  isValidBase64: vi.fn(() => true),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

import {
  parseCertificateInfo,
  updateBodyLabel,
  initializeCACertUpload,
  validateCACertFiles,
} from "../../../mcpgateway/admin_ui/caCertificate.js";

// ---------------------------------------------------------------------------
// parseCertificateInfo
// ---------------------------------------------------------------------------
describe("parseCertificateInfo", () => {
  test("detects root CA when Subject equals Issuer", () => {
    const content = `
-----BEGIN CERTIFICATE-----
Subject: CN=Root CA
Issuer: CN=Root CA
MIIBxx...
-----END CERTIFICATE-----`;
    const result = parseCertificateInfo(content);
    expect(result.isRoot).toBe(true);
    expect(result.subject).toBe("CN=Root CA");
    expect(result.issuer).toBe("CN=Root CA");
  });

  test("detects intermediate when Subject differs from Issuer", () => {
    const content = `
-----BEGIN CERTIFICATE-----
Subject: CN=Intermediate CA
Issuer: CN=Root CA
MIIBxx...
-----END CERTIFICATE-----`;
    const result = parseCertificateInfo(content);
    expect(result.isRoot).toBe(false);
    expect(result.subject).toBe("CN=Intermediate CA");
    expect(result.issuer).toBe("CN=Root CA");
  });

  test("returns isRoot=false when Subject or Issuer is missing", () => {
    const result = parseCertificateInfo("-----BEGIN CERTIFICATE-----\nMIIBxx...\n-----END CERTIFICATE-----");
    expect(result.isRoot).toBe(false);
  });

  test("returns isRoot=false for empty content", () => {
    const result = parseCertificateInfo("");
    expect(result.isRoot).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// updateBodyLabel
// ---------------------------------------------------------------------------
describe("updateBodyLabel", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows form data hint when content type is form-urlencoded", () => {
    const label = document.createElement("div");
    label.id = "gateway-test-body-label";
    document.body.appendChild(label);

    const select = document.createElement("select");
    select.id = "gateway-test-content-type";
    const option = document.createElement("option");
    option.value = "application/x-www-form-urlencoded";
    option.selected = true;
    select.appendChild(option);
    document.body.appendChild(select);

    updateBodyLabel();
    expect(label.innerHTML).toContain("Auto-converts to form data");
  });

  test("shows plain JSON label for other content types", () => {
    const label = document.createElement("div");
    label.id = "gateway-test-body-label";
    document.body.appendChild(label);

    const select = document.createElement("select");
    select.id = "gateway-test-content-type";
    const option = document.createElement("option");
    option.value = "application/json";
    option.selected = true;
    select.appendChild(option);
    document.body.appendChild(select);

    updateBodyLabel();
    expect(label.innerHTML).toBe("Body (JSON)");
  });

  test("does nothing when label element is missing", () => {
    expect(() => updateBodyLabel()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// initializeCACertUpload
// ---------------------------------------------------------------------------
describe("initializeCACertUpload", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("attaches click, dragover, dragleave, drop events", () => {
    const dropZone = document.createElement("div");
    dropZone.id = "ca-certificate-upload-drop-zone";
    document.body.appendChild(dropZone);

    const fileInput = document.createElement("input");
    fileInput.id = "upload-ca-certificate";
    fileInput.type = "file";
    document.body.appendChild(fileInput);

    const dropSpy = vi.spyOn(dropZone, "addEventListener");
    initializeCACertUpload();

    const events = dropSpy.mock.calls.map((c) => c[0]);
    expect(events).toContain("click");
    expect(events).toContain("dragover");
    expect(events).toContain("dragleave");
    expect(events).toContain("drop");
  });

  test("does nothing when elements are missing", () => {
    expect(() => initializeCACertUpload()).not.toThrow();
  });

  test("click on drop zone triggers file input click", () => {
    const dropZone = document.createElement("div");
    dropZone.id = "ca-certificate-upload-drop-zone";
    document.body.appendChild(dropZone);

    const fileInput = document.createElement("input");
    fileInput.id = "upload-ca-certificate";
    fileInput.type = "file";
    document.body.appendChild(fileInput);

    initializeCACertUpload();

    const clickSpy = vi.spyOn(fileInput, "click");
    dropZone.click();
    expect(clickSpy).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// validateCACertFiles
// ---------------------------------------------------------------------------
describe("validateCACertFiles", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  test("shows error for no files selected", async () => {
    const feedback = document.createElement("div");
    feedback.id = "ca-certificate-feedback";
    document.body.appendChild(feedback);

    const event = { target: { files: [] } };
    await validateCACertFiles(event);
    expect(feedback.textContent).toContain("No files selected");
  });

  test("rejects oversized files", async () => {
    const feedback = document.createElement("div");
    feedback.id = "ca-certificate-feedback";
    document.body.appendChild(feedback);

    const bigFile = new File(["x".repeat(100)], "big.pem", { type: "text/plain" });
    Object.defineProperty(bigFile, "size", { value: 11 * 1024 * 1024 }); // 11MB

    const event = { target: { files: [bigFile], value: "big.pem" } };
    await validateCACertFiles(event);
    expect(feedback.innerHTML).toContain("too large");
  });

  test("rejects invalid file extensions", async () => {
    const feedback = document.createElement("div");
    feedback.id = "ca-certificate-feedback";
    document.body.appendChild(feedback);

    const file = new File(["content"], "cert.txt", { type: "text/plain" });
    Object.defineProperty(file, "size", { value: 100 });

    const event = { target: { files: [file], value: "cert.txt" } };
    await validateCACertFiles(event);
    expect(feedback.innerHTML).toContain("Invalid file type");
  });
});
