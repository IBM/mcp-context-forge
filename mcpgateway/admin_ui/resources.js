import { getSelectedGatewayIds } from "./gateway.js";
import { openModal } from "./modals.js";
import { validateInputName } from "./security.js";
import { fetchWithTimeout, getCurrentTeamId, handleFetchError, isInactiveChecked, parseUriTemplate, safeGetElement, showErrorMessage } from "./utils";

export const testResource = async function (resourceId) {
  try {
    console.log(`Testing the resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
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

    const data = await response.json();
    const resource = data.resource;
    //  console.log("Resource JSON:\n", JSON.stringify(resource, null, 2));
    openResourceTestModal(resource);
  } catch (error) {
    console.error("Error fetching resource details:", error);
    const errorMessage = handleFetchError(error, "load resource details");
    showErrorMessage(errorMessage);
  }
};

export const openResourceTestModal = function (resource) {
  const title = safeGetElement("resource-test-modal-title");
  const fieldsContainer = safeGetElement("resource-test-form-fields");
  const resultBox = safeGetElement("resource-test-result");

  title.textContent = `Test Resource: ${resource.name}`;

  fieldsContainer.innerHTML = "";
  resultBox.textContent = "Fill the fields and click Invoke Resource";

  // 1️⃣ Build form fields ONLY if uriTemplate exists
  if (resource.uriTemplate) {
    const fieldNames = parseUriTemplate(resource.uriTemplate);

    fieldNames.forEach((name) => {
      const div = document.createElement("div");
      div.className = "space-y-1";

      div.innerHTML = `
                <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                    ${name}
                </label>
                <input type="text"
                    id="resource-field-${name}"
                    class="mt-1 px-2 py-1 block w-full rounded-md border border-gray-300 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-300"
                />
            `;

      fieldsContainer.appendChild(div);
    });
  } else {
    // 2️⃣ If no template → show a simple message
    fieldsContainer.innerHTML = `
            <div class="text-gray-500 dark:text-gray-400 italic">
                This resource has no URI template.
                Click "Invoke Resource" to test directly.
            </div>
        `;
  }

  window.Admin.CurrentResourceUnderTest = resource;
  openModal("resource-test-modal");
};

export const runResourceTest = async function () {
  const resource = window.Admin.CurrentResourceUnderTest;
  if (!resource) {
    return;
  }

  let finalUri = "";

  if (resource.uriTemplate) {
    finalUri = resource.uriTemplate;

    const fieldNames = parseUriTemplate(resource.uriTemplate);
    fieldNames.forEach((name) => {
      const value = safeGetElement(`resource-field-${name}`).value;
      finalUri = finalUri.replace(`{${name}}`, encodeURIComponent(value));
    });
  } else {
    finalUri = resource.uri; // direct test
  }

  console.log("Final URI:", finalUri);

  const response = await fetchWithTimeout(
    `${window.ROOT_PATH}/admin/resources/test/${encodeURIComponent(finalUri)}`
  );

  const json = await response.json();

  const resultBox = safeGetElement("resource-test-result");
  resultBox.innerHTML = ""; // clear previous

  const container = document.createElement("div");
  resultBox.appendChild(container);

  // Extract the content text (fallback if missing)
  const content = json.content || {};
  let contentStr = content.text || JSON.stringify(content, null, 2);

  // Try to prettify JSON content
  try {
    const parsed = JSON.parse(contentStr);
    contentStr = JSON.stringify(parsed, null, 2);
  } catch (_) {}

  // ---- Content Section (same as prompt tester) ----
  const contentSection = document.createElement("div");
  contentSection.className = "mt-4";

  // Header
  const contentHeader = document.createElement("div");
  contentHeader.className =
    "flex items-center justify-between cursor-pointer select-none p-2 bg-gray-200 dark:bg-gray-700 rounded";
  contentSection.appendChild(contentHeader);

  // Title
  const contentTitle = document.createElement("strong");
  contentTitle.textContent = "Content";
  contentHeader.appendChild(contentTitle);

  // Right controls (arrow/copy/fullscreen/download)
  const headerRight = document.createElement("div");
  headerRight.className = "flex items-center space-x-2";
  contentHeader.appendChild(headerRight);

  // Arrow icon
  const toggleIcon = document.createElement("span");
  toggleIcon.innerHTML = "▶";
  toggleIcon.className = "transform transition-transform text-xs";
  headerRight.appendChild(toggleIcon);

  // Copy button
  const copyBtn = document.createElement("button");
  copyBtn.textContent = "Copy";
  copyBtn.className =
    "text-xs px-2 py-1 rounded bg-gray-300 dark:bg-gray-600 hover:bg-gray-400 dark:hover:bg-gray-500";
  headerRight.appendChild(copyBtn);

  // Fullscreen button
  const fullscreenBtn = document.createElement("button");
  fullscreenBtn.textContent = "Fullscreen";
  fullscreenBtn.className =
    "text-xs px-2 py-1 rounded bg-blue-300 dark:bg-blue-600 hover:bg-blue-400 dark:hover:bg-blue-500";
  headerRight.appendChild(fullscreenBtn);

  // Download button
  const downloadBtn = document.createElement("button");
  downloadBtn.textContent = "Download";
  downloadBtn.className =
    "text-xs px-2 py-1 rounded bg-green-300 dark:bg-green-600 hover:bg-green-400 dark:hover:bg-green-500";
  headerRight.appendChild(downloadBtn);

  // Collapsible body
  const contentBody = document.createElement("div");
  contentBody.className = "hidden mt-2";
  contentSection.appendChild(contentBody);

  // Pre block
  const contentPre = document.createElement("pre");
  contentPre.className =
    "bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100 text-sm whitespace-pre-wrap";
  contentPre.textContent = contentStr;
  contentBody.appendChild(contentPre);

  // Auto-collapse if too large
  const lineCount = contentStr.split("\n").length;

  if (lineCount > 30) {
    contentBody.classList.add("hidden");
    toggleIcon.style.transform = "rotate(0deg)";
    contentTitle.textContent = "Content (Large - Click to expand)";
  } else {
    contentBody.classList.remove("hidden");
    toggleIcon.style.transform = "rotate(90deg)";
  }

  // Toggle expand/collapse
  contentHeader.onclick = () => {
    contentBody.classList.toggle("hidden");
    toggleIcon.style.transform = contentBody.classList.contains("hidden")
      ? "rotate(0deg)"
      : "rotate(90deg)";
  };

  // Copy button
  copyBtn.onclick = (event) => {
    event.stopPropagation();
    navigator.clipboard.writeText(contentStr).then(() => {
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
    });
  };

  // Fullscreen mode
  fullscreenBtn.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();

    const overlay = document.createElement("div");
    overlay.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    overlay.className =
      "fixed inset-0 bg-black bg-opacity-70 z-[9999] flex items-center justify-center p-4";

    const box = document.createElement("div");
    box.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    box.className =
      "bg-white dark:bg-gray-900 rounded-lg w-full h-full p-4 overflow-auto";

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close";
    closeBtn.className =
      "text-xs px-3 py-1 mb-2 rounded bg-red-400 hover:bg-red-500 dark:bg-red-700 dark:hover:bg-red-600";

    closeBtn.onclick = () => overlay.remove();

    const fsPre = document.createElement("pre");
    fsPre.className =
      "bg-gray-100 p-4 rounded overflow-auto h-full dark:bg-gray-800 dark:text-gray-100 text-sm whitespace-pre-wrap";
    fsPre.textContent = contentStr;

    box.appendChild(closeBtn);
    box.appendChild(fsPre);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  };

  // Download
  downloadBtn.onclick = (event) => {
    event.stopPropagation();

    let blob;
    let filename;

    // JSON?
    try {
      JSON.parse(contentStr);
      blob = new Blob([contentStr], { type: "application/json" });
      filename = "resource.json";
    } catch (_) {
      blob = new Blob([contentStr], { type: "text/plain" });
      filename = "resource.txt";
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  container.appendChild(contentSection);

  // resultBox.textContent = JSON.stringify(json, null, 2);
};

/**
 * SECURE: View Resource function with safe display
 */
export const viewResource = async function (resourceId) {
  try {
    console.log(`Viewing resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
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

    const data = await response.json();
    const resource = data.resource;

    // console.log("Resource JSON:\n", JSON.stringify(resource, null, 2));
    // const content = data.content;

    const resourceDetailsDiv = safeGetElement("resource-details");
    if (resourceDetailsDiv) {
      // Create safe display elements
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      // Add each piece of information safely
      const fields = [
        { label: "URI", value: resource.uri },
        { label: "Name", value: resource.name },
        { label: "Type", value: resource.mimeType || "N/A" },
        { label: "Description", value: resource.description || "N/A" },
        {
          label: "Visibility",
          value: resource.visibility || "private",
        },
      ];

      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Tags section
      const tagsP = document.createElement("p");
      const tagsStrong = document.createElement("strong");
      tagsStrong.textContent = "Tags: ";
      tagsP.appendChild(tagsStrong);

      if (resource.tags && resource.tags.length > 0) {
        resource.tags.forEach((tag) => {
          const tagSpan = document.createElement("span");
          tagSpan.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
          const raw =
            typeof tag === "object" && tag !== null
              ? tag.id || tag.label || JSON.stringify(tag)
              : tag;
          tagSpan.textContent = raw;
          tagsP.appendChild(tagSpan);
        });
      } else {
        tagsP.appendChild(document.createTextNode("None"));
      }
      container.appendChild(tagsP);

      // Status with safe styling
      const statusP = document.createElement("p");
      const statusStrong = document.createElement("strong");
      statusStrong.textContent = "Status: ";
      statusP.appendChild(statusStrong);

      const isActive = resource.enabled === true;
      const statusSpan = document.createElement("span");
      statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
        isActive ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
      }`;
      statusSpan.textContent = isActive ? "Active" : "Inactive";

      statusP.appendChild(statusSpan);
      container.appendChild(statusP);

      // Content display - safely handle different types
      // const contentDiv = document.createElement("div");
      // const contentStrong = document.createElement("strong");
      // contentStrong.textContent = "Content:";
      // contentDiv.appendChild(contentStrong);

      // const contentPre = document.createElement("pre");
      // contentPre.className =
      //     "mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100";

      // // Handle content display - extract actual content from object if needed
      // let contentStr = extractContent(
      //     content,
      //     resource.description || "No content available",
      // );

      // if (!contentStr.trim()) {
      //     contentStr = resource.description || "No content available";
      // }

      // contentPre.textContent = contentStr;
      // contentDiv.appendChild(contentPre);
      // container.appendChild(contentDiv);

      // Metrics display
      if (resource.metrics) {
        const metricsDiv = document.createElement("div");
        const metricsStrong = document.createElement("strong");
        metricsStrong.textContent = "Metrics:";
        metricsDiv.appendChild(metricsStrong);

        const metricsList = document.createElement("ul");
        metricsList.className = "list-disc list-inside ml-4";

        const metricsData = [
          {
            label: "Total Executions",
            value: resource.metrics.totalExecutions ?? 0,
          },
          {
            label: "Successful Executions",
            value: resource.metrics.successfulExecutions ?? 0,
          },
          {
            label: "Failed Executions",
            value: resource.metrics.failedExecutions ?? 0,
          },
          {
            label: "Failure Rate",
            value: resource.metrics.failureRate ?? 0,
          },
          {
            label: "Min Response Time",
            value: resource.metrics.minResponseTime ?? "N/A",
          },
          {
            label: "Max Response Time",
            value: resource.metrics.maxResponseTime ?? "N/A",
          },
          {
            label: "Average Response Time",
            value: resource.metrics.avgResponseTime ?? "N/A",
          },
          {
            label: "Last Execution Time",
            value: resource.metrics.lastExecutionTime ?? "N/A",
          },
        ];

        metricsData.forEach((metric) => {
          const li = document.createElement("li");
          li.textContent = `${metric.label}: ${metric.value}`;
          metricsList.appendChild(li);
        });

        metricsDiv.appendChild(metricsList);
        container.appendChild(metricsDiv);
      }

      // Add metadata section
      const metadataDiv = document.createElement("div");
      metadataDiv.className = "mt-6 border-t pt-4";

      const metadataTitle = document.createElement("strong");
      metadataTitle.textContent = "Metadata:";
      metadataDiv.appendChild(metadataTitle);

      const metadataGrid = document.createElement("div");
      metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

      const metadataFields = [
        {
          label: "Created By",
          value: resource.created_by || resource.createdBy || "Legacy Entity",
        },
        {
          label: "Created At",
          value:
            resource.created_at || resource.createdAt
              ? new Date(
                resource.created_at || resource.createdAt
              ).toLocaleString()
              : "Pre-metadata",
        },
        {
          label: "Created From IP",
          value:
            resource.created_from_ip || resource.createdFromIp || "Unknown",
        },
        {
          label: "Created Via",
          value: resource.created_via || resource.createdVia || "Unknown",
        },
        {
          label: "Last Modified By",
          value: resource.modified_by || resource.modifiedBy || "N/A",
        },
        {
          label: "Last Modified At",
          value:
            resource.updated_at || resource.updatedAt
              ? new Date(
                resource.updated_at || resource.updatedAt
              ).toLocaleString()
              : "N/A",
        },
        {
          label: "Modified From IP",
          value: resource.modified_from_ip || resource.modifiedFromIp || "N/A",
        },
        {
          label: "Modified Via",
          value: resource.modified_via || resource.modifiedVia || "N/A",
        },
        {
          label: "Version",
          value: resource.version || "1",
        },
        {
          label: "Import Batch",
          value: resource.import_batch_id || resource.importBatchId || "N/A",
        },
      ];

      metadataFields.forEach((field) => {
        const fieldDiv = document.createElement("div");

        const labelSpan = document.createElement("span");
        labelSpan.className = "font-medium text-gray-600 dark:text-gray-400";
        labelSpan.textContent = field.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "ml-2";
        valueSpan.textContent = field.value;

        fieldDiv.appendChild(labelSpan);
        fieldDiv.appendChild(valueSpan);
        metadataGrid.appendChild(fieldDiv);
      });

      metadataDiv.appendChild(metadataGrid);
      container.appendChild(metadataDiv);

      // Replace content safely
      resourceDetailsDiv.innerHTML = "";
      resourceDetailsDiv.appendChild(container);
    }

    openModal("resource-modal");
    console.log("✓ Resource details loaded successfully");
  } catch (error) {
    console.error("Error fetching resource details:", error);
    const errorMessage = handleFetchError(error, "load resource details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Resource function with validation
 */
export const editResource = async function (resourceId) {
  try {
    console.log(`Editing resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
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

    const data = await response.json();
    const resource = data.resource;
    // const content = data.content;
    // Ensure hidden inactive flag is preserved
    const isInactiveCheckedBool = isInactiveChecked("resources");
    let hiddenField = safeGetElement("edit-resource-show-inactive");
    const editForm = safeGetElement("edit-resource-form");

    if (!hiddenField && editForm) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-resource-show-inactive";
      const editForm = safeGetElement("edit-resource-form");
      editForm.appendChild(hiddenField);
    }
    hiddenField.value = isInactiveCheckedBool;

    // ✅ Prefill visibility radios (consistent with server)
    const visibility = resource.visibility
      ? resource.visibility.toLowerCase()
      : null;

    const publicRadio = safeGetElement("edit-resource-visibility-public");
    const teamRadio = safeGetElement("edit-resource-visibility-team");
    const privateRadio = safeGetElement("edit-resource-visibility-private");

    // Clear all first
    if (publicRadio) {
      publicRadio.checked = false;
    }
    if (teamRadio) {
      teamRadio.checked = false;
    }
    if (privateRadio) {
      privateRadio.checked = false;
    }

    if (visibility) {
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    // Set form action and populate fields with validation
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}/edit`;
    }

    // Validate inputs
    const nameValidation = validateInputName(resource.name, "resource");
    const uriValidation = validateInputName(resource.uri, "resource URI");

    const uriField = safeGetElement("edit-resource-uri");
    const nameField = safeGetElement("edit-resource-name");
    const descField = safeGetElement("edit-resource-description");
    const mimeField = safeGetElement("edit-resource-mime-type");
    // const contentField = safeGetElement("edit-resource-content");

    if (uriField && uriValidation.valid) {
      uriField.value = uriValidation.value;
    }
    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (descField) {
      descField.value = resource.description || "";
    }
    if (mimeField) {
      mimeField.value = resource.mimeType || "";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-resource-tags");
    if (tagsField) {
      const rawTags = resource.tags
        ? resource.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    // if (contentField) {
    //     let contentStr = extractContent(
    //         content,
    //         resource.description || "No content available",
    //     );

    //     if (!contentStr.trim()) {
    //         contentStr = resource.description || "No content available";
    //     }

    //     contentField.value = contentStr;
    // }

    // // Update CodeMirror editor if it exists
    // if (window.editResourceContentEditor) {
    //     let contentStr = extractContent(
    //         content,
    //         resource.description || "No content available",
    //     );

    //     if (!contentStr.trim()) {
    //         contentStr = resource.description || "No content available";
    //     }

    //     window.editResourceContentEditor.setValue(contentStr);
    //     window.editResourceContentEditor.refresh();
    // }

    openModal("resource-edit-modal");

    // Refresh editor after modal display
    setTimeout(() => {
      if (window.editResourceContentEditor) {
        window.editResourceContentEditor.refresh();
      }
    }, 100);

    console.log("✓ Resource edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching resource for editing:", error);
    const errorMessage = handleFetchError(error, "load resource for editing");
    showErrorMessage(errorMessage);
  }
};

export const initResourceSelect = function (
  selectId,
  pillsId,
  warnId,
  max = 10,
  selectBtnId = null,
  clearBtnId = null
) {
  const container = safeGetElement(selectId);
  const pillsBox = safeGetElement(pillsId);
  const warnBox = safeGetElement(warnId);
  const clearBtn = clearBtnId ? safeGetElement(clearBtnId) : null;
  const selectBtn = selectBtnId ? safeGetElement(selectBtnId) : null;

  if (!container || !pillsBox || !warnBox) {
    console.warn(
      `Resource select elements not found: ${selectId}, ${pillsId}, ${warnId}`
    );
    return;
  }

  const pillClasses =
    "inline-block px-3 py-1 text-xs font-semibold text-blue-700 bg-blue-100 rounded-full shadow dark:text-blue-300 dark:bg-blue-900";

  const update = function () {
    try {
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      const checked = Array.from(checkboxes).filter((cb) => cb.checked);

      // Select All handling
      const selectAllInput = container.querySelector(
        'input[name="selectAllResources"]'
      );
      const allIdsInput = container.querySelector(
        'input[name="allResourceIds"]'
      );

      // Get persisted selections for Add Server mode
      let persistedResourceIds = [];
      if (selectId === "associatedResources") {
        const dataAttr = container.getAttribute("data-selected-resources");
        if (dataAttr) {
          try {
            persistedResourceIds = JSON.parse(dataAttr);
          } catch (e) {
            console.error("Error parsing data-selected-resources:", e);
          }
        }
        if (
          (!persistedResourceIds || persistedResourceIds.length === 0) &&
          Array.isArray(window.Admin._selectedAssociatedResources)
        ) {
          persistedResourceIds = window.Admin._selectedAssociatedResources.slice();
        }
      }

      let count = checked.length;
      const pillsData = [];

      if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
        try {
          const allIds = JSON.parse(allIdsInput.value);
          count = allIds.length;
        } catch (e) {
          console.error("Error parsing allResourceIds:", e);
        }
      }
      // If in Add Server mode with persisted selections, use persisted count and build pills from persisted data
      else if (
        selectId === "associatedResources" &&
        persistedResourceIds &&
        persistedResourceIds.length > 0
      ) {
        count = persistedResourceIds.length;
        // Build pill data from persisted IDs - find matching checkboxes or use ID as fallback
        const checkboxMap = new Map();
        checkboxes.forEach((cb) => {
          checkboxMap.set(
            cb.value,
            cb.nextElementSibling?.textContent?.trim() || cb.value
          );
        });
        persistedResourceIds.forEach((id) => {
          const name = checkboxMap.get(id) || id;
          pillsData.push({ id, name });
        });
      }

      // Rebuild pills safely - show first 3, then summarize the rest
      pillsBox.innerHTML = "";
      const maxPillsToShow = 3;

      // Determine which pills to display based on mode
      if (selectId === "associatedResources" && pillsData.length > 0) {
        // In Add Server mode with persisted data, show pills from persisted selections
        pillsData.slice(0, maxPillsToShow).forEach((item) => {
          const span = document.createElement("span");
          span.className = pillClasses;
          span.textContent = item.name || "Unnamed";
          span.title = item.name;
          pillsBox.appendChild(span);
        });
      } else {
        // Default: show pills from currently checked checkboxes
        checked.slice(0, maxPillsToShow).forEach((cb) => {
          const span = document.createElement("span");
          span.className = pillClasses;
          span.textContent =
            cb.nextElementSibling?.textContent?.trim() || "Unnamed";
          pillsBox.appendChild(span);
        });
      }

      // If more than maxPillsToShow, show a summary pill
      if (count > maxPillsToShow) {
        const span = document.createElement("span");
        span.className = pillClasses + " cursor-pointer";
        span.title = "Click to see all selected resources";
        const remaining = count - maxPillsToShow;
        span.textContent = `+${remaining} more`;
        pillsBox.appendChild(span);
      }

      // Warning when > max
      if (count > max) {
        warnBox.textContent = `Selected ${count} resources. Selecting more than ${max} resources can degrade agent performance with the server.`;
      } else {
        warnBox.textContent = "";
      }
    } catch (error) {
      console.error("Error updating resource select:", error);
    }
  };

  // Remove old event listeners by cloning and replacing (preserving ID)
  if (clearBtn && !clearBtn.dataset.listenerAttached) {
    clearBtn.dataset.listenerAttached = "true";
    const newClearBtn = clearBtn.cloneNode(true);
    newClearBtn.dataset.listenerAttached = "true";
    clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

    newClearBtn.addEventListener("click", () => {
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach((cb) => (cb.checked = false));

      // Remove any select-all hidden inputs
      const selectAllInput = container.querySelector(
        'input[name="selectAllResources"]'
      );
      if (selectAllInput) {
        selectAllInput.remove();
      }
      const allIdsInput = container.querySelector(
        'input[name="allResourceIds"]'
      );
      if (allIdsInput) {
        allIdsInput.remove();
      }

      update();
    });
  }

  if (selectBtn && !selectBtn.dataset.listenerAttached) {
    selectBtn.dataset.listenerAttached = "true";
    const newSelectBtn = selectBtn.cloneNode(true);
    newSelectBtn.dataset.listenerAttached = "true";
    selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);

    newSelectBtn.addEventListener("click", async () => {
      const originalText = newSelectBtn.textContent;
      newSelectBtn.disabled = true;
      newSelectBtn.textContent = "Selecting all resources...";

      try {
        // Prefer full-set selection when pagination/infinite-scroll is present
        const loadedCheckboxes = container.querySelectorAll(
          'input[type="checkbox"]'
        );
        const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
          (cb) => cb.offsetParent !== null
        );

        // Detect pagination/infinite-scroll controls for resources
        const hasPaginationControls = !!safeGetElement(
          "resources-pagination-controls"
        );
        const hasScrollTrigger = !!document.querySelector(
          "[id^='resources-scroll-trigger']"
        );
        const isPaginated = hasPaginationControls || hasScrollTrigger;

        let allIds = [];

        if (!isPaginated && visibleCheckboxes.length > 0) {
          // No pagination and some visible items => select visible set
          allIds = visibleCheckboxes.map((cb) => cb.value);
          visibleCheckboxes.forEach((cb) => (cb.checked = true));
        } else {
          // Paginated (or no visible items) => fetch full set from server
          const selectedGatewayIds = getSelectedGatewayIds
            ? getSelectedGatewayIds()
            : [];
          const selectedTeamId = getCurrentTeamId();
          const params = new URLSearchParams();
          if (selectedGatewayIds && selectedGatewayIds.length) {
            params.set("gateway_id", selectedGatewayIds.join(","));
          }
          if (selectedTeamId) {
            params.set("team_id", selectedTeamId);
          }
          const queryString = params.toString();
          const resp = await fetch(
            `${window.ROOT_PATH}/admin/resources/ids${queryString ? `?${queryString}` : ""}`
          );
          if (!resp.ok) {
            throw new Error("Failed to fetch resource IDs");
          }
          const data = await resp.json();
          allIds = data.resource_ids || [];
          // If nothing visible (paginated), check loaded checkboxes
          loadedCheckboxes.forEach((cb) => (cb.checked = true));
        }

        // Add hidden select-all flag
        let selectAllInput = container.querySelector(
          'input[name="selectAllResources"]'
        );
        if (!selectAllInput) {
          selectAllInput = document.createElement("input");
          selectAllInput.type = "hidden";
          selectAllInput.name = "selectAllResources";
          container.appendChild(selectAllInput);
        }
        selectAllInput.value = "true";

        // Store IDs as JSON for backend handling
        let allIdsInput = container.querySelector(
          'input[name="allResourceIds"]'
        );
        if (!allIdsInput) {
          allIdsInput = document.createElement("input");
          allIdsInput.type = "hidden";
          allIdsInput.name = "allResourceIds";
          container.appendChild(allIdsInput);
        }
        allIdsInput.value = JSON.stringify(allIds);

        update();

        newSelectBtn.textContent = `✓ All ${allIds.length} resources selected`;
        setTimeout(() => {
          newSelectBtn.textContent = originalText;
        }, 2000);
      } catch (error) {
        console.error("Error selecting all resources:", error);
        alert("Failed to select all resources. Please try again.");
      } finally {
        newSelectBtn.disabled = false;
      }
    });
  }

  update(); // Initial render

  // Attach change listeners using delegation for dynamic content
  if (!container.dataset.changeListenerAttached) {
    container.dataset.changeListenerAttached = "true";
    container.addEventListener("change", (e) => {
      if (e.target.type === "checkbox") {
        // If Select All mode is active, update the stored IDs array
        const selectAllInput = container.querySelector(
          'input[name="selectAllResources"]'
        );
        const allIdsInput = container.querySelector(
          'input[name="allResourceIds"]'
        );

        if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
          try {
            let allIds = JSON.parse(allIdsInput.value);
            const id = e.target.value;
            if (e.target.checked) {
              if (!allIds.includes(id)) {
                allIds.push(id);
              }
            } else {
              allIds = allIds.filter((x) => x !== id);
            }
            allIdsInput.value = JSON.stringify(allIds);
          } catch (err) {
            console.error("Error updating allResourceIds:", err);
          }
        }

        // If we're in the edit-server-resources container, maintain the
        // `data-server-resources` attribute so user selections persist
        // across gateway-filtered reloads.
        else if (selectId === "edit-server-resources") {
          try {
            let serverResources = [];
            const dataAttr = container.getAttribute("data-server-resources");
            if (dataAttr) {
              try {
                serverResources = JSON.parse(dataAttr);
              } catch (e) {
                console.error("Error parsing data-server-resources:", e);
              }
            }

            const idVal = e.target.value;
            if (!Number.isNaN(idVal)) {
              if (e.target.checked) {
                if (!serverResources.includes(idVal)) {
                  serverResources.push(idVal);
                }
              } else {
                serverResources = serverResources.filter((x) => x !== idVal);
              }

              container.setAttribute(
                "data-server-resources",
                JSON.stringify(serverResources)
              );
            }
          } catch (err) {
            console.error("Error updating data-server-resources:", err);
          }
        }
        // If we're in the Add Server resources container, persist selected IDs incrementally
        else if (selectId === "associatedResources") {
          try {
            const changedEl = e.target;
            const changedId = changedEl.value;

            let persisted = [];
            const dataAttr = container.getAttribute("data-selected-resources");
            if (dataAttr) {
              try {
                const parsed = JSON.parse(dataAttr);
                if (Array.isArray(parsed)) {
                  persisted = parsed.slice();
                }
              } catch (parseErr) {
                console.error(
                  "Error parsing existing data-selected-resources:",
                  parseErr
                );
              }
            } else if (Array.isArray(window.Admin._selectedAssociatedResources)) {
              persisted = window.Admin._selectedAssociatedResources.slice();
            }

            if (changedEl.checked) {
              if (!persisted.includes(changedId)) {
                persisted.push(changedId);
              }
            } else {
              persisted = persisted.filter((x) => x !== changedId);
            }

            const visibleChecked = Array.from(
              container.querySelectorAll('input[type="checkbox"]:checked')
            ).map((cb) => cb.value);
            visibleChecked.forEach((id) => {
              if (!persisted.includes(id)) {
                persisted.push(id);
              }
            });

            container.setAttribute(
              "data-selected-resources",
              JSON.stringify(persisted)
            );
            try {
              window.Admin._selectedAssociatedResources = persisted.slice();
            } catch (err) {
              console.error(
                "Error persisting Admin._selectedAssociatedResources:",
                err
              );
            }
          } catch (err) {
            console.error(
              "Error updating data-selected-resources (incremental):",
              err
            );
          }
        }

        update();
      }
    });
  }
};

/**
 * Clean up resource test modal state
 */
export const cleanupResourceTestModal = function () {
  try {
    // Clear stored state
    window.Admin.CurrentResourceUnderTest = null;

    // Reset form fields container
    const fieldsContainer = safeGetElement("resource-test-form-fields");
    if (fieldsContainer) {
      fieldsContainer.innerHTML = "";
    }

    // Reset result box
    const resultBox = safeGetElement("resource-test-result");
    if (resultBox) {
      resultBox.innerHTML = `
                <div class="text-gray-500 dark:text-gray-400 italic">
                    Fill the fields and click Invoke Resource
                </div>
            `;
    }

    // Hide loading if exists
    const loading = safeGetElement("resource-test-loading");
    if (loading) {
      loading.classList.add("hidden");
    }

    console.log("✓ Resource test modal cleaned up");
  } catch (err) {
    console.error("Error cleaning up resource test modal:", err);
  }
};
