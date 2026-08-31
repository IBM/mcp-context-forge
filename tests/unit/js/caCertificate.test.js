/**
 * Unit tests for caCertificate.js module
 * Tests: validateCACertFiles, parseCertificateInfo, orderCertificateChain,
 *        formatFileSize, updateBodyLabel, initializeCACertUpload
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  parseCertificateInfo,
  orderCertificateChain,
  formatFileSize,
  updateBodyLabel,
  initializeCACertUpload,
  validateCACertFiles,
} from "../../../mcpgateway/admin_ui/caCertificate.js";

import { isValidBase64 } from "../../../mcpgateway/admin_ui/utils.js";

vi.mock("../../../mcpgateway/admin_ui/security.js", () => ({
  escapeHtml: vi.fn((s) => (s != null ? String(s) : "")),
}));
vi.mock("../../../mcpgateway/admin_ui/utils.js", () => ({
  isValidBase64: vi.fn(() => true),
  safeGetElement: vi.fn((id) => document.getElementById(id)),
}));

// ---------------------------------------------------------------------------
// Test constants
// ---------------------------------------------------------------------------
const LONG_BASE64 = "A".repeat(120);

const VALID_PEM_ROOT = [
  "Subject: CN=Root CA",
  "Issuer: CN=Root CA",
  "-----BEGIN CERTIFICATE-----",
  LONG_BASE64,
  "-----END CERTIFICATE-----",
].join("\n");

const VALID_PEM_INTERMEDIATE = [
  "Subject: CN=Intermediate CA",
  "Issuer: CN=Root CA",
  "-----BEGIN CERTIFICATE-----",
  LONG_BASE64,
  "-----END CERTIFICATE-----",
].join("\n");

const INVALID_PEM = "not a certificate at all";

// ---------------------------------------------------------------------------
// FileReader mock helper
// ---------------------------------------------------------------------------
const mockFileReader = (fileContentMap, failFiles = []) => {
  vi.stubGlobal(
    "FileReader",
    vi.fn(function () {
      const reader = {
        onload: null,
        onerror: null,
        readAsText: vi.fn(function (file) {
          if (failFiles.includes(file.name)) {
            Promise.resolve().then(() => reader.onerror && reader.onerror());
          } else {
            const content = fileContentMap[file.name] ?? "";
            Promise.resolve().then(
              () => reader.onload && reader.onload({ target: { result: content } })
            );
          }
        }),
      };
      return reader;
    })
  );
};

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
    const result = parseCertificateInfo(
      "-----BEGIN CERTIFICATE-----\nMIIBxx...\n-----END CERTIFICATE-----"
    );
    expect(result.isRoot).toBe(false);
  });

  test("returns isRoot=false for empty content", () => {
    const result = parseCertificateInfo("");
    expect(result.isRoot).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// formatFileSize
// ---------------------------------------------------------------------------
describe("formatFileSize", () => {
  test("returns '0 Bytes' for 0", () => {
    expect(formatFileSize(0)).toBe("0 Bytes");
  });

  test("formats bytes", () => {
    expect(formatFileSize(512)).toBe("512 Bytes");
  });

  test("formats kilobytes", () => {
    expect(formatFileSize(1024)).toBe("1 KB");
  });

  test("formats megabytes", () => {
    expect(formatFileSize(1024 * 1024)).toBe("1 MB");
  });

  test("formats gigabytes", () => {
    expect(formatFileSize(1024 * 1024 * 1024)).toBe("1 GB");
  });
});

// ---------------------------------------------------------------------------
// orderCertificateChain
// ---------------------------------------------------------------------------
describe("orderCertificateChain", () => {
  test("places root CAs before intermediates", () => {
    const results = [
      { certInfo: { isRoot: false }, content: "intermediate" },
      { certInfo: { isRoot: true }, content: "root" },
    ];
    const ordered = orderCertificateChain(results);
    expect(ordered[0].content).toBe("root");
    expect(ordered[1].content).toBe("intermediate");
  });

  test("handles all roots", () => {
    const results = [
      { certInfo: { isRoot: true }, content: "root1" },
      { certInfo: { isRoot: true }, content: "root2" },
    ];
    const ordered = orderCertificateChain(results);
    expect(ordered).toHaveLength(2);
    expect(ordered.every((r) => r.certInfo.isRoot)).toBe(true);
  });

  test("filters out entries with null certInfo", () => {
    const results = [
      { certInfo: null, content: "no-info" },
      { certInfo: { isRoot: true }, content: "root" },
    ];
    const ordered = orderCertificateChain(results);
    expect(ordered).toHaveLength(1);
    expect(ordered[0].content).toBe("root");
  });

  test("handles all non-roots", () => {
    const results = [
      { certInfo: { isRoot: false }, content: "inter1" },
      { certInfo: { isRoot: false }, content: "inter2" },
    ];
    const ordered = orderCertificateChain(results);
    expect(ordered).toHaveLength(2);
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

  test("shows plain JSON label when content type element is absent", () => {
    const label = document.createElement("div");
    label.id = "gateway-test-body-label";
    document.body.appendChild(label);

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

  function setupDropZone() {
    const dropZone = document.createElement("div");
    dropZone.id = "ca-certificate-upload-drop-zone";
    document.body.appendChild(dropZone);

    const fileInput = document.createElement("input");
    fileInput.id = "upload-ca-certificate";
    fileInput.type = "file";
    document.body.appendChild(fileInput);

    return { dropZone, fileInput };
  }

  test("attaches click, dragover, dragleave, drop events", () => {
    const { dropZone } = setupDropZone();
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

  test("does not re-attach listeners when called twice on the same drop zone", () => {
    const { dropZone, fileInput } = setupDropZone();
    const addSpy = vi.spyOn(dropZone, "addEventListener");

    initializeCACertUpload();
    initializeCACertUpload();

    const clickCalls = addSpy.mock.calls.filter((c) => c[0] === "click");
    expect(clickCalls).toHaveLength(1);

    const clickSpy = vi.spyOn(fileInput, "click");
    dropZone.click();
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  test("click on drop zone triggers file input click", () => {
    const { dropZone, fileInput } = setupDropZone();
    initializeCACertUpload();

    const clickSpy = vi.spyOn(fileInput, "click");
    dropZone.click();
    expect(clickSpy).toHaveBeenCalled();
  });

  test("dragover adds indigo classes and prevents default", () => {
    const { dropZone } = setupDropZone();
    initializeCACertUpload();

    const event = new Event("dragover", { bubbles: true });
    const preventSpy = vi.spyOn(event, "preventDefault");
    dropZone.dispatchEvent(event);

    expect(preventSpy).toHaveBeenCalled();
    expect(dropZone.classList.contains("border-indigo-500")).toBe(true);
    expect(dropZone.classList.contains("bg-indigo-50")).toBe(true);
  });

  test("dragleave removes indigo classes and prevents default", () => {
    const { dropZone } = setupDropZone();
    initializeCACertUpload();

    dropZone.classList.add("border-indigo-500", "bg-indigo-50");

    const event = new Event("dragleave", { bubbles: true });
    const preventSpy = vi.spyOn(event, "preventDefault");
    dropZone.dispatchEvent(event);

    expect(preventSpy).toHaveBeenCalled();
    expect(dropZone.classList.contains("border-indigo-500")).toBe(false);
    expect(dropZone.classList.contains("bg-indigo-50")).toBe(false);
  });

  test("drop with files dispatches change event on file input", () => {
    const { dropZone, fileInput } = setupDropZone();
    initializeCACertUpload();

    const dispatchSpy = vi.spyOn(fileInput, "dispatchEvent");
    const mockFile = new File(["content"], "test.pem");

    // Mock the files property setter to avoid JSDOM limitation
    Object.defineProperty(fileInput, "files", {
      writable: true,
      value: [mockFile],
    });

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.preventDefault = vi.fn();
    dropEvent.stopPropagation = vi.fn();
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [mockFile] },
    });

    dropZone.dispatchEvent(dropEvent);

    expect(dropEvent.preventDefault).toHaveBeenCalled();
    expect(dropEvent.stopPropagation).toHaveBeenCalled();
    expect(dropZone.classList.contains("border-indigo-500")).toBe(false);
    expect(dispatchSpy).toHaveBeenCalled();
  });

  test("drop with no files does not dispatch change event", () => {
    const { dropZone, fileInput } = setupDropZone();
    initializeCACertUpload();

    const dispatchSpy = vi.spyOn(fileInput, "dispatchEvent");

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.preventDefault = vi.fn();
    dropEvent.stopPropagation = vi.fn();
    Object.defineProperty(dropEvent, "dataTransfer", {
      value: { files: [] },
    });

    dropZone.dispatchEvent(dropEvent);

    expect(dispatchSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// validateCACertFiles
// ---------------------------------------------------------------------------
describe("validateCACertFiles", () => {
  beforeEach(() => {
    vi.mocked(isValidBase64).mockReturnValue(true);
  });

  afterEach(() => {
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  function setupDOM({ withDropZone = false, withHiddenInput = false } = {}) {
    const feedback = document.createElement("div");
    feedback.id = "ca-certificate-feedback";
    document.body.appendChild(feedback);

    const form = document.createElement("form");
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.id = "upload-ca-certificate";
    form.appendChild(fileInput);
    document.body.appendChild(form);

    if (withDropZone) {
      const dropZone = document.createElement("div");
      dropZone.id = "ca-certificate-upload-drop-zone";
      document.body.appendChild(dropZone);
    }

    if (withHiddenInput) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.id = "ca_certificate_concatenated";
      hiddenInput.name = "ca_certificate";
      document.body.appendChild(hiddenInput);
    }

    return { feedback, form };
  }

  function makeFile(name, sizeBytes = 1024) {
    const file = new File(["x"], name, { type: "text/plain" });
    Object.defineProperty(file, "size", { value: sizeBytes });
    return file;
  }

  test("shows error for no files selected", async () => {
    const { feedback } = setupDOM();
    const event = { target: { files: [] } };
    await validateCACertFiles(event);
    expect(feedback.textContent).toContain("No files selected");
  });

  test("rejects oversized files and clears input", async () => {
    const { feedback } = setupDOM();
    const bigFile = makeFile("big.pem", 11 * 1024 * 1024);
    const event = { target: { files: [bigFile], value: "big.pem" } };
    await validateCACertFiles(event);
    expect(feedback.innerHTML).toContain("too large");
    expect(event.target.value).toBe("");
  });

  test("rejects invalid file extensions and clears input", async () => {
    const { feedback } = setupDOM();
    const file = makeFile("cert.txt", 100);
    const event = { target: { files: [file], value: "cert.txt" } };
    await validateCACertFiles(event);
    expect(feedback.innerHTML).toContain("Invalid file type");
    expect(event.target.value).toBe("");
  });

  test("processes a valid root CA certificate successfully", async () => {
    const { feedback, form } = setupDOM({ withDropZone: true });
    mockFileReader({ "root.pem": VALID_PEM_ROOT });

    const file = makeFile("root.pem");
    const event = { target: { files: [file], form, value: "" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("All certificates validated successfully");
    const hiddenInput = document.getElementById("ca_certificate_concatenated");
    expect(hiddenInput).toBeTruthy();
    expect(hiddenInput.value).toContain(LONG_BASE64);
  });

  test("reuses existing hidden input element when present", async () => {
    const { feedback, form } = setupDOM({ withHiddenInput: true });
    mockFileReader({ "cert.pem": VALID_PEM_INTERMEDIATE });

    const file = makeFile("cert.pem");
    const event = { target: { files: [file], form, value: "" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("All certificates validated successfully");
    const hiddenInput = document.getElementById("ca_certificate_concatenated");
    expect(hiddenInput.value).toBeTruthy();
  });

  test("handles invalid PEM content and shows failure", async () => {
    const { feedback } = setupDOM();
    mockFileReader({ "bad.pem": INVALID_PEM });

    const file = makeFile("bad.pem");
    const event = { target: { files: [file], value: "bad.pem" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("Some certificates failed validation");
    expect(event.target.value).toBe("");
  });

  test("handles file read error gracefully", async () => {
    const { feedback } = setupDOM();
    mockFileReader({}, ["error.pem"]);

    const file = makeFile("error.pem");
    const event = { target: { files: [file], value: "error.pem" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("Some certificates failed validation");
  });

  test("processes multiple files: root CA first, then intermediate", async () => {
    const { feedback, form } = setupDOM({ withDropZone: true });
    mockFileReader({
      "intermediate.crt": VALID_PEM_INTERMEDIATE,
      "root.pem": VALID_PEM_ROOT,
    });

    const file1 = makeFile("intermediate.crt");
    const file2 = makeFile("root.pem");
    const event = { target: { files: [file1, file2], form, value: "" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("All certificates validated successfully");
    expect(feedback.innerHTML).toContain("Root CA");
  });

  test("shows per-file failure when one cert is invalid", async () => {
    const { feedback } = setupDOM();
    mockFileReader({
      "bad.cer": INVALID_PEM,
    });

    const file = makeFile("bad.cer");
    const event = { target: { files: [file], value: "bad.cer" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("Some certificates failed validation");
    expect(feedback.innerHTML).toContain("bad.cer");
  });

  test("valid cert without drop zone completes without error", async () => {
    const { feedback, form } = setupDOM({ withDropZone: false });
    mockFileReader({ "cert.pem": VALID_PEM_ROOT });

    const file = makeFile("cert.pem");
    const event = { target: { files: [file], form, value: "" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("All certificates validated successfully");
  });

  test("cert with base64 failing isValidBase64 is marked invalid", async () => {
    vi.mocked(isValidBase64).mockReturnValue(false);
    const { feedback } = setupDOM();
    mockFileReader({ "cert.pem": VALID_PEM_ROOT });

    const file = makeFile("cert.pem");
    const event = { target: { files: [file], value: "cert.pem" } };
    await validateCACertFiles(event);

    expect(feedback.innerHTML).toContain("Some certificates failed validation");
  });
});
