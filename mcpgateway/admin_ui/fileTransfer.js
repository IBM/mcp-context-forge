import { escapeHtml } from "./security.js";
import { displayImportPreview } from "./selectiveImport.js";
import { getAuthToken } from "./tokens";
import { loadTools } from "./tools";
import { showNotification, safeGetElement } from "./utils";

// ===================================================================
// EXPORT/IMPORT FUNCTIONALITY
// ===================================================================

/**
 * Handle export all configuration
 */
export const handleExportAll = async function () {
  console.log("📤 Starting export all configuration");

  try {
    showExportProgress(true);

    const options = getExportOptions();
    const params = new URLSearchParams();

    if (options.types.length > 0) {
      params.append("types", options.types.join(","));
    }
    if (options.tags) {
      params.append("tags", options.tags);
    }
    if (options.includeInactive) {
      params.append("include_inactive", "true");
    }
    if (!options.includeDependencies) {
      params.append("include_dependencies", "false");
    }

    const response = await fetch(
      `${window.ROOT_PATH}/admin/export/configuration?${params}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (!response.ok) {
      throw new Error(`Export failed: ${response.statusText}`);
    }

    // Create download
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mcpgateway-export-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    showNotification("✅ Export completed successfully!", "success");
  } catch (error) {
    console.error("Export error:", error);
    showNotification(`❌ Export failed: ${error.message}`, "error");
  } finally {
    showExportProgress(false);
  }
};

/**
 * Handle export selected configuration
 */
export const handleExportSelected = async function () {
  console.log("📋 Starting selective export");

  try {
    showExportProgress(true);

    // This would need entity selection logic - for now, just do a filtered export
    await handleExportAll(); // Simplified implementation
  } catch (error) {
    console.error("Selective export error:", error);
    showNotification(`❌ Selective export failed: ${error.message}`, "error");
  } finally {
    showExportProgress(false);
  }
};

/**
 * Get export options from form
 */
const getExportOptions = function () {
  const types = [];

  if (safeGetElement("export-tools")?.checked) {
    types.push("tools");
  }
  if (safeGetElement("export-gateways")?.checked) {
    types.push("gateways");
  }
  if (safeGetElement("export-servers")?.checked) {
    types.push("servers");
  }
  if (safeGetElement("export-prompts")?.checked) {
    types.push("prompts");
  }
  if (safeGetElement("export-resources")?.checked) {
    types.push("resources");
  }
  if (safeGetElement("export-roots")?.checked) {
    types.push("roots");
  }

  return {
    types,
    tags: safeGetElement("export-tags")?.value || "",
    includeInactive:
      safeGetElement("export-include-inactive")?.checked || false,
    includeDependencies:
      safeGetElement("export-include-dependencies")?.checked || true,
  };
};

/**
 * Show/hide export progress
 */
export const showExportProgress = function (show) {
  const progressEl = safeGetElement("export-progress");
  if (progressEl) {
    progressEl.classList.toggle("hidden", !show);
    if (show) {
      let progress = 0;
      const progressBar = safeGetElement("export-progress-bar");
      const interval = setInterval(() => {
        progress += 10;
        if (progressBar) {
          progressBar.style.width = `${Math.min(progress, 90)}%`;
        }
        if (progress >= 100) {
          clearInterval(interval);
        }
      }, 200);
    }
  }
};

/**
 * Handle file selection for import
 */
export const handleFileSelect = function (event) {
  const file = event.target.files[0];
  if (file) {
    processImportJSONFile(file);
  }
};

/**
 * Handle drag over for file drop
 */
export const handleDragOver = function (event) {
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
  event.currentTarget.classList.add(
    "border-blue-500",
    "bg-blue-50",
    "dark:bg-blue-900",
  );
};

/**
 * Handle drag leave
 */
export const handleDragLeave = function (event) {
  event.preventDefault();
  event.currentTarget.classList.remove(
    "border-blue-500",
    "bg-blue-50",
    "dark:bg-blue-900",
  );
};

/**
 * Handle file drop
 */
export const handleFileDrop = function (event) {
  event.preventDefault();
  event.currentTarget.classList.remove(
    "border-blue-500",
    "bg-blue-50",
    "dark:bg-blue-900",
  );

  const files = event.dataTransfer.files;
  if (files.length > 0) {
    processImportJSONFile(files[0]);
  }
};

/**
 * Process selected import file
 */
export const processImportJSONFile = function (file) {
  console.log("📁 Processing import file:", file.name);

  if (!file.type.includes("json")) {
    showNotification("❌ Please select a JSON file", "error");
    return;
  }

  const reader = new FileReader();
  reader.onload = function (e) {
    try {
      const importData = JSON.parse(e.target.result);

      // Validate basic structure
      if (!importData.version || !importData.entities) {
        throw new Error("Invalid import file format");
      }

      // Store import data and enable buttons
      window.Admin.currentImportData = importData;

      const previewBtn = safeGetElement("import-preview-btn");
      const validateBtn = safeGetElement("import-validate-btn");
      const executeBtn = safeGetElement("import-execute-btn");

      if (previewBtn) {
        previewBtn.disabled = false;
      }
      if (validateBtn) {
        validateBtn.disabled = false;
      }
      if (executeBtn) {
        executeBtn.disabled = false;
      }

      // Update drop zone to show file loaded
      updateDropZoneStatus(file.name, importData);

      showNotification(`✅ Import file loaded: ${file.name}`, "success");
    } catch (error) {
      console.error("File processing error:", error);
      showNotification(`❌ Invalid JSON file: ${error.message}`, "error");
    }
  };

  reader.readAsText(file);
};

/**
 * Update drop zone to show loaded file
 */
const updateDropZoneStatus = function (fileName, importData) {
  const dropZone = safeGetElement("import-drop-zone");
  if (dropZone) {
    const entityCounts = importData.metadata?.entity_counts || {};
    const totalEntities = Object.values(entityCounts).reduce(
      (sum, count) => sum + count,
      0,
    );

    dropZone.innerHTML = `
                <div class="space-y-2">
                    <svg class="mx-auto h-8 w-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <div class="text-sm text-gray-900 dark:text-white font-medium">
                        📁 ${escapeHtml(fileName)}
                    </div>
                    <div class="text-xs text-gray-500 dark:text-gray-400">
                        ${totalEntities} entities • Version ${escapeHtml(importData.version || "unknown")}
                    </div>
                    <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="Admin.resetImportFile()">
                        Choose different file
                    </button>
                </div>
            `;
  }
};

/**
 * Reset import file selection
 */
export const resetImportFile = function () {
  window.Admin.currentImportData = null;

  const dropZone = safeGetElement("import-drop-zone");
  if (dropZone) {
    dropZone.innerHTML = `
                <div class="space-y-2">
                    <svg class="mx-auto h-12 w-12 text-gray-400" stroke="currentColor" fill="none" viewBox="0 0 48 48">
                        <path d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3-3m-3 3l3 3m-3-3V8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <div class="text-sm text-gray-600 dark:text-gray-300">
                        <span class="font-medium text-blue-600 dark:text-blue-400">Click to upload</span>
                        or drag and drop
                    </div>
                    <p class="text-xs text-gray-500 dark:text-gray-400">JSON export files only</p>
                </div>
            `;
  }

  const previewBtn = safeGetElement("import-preview-btn");
  const validateBtn = safeGetElement("import-validate-btn");
  const executeBtn = safeGetElement("import-execute-btn");

  if (previewBtn) {
    previewBtn.disabled = true;
  }
  if (validateBtn) {
    validateBtn.disabled = true;
  }
  if (executeBtn) {
    executeBtn.disabled = true;
  }

  // Hide status section
  const statusSection = safeGetElement("import-status-section");
  if (statusSection) {
    statusSection.classList.add("hidden");
  }
};

/**
 * Preview import file for selective import
 */
export const previewImport = async function () {
  console.log("🔍 Generating import preview...");

  if (!window.currentImportData) {
    showNotification("❌ Please select an import file first", "error");
    return;
  }

  try {
    showImportProgress(true);

    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/preview",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify({ data: window.currentImportData }),
      },
    );

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `Preview failed: ${response.statusText}`,
      );
    }

    const result = await response.json();
    displayImportPreview(result.preview);

    showNotification("✅ Import preview generated successfully", "success");
  } catch (error) {
    console.error("Import preview error:", error);
    showNotification(`❌ Preview failed: ${error.message}`, "error");
  } finally {
    showImportProgress(false);
  }
};

/**
 * Handle import (validate or execute)
 */
export const handleImport = async function (dryRun = false) {
  console.log(`🔄 Starting import (dry_run=${dryRun})`);

  if (!window.currentImportData) {
    showNotification("❌ Please select an import file first", "error");
    return;
  }

  try {
    showImportProgress(true);

    const conflictStrategy =
      safeGetElement("import-conflict-strategy")?.value || "update";
    const rekeySecret = safeGetElement("import-rekey-secret")?.value || null;

    const requestData = {
      import_data: window.currentImportData,
      conflict_strategy: conflictStrategy,
      dry_run: dryRun,
      rekey_secret: rekeySecret,
    };

    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify(requestData),
      },
    );

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `Import failed: ${response.statusText}`,
      );
    }

    const result = await response.json();
    displayImportResults(result, dryRun);

    if (!dryRun) {
      // Refresh the current tab data if import was successful
      refreshCurrentTabData();
    }
  } catch (error) {
    console.error("Import error:", error);
    showNotification(`❌ Import failed: ${error.message}`, "error");
  } finally {
    showImportProgress(false);
  }
};

/**
 * Display import results
 */
export const displayImportResults = function (result, isDryRun) {
  const statusSection = safeGetElement("import-status-section");
  if (statusSection) {
    statusSection.classList.remove("hidden");
  }

  const progress = result.progress || {};

  // Update progress bars and counts
  updateImportCounts(progress);

  // Show messages
  displayImportMessages(result.errors || [], result.warnings || [], isDryRun);

  const action = isDryRun ? "validation" : "import";
  const statusText = result.status || "completed";
  showNotification(`✅ ${action} ${statusText}!`, "success");
};

/**
 * Update import progress counts
 */
const updateImportCounts = function (progress) {
  const total = progress.total || 0;
  const processed = progress.processed || 0;
  const created = progress.created || 0;
  const updated = progress.updated || 0;
  const failed = progress.failed || 0;

  safeGetElement("import-total").textContent = total;
  safeGetElement("import-created").textContent = created;
  safeGetElement("import-updated").textContent = updated;
  safeGetElement("import-failed").textContent = failed;

  // Update progress bar
  const progressBar = safeGetElement("import-progress-bar");
  const progressText = safeGetElement("import-progress-text");

  if (progressBar && progressText && total > 0) {
    const percentage = Math.round((processed / total) * 100);
    progressBar.style.width = `${percentage}%`;
    progressText.textContent = `${percentage}%`;
  }
};

/**
 * Display import messages (errors and warnings)
 */
const displayImportMessages = function (errors, warnings, isDryRun) {
  const messagesContainer = safeGetElement("import-messages");
  if (!messagesContainer) {
    return;
  }

  messagesContainer.innerHTML = "";

  // Show errors
  if (errors.length > 0) {
    const errorDiv = document.createElement("div");
    errorDiv.className =
      "bg-red-100 dark:bg-red-900 border border-red-400 dark:border-red-600 text-red-700 dark:text-red-300 px-4 py-3 rounded";
    errorDiv.innerHTML = `
                <div class="font-bold">❌ Errors (${errors.length})</div>
                <ul class="mt-2 text-sm list-disc list-inside">
                    ${errors
    .slice(0, 5)
    .map((error) => `<li>${escapeHtml(error)}</li>`)
    .join("")}
                    ${errors.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${errors.length - 5} more errors</li>` : ""}
                </ul>
            `;
    messagesContainer.appendChild(errorDiv);
  }

  // Show warnings
  if (warnings.length > 0) {
    const warningDiv = document.createElement("div");
    warningDiv.className =
      "bg-yellow-100 dark:bg-yellow-900 border border-yellow-400 dark:border-yellow-600 text-yellow-700 dark:text-yellow-300 px-4 py-3 rounded";
    const warningTitle = isDryRun ? "🔍 Would Import" : "⚠️ Warnings";
    warningDiv.innerHTML = `
                <div class="font-bold">${warningTitle} (${warnings.length})</div>
                <ul class="mt-2 text-sm list-disc list-inside">
                    ${warnings
    .slice(0, 5)
    .map((warning) => `<li>${escapeHtml(warning)}</li>`)
    .join("")}
                    ${warnings.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${warnings.length - 5} more warnings</li>` : ""}
                </ul>
            `;
    messagesContainer.appendChild(warningDiv);
  }
};

/**
 * Show/hide import progress
 */
export const showImportProgress = function (show) {
  // Disable/enable buttons during operation
  const previewBtn = safeGetElement("import-preview-btn");
  const validateBtn = safeGetElement("import-validate-btn");
  const executeBtn = safeGetElement("import-execute-btn");

  if (previewBtn) {
    previewBtn.disabled = show;
  }
  if (validateBtn) {
    validateBtn.disabled = show;
  }
  if (executeBtn) {
    executeBtn.disabled = show;
  }
};

/**
 * Load recent import operations
 */
export const loadRecentImports = async function () {
  try {
    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/status",
      {
        headers: {
          Authorization: `Bearer ${await getAuthToken()}`,
        },
      },
    );

    if (response.ok) {
      const imports = await response.json();
      console.log("Loaded recent imports:", imports.length);
    }
  } catch (error) {
    console.error("Failed to load recent imports:", error);
  }
};

/**
 * Refresh current tab data after successful import
 */
export const refreshCurrentTabData = function () {
  // Find the currently active tab and refresh its data
  const activeTab = document.querySelector(".tab-link.border-indigo-500");
  if (activeTab) {
    const href = activeTab.getAttribute("href");
    if (href === "#catalog") {
      // Refresh servers
      if (typeof window.loadCatalog === "function") {
        window.loadCatalog();
      }
    } else if (href === "#tools") {
      // Refresh tools (for tool-ops-panel when toolops_enabled=true)
      if (typeof loadTools === "function") {
        loadTools();
      }
    } else if (href === "#gateways") {
      // Refresh gateways
      if (typeof window.Admin.loadGateways === "function") {
        window.Admin.loadGateways();
      }
    }
    // Add other tab refresh logic as needed
  }
};
