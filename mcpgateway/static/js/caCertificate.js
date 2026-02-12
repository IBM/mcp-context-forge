// ============================================================================
// CA Certificate Validation Functions
// ============================================================================

import { escapeHtml } from "./security";
import { isValidBase64, safeGetElement } from "./utils";

/**
 * Validate CA certificate file on upload (supports multiple files)
 * @param {Event} event - The file input change event
 */
export const validateCACertFiles = async function (event) {
  const files = Array.from(event.target.files);
  const feedbackEl = safeGetElement("ca-certificate-feedback");

  if (!files.length) {
    feedbackEl.textContent = "No files selected.";
    return;
  }

  // Check file size (max 10MB for cert files)
  const maxSize = 10 * 1024 * 1024; // 10MB
  const oversizedFiles = files.filter((f) => f.size > maxSize);
  if (oversizedFiles.length > 0) {
    if (feedbackEl) {
      feedbackEl.innerHTML = `
  <div class="flex items-center text-red-600">
  <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
  <span>Certificate file(s) too large. Maximum size is 10MB per file.</span>
  </div>
  `;
      feedbackEl.className = "mt-2 text-sm";
    }
    event.target.value = "";
    return;
  }

  // Check file extensions
  const validExtensions = [".pem", ".crt", ".cer", ".cert"];
  const invalidFiles = files.filter((file) => {
    const fileName = file.name.toLowerCase();
    return !validExtensions.some((ext) => fileName.endsWith(ext));
  });

  if (invalidFiles.length > 0) {
    if (feedbackEl) {
      feedbackEl.innerHTML = `
  <div class="flex items-center text-red-600">
  <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
  <span>Invalid file type. Please upload valid certificate files (.pem, .crt, .cer, .cert)</span>
  </div>
  `;
      feedbackEl.className = "mt-2 text-sm";
    }
    event.target.value = "";
    return;
  }

  // Read and validate all files
  const certResults = [];
  for (const file of files) {
    try {
      const content = await readFileAsync(file);
      const isValid = isValidCertificate(content);
      const certInfo = isValid ? parseCertificateInfo(content) : null;

      certResults.push({
        file,
        content,
        isValid,
        certInfo,
      });
    } catch (error) {
      certResults.push({
        file,
        content: null,
        isValid: false,
        certInfo: null,
        error: error.message,
      });
    }
  }

  // Display per-file validation results
  displayCertValidationResults(certResults, feedbackEl);

  // If all valid, order and concatenate
  const allValid = certResults.every((r) => r.isValid);
  if (allValid) {
    const orderedCerts = orderCertificateChain(certResults);
    const concatenated = orderedCerts.map((r) => r.content.trim()).join("\n");

    // Store concatenated result in a hidden field
    let hiddenInput = safeGetElement("ca_certificate_concatenated");
    if (!hiddenInput) {
      hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.id = "ca_certificate_concatenated";
      hiddenInput.name = "ca_certificate";
      event.target.form.appendChild(hiddenInput);
    }
    hiddenInput.value = concatenated;

    // Update drop zone
    updateDropZoneWithFiles(files);
  } else {
    event.target.value = "";
  }
};

/**
 * Helper function to read file as text asynchronously
 * @param {File} file - The file to read
 * @returns {Promise<string>} - Promise resolving to file content
 */
const readFileAsync = function (file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target.result);
    reader.onerror = () => reject(new Error("Error reading file"));
    reader.readAsText(file);
  });
};

/**
 * Parse certificate information to determine if it's self-signed (root CA)
 * @param {string} content - PEM certificate content
 * @returns {Object} - Certificate info with isRoot flag
 */
const parseCertificateInfo = function (content) {
  // Basic heuristic: check if Subject and Issuer appear the same
  // In a real implementation, you'd parse the ASN.1 structure properly
  const subjectMatch = content.match(/Subject:([^\n]+)/i);
  const issuerMatch = content.match(/Issuer:([^\n]+)/i);

  // If we can't parse, assume it's an intermediate
  if (!subjectMatch || !issuerMatch) {
    return { isRoot: false };
  }

  const subject = subjectMatch[1].trim();
  const issuer = issuerMatch[1].trim();

  return {
    isRoot: subject === issuer,
    subject,
    issuer,
  };
};

/**
 * Order certificates in chain: root CA first, then intermediates, then leaf
 * @param {Array} certResults - Array of certificate result objects
 * @returns {Array} - Ordered array of certificate results
 */
const orderCertificateChain = function (certResults) {
  const roots = certResults.filter((r) => r.certInfo && r.certInfo.isRoot);
  const nonRoots = certResults.filter((r) => r.certInfo && !r.certInfo.isRoot);

  // Simple ordering: roots first, then rest
  // In production, you'd build a proper chain by matching issuer/subject
  return [...roots, ...nonRoots];
};

/**
 * Display validation results for each certificate file
 * @param {Array} certResults - Array of validation result objects
 * @param {HTMLElement} feedbackEl - Element to display feedback
 */
