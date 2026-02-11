import { getSelectedGatewayIds } from "./gateway";
import { getCurrentTeamId, safeGetElement } from "./utils";

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
          Array.isArray(Admin._selectedAssociatedResources)
        ) {
          persistedResourceIds = Admin._selectedAssociatedResources.slice();
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
            } else if (Array.isArray(Admin._selectedAssociatedResources)) {
              persisted = Admin._selectedAssociatedResources.slice();
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
              Admin._selectedAssociatedResources = persisted.slice();
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
    Admin.CurrentResourceUnderTest = null;

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
