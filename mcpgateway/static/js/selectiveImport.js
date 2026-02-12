import {
  displayImportResults,
  refreshCurrentTabData,
  showImportProgress,
} from "./fileTransfer.js";
import { getAuthToken } from "./tokens.js";

// ===================================================================
// SELECTIVE IMPORT FUNCTIONS
// ===================================================================

import { safeGetElement, showNotification } from "./utils";

/**
 * Display import preview with selective import options
 */
export const displayImportPreview = function (preview) {
  console.log("📋 Displaying import preview:", preview);

  // Find or create preview container
  let previewContainer = safeGetElement("import-preview-container");
  if (!previewContainer) {
    previewContainer = document.createElement("div");
    previewContainer.id = "import-preview-container";
    previewContainer.className = "mt-6 border-t pt-6";

    // Insert after import options in the import section
    const importSection =
      document.querySelector("#import-drop-zone").parentElement.parentElement;
    importSection.appendChild(previewContainer);
  }

  previewContainer.innerHTML = `
            <h4 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
                📋 Selective Import - Choose What to Import
            </h4>

            <!-- Summary -->
            <div class="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
                <div class="flex items-center">
                    <div class="ml-3">
                        <h3 class="text-sm font-medium text-blue-800 dark:text-blue-200">
                            Found ${preview.summary.total_items} items in import file
                        </h3>
                        <div class="mt-1 text-sm text-blue-600 dark:text-blue-300">
                            ${Object.entries(preview.summary.by_type)
    .map(([type, count]) => `${type}: ${count}`)
    .join(", ")}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Selection Controls -->
            <div class="flex justify-between items-center mb-4">
                <div class="space-x-4">
                    <button onclick="Admin.selectAllItems()"
                            class="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline">
                        Select All
                    </button>
                    <button onclick="Admin.selectNoneItems()"
                            class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-300 underline">
                        Select None
                    </button>
                    <button onclick="Admin.selectOnlyCustom()"
                            class="text-sm text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 underline">
                        Custom Items Only
                    </button>
                </div>

                <div class="text-sm text-gray-500 dark:text-gray-400">
                    <span id="selection-count">0 items selected</span>
                </div>
            </div>

            <!-- Gateway Bundles -->
            ${
  Object.keys(preview.bundles || {}).length > 0
    ? `
                <div class="mb-6">
                    <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3">
                        🌐 Gateway Bundles (Gateway + Auto-discovered Items)
                    </h5>
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        ${Object.entries(preview.bundles)
    .map(
      ([gatewayName, bundle]) => `
                            <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-750">
                                <label class="flex items-start cursor-pointer">
                                    <input type="checkbox"
                                        class="gateway-checkbox mt-1 mr-3"
                                        data-gateway="${gatewayName}"
                                        onchange="Admin.updateSelectionCount()">
                                    <div class="flex-1">
                                        <div class="font-medium text-gray-900 dark:text-white">
                                            ${bundle.gateway.name}
                                        </div>
                                        <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
                                            ${bundle.gateway.description || "No description"}
                                        </div>
                                        <div class="text-xs text-blue-600 dark:text-blue-400">
                                            Bundle includes: ${bundle.total_items} items
                                            (${Object.entries(bundle.items)
    .filter(
      ([type, items]) =>
        items.length > 0
    )
    .map(
      ([type, items]) =>
        `${items.length} ${type}`
    )
    .join(", ")})
                                        </div>
                                    </div>
                                </label>
                            </div>
                        `
    )
    .join("")}
                    </div>
                </div>
            `
    : ""
}

            <!-- Custom Items by Type -->
            ${Object.entries(preview.items || {})
    .map(([entityType, items]) => {
      const customItems = items.filter((item) => item.is_custom);
      return customItems.length > 0
        ? `
                    <div class="mb-6">
                        <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3 capitalize">
                            🛠️ Custom ${entityType}
                        </h5>
                        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            ${customItems
    .map(
      (item) => `
                                <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-3 hover:bg-gray-50 dark:hover:bg-gray-750 ${item.conflicts_with ? "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900" : ""}">
                                    <label class="flex items-start cursor-pointer">
                                        <input type="checkbox"
                                            class="item-checkbox mt-1 mr-3"
                                            data-type="${entityType}"
                                            data-id="${item.id}"
                                            onchange="Admin.updateSelectionCount()">
                                        <div class="flex-1">
                                            <div class="text-sm font-medium text-gray-900 dark:text-white">
                                                ${item.name}
                                                ${
  item.conflicts_with
    ? '<span class="text-orange-600 text-xs ml-1">⚠️ Conflict</span>'
    : ""
}
                                            </div>
                                            <div class="text-xs text-gray-500 dark:text-gray-400">
                                                ${item.description || `Custom ${entityType} item`}
                                            </div>
                                        </div>
                                    </label>
                                </div>
                            `
    )
    .join("")}
                        </div>
                    </div>
                `
        : "";
    })
    .join("")}

            <!-- Conflicts Warning -->
            ${
  Object.keys(preview.conflicts || {}).length > 0
    ? `
                <div class="mb-6">
                    <div class="bg-orange-50 dark:bg-orange-900 border border-orange-200 dark:border-orange-800 rounded-lg p-4">
                        <div class="flex items-start">
                            <div class="flex-shrink-0">
                                <svg class="h-5 w-5 text-orange-400" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                                </svg>
                            </div>
                            <div class="ml-3">
                                <h3 class="text-sm font-medium text-orange-800 dark:text-orange-200">
                                    Naming conflicts detected
                                </h3>
                                <div class="mt-1 text-sm text-orange-600 dark:text-orange-300">
                                    Some items have the same names as existing items. Use conflict strategy to resolve.
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `
    : ""
}

            <!-- Action Buttons -->
            <div class="flex justify-between pt-6 border-t border-gray-200 dark:border-gray-700">
                <button onclick="Admin.resetImportSelection()"
                        class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                    🔄 Reset Selection
                </button>

                <div class="space-x-3">
                    <button onclick="Admin.handleSelectiveImport(true)"
                            class="px-4 py-2 text-sm font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-md hover:bg-blue-100 dark:hover:bg-blue-800">
                        🧪 Preview Selected
                    </button>
                    <button onclick="Admin.handleSelectiveImport(false)"
                            class="px-4 py-2 text-sm font-medium text-white bg-green-600 border border-transparent rounded-md hover:bg-green-700">
                        ✅ Import Selected Items
                    </button>
                </div>
            </div>
        `;

  // Store preview data and show preview section
  updateSelectionCount();
};