const displayCertValidationResults = function (certResults, feedbackEl) {
  const allValid = certResults.every((r) => r.isValid);

  let html = '<div class="space-y-2">';

  // Overall status
  if (allValid) {
    html += `
  <div class="flex items-center text-green-600 font-semibold text-lg">
  <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
  <span>All certificates validated successfully!</span>
  </div>
  `;
  } else {
    html += `
  <div class="flex items-center text-red-600 font-semibold text-lg">
  <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
  <span>Some certificates failed validation</span>
  </div>
  `;
  }

  // Per-file results
  html += '<div class="mt-3 space-y-1">';
  for (const result of certResults) {
    const icon = result.isValid
      ? '<svg class="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
      : '<svg class="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';

    const statusClass = result.isValid ? "text-gray-700" : "text-red-700";
    const typeLabel =
      result.certInfo && result.certInfo.isRoot ? " (Root CA)" : "";

    html += `
  <div class="flex items-center ${statusClass}">
  ${icon}
  <span class="ml-2">${escapeHtml(result.file.name)}${typeLabel} - ${formatFileSize(result.file.size)}</span>
  </div>
  `;
  }
  html += "</div></div>";

  feedbackEl.innerHTML = html;
  feedbackEl.className = "mt-2 text-sm";
};

/**
 * Validate certificate content (PEM format)
 * @param {string} content - The certificate file content
 * @returns {boolean} - True if valid certificate
 */
const isValidCertificate = function (content) {
  // Trim whitespace
  content = content.trim();

  // Check for PEM certificate markers
  const beginCertPattern = /-----BEGIN CERTIFICATE-----/;
  const endCertPattern = /-----END CERTIFICATE-----/;

  if (!beginCertPattern.test(content) || !endCertPattern.test(content)) {
    return false;
  }

  // Check for proper structure
  const certPattern =
    /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;
  const matches = content.match(certPattern);

  if (!matches || matches.length === 0) {
    return false;
  }

  // Validate base64 content between markers
  for (const cert of matches) {
    const base64Content = cert
      .replace(/-----BEGIN CERTIFICATE-----/, "")
      .replace(/-----END CERTIFICATE-----/, "")
      .replace(/\s/g, "");

    // Check if content is valid base64
    if (!isValidBase64(base64Content)) {
      return false;
    }

    // Basic length check (certificates are typically > 100 chars of base64)
    if (base64Content.length < 100) {
      return false;
    }
  }

  return true;
};

/**
 * Update drop zone UI with selected file info
 * @param {File} file - The selected file
 */
const updateDropZoneWithFiles = function (files) {
  const dropZone = safeGetElement("ca-certificate-upload-drop-zone");
  if (!dropZone) {
    return;
  }

  const fileListHTML = Array.from(files)
    .map(
      (file) =>
        `<div>${escapeHtml(file.name)} • ${formatFileSize(file.size)}</div>`
    )
    .join("");

  dropZone.innerHTML = `
        <div class="space-y-2">
            <svg class="mx-auto h-12 w-12 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <div class="text-sm text-gray-700 dark:text-gray-300">
                <span class="font-medium">Selected Certificates:</span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${fileListHTML}</div>
        </div>
    `;
};

/**
 * Format file size for display
 * @param {number} bytes - File size in bytes
 * @returns {string} - Formatted file size
 */
export const formatFileSize = function (bytes) {
  if (bytes === 0) {
    return "0 Bytes";
  }
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
};

/**
 * Initialize drag and drop for CA cert upload
 * Called on DOMContentLoaded
 */
export const initializeCACertUpload = function () {
  const dropZone = safeGetElement("ca-certificate-upload-drop-zone");
  const fileInput = safeGetElement("upload-ca-certificate");

  if (dropZone && fileInput) {
    // Click to upload
    dropZone.addEventListener("click", function (e) {
      fileInput.click();
    });

    // Drag and drop handlers
    dropZone.addEventListener("dragover", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add(
        "border-indigo-500",
        "bg-indigo-50",
        "dark:bg-indigo-900/20"
      );
    });

    dropZone.addEventListener("dragleave", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove(
        "border-indigo-500",
        "bg-indigo-50",
        "dark:bg-indigo-900/20"
      );
    });

    dropZone.addEventListener("drop", function (e) {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove(
        "border-indigo-500",
        "bg-indigo-50",
        "dark:bg-indigo-900/20"
      );

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        fileInput.files = files;
        // Trigger the validation
        const event = new Event("change", { bubbles: true });
        fileInput.dispatchEvent(event);
      }
    });
  }
};

// Function to update body label based on content type selection
export const updateBodyLabel = function () {
  const bodyLabel = safeGetElement("gateway-test-body-label");
  const contentType = safeGetElement("gateway-test-content-type")?.value;

  if (bodyLabel) {
    bodyLabel.innerHTML =
      contentType === "application/x-www-form-urlencoded"
        ? 'Body (JSON)<br><small class="text-gray-500">Auto-converts to form data</small>'
        : "Body (JSON)";
  }
};
