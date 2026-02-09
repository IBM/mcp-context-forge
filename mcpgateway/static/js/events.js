import { AppState } from "./appState";
import { setupFormValidation } from "./formValidation";
import { initializeCodeMirrorEditors, initializeEventListeners, initializeExportImport, initializeTabState, initializeToolSelects, setupBulkImportModal } from "./initialization";
import { closeModal } from "./modals";
import { initializeTagFiltering } from "./tags";
import { cleanupToolTestState, loadTools } from "./tools";
import { safeGetElement, showErrorMessage, showSuccessMessage } from "./utils";

((Admin) => {
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
  
  // Executes MCP tools via SSE streaming. Streams results to UI textarea.
  document.addEventListener("DOMContentLoaded", () => {
    // Use #tool-ops-main-content-wrapper as the event delegation target because
    // #toolBody gets replaced by HTMX swaps. The wrapper survives swaps.
    const toolOpsWrapper = safeGetElement(
      "tool-ops-main-content-wrapper",
    );
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
          item.querySelector(".remove-btn").addEventListener(
            "click",
            () => {
              selectedTools = selectedTools.filter((t) => t !== tool);
              const box = document.querySelector(`
                .tool-checkbox[data-tool="${tool}"]`);
              if (box) {
                box.checked = false;
              }
              updateSelectedList();
            },
          );
          selectedList.appendChild(item);
        });
      }
      selectedCount.textContent = selectedTools.length;
    }
      
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
              (t) => t !== toolName.split("###")[0],
            );
            selectedToolIds = selectedToolIds.filter(
              (t) => t !== toolName.split("###")[1],
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
          row.style.display =
          name && name.includes(query) ? "" : "none";
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
    
    Admin.generateBulkTestCases = async function () {
      const testCases = parseInt(
        safeGetElement("gen-bulk-testcase-count").value,
      );
      const variations = parseInt(
        safeGetElement("gen-bulk-nl-variation-count").value,
      );
      
      if (!testCases || !variations || testCases < 1 || variations < 1) {
        showErrorMessage(
          "⚠️ Please enter valid numbers for test cases and variations.",
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
            },
          );
        }
        showSuccessMessage(
          "Test case generation for tool validation has started.",
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
    }
    
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
      .addEventListener("click", Admin.generateBulkTestCases);
    }
    
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
    }
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
      Admin.initGatewaySelect(
        "associatedGateways",
        "selectedGatewayPills",
        "selectedGatewayWarning",
        12,
        "selectAllGatewayBtn",
        "clearAllGatewayBtn",
        "searchGateways",
      );
    }
  });
  
  document.addEventListener("DOMContentLoaded", loadTools);
  
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

  // ===============================================
  // TAG FILTERING FUNCTIONALITY
  // ===============================================

  // Initialize tag filtering when page loads
  document.addEventListener("DOMContentLoaded", function () {
      initializeTagFiltering();

      if (typeof initializeTeamScopingMonitor === "function") {
          Admin.initializeTeamScopingMonitor();
      }
  });

  // ===================================================================
  // CHART.JS INSTANCE CLEANUP
  // ===================================================================
  window.addEventListener("beforeunload", () => {
    Admin.chartRegistry.destroyAll();
  });


  // ===================================================================
  // Initialization
  // ===================================================================
  document.addEventListener("DOMContentLoaded", () => {
    console.log("🔐 DOM loaded - initializing secure admin interface...");
    
    try {      
      // 1. Initialize CodeMirror editors first
      initializeCodeMirrorEditors();
      
      // 2. Initialize tool selects
      initializeToolSelects();
      
      // 3. Set up all event listeners
      initializeEventListeners();
      
      // 4. Handle initial tab/state
      initializeTabState();
      
      // 5. Set up form validation
      setupFormValidation();
      
      // 6. Setup bulk import modal
      try {
        setupBulkImportModal();
      } catch (error) {
        console.error("Error setting up bulk import modal:", error);
      }
      
      // 7. Initialize export/import functionality
      try {
        initializeExportImport();
      } catch (error) {
        console.error(
          "Error setting up export/import functionality:",
          error,
        );
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
      
      console.log(
        "✅ Secure initialization complete - XSS protection active",
      );
    } catch (error) {
      console.error("❌ Initialization failed:", error);
      showErrorMessage(
        "Failed to initialize the application. Please refresh the page.",
      );
    }
  });
})(window.Admin)