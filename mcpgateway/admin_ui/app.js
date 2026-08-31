import { emergencyFixMCPSearch } from "./logging.js";
import { populatePluginFilters } from "./plugins.js";
import { installInnerHtmlGuard } from "./security.js";
import {
  getEditSelections,
  updatePromptMapping,
  updateResourceMapping,
} from "./servers.js";
import { isAdminUser, safeGetElement } from "./utils.js";

((Admin) => {
  // ===================================================================
  // GLOBAL CHART.JS INSTANCE REGISTRY
  // ===================================================================
  // Centralized chart management to prevent "Canvas is already in use" errors
  Admin.chartRegistry = {
    charts: new Map(),

    register(id, chart) {
      // Destroy existing chart with same ID before registering new one
      if (this.charts.has(id)) {
        this.destroy(id);
      }
      this.charts.set(id, chart);
      console.log(`Chart registered: ${id}`);
    },

    destroy(id) {
      const chart = this.charts.get(id);
      if (chart) {
        try {
          chart.destroy();
          console.log(`Chart destroyed: ${id}`);
        } catch (e) {
          console.warn(`Failed to destroy chart ${id}:`, e);
        }
        this.charts.delete(id);
      }
    },

    destroyAll() {
      console.log(`Destroying all charts (${this.charts.size} total)`);
      this.charts.forEach((chart, id) => {
        this.destroy(id);
      });
    },

    destroyByPrefix(prefix) {
      const toDestroy = [];
      this.charts.forEach((chart, id) => {
        if (id.startsWith(prefix)) {
          toDestroy.push(id);
        }
      });
      console.log(
        `Destroying ${toDestroy.length} charts with prefix: ${prefix}`
      );
      toDestroy.forEach((id) => this.destroy(id));
    },

    has(id) {
      return this.charts.has(id);
    },

    get(id) {
      return this.charts.get(id);
    },

    size() {
      return this.charts.size;
    },
  };

  // ===================================================================
  // HTMX HANDLERS for dynamic content loading
  // ===================================================================

  // Set up HTMX handler for auto-checking newly loaded tools when Select All is active or Edit Server mode
  if (window.htmx && !window._toolsHtmxHandlerAttached) {
    Admin._toolsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle tool pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/tools/partial")
      ) {
        // Use a slight delay to ensure DOM is fully updated
        setTimeout(() => {
          // Find which container actually triggered the request by checking the target
          let container = null;
          const target = evt.detail.target;

          // Check if the target itself is the edit server tools container (most common case for infinite scroll)
          if (target && target.id === "edit-server-tools") {
            container = target;
          }
          // Or if target is the associated tools container (for add server)
          else if (target && target.id === "associatedTools") {
            container = target;
          }
          // Otherwise try to find the container using closest
          else if (target) {
            container =
              target.closest("#associatedTools") ||
              target.closest("#edit-server-tools");
          }

          // Fallback logic if container still not found
          if (!container) {
            // Check which modal/dialog is currently open to determine the correct container
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-tools");
            } else {
              container = safeGetElement("associatedTools");
            }
          }

          // Final safety check - use direct lookup if still not found
          if (!container) {
            const addServerContainer = safeGetElement("associatedTools");
            const editServerContainer = safeGetElement("edit-server-tools");

            // Check if edit server container has the server tools data attribute set
            if (
              editServerContainer &&
              editServerContainer.getAttribute("data-server-tools")
            ) {
              container = editServerContainer;
            } else if (
              addServerContainer &&
              addServerContainer.offsetParent !== null
            ) {
              container = addServerContainer;
            } else if (
              editServerContainer &&
              editServerContainer.offsetParent !== null
            ) {
              container = editServerContainer;
            } else {
              // Last resort: just pick one that exists
              container = addServerContainer || editServerContainer;
            }
          }

          if (container) {
            // Update tool mapping for newly loaded tools
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            if (!Admin.toolMapping) {
              Admin.toolMapping = {};
            }

            newCheckboxes.forEach((cb) => {
              const toolId = cb.value;
              const toolName = cb.getAttribute("data-tool-name");
              if (toolId && toolName) {
                Admin.toolMapping[toolId] = toolName;
              }
            });

            const selectAllInput = container.querySelector(
              'input[name="selectAllTools"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
            // Check if we're in Edit Server mode and need to pre-select tools
            else if (container.id === "edit-server-tools") {
              // Try to get server tools from data attribute (primary source)
              let serverTools = null;
              const dataAttr = container.getAttribute("data-server-tools");

              if (dataAttr) {
                try {
                  serverTools = JSON.parse(dataAttr);
                } catch (e) {
                  console.error("Failed to parse data-server-tools:", e);
                }
              }

              const editToolSel = getEditSelections("edit-server-tools");
              if (
                (serverTools && serverTools.length > 0) ||
                editToolSel.size > 0
              ) {
                newCheckboxes.forEach((cb) => {
                  const toolId = cb.value;
                  const toolName = cb.getAttribute("data-tool-name");
                  if (toolId && toolName) {
                    if (
                      (serverTools && serverTools.includes(toolName)) ||
                      editToolSel.has(toolId)
                    ) {
                      cb.checked = true;
                      editToolSel.add(toolId);
                    }
                  }
                  cb.removeAttribute("data-auto-check");
                });

                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
            // If we're in the Add Server tools container, restore persisted selections
            else if (container.id === "associatedTools") {
              const addToolSel = getEditSelections("associatedTools");
              if (addToolSel.size > 0) {
                newCheckboxes.forEach((cb) => {
                  if (addToolSel.has(cb.value)) {
                    cb.checked = true;
                  }
                  cb.removeAttribute("data-auto-check");
                });

                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
          }
        }, 10); // Small delay to ensure DOM is updated
      }
    });
  }

  // Set up HTMX handler for auto-checking newly loaded resources when Select All is active
  if (window.htmx && !window._resourcesHtmxHandlerAttached) {
    Admin._resourcesHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle resource pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/resources/partial")
      ) {
        setTimeout(() => {
          // Find the container
          let container = null;
          const target = evt.detail.target;

          if (target && target.id === "edit-server-resources") {
            container = target;
          } else if (target && target.id === "associatedResources") {
            container = target;
          } else if (target) {
            container =
              target.closest("#associatedResources") ||
              target.closest("#edit-server-resources");
          }

          if (!container) {
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-resources");
            } else {
              container = safeGetElement("associatedResources");
            }
          }

          if (container) {
            // Populate resource mapping for pill display names
            updateResourceMapping(container);
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            const selectAllInput = container.querySelector(
              'input[name="selectAllResources"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // Also check for edit mode: pre-select items based on server's associated resources
            const editResSel = getEditSelections("edit-server-resources");
            const dataAttr = container.getAttribute("data-server-resources");
            let associatedResourceIds = [];
            if (dataAttr) {
              try {
                associatedResourceIds = JSON.parse(dataAttr);
              } catch (e) {
                console.error("Error parsing data-server-resources:", e);
              }
            }

            if (associatedResourceIds.length > 0 || editResSel.size > 0) {
              newCheckboxes.forEach((cb) => {
                const checkboxValue = cb.value;
                if (
                  associatedResourceIds.includes(checkboxValue) ||
                  editResSel.has(checkboxValue)
                ) {
                  cb.checked = true;
                  editResSel.add(checkboxValue);
                }
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // If we're in the Add Server resources container, restore persisted selections
            else if (container.id === "associatedResources") {
              const addResSel = getEditSelections("associatedResources");
              if (addResSel.size > 0) {
                newCheckboxes.forEach((cb) => {
                  if (addResSel.has(cb.value)) {
                    cb.checked = true;
                  }
                  cb.removeAttribute("data-auto-check");
                });

                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
          }
        }, 10);
      }
    });
  }

  // Set up HTMX handler for auto-checking newly loaded prompts when Select All is active
  if (window.htmx && !window._promptsHtmxHandlerAttached) {
    Admin._promptsHtmxHandlerAttached = true;

    window.htmx.on("htmx:afterSettle", function (evt) {
      // Only handle prompt pagination requests
      if (
        evt.detail.pathInfo &&
        evt.detail.pathInfo.requestPath &&
        evt.detail.pathInfo.requestPath.includes("/admin/prompts/partial")
      ) {
        setTimeout(() => {
          // Find the container
          let container = null;
          const target = evt.detail.target;

          if (target && target.id === "edit-server-prompts") {
            container = target;
          } else if (target && target.id === "associatedPrompts") {
            container = target;
          } else if (target) {
            container =
              target.closest("#associatedPrompts") ||
              target.closest("#edit-server-prompts");
          }

          if (!container) {
            const editModal = safeGetElement("server-edit-modal");
            const isEditModalOpen =
              editModal && !editModal.classList.contains("hidden");

            if (isEditModalOpen) {
              container = safeGetElement("edit-server-prompts");
            } else {
              container = safeGetElement("associatedPrompts");
            }
          }

          if (container) {
            // Populate prompt mapping for pill display names
            updatePromptMapping(container);
            const newCheckboxes = container.querySelectorAll(
              "input[data-auto-check=true]"
            );

            const selectAllInput = container.querySelector(
              'input[name="selectAllPrompts"]'
            );

            // Check if Select All is active
            if (selectAllInput && selectAllInput.value === "true") {
              newCheckboxes.forEach((cb) => {
                cb.checked = true;
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // Also check for edit mode: pre-select items based on server's associated prompts
            const editPromptSel = getEditSelections("edit-server-prompts");
            const dataAttr = container.getAttribute("data-server-prompts");
            let associatedPromptIds = [];
            if (dataAttr) {
              try {
                associatedPromptIds = JSON.parse(dataAttr);
              } catch (e) {
                console.error("Error parsing data-server-prompts:", e);
              }
            }

            if (associatedPromptIds.length > 0 || editPromptSel.size > 0) {
              newCheckboxes.forEach((cb) => {
                const checkboxValue = cb.value;
                if (
                  associatedPromptIds.includes(checkboxValue) ||
                  editPromptSel.has(checkboxValue)
                ) {
                  cb.checked = true;
                  editPromptSel.add(checkboxValue);
                }
                cb.removeAttribute("data-auto-check");
              });

              if (newCheckboxes.length > 0) {
                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }

            // If we're in the Add Server prompts container, restore persisted selections
            else if (container.id === "associatedPrompts") {
              const addPromptSel = getEditSelections("associatedPrompts");
              if (addPromptSel.size > 0) {
                newCheckboxes.forEach((cb) => {
                  if (addPromptSel.has(cb.value)) {
                    cb.checked = true;
                  }
                  cb.removeAttribute("data-auto-check");
                });

                const event = new Event("change", {
                  bubbles: true,
                });
                container.dispatchEvent(event);
              }
            }
          }
        }, 10);
      }
    });
  }

  installInnerHtmlGuard();

  // Initialize plugin functions if plugins panel exists
  if (isAdminUser() && safeGetElement("plugins-panel")) {
    // Populate filter dropdowns on initial load
    if (populatePluginFilters) {
      populatePluginFilters();
    }
  }

  // Auto-fix MCP Search on page load
  setTimeout(function () {
    console.log("🔄 AUTO-FIX: Attempting to fix MCP search after page load...");
    emergencyFixMCPSearch();
  }, 1000);
})(window.Admin);
