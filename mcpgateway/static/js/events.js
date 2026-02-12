import { AppState } from "./appState";
import { initializeCACertUpload } from "./caCertificate";
import { setupFormValidation } from "./formValidation";
import { initGatewaySelect } from "./gateway";
import {
  initializeCodeMirrorEditors,
  initializeEventListeners,
  initializeExportImport,
  initializeSearchInputs,
  initializeTabState,
  initializeToolSelects,
  registerReloadAllResourceSections,
  setupBulkImportModal,
  setupTooltipsWithAlpine,
} from "./initialization";
import { closeModal } from "./modals";
import { initializeRealTimeMonitoring } from "./monitoring";
import { initializeTagFiltering } from "./tags";
import { initializePasswordValidation } from "./teams";
import { initializeTeamScopingMonitor } from "./tokens";
import { cleanupToolTestState, loadTools } from "./tools";
import {
  hideTeamEditModal,
  hideUserEditModal,
  initializeAddMembersForms,
  performUserSearch,
  registerAdminActionListeners,
} from "./users";
import {
  createMemoizedInit,
  safeGetElement,
  showErrorMessage,
  showSuccessMessage,
  updateEditToolUrl,
} from "./utils";

((Admin) => {
  // ===================================================================
  // Initialization
  // ===================================================================

  // Initialise 3rd Party and setup Context Forge
  document.addEventListener("DOMContentLoaded", () => {
    console.log("🔐 DOM loaded - initializing secure admin interface...");

    /* ---------------------------------------------------------------------------
    Robust reloadAllResourceSections
    - Replaces each section's full innerHTML with a server-rendered partial
    - Restores saved initial markup on failure
    - Re-runs initializers (Alpine, CodeMirror, select/pills, event handlers)
    --------------------------------------------------------------------------- */

    try {
      // 1. Initialize Alpine tooltips
      setupTooltipsWithAlpine();

      // 2. Initialize CodeMirror editors first
      initializeCodeMirrorEditors();

      // 3. Reload all resource panels data
      registerReloadAllResourceSections();

      // 4. Initialize tool selects
      initializeToolSelects();

      // 5. Set up all event listeners
      initializeEventListeners();

      // 6. Handle initial tab/state
      initializeTabState();

      // 7. Set up form validation
      setupFormValidation();

      // 8. Setup bulk import modal
      try {
        setupBulkImportModal();
      } catch (error) {
        console.error("Error setting up bulk import modal:", error);
      }

      // 9. Initialize export/import functionality
      try {
        initializeExportImport();
      } catch (error) {
        console.error("Error setting up export/import functionality:", error);
      }

      // // ✅ 4.1 Set up tab button click handlers
      // document.querySelectorAll('.tab-button').forEach(button => {
      //     button.addEventListener('click', () => {
      //         const tabId = button.getAttribute('data-tab');

      //         document.querySelectorAll('.tab-panel').forEach(panel => {
      //             panel.classList.add('hidden');
      //         });

      //         safeGetElement(tabId).classList.remove('hidden');
      //     });
      // });

      // Mark as initialized
      AppState.isInitialized = true;

      console.log("✅ Secure initialization complete - XSS protection active");
    } catch (error) {
      console.error("❌ Initialization failed:", error);
      showErrorMessage(
        "Failed to initialize the application. Please refresh the page."
      );
    }
  });

  // Executes MCP tools via SSE streaming. Streams results to UI textarea.
  document.addEventListener("DOMContentLoaded", () => {
    // Use #tool-ops-main-content-wrapper as the event delegation target because
    // #toolBody gets replaced by HTMX swaps. The wrapper survives swaps.
    const toolOpsWrapper = safeGetElement("tool-ops-main-content-wrapper");
    const selectedList = safeGetElement("selectedList");
    const selectedCount = safeGetElement("selectedCount");
    const searchBox = safeGetElement("searchBox");

    let selectedTools = [];
    let selectedToolIds = [];

    const updateSelectedList = function () {
      selectedList.innerHTML = "";
      if (selectedTools.length === 0) {
        selectedList.textContent = "No tools selected";
      } else {
        selectedTools.forEach((tool) => {
          const item = document.createElement("div");
          item.className =
            "flex items-center justify-between bg-indigo-100 text-indigo-800 px-3 py-1 rounded-md";
          item.innerHTML = `
              <span>${tool}</span>
              <button class="text-indigo-500 hover:text-indigo-700 font-bold remove-btn">&times;</button>
          `;
          item.querySelector(".remove-btn").addEventListener("click", () => {
            selectedTools = selectedTools.filter((t) => t !== tool);
            const box = document.querySelector(`
                .tool-checkbox[data-tool="${tool}"]`);
            if (box) {
              box.checked = false;
            }
            updateSelectedList();
          });
          selectedList.appendChild(item);
        });
      }
      selectedCount.textContent = selectedTools.length;
    };

    if (toolOpsWrapper !== null) {
      // ✅ Use event delegation on wrapper (survives HTMX swaps)
      toolOpsWrapper.addEventListener("change", (event) => {
        const cb = event.target;
        if (cb.classList.contains("tool-checkbox")) {
          const toolName = cb.getAttribute("data-tool");
          if (cb.checked) {
            if (!selectedTools.includes(toolName)) {
              selectedTools.push(toolName.split("###")[0]);
              selectedToolIds.push(toolName.split("###")[1]);
            }
          } else {
            selectedTools = selectedTools.filter(
              (t) => t !== toolName.split("###")[0]
            );
            selectedToolIds = selectedToolIds.filter(
              (t) => t !== toolName.split("###")[1]
            );
          }
          updateSelectedList();
        }
      });
    }

    // --- Search logic ---
    if (searchBox !== null) {
      searchBox.addEventListener("input", () => {
        const query = searchBox.value.trim().toLowerCase();
        // Search within #toolBody (which is inside #tool-ops-main-content-wrapper)
        document
          .querySelectorAll("#tool-ops-main-content-wrapper #toolBody tr")
          .forEach((row) => {
            const name = row.dataset.name;
            row.style.display = name && name.includes(query) ? "" : "none";
          });
      });
    }

    // Generic API call for Enrich/Validate
    const callEnrichment = async function () {
      if (selectedTools.length === 0) {
        showErrorMessage("⚠️ Please select at least one tool.");
        return;
      }
      try {
        console.log(selectedToolIds);
        selectedToolIds.forEach((toolId) => {
          console.log(toolId);
          fetch(`/toolops/enrichment/enrich_tool?tool_id=${toolId}`, {
            method: "POST",
            headers: {
              "Cache-Control": "no-cache",
              Pragma: "no-cache",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ tool_id: toolId }),
          });
        });
        showSuccessMessage("Tool description enrichment has started.");
        // Uncheck all checkboxes
        document.querySelectorAll(".tool-checkbox").forEach((cb) => {
          cb.checked = false;
        });

        // Empty the selected tools array
        selectedTools = [];
        selectedToolIds = [];

        // Update the selected tools list UI
        updateSelectedList();
      } catch (err) {
        //   responseDiv.textContent = `❌ Error: ${err.message}`;
        showErrorMessage(`❌ Error: ${err.message}`);
      }
    };

    const generateBulkTestCases = async function () {
      const testCases = parseInt(
        safeGetElement("gen-bulk-testcase-count").value
      );
      const variations = parseInt(
        safeGetElement("gen-bulk-nl-variation-count").value
      );

      if (!testCases || !variations || testCases < 1 || variations < 1) {
        showErrorMessage(
          "⚠️ Please enter valid numbers for test cases and variations."
        );
        return;
      }

      try {
        for (const toolId of selectedToolIds) {
          fetch(
            `/toolops/validation/generate_testcases?tool_id=${toolId}&number_of_test_cases=${testCases}&number_of_nl_variations=${variations}&mode=generate`,
            {
              method: "POST",
              headers: {
                "Cache-Control": "no-cache",
                Pragma: "no-cache",
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ tool_id: toolId }),
            }
          );
        }
        showSuccessMessage(
          "Test case generation for tool validation has started."
        );
        // Reset selections
        document.querySelectorAll(".tool-checkbox").forEach((cb) => {
          cb.checked = false;
        });
        selectedTools = [];
        selectedToolIds = [];
        updateSelectedList();

        // Close modal immediately after clicking Generate
        closeModal("bulk-testcase-gen-modal");
      } catch (err) {
        showErrorMessage(`❌ Error: ${err.message}`);
      }
    };
    Admin.generateBulkTestCases = generateBulkTestCases;

    const openTestCaseModal = function () {
      if (selectedToolIds.length === 0) {
        showErrorMessage("⚠️ Please select at least one tool.");
        return;
      }

      // Show modal
      document
        .getElementById("bulk-testcase-gen-modal")
        .classList.remove("hidden");
      document
        .getElementById("bulk-generate-btn")
        .addEventListener("click", generateBulkTestCases);
    };

    const clearAllSelections = function () {
      // Uncheck all checkboxes
      document.querySelectorAll(".tool-checkbox").forEach((cb) => {
        cb.checked = false;
      });

      // Empty the selected tools array
      selectedTools = [];
      selectedToolIds = [];

      // Update the selected tools list UI
      updateSelectedList();
    };
    // Button listeners
    const enrichToolsBtn = safeGetElement("enrichToolsBtn");

    if (enrichToolsBtn !== null) {
      document
        .getElementById("enrichToolsBtn")
        .addEventListener("click", () => callEnrichment());
      document
        .getElementById("validateToolsBtn")
        .addEventListener("click", () => openTestCaseModal());
      document
        .getElementById("clearToolsBtn")
        .addEventListener("click", () => clearAllSelections());
    }
  });

  // Prevent manual REST→MCP changes in edit-tool-form
  document.addEventListener("DOMContentLoaded", function () {
    const editToolTypeSelect = safeGetElement("edit-tool-type");
    if (editToolTypeSelect) {
      // Store the initial value for comparison
      editToolTypeSelect.dataset.prevValue = editToolTypeSelect.value;

      editToolTypeSelect.addEventListener("change", function (e) {
        const prevType = this.dataset.prevValue;
        const selectedType = this.value;
        if (prevType === "REST" && selectedType === "MCP") {
          alert("You cannot change integration type from REST to MCP.");
          this.value = prevType;
          // Optionally, reset any dependent fields here
        } else {
          this.dataset.prevValue = selectedType;
        }
      });
    }
  });

  // Initialize gateway select on page load
  document.addEventListener("DOMContentLoaded", function () {
    // Initialize for the create server form
    if (safeGetElement("associatedGateways")) {
      initGatewaySelect(
        "associatedGateways",
        "selectedGatewayPills",
        "selectedGatewayWarning",
        12,
        "selectAllGatewayBtn",
        "clearAllGatewayBtn",
        "searchGateways"
      );
    }
  });

  document.addEventListener("DOMContentLoaded", loadTools);

  /**
   * Close modal when clicking outside of it
   */
  document.addEventListener("DOMContentLoaded", function () {
    const userModal = safeGetElement("user-edit-modal");
    if (userModal) {
      userModal.addEventListener("click", function (event) {
        if (event.target === userModal) {
          hideUserEditModal();
        }
      });
    }

    const teamModal = safeGetElement("team-edit-modal");
    if (teamModal) {
      teamModal.addEventListener("click", function (event) {
        if (event.target === teamModal) {
          hideTeamEditModal();
        }
      });
    }
  });

  /**
   * Create memoized version of search inputs initialization
   * This prevents repeated initialization and provides explicit reset capability
   */
  const {
    init: initializeSearchInputsMemoized,
    debouncedInit: initializeSearchInputsDebounced,
    reset: resetSearchInputsState,
  } = createMemoizedInit(initializeSearchInputs, 300, "SearchInputs");

  // Attach event listener after DOM is loaded or when modal opens
  document.addEventListener("DOMContentLoaded", function () {
    const TypeField = safeGetElement("edit-tool-type");
    if (TypeField) {
      TypeField.addEventListener("change", updateEditToolUrl);
      // Set initial state
      updateEditToolUrl();
    }

    // Initialize CA certificate upload immediately
    initializeCACertUpload();

    // Also try to initialize after a short delay (in case the panel loads later)
    setTimeout(initializeCACertUpload, 500);

    // Re-initialize when switching to gateways tab
    const gatewaysTab = document.querySelector('[onclick*="gateways"]');
    if (gatewaysTab) {
      gatewaysTab.addEventListener("click", function () {
        setTimeout(initializeCACertUpload, 100);
      });
    }

    // Initialize search functionality for all entity types (immediate, no debounce)
    initializeSearchInputsMemoized();
    // Only initialize password validation if password fields exist on page
    if (document.getElementById("password-field")) {
      initializePasswordValidation();
    }
    initializeAddMembersForms();

    // Event delegation for team member search - server-side search for unified view
    // This handler is initialized here for early binding, but the actual search logic
    // is in Admin.performUserSearch() which is attached when the form is initialized
    const teamSearchTimeouts = {};
    const teamMemberDataCache = {};

    document.body.addEventListener("input", async function (event) {
      const target = event.target;
      if (target.id && target.id.startsWith("user-search-")) {
        const teamId = target.id.replace("user-search-", "");
        const listContainer = safeGetElement(`team-members-list-${teamId}`);

        if (!listContainer) return;

        const query = target.value.trim();

        // Clear previous timeout for this team
        if (teamSearchTimeouts[teamId]) {
          clearTimeout(teamSearchTimeouts[teamId]);
        }

        // Get team member data from cache or script tag
        if (!teamMemberDataCache[teamId]) {
          const teamMemberDataScript = safeGetElement(
            `team-member-data-${teamId}`
          );
          if (teamMemberDataScript) {
            try {
              teamMemberDataCache[teamId] = JSON.parse(
                teamMemberDataScript.textContent || "{}"
              );
              console.log(
                `[Team ${teamId}] Loaded team member data for ${Object.keys(teamMemberDataCache[teamId]).length} members`
              );
            } catch (e) {
              console.error(
                `[Team ${teamId}] Failed to parse team member data:`,
                e
              );
              teamMemberDataCache[teamId] = {};
            }
          } else {
            teamMemberDataCache[teamId] = {};
          }
        }

        // Debounce server call
        teamSearchTimeouts[teamId] = setTimeout(async () => {
          await performUserSearch(
            teamId,
            query,
            listContainer,
            teamMemberDataCache[teamId]
          );
        }, 300);
      }
    });

    // Re-initialize search inputs when HTMX content loads
    // Only re-initialize if the swap affects search-related content
    document.body.addEventListener("htmx:afterSwap", function (event) {
      const target = event.detail.target;
      const relevantPanels = [
        "catalog-panel",
        "gateways-panel",
        "tools-panel",
        "resources-panel",
        "prompts-panel",
        "a2a-agents-panel",
      ];

      if (
        target &&
        relevantPanels.some(
          (panelId) => target.id === panelId || target.closest(`#${panelId}`)
        )
      ) {
        console.log(
          `📝 HTMX swap detected in ${target.id}, resetting search state`
        );
        resetSearchInputsState();
        initializeSearchInputsDebounced();
      }
    });

    // Initialize search when switching tabs
    document.addEventListener("click", function (event) {
      if (
        event.target.matches('[onclick*="Admin.showTab"]') ||
        event.target.closest('[onclick*="Admin.showTab"]')
      ) {
        console.log("🔄 Tab switch detected, resetting search state");
        resetSearchInputsState();
        initializeSearchInputsDebounced();
      }
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    initializeRealTimeMonitoring();
  });

  // ===============================================
  // TAG FILTERING FUNCTIONALITY
  // ===============================================

  // Initialize tag filtering when page loads
  document.addEventListener("DOMContentLoaded", function () {
    initializeTagFiltering();

    if (typeof initializeTeamScopingMonitor === "function") {
      initializeTeamScopingMonitor();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", registerAdminActionListeners);
  } else {
    registerAdminActionListeners();
  }

  // ===================================================================
  // GLOBAL ERROR HANDLERS
  // ===================================================================

  window.addEventListener("error", (e) => {
    console.error("Global error:", e.error, e.filename, e.lineno);
    // Don't show user error for every script error, just log it
  });

  window.addEventListener("unhandledrejection", (e) => {
    console.error("Unhandled promise rejection:", e.reason);
    // Show user error for unhandled promises as they're often more serious
    showErrorMessage("An unexpected error occurred. Please refresh the page.");
  });

  // Enhanced cleanup function for page unload
  window.addEventListener("beforeunload", () => {
    try {
      AppState.reset();
      cleanupToolTestState();
      console.log("✓ Application state cleaned up before unload");
    } catch (error) {
      console.error("Error during cleanup:", error);
    }
  });

  // Performance monitoring
  if (window.performance && window.performance.mark) {
    window.performance.mark("app-security-complete");
    console.log("✓ Performance markers available");
  }

  // ===================================================================
  // CHART.JS INSTANCE CLEANUP
  // ===================================================================
  window.addEventListener("beforeunload", () => {
    Admin.chartRegistry.destroyAll();
  });

  // ===================================================================
  // KEYBOARD EVENTS
  // ===================================================================

  // Global event handler for Escape key on modals
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      // Find any active modal
      const activeModal = Array.from(AppState.activeModals)[0];
      if (activeModal) {
        closeModal(activeModal);
      }
    }
  });
})(window.Admin);