/**
 * Handle selective import based on user selections
 */
export const handleSelectiveImport = async function (dryRun = false) {
  console.log(`🎯 Starting selective import (dry_run=${dryRun})`);

  if (!Admin.currentImportData) {
    showNotification("❌ Please select an import file first", "error");
    return;
  }

  try {
    showImportProgress(true);

    // Collect user selections
    const selectedEntities = collectUserSelections();

    if (Object.keys(selectedEntities).length === 0) {
      showNotification(
        "❌ Please select at least one item to import",
        "warning"
      );
      showImportProgress(false);
      return;
    }

    const conflictStrategy =
      safeGetElement("import-conflict-strategy")?.value || "update";
    const rekeySecret = safeGetElement("import-rekey-secret")?.value || null;

    const requestData = {
      import_data: Admin.currentImportData,
      conflict_strategy: conflictStrategy,
      dry_run: dryRun,
      rekey_secret: rekeySecret,
      selectedEntities,
    };

    console.log("🎯 Selected entities for import:", selectedEntities);

    const response = await fetch(
      (window.ROOT_PATH || "") + "/admin/import/configuration",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${await getAuthToken()}`,
        },
        body: JSON.stringify(requestData),
      }
    );

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `Import failed: ${response.statusText}`
      );
    }

    const result = await response.json();
    displayImportResults(result, dryRun);

    if (!dryRun) {
      refreshCurrentTabData();
      showNotification(
        "✅ Selective import completed successfully",
        "success"
      );
    } else {
      showNotification("✅ Import preview completed", "success");
    }
  } catch (error) {
    console.error("Selective import error:", error);
    showNotification(`❌ Import failed: ${error.message}`, "error");
  } finally {
    showImportProgress(false);
  }
};

/**
 * Collect user selections for selective import
 */
const collectUserSelections = function () {
  const selections = {};

  // Collect gateway selections
  document
    .querySelectorAll(".gateway-checkbox:checked")
    .forEach((checkbox) => {
      const gatewayName = checkbox.dataset.gateway;
      if (!selections.gateways) {
        selections.gateways = [];
      }
      selections.gateways.push(gatewayName);
    });

  // Collect individual item selections
  document.querySelectorAll(".item-checkbox:checked").forEach((checkbox) => {
    const entityType = checkbox.dataset.type;
    const itemId = checkbox.dataset.id;
    if (!selections[entityType]) {
      selections[entityType] = [];
    }
    selections[entityType].push(itemId);
  });

  return selections;
};

/**
 * Update selection count display
 */
export const updateSelectionCount = function () {
  const gatewayCount = document.querySelectorAll(
    ".gateway-checkbox:checked"
  ).length;
  const itemCount = document.querySelectorAll(
    ".item-checkbox:checked"
  ).length;
  const totalCount = gatewayCount + itemCount;

  const countElement = safeGetElement("selection-count");
  if (countElement) {
    countElement.textContent = `${totalCount} items selected (${gatewayCount} gateways, ${itemCount} individual items)`;
  }
};

/**
 * Select all items
 */
export const selectAllItems = function () {
  document
    .querySelectorAll(".gateway-checkbox, .item-checkbox")
    .forEach((checkbox) => {
      checkbox.checked = true;
    });
  updateSelectionCount();
};

/**
 * Select no items
 */
export const selectNoneItems = function () {
  document
    .querySelectorAll(".gateway-checkbox, .item-checkbox")
    .forEach((checkbox) => {
      checkbox.checked = false;
    });
  updateSelectionCount();
};

/**
 * Select only custom items (not gateway items)
 */
export const selectOnlyCustom = function () {
  document.querySelectorAll(".gateway-checkbox").forEach((checkbox) => {
    checkbox.checked = false;
  });
  document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
    checkbox.checked = true;
  });
  updateSelectionCount();
};

/**
 * Reset import selection
 */
export const resetImportSelection = function () {
  const previewContainer = safeGetElement("import-preview-container");
  if (previewContainer) {
    previewContainer.remove();
  }
};