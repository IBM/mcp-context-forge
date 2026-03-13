import { openModal } from "./modals.js";
import { validateInputName } from "./security.js";
import {
  safeGetElement,
  fetchWithTimeout,
  isInactiveChecked,
  handleFetchError,
  showErrorMessage,
} from "./utils.js";

// -------------------- Root Management ------------------ //

/**
 * SECURE: View Root function with safe display
 */
export const viewRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const root = await response.json();

    const rootDetailsDiv = safeGetElement("root-details");
    if (rootDetailsDiv) {
      // Create safe display elements
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      // Add each piece of information safely
      const fields = [
        { label: "URI", value: root.uri },
        { label: "Name", value: root.name || "N/A" },
      ];

      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Replace content safely
      rootDetailsDiv.innerHTML = "";
      rootDetailsDiv.appendChild(container);
    }

    openModal("root-details-modal");
  } catch (error) {
    console.error("Error fetching root details:", error);
    const errorMessage = handleFetchError(error, "load root details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Root function with validation
 */
export const editRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const root = await response.json();

    // Ensure hidden inactive flag is preserved
    const isInactiveCheckedBool = isInactiveChecked("roots");
    let hiddenField = safeGetElement("edit-root-show-inactive");
    const editForm = safeGetElement("edit-root-form");

    if (!hiddenField && editForm) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-root-show-inactive";
      editForm.appendChild(hiddenField);
    }
    if (hiddenField) {
      hiddenField.value = isInactiveCheckedBool;
    }

    // Set form action and populate fields with validation
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}/update`;
    }

    // Validate inputs
    const nameValidation = validateInputName(root.name || "", "root name");
    const uriValidation = validateInputName(root.uri, "root URI");

    const uriField = safeGetElement("edit-root-uri");
    const nameField = safeGetElement("edit-root-name");

    // URI is read-only, just display it
    if (uriField && uriValidation.valid) {
      uriField.value = uriValidation.value;
    }

    // Name is editable
    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    } else if (nameField) {
      // If name is null/empty, set empty string
      nameField.value = "";
    }

    openModal("root-edit-modal");
  } catch (error) {
    console.error("Error fetching root for editing:", error);
    const errorMessage = handleFetchError(error, "load root for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * Handle export root details
 */
export const exportRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/export?uri=${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Trigger download
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;

    // Safely extract filename from Content-Disposition header
    const contentDisposition = response.headers.get("Content-Disposition");
    let filename = `root-export-${Date.now()}.json`;
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (filenameMatch && filenameMatch[1]) {
        filename = filenameMatch[1];
      }
    }
    a.download = filename;

    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  } catch (error) {
    console.error("Error exporting root:", error);
    showErrorMessage("Failed to export root");
  }
};
