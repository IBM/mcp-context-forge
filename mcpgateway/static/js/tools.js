/* global Admin */
import { AppState } from "./appState";
import { getSelectedGatewayIds } from "./gateway";
import { closeModal, openModal } from "./modals";
import { 
  escapeHtml, 
  safeSetInnerHTML, 
  validateInputName, 
  validatePassthroughHeader, 
} from "./security";
import { 
  fetchWithTimeout, 
  getCurrentTeamId, 
  handleFetchError, 
  safeGetElement, 
  showErrorMessage, 
  showSuccessMessage, 
} from "./utils";

// ===================================================================
// TOOL SELECT FUNCTIONALITY
// ===================================================================
export const initToolSelect = function (
  selectId,
  pillsId,
  warnId,
  max = 6,
  selectBtnId = null,
  clearBtnId = null,
) {
  const container = safeGetElement(selectId);
  const pillsBox = safeGetElement(pillsId);
  const warnBox = safeGetElement(warnId);
  const clearBtn = clearBtnId ? safeGetElement(clearBtnId) : null;
  const selectBtn = selectBtnId ? safeGetElement(selectBtnId) : null;
  
  if (!container || !pillsBox || !warnBox) {
    console.warn(
      `Tool select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
    );
    return;
  }
  
  // Instrument changes to the data-selected-tools attribute for debugging
  if (!container.dataset.attrObserverAttached) {
    try {
      const attrObserver = new MutationObserver((mutationsList) => {
        for (const mut of mutationsList) {
          if (
            mut.type === "attributes" &&
            mut.attributeName === "data-selected-tools"
          ) {
            const oldVal = mut.oldValue;
            const newVal = container.getAttribute(
              "data-selected-tools",
            );
            console.info(
              `[DATA-INSTRUMENT] ${selectId} data-selected-tools changed — old: ${oldVal} new: ${newVal}`,
            );
          }
        }
      });
      
      // Observe attribute changes and capture previous value
      attrObserver.observe(container, {
        attributes: true,
        attributeOldValue: true,
        attributeFilter: ["data-selected-tools"],
      });
      
      // Prevent double attaching
      container.dataset.attrObserverAttached = "true";
      // Keep a reference so it doesn't get GC'd (and so we could disconnect if needed)
      container._dbgAttrObserver = attrObserver;
    } catch (e) {
      console.error(
        "[DATA-INSTRUMENT] failed to attach attribute observer:",
        e,
      );
    }
  }
  
  const pillClasses =
  "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full dark:bg-green-900 dark:text-green-200";
  
  const update = function () {
    try {
      const checkboxes = container.querySelectorAll(
        'input[type="checkbox"]',
      );
      const checked = Array.from(checkboxes).filter((cb) => cb.checked);
      
      // Check if "Select All" mode is active
      const selectAllInput = container.querySelector(
        'input[name="selectAllTools"]',
      );
      const allIdsInput = container.querySelector(
        'input[name="allToolIds"]',
      );
      
      // Check if this is the edit server tools container
      const isEditServerMode = selectId === "edit-server-tools";
      let serverTools = null;
      
      if (isEditServerMode) {
        const dataAttr = container.getAttribute("data-server-tools");
        if (dataAttr) {
          try {
            serverTools = JSON.parse(dataAttr);
          } catch (e) {
            console.error("Error parsing data-server-tools:", e);
          }
        }
      }
      
      // Get persisted selections for Add Server mode
      let persistedToolIds = [];
      if (selectId === "associatedTools") {
        const dataAttr = container.getAttribute("data-selected-tools");
        if (dataAttr) {
          try {
            persistedToolIds = JSON.parse(dataAttr);
          } catch (e) {
            console.error("Error parsing data-selected-tools:", e);
          }
        }
        if (
          (!persistedToolIds || persistedToolIds.length === 0) &&
          Array.isArray(Admin._selectedAssociatedTools)
        ) {
          persistedToolIds = Admin._selectedAssociatedTools.slice();
        }
      }
      
      let count = checked.length;
      const pillsData = [];
      
      // If Select All mode is active, use the count from allToolIds
      if (
        selectAllInput &&
        selectAllInput.value === "true" &&
        allIdsInput
      ) {
        try {
          const allIds = JSON.parse(allIdsInput.value);
          count = allIds.length;
        } catch (e) {
          console.error("Error parsing allToolIds:", e);
        }
      }
      // If in edit server mode and we have server tools data, use that count
      else if (
        isEditServerMode &&
        serverTools &&
        Array.isArray(serverTools)
      ) {
        count = serverTools.length;
      }
      // If in Add Server mode with persisted selections, use persisted count and build pills from persisted data
      else if (
        selectId === "associatedTools" &&
        persistedToolIds &&
        persistedToolIds.length > 0
      ) {
        count = persistedToolIds.length;
        // Build pill data from persisted IDs using toolMapping
        if (Admin.toolMapping) {
          persistedToolIds.forEach((id) => {
            const toolName = Admin.toolMapping[id];
            if (toolName) {
              pillsData.push({ id, name: toolName });
            }
          });
        }
      }
      
      // Rebuild pills safely - show first 3, then summarize the rest
      pillsBox.innerHTML = "";
      const maxPillsToShow = 3;
      
      // Determine which pills to display based on mode
      if (selectId === "associatedTools" && pillsData.length > 0) {
        // In Add Server mode with persisted data, show pills from persisted selections
        pillsData.slice(0, maxPillsToShow).forEach((item) => {
          const span = document.createElement("span");
          span.className = pillClasses;
          span.textContent = item.name || "Unnamed";
          span.title = item.name;
          pillsBox.appendChild(span);
        });
      } else if (
        isEditServerMode &&
        serverTools &&
        Array.isArray(serverTools) &&
        Admin.toolMapping
      ) {
        // In edit server mode, show the server tools rather than just currently checked ones
        const allLoadedTools = Array.from(checkboxes);
        const pillsToDisplay = allLoadedTools.filter((checkbox) => {
          const toolName = Admin.toolMapping[checkbox.value];
          return toolName && serverTools.includes(toolName);
        });
        pillsToDisplay.slice(0, maxPillsToShow).forEach((cb) => {
          const span = document.createElement("span");
          span.className = pillClasses;
          span.textContent =
          cb.nextElementSibling?.textContent?.trim() || "Unnamed";
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
        span.title = "Click to see all selected tools";
        const remaining = count - maxPillsToShow;
        span.textContent = `+${remaining} more`;
        pillsBox.appendChild(span);
      }
      
      // Warning when > max
      if (count > max) {
        warnBox.textContent = `Selected ${count} tools. Selecting more than ${max} tools can degrade agent performance with the server.`;
      } else {
        warnBox.textContent = "";
      }
    } catch (error) {
      console.error("Error updating tool select:", error);
    }
  }
  
  // Remove old event listeners by cloning and replacing (preserving ID)
  if (clearBtn && !clearBtn.dataset.listenerAttached) {
    clearBtn.dataset.listenerAttached = "true";
    const newClearBtn = clearBtn.cloneNode(true);
    newClearBtn.dataset.listenerAttached = "true";
    clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);
    
    newClearBtn.addEventListener("click", () => {
      const checkboxes = container.querySelectorAll(
        'input[type="checkbox"]',
      );
      checkboxes.forEach((cb) => (cb.checked = false));
      
      // Clear the "select all" flag
      const selectAllInput = container.querySelector(
        'input[name="selectAllTools"]',
      );
      if (selectAllInput) {
        selectAllInput.remove();
      }
      const allIdsInput = container.querySelector(
        'input[name="allToolIds"]',
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
      // Disable button and show loading state
      const originalText = newSelectBtn.textContent;
      newSelectBtn.disabled = true;
      newSelectBtn.textContent = "Selecting all tools...";
      
      try {
        // Prefer full-set selection when pagination/infinite-scroll is present
        const loadedCheckboxes = container.querySelectorAll(
          'input[type="checkbox"]',
        );
        const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
          (cb) => cb.offsetParent !== null,
        );
        
        // Detect pagination/infinite-scroll controls for tools
        const hasPaginationControls = !!safeGetElement(
          "tools-pagination-controls",
        );
        const hasScrollTrigger = !!document.querySelector(
          "[id^='tools-scroll-trigger']",
        );
        const isPaginated = hasPaginationControls || hasScrollTrigger;
        
        let allToolIds = [];
        
        if (!isPaginated && visibleCheckboxes.length > 0) {
          // No pagination and some visible items => select visible set
          allToolIds = visibleCheckboxes.map((cb) => cb.value);
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
          const response = await fetch(
            `${window.ROOT_PATH}/admin/tools/ids${queryString ? `?${queryString}` : ""}`,
          );
          if (!response.ok) {
            throw new Error("Failed to fetch tool IDs");
          }
          const data = await response.json();
          allToolIds = data.tool_ids || [];
          // Check loaded checkboxes so UI shows selection where possible
          loadedCheckboxes.forEach((cb) => (cb.checked = true));
        }
        
        // Add a hidden input to indicate "select all" mode
        let selectAllInput = container.querySelector(
          'input[name="selectAllTools"]',
        );
        if (!selectAllInput) {
          selectAllInput = document.createElement("input");
          selectAllInput.type = "hidden";
          selectAllInput.name = "selectAllTools";
          container.appendChild(selectAllInput);
        }
        selectAllInput.value = "true";
        
        // Also store the IDs as a JSON array for the backend
        let allIdsInput = container.querySelector(
          'input[name="allToolIds"]',
        );
        if (!allIdsInput) {
          allIdsInput = document.createElement("input");
          allIdsInput.type = "hidden";
          allIdsInput.name = "allToolIds";
          container.appendChild(allIdsInput);
        }
        allIdsInput.value = JSON.stringify(allToolIds);
        
        update();
        
        newSelectBtn.textContent = `✓ All ${allToolIds.length} tools selected`;
        setTimeout(() => {
          newSelectBtn.textContent = originalText;
        }, 2000);
      } catch (error) {
        console.error("Error in Select All:", error);
        alert("Failed to select all tools. Please try again.");
        newSelectBtn.disabled = false;
        newSelectBtn.textContent = originalText;
      } finally {
        newSelectBtn.disabled = false;
      }
    });
  }
  
  update(); // Initial render
  
  // Attach change listeners to checkboxes (using delegation for dynamic content)
  if (!container.dataset.changeListenerAttached) {
    container.dataset.changeListenerAttached = "true";
    container.addEventListener("change", (e) => {
      if (e.target.type === "checkbox") {
        // Check if we're in "Select All" mode
        const selectAllInput = container.querySelector(
          'input[name="selectAllTools"]',
        );
        const allIdsInput = container.querySelector(
          'input[name="allToolIds"]',
        );
        
        if (
          selectAllInput &&
          selectAllInput.value === "true" &&
          allIdsInput
        ) {
          // User is manually checking/unchecking after Select All
          // Update the allToolIds array to reflect the change
          try {
            let allIds = JSON.parse(allIdsInput.value);
            const toolId = e.target.value;
            
            if (e.target.checked) {
              // Add the ID if it's not already there
              if (!allIds.includes(toolId)) {
                allIds.push(toolId);
              }
            } else {
              // Remove the ID from the array
              allIds = allIds.filter((id) => id !== toolId);
            }
            
            // Update the hidden field
            allIdsInput.value = JSON.stringify(allIds);
          } catch (error) {
            console.error("Error updating allToolIds:", error);
          }
        }
        // Check if we're in edit server mode
        else if (selectId === "edit-server-tools") {
          // In edit server mode, update the server tools data based on checkbox state
          const dataAttr =
          container.getAttribute("data-server-tools");
          let serverTools = [];
          
          if (dataAttr) {
            try {
              serverTools = JSON.parse(dataAttr);
            } catch (e) {
              console.error(
                "Error parsing data-server-tools:",
                e,
              );
            }
          }
          
          // Get the tool name from toolMapping to update serverTools array
          const toolId = e.target.value;
          const toolName =
          Admin.toolMapping && Admin.toolMapping[toolId];
          
          if (toolName) {
            if (e.target.checked) {
              // Add tool name to server tools if not already there
              if (!serverTools.includes(toolName)) {
                serverTools.push(toolName);
              }
            } else {
              // Remove tool name from server tools
              serverTools = serverTools.filter(
                (name) => name !== toolName,
              );
            }
            
            // Update the data attribute
            container.setAttribute(
              "data-server-tools",
              JSON.stringify(serverTools),
            );
          }
        }
        // If we're in the Add Server tools container, persist selected IDs
        else if (selectId === "associatedTools") {
          try {
            // Incrementally update persisted selection instead of
            // replacing it wholesale. This preserves selections made
            // in previous filtered views where those checkboxes are
            // not present in the current DOM.
            const changedEl = e.target;
            const changedId = changedEl.value;
            
            // Load existing persisted set: prefer container attribute,
            // fall back to the in-memory window variable.
            let persisted = [];
            const dataAttr = container.getAttribute(
              "data-selected-tools",
            );
            if (dataAttr) {
              try {
                const parsed = JSON.parse(dataAttr);
                if (Array.isArray(parsed)) {
                  persisted = parsed.slice();
                }
              } catch (parseErr) {
                console.error(
                  "Error parsing existing data-selected-tools:",
                  parseErr,
                );
              }
            } else if (
              Array.isArray(Admin._selectedAssociatedTools)
            ) {
              persisted = Admin._selectedAssociatedTools.slice();
            }
            
            if (changedEl.checked) {
              if (!persisted.includes(changedId)) {
                persisted.push(changedId);
              }
            } else {
              persisted = persisted.filter(
                (x) => x !== changedId,
              );
            }
            
            // Ensure any currently visible checked boxes are included
            const visibleChecked = Array.from(
              container.querySelectorAll(
                'input[type="checkbox"]:checked',
              ),
            ).map((cb) => cb.value);
            visibleChecked.forEach((id) => {
              if (!persisted.includes(id)) {
                persisted.push(id);
              }
            });
            
            // Persist back to both the container attribute and global fallback
            container.setAttribute(
              "data-selected-tools",
              JSON.stringify(persisted),
            );
            try {
              Admin._selectedAssociatedTools = persisted.slice();
            } catch (e) {
              console.error(
                "Error persisting Admin._selectedAssociatedTools:",
                e,
              );
            }
          } catch (err) {
            console.error(
              "Error updating data-selected-tools (incremental):",
              err,
            );
          }
        }
        
        update();
      }
    });
  }
};

// ===================================================================
// ENHANCED TOOL TESTING with Safe State Management
// ===================================================================

// Track active tool test requests globally
const toolTestState = {
  activeRequests: new Map(), // toolId -> AbortController
  lastRequestTime: new Map(), // toolId -> timestamp
  debounceDelay: 1000, // Increased from 500ms
  requestTimeout: window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
};

let toolInputSchemaRegistry = null;

/**
* ENHANCED: Tool testing with improved race condition handling
*/
export const testTool = async function (toolId) {
  try {
    console.log(`Testing tool ID: ${toolId}`);
    
    // 1. ENHANCED DEBOUNCING: More aggressive to prevent rapid clicking
    const now = Date.now();
    const lastRequest = toolTestState.lastRequestTime.get(toolId) || 0;
    const timeSinceLastRequest = now - lastRequest;
    const enhancedDebounceDelay = 2000; // Increased from 1000ms
    
    if (timeSinceLastRequest < enhancedDebounceDelay) {
      console.log(
        `Tool ${toolId} test request debounced (${timeSinceLastRequest}ms ago)`,
      );
      const waitTime = Math.ceil(
        (enhancedDebounceDelay - timeSinceLastRequest) / 1000,
      );
      showErrorMessage(
        `Please wait ${waitTime} more second${waitTime > 1 ? "s" : ""} before testing again`,
      );
      return;
    }
    
    // 2. MODAL PROTECTION: Enhanced check
    if (AppState.isModalActive("tool-test-modal")) {
      console.warn("Tool test modal is already active");
      return; // Silent fail for better UX
    }
    
    // 3. BUTTON STATE: Immediate feedback with better state management
    const testButton = document.querySelector(
      `[onclick*="testTool('${toolId}')"]`,
    );
    if (testButton) {
      if (testButton.disabled) {
        console.log(
          "Test button already disabled, request in progress",
        );
        return;
      }
      testButton.disabled = true;
      testButton.textContent = "Testing...";
      testButton.classList.add("opacity-50", "cursor-not-allowed");
    }
    
    // 4. REQUEST CANCELLATION: Enhanced cleanup
    const existingController = toolTestState.activeRequests.get(toolId);
    if (existingController) {
      console.log(`Cancelling existing request for tool ${toolId}`);
      existingController.abort();
      toolTestState.activeRequests.delete(toolId);
    }
    
    // 5. CREATE NEW REQUEST with longer timeout
    const controller = new AbortController();
    toolTestState.activeRequests.set(toolId, controller);
    toolTestState.lastRequestTime.set(toolId, now);
    
    // 6. MAKE REQUEST with increased timeout
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/tools/${toolId}`,
      {
        signal: controller.signal,
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      },
      toolTestState.requestTimeout, // Use the increased timeout
    );
    
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          `Tool with ID ${toolId} not found. It may have been deleted.`,
        );
      } else if (response.status === 429) {
        throw new Error(
          "Too many requests. Please wait a moment before testing again.",
        );
      } else if (response.status >= 500) {
        throw new Error(
          `Server error (${response.status}). The server may be overloaded. Please try again in a few seconds.`,
        );
      } else {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`,
        );
      }
    }
    
    const tool = await response.json();
    console.log(`Tool ${toolId} fetched successfully`, tool);
    toolInputSchemaRegistry = tool;
    
    // 7. CLEAN STATE before proceeding
    toolTestState.activeRequests.delete(toolId);
    
    // Store in safe state
    AppState.currentTestTool = tool;
    
    // Set modal title and description safely - NO DOUBLE ESCAPING
    const titleElement = safeGetElement("tool-test-modal-title");
    const descElement = safeGetElement("tool-test-modal-description");
    
    if (titleElement) {
      titleElement.textContent = "Test Tool: " + (tool.name || "Unknown");
    }
    if (descElement) {
      if (tool.description) {
        // Escape HTML and then replace newlines with <br/> tags
        descElement.innerHTML = escapeHtml(tool.description).replace(
          /\n/g,
          "<br/>",
        );
      } else {
        descElement.textContent = "No description available.";
      }
    }
    
    const container = safeGetElement("tool-test-form-fields");
    if (!container) {
      console.error("Tool test form fields container not found");
      return;
    }
    
    container.innerHTML = ""; // Clear previous fields
    
    // Parse the input schema safely
    let schema = tool.inputSchema;
    if (typeof schema === "string") {
      try {
        schema = JSON.parse(schema);
      } catch (e) {
        console.error("Invalid JSON schema", e);
        schema = {};
      }
    }
    
    // Dynamically create form fields based on schema.properties
    if (schema && schema.properties) {
      for (const key in schema.properties) {
        const prop = schema.properties[key];
        
        // Validate the property name
        const keyValidation = validateInputName(key, "schema property");
        if (!keyValidation.valid) {
          console.warn(`Skipping invalid schema property: ${key}`);
          continue;
        }
        
        const fieldDiv = document.createElement("div");
        fieldDiv.className = "mb-4";
        
        // Field label - use textContent to avoid double escaping
        const label = document.createElement("label");
        label.className =
        "block text-sm font-medium text-gray-700 dark:text-gray-300";
        
        // Create span for label text
        const labelText = document.createElement("span");
        labelText.textContent = keyValidation.value;
        label.appendChild(labelText);
        
        // Add red star if field is required
        if (schema.required && schema.required.includes(key)) {
          const requiredMark = document.createElement("span");
          requiredMark.textContent = " *";
          requiredMark.className = "text-red-500";
          label.appendChild(requiredMark);
        }
        
        fieldDiv.appendChild(label);
        
        // Description help text - use textContent
        if (prop.description) {
          const description = document.createElement("small");
          description.textContent = prop.description;
          description.className = "text-gray-500 block mb-1";
          fieldDiv.appendChild(description);
        }
        
        if (prop.type === "array") {
          const arrayContainer = document.createElement("div");
          arrayContainer.className = "space-y-2";
          
          const createArrayInput = function (value = "") {
            const wrapper = document.createElement("div");
            wrapper.className = "flex items-center space-x-2";
            
            const input = document.createElement("input");
            input.name = keyValidation.value;
            input.required =
            schema.required && schema.required.includes(key);
            input.className =
            "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";
            
            const itemTypes = Array.isArray(prop.items?.anyOf)
              ? prop.items.anyOf.map((t) => t.type)
              : [prop.items?.type];
            
            if (
              itemTypes.includes("number") ||
              itemTypes.includes("integer")
            ) {
              input.type = "number";
              input.step = itemTypes.includes("integer")
                ? "1"
                : "any";
            } else if (itemTypes.includes("boolean")) {
              input.type = "checkbox";
              input.value = "true";
              input.checked = value === true || value === "true";
            } else {
              input.type = "text";
            }
            
            if (
              typeof value === "string" ||
              typeof value === "number"
            ) {
              input.value = value;
            }
            
            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className =
            "ml-2 text-red-600 hover:text-red-800 focus:outline-none";
            delBtn.title = "Delete";
            delBtn.textContent = "×";
            delBtn.addEventListener("click", () => {
              arrayContainer.removeChild(wrapper);
            });
            
            wrapper.appendChild(input);
            
            if (itemTypes.includes("boolean")) {
              const hidden = document.createElement("input");
              hidden.type = "hidden";
              hidden.name = keyValidation.value;
              hidden.value = "false";
              wrapper.appendChild(hidden);
            }
            
            wrapper.appendChild(delBtn);
            return wrapper;
          }
          
          const addBtn = document.createElement("button");
          addBtn.type = "button";
          addBtn.className =
          "mt-2 px-2 py-1 bg-indigo-500 text-white rounded hover:bg-indigo-600 focus:outline-none";
          addBtn.textContent = "Add items";
          addBtn.addEventListener("click", () => {
            arrayContainer.appendChild(createArrayInput());
          });
          
          if (Array.isArray(prop.default)) {
            if (prop.default.length > 0) {
              prop.default.forEach((val) => {
                arrayContainer.appendChild(
                  createArrayInput(val),
                );
              });
            } else {
              // Create one empty input for empty default arrays
              arrayContainer.appendChild(createArrayInput());
            }
          } else {
            arrayContainer.appendChild(createArrayInput());
          }
          
          fieldDiv.appendChild(arrayContainer);
          fieldDiv.appendChild(addBtn);
        } else {
          // Input field with validation (with multiline support)
          let fieldInput;
          const isTextType = prop.type === "text";
          if (isTextType) {
            fieldInput = document.createElement("textarea");
            fieldInput.rows = 4;
          } else {
            fieldInput = document.createElement("input");
            if (prop.type === "number" || prop.type === "integer") {
              fieldInput.type = "number";
            } else if (prop.type === "boolean") {
              fieldInput.type = "checkbox";
              fieldInput.value = "true";
            } else {
              fieldInput = document.createElement("textarea");
              fieldInput.rows = 1;
            }
          }
          
          fieldInput.name = keyValidation.value;
          fieldInput.required =
          schema.required && schema.required.includes(key);
          fieldInput.className =
          prop.type === "boolean"
            ? "mt-1 h-4 w-4 text-indigo-600 dark:text-indigo-200 border border-gray-300 rounded"
            : "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";
          
          // Set default values here
          if (prop.default !== undefined) {
            if (fieldInput.type === "checkbox") {
              fieldInput.checked = prop.default === true;
            } else if (isTextType) {
              fieldInput.value = prop.default;
            } else {
              fieldInput.value = prop.default;
            }
          }
          
          fieldDiv.appendChild(fieldInput);
          if (prop.default !== undefined) {
            if (fieldInput.type === "checkbox") {
              const hiddenInput = document.createElement("input");
              hiddenInput.type = "hidden";
              hiddenInput.value = "false";
              hiddenInput.name = keyValidation.value;
              fieldDiv.appendChild(hiddenInput);
            }
          }
        }
        
        container.appendChild(fieldDiv);
      }
    }
    
    openModal("tool-test-modal");
    console.log("✓ Tool test modal loaded successfully");
  } catch (error) {
    console.error("Error fetching tool details for testing:", error);
    
    // Clean up state on error
    toolTestState.activeRequests.delete(toolId);
    
    let errorMessage = error.message;
    
    // Enhanced error handling for rapid clicking scenarios
    if (error.name === "AbortError") {
      errorMessage = "Request was cancelled. Please try again.";
    } else if (
      error.message.includes("Failed to fetch") ||
      error.message.includes("NetworkError")
    ) {
      errorMessage =
      "Unable to connect to the server. Please wait a moment and try again.";
    } else if (
      error.message.includes("empty response") ||
      error.message.includes("ERR_EMPTY_RESPONSE")
    ) {
      errorMessage =
      "The server returned an empty response. Please wait a moment and try again.";
    } else if (error.message.includes("timeout")) {
      errorMessage =
      "Request timed out. Please try again in a few seconds.";
    }
    
    showErrorMessage(errorMessage);
  } finally {
    // 8. ALWAYS RESTORE BUTTON STATE
    const testButton = document.querySelector(
      `[onclick*="testTool('${toolId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Test";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

export const loadTools = async function () {
  const toolBody = safeGetElement("toolBody");
  console.log("Loading tools...");
  try {
    if (toolBody !== null) {
      toolBody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center py-4 text-gray-500">Loading tools...</td>
                </tr>
                `;
      const response = await fetch(`${window.ROOT_PATH}/admin/tools`, {
        method: "GET",
      });
      
      if (!response.ok) {
        throw new Error("Failed to load tools");
      }
      let tools = await response.json();
      if ("data" in tools) {
        tools = tools.data;
      }
      console.log("Fetched tools:", tools);
      
      if (!tools.length) {
        toolBody.innerHTML = `
                <tr><td colspan="5" class="text-center py-4 text-gray-500">No tools found.</td></tr>
                `;
        return;
      }
      
      const rows = tools
        .map((tool) => {
          const { id, name, integrationType, enabled, reachable } =
        tool;
          let statusText = "";
          let statusClass = "";
          if (enabled && reachable) {
            statusText = "Online";
            statusClass = "bg-green-100 text-green-800";
          } else if (enabled) {
            statusText = "Offline";
            statusClass = "bg-yellow-100 text-yellow-800";
          } else {
            statusText = "Inactive";
            statusClass = "bg-red-100 text-red-800";
          }
          return `
                <tr data-name="${name.toLowerCase()}" data-status="${enabled ? "enabled" : "disabled"}">
                    <td class="px-4 py-3">
                    <input type="checkbox" class="tool-checkbox h-4 w-4 text-indigo-600 border-gray-300 rounded"
                            data-tool="${name}###${id}">
                    </td>
                    <td class="px-4 py-3">${name}</td>
                    <td class="px-4 py-3">${integrationType || "-"}</td>
                    <td class="px-2 py-4 whitespace-nowrap text-sm w-12">
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusClass}">
                        ${statusText}
                    </span>
                    </td>
                    <td class="px-2 py-4 whitespace-nowrap text-sm font-medium w-32">
                    <div class="grid grid-cols-2 gap-x-2 gap-y-0 max-w-48">
                        <button onclick="Admin.enrichTool('${id}')"
                        class="col-span-2 px-2 py-1 text-xs font-medium rounded-md text-teal-600 hover:bg-teal-50">
                        Enrich
                        </button>
                        <button onclick="Admin.generateToolTestCases('${id}')"
                        class="col-span-2 px-2 py-1 text-[11px] font-small rounded-md text-purple-600 hover:bg-purple-50">
                        Generate Test Cases
                        </button>
                        <button onclick="Admin.validateTool('${id}')"
                        class="col-span-2 px-2 py-1 text-xs font-medium rounded-md text-yellow-600 hover:bg-yellow-50">
                        Validate
                        </button>
                        <button onclick="Admin.viewTool('${id}')"
                        class="px-2 py-1 text-xs font-medium rounded-md text-indigo-600 hover:bg-indigo-50">
                        View
                        </button>
                        <button onclick="Admin.editTool('${id}')"
                        class="px-2 py-1 text-xs font-medium rounded-md text-green-600 hover:bg-green-50">
                        Edit
                        </button>
                    </div>
                    </td>
                </tr>
                `;
        })
        .join("");
      toolBody.innerHTML = rows;
    }
  } catch (error) {
    console.error("Error loading tools:", error);
    if (toolBody !== null) {
      toolBody.innerHTML = `
                <tr>
                <td colspan="5" class="text-center py-4 text-red-500">Failed to load tools. Please try again.</td>
                </tr>
            `;
    }
  }
};

export const enrichTool = async function (toolId) {
  try {
    console.log(`Enriching tool ID: ${toolId}`);
    const now = Date.now();
    const lastRequest = toolTestState.lastRequestTime.get(toolId) || 0;
    const timeSinceLastRequest = now - lastRequest;
    const enhancedDebounceDelay = 2000; // Increased from 1000ms
    
    if (timeSinceLastRequest < enhancedDebounceDelay) {
      console.log(
        `Tool ${toolId} test request debounced (${timeSinceLastRequest}ms ago)`,
      );
      const waitTime = Math.ceil(
        (enhancedDebounceDelay - timeSinceLastRequest) / 1000,
      );
      showErrorMessage(
        `Please wait ${waitTime} more second${waitTime > 1 ? "s" : ""} before testing again`,
      );
      return;
    }
    
    // 3. BUTTON STATE: Immediate feedback with better state management
    const enrichButton = document.querySelector(
      `[onclick*="enrichTool('${toolId}')"]`,
    );
    if (enrichButton) {
      if (enrichButton.disabled) {
        console.log(
          "Test button already disabled, request in progress",
        );
        return;
      }
      enrichButton.disabled = true;
      enrichButton.textContent = "Enriching...";
      enrichButton.classList.add("opacity-50", "cursor-not-allowed");
    }
    
    // 4. REQUEST CANCELLATION: Enhanced cleanup
    const existingController = toolTestState.activeRequests.get(toolId);
    if (existingController) {
      console.log(`Cancelling existing request for tool ${toolId}`);
      existingController.abort();
      toolTestState.activeRequests.delete(toolId);
    }
    
    // 5. CREATE NEW REQUEST with longer timeout
    const controller = new AbortController();
    toolTestState.activeRequests.set(toolId, controller);
    toolTestState.lastRequestTime.set(toolId, now);
    
    // 6. MAKE REQUEST with increased timeout
    //    const response = await fetchWithTimeout(`/enrich_tools_util`, {
    const response = await fetchWithTimeout(
      `/toolops/enrichment/enrich_tool?tool_id=${toolId}`,
      {
        method: "POST",
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tool_id: toolId }),
      },
      toolTestState.requestTimeout, // Use the increased timeout
    );
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          `Tool with ID ${toolId} not found. It may have been deleted.`,
        );
      } else if (response.status === 429) {
        throw new Error(
          "Too many requests. Please wait a moment before validating again.",
        );
      } else if (response.status >= 500) {
        throw new Error(
          `Server error (${response.status}). The server may be overloaded. Please try again in a few seconds.`,
        );
      } else {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`,
        );
      }
    }
    
    const data = await response.json();
    enrichButton.disabled = false;
    enrichButton.textContent = "Enrich";
    enrichButton.classList.remove("opacity-50", "cursor-not-allowed");
    console.log(`Tool ${toolId} enriched successfully`, data);
    // showSuccessMessage(`Tool ${toolId} enriched successfully`);
    
    const newDesc = safeGetElement("view-new-description");
    const oldDesc = safeGetElement("view-old-description");
    
    if (newDesc) {
      newDesc.textContent = data.enriched_desc || "";
    }
    if (oldDesc) {
      oldDesc.textContent =
      data.original_desc.slice(0, data.original_desc.indexOf("*")) ||
      "";
    }
    openModal("description-view-modal");
    // showSuccessMessage(`Tool enriched successfully`);
  } catch (error) {
    console.error("Error fetching tool details for testing:", error);
    showErrorMessage(error.message);
  } finally {
    const testButton = document.querySelector(
      `[onclick*="enrichTool('${toolId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Enrich";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

export const generateToolTestCases = async function (toolId) {
  try {
    console.log(`Generating Test cases for tool ID: ${toolId}`);
    const now = Date.now();
    const lastRequest = toolTestState.lastRequestTime.get(toolId) || 0;
    const timeSinceLastRequest = now - lastRequest;
    const enhancedDebounceDelay = 2000; // Increased from 1000ms
    
    if (timeSinceLastRequest < enhancedDebounceDelay) {
      console.log(
        `Tool ${toolId} test request debounced (${timeSinceLastRequest}ms ago)`,
      );
      const waitTime = Math.ceil(
        (enhancedDebounceDelay - timeSinceLastRequest) / 1000,
      );
      showErrorMessage(
        `Please wait ${waitTime} more second${waitTime > 1 ? "s" : ""} before testing again`,
      );
      return;
    }
    
    // 3. BUTTON STATE: Immediate feedback with better state management
    const tcgButton = document.querySelector(
      `[onclick*="generateToolTestCases('${toolId}')"]`,
    );
    if (tcgButton) {
      if (tcgButton.disabled) {
        console.log(
          "Generate Test Cases button already disabled, request in progress",
        );
        return;
      }
      tcgButton.disabled = true;
      tcgButton.textContent = "Generating Test Cases...";
      tcgButton.classList.add("opacity-50", "cursor-not-allowed");
    }
    
    // 4. REQUEST CANCELLATION: Enhanced cleanup
    const existingController = toolTestState.activeRequests.get(toolId);
    if (existingController) {
      console.log(`Cancelling existing request for tool ${toolId}`);
      existingController.abort();
      toolTestState.activeRequests.delete(toolId);
    }
    
    // 5. CREATE NEW REQUEST with longer timeout
    const controller = new AbortController();
    toolTestState.activeRequests.set(toolId, controller);
    toolTestState.lastRequestTime.set(toolId, now);
    
    const toolIdElement = safeGetElement("gen-test-tool-id");
    if (toolIdElement) {
      toolIdElement.textContent = toolId || "Unknown";
    }
    safeGetElement("gen-test-tool-id").style.display = "none";
    // safeGetElement("gen-test-tool-id").style.display = 'block';
    
    openModal("testcase-gen-modal");
    
    tcgButton.disabled = false;
    tcgButton.textContent = "Generate Test Cases";
    tcgButton.classList.remove("opacity-50", "cursor-not-allowed");
  } catch (error) {
    console.error("Error fetching tool details for testing:", error);
    showErrorMessage(error.message);
  } finally {
    const testButton = document.querySelector(
      `[onclick*="generateToolTestCases('${toolId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Generate Test Cases";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

export const generateTestCases = async function () {
  const testCases = safeGetElement("gen-testcase-count").value;
  const variations = safeGetElement("gen-nl-variation-count").value;
  let toolId;
  // const toolId = safeGetElement("gen-test-tool-id").value;
  const toolIdElement = safeGetElement("gen-test-tool-id");
  if (toolIdElement) {
    toolId = toolIdElement.textContent || "Unknown";
  }
  console.log(
    `Generate ${testCases} test cases with ${variations} variations for tool ${toolId}`,
  );
  
  try {
    showSuccessMessage(
      "Test case generation started successfully for the tool.",
    );
    closeModal("testcase-gen-modal");
    const response = await fetch(
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
    
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          `Tool with ID ${toolId} not found. It may have been deleted.`,
        );
      } else if (response.status === 429) {
        throw new Error(
          "Too many requests. Please wait a moment before validating again.",
        );
      } else if (response.status >= 500) {
        throw new Error(
          `Server error (${response.status}). The server may be overloaded. Please try again in a few seconds.`,
        );
      } else {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`,
        );
      }
    }
    // const data = await response.json();
    // console.log(data)
    // showSuccessMessage(`Tool ${toolId} enriched successfully`);
  } catch (error) {
    console.error("Error fetching tool details for testing:", error);
    showErrorMessage(error.message);
  } finally {
    const testButton = document.querySelector(
      `[onclick*="generateToolTestCases('${toolId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Generate Test Cases";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

export const validateTool = async function (toolId) {
  try {
    console.log(`Validating tool ID: ${toolId}`);
    
    // 1. ENHANCED DEBOUNCING: More aggressive to prevent rapid clicking
    const now = Date.now();
    const lastRequest = toolTestState.lastRequestTime.get(toolId) || 0;
    const timeSinceLastRequest = now - lastRequest;
    const enhancedDebounceDelay = 2000; // Increased from 1000ms
    
    if (timeSinceLastRequest < enhancedDebounceDelay) {
      console.log(
        `Tool ${toolId} test request debounced (${timeSinceLastRequest}ms ago)`,
      );
      const waitTime = Math.ceil(
        (enhancedDebounceDelay - timeSinceLastRequest) / 1000,
      );
      showErrorMessage(
        `Please wait ${waitTime} more second${waitTime > 1 ? "s" : ""} before testing again`,
      );
      return;
    }
    
    // 2. MODAL PROTECTION: Enhanced check
    if (AppState.isModalActive("tool-validation-modal")) {
      console.warn("Tool validation modal is already active");
      return; // Silent fail for better UX
    }
    
    // 3. BUTTON STATE: Immediate feedback with better state management
    const validateButton = document.querySelector(
      `[onclick*="validateTool('${toolId}')"]`,
    );
    if (validateButton) {
      if (validateButton.disabled) {
        console.log(
          "Test button already disabled, request in progress",
        );
        return;
      }
      validateButton.disabled = true;
      validateButton.textContent = "Generating Test Cases...";
      validateButton.classList.add("opacity-50", "cursor-not-allowed");
    }
    
    // 4. REQUEST CANCELLATION: Enhanced cleanup
    const existingController = toolTestState.activeRequests.get(toolId);
    if (existingController) {
      console.log(`Cancelling existing request for tool ${toolId}`);
      existingController.abort();
      toolTestState.activeRequests.delete(toolId);
    }
    
    // 5. CREATE NEW REQUEST with longer timeout
    const controller = new AbortController();
    toolTestState.activeRequests.set(toolId, controller);
    toolTestState.lastRequestTime.set(toolId, now);
    
    // 6. MAKE REQUEST with increased timeout
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/tools/${toolId}`,
      {
        signal: controller.signal,
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      },
      toolTestState.requestTimeout, // Use the increased timeout
    );
    
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          `Tool with ID ${toolId} not found. It may have been deleted.`,
        );
      } else if (response.status === 429) {
        throw new Error(
          "Too many requests. Please wait a moment before validating again.",
        );
      } else if (response.status >= 500) {
        throw new Error(
          `Server error (${response.status}). The server may be overloaded. Please try again in a few seconds.`,
        );
      } else {
        throw new Error(
          `HTTP ${response.status}: ${response.statusText}`,
        );
      }
    }
    const tool = await response.json();
    console.log(`Tool ${toolId} fetched successfully`, tool);
    toolInputSchemaRegistry = tool;
    
    // 7. CLEAN STATE before proceeding
    toolTestState.activeRequests.delete(toolId);
    
    // Store in safe state
    AppState.currentTestTool = tool;
    
    // Set modal title and description safely - NO DOUBLE ESCAPING
    const titleElement = safeGetElement("tool-validation-modal-title");
    const descElement = safeGetElement("tool-validation-modal-description");
    
    if (titleElement) {
      titleElement.textContent = "Test Tool: " + (tool.name || "Unknown");
    }
    if (descElement) {
      if (tool.description) {
        // Escape HTML and then replace newlines with <br/> tags
        tool.description = tool.description.slice(
          0,
          tool.description.indexOf("*"),
        );
        descElement.innerHTML = escapeHtml(tool.description).replace(
          /\n/g,
          "<br/>",
        );
      } else {
        descElement.textContent = "No description available.";
      }
    }
    
    const container = safeGetElement("tool-validation-form-fields");
    if (!container) {
      console.error("Tool validation form fields container not found");
      return;
    }
    
    container.innerHTML = ""; // Clear previous fields
    
    // Parse the input schema safely
    let schema = tool.inputSchema;
    if (typeof schema === "string") {
      try {
        schema = JSON.parse(schema);
      } catch (e) {
        console.error("Invalid JSON schema", e);
        schema = {};
      }
    }
    
    // Modal setup
    const title = safeGetElement("tool-validation-modal-title");
    const desc = safeGetElement("tool-validation-modal-description");
    if (title) {
      title.textContent = `Test Tool: ${tool.name || "Unknown"}`;
    }
    if (desc) {
      desc.textContent = tool.description || "No description available.";
    }
    if (!container) {
      return;
    }
    
    container.innerHTML = "";
    
    // Parse schema safely
    if (typeof schema === "string") {
      try {
        schema = JSON.parse(schema);
      } catch (e) {
        console.error("Invalid schema JSON", e);
        schema = {};
      }
    }
    
    // Example validat cases (you can replace this with API-provided cases)
    let testCases = tool.testCases || [
      { id: "t1", name: "Test Case 1", input_parameters: {} },
      { id: "t2", name: "Test Case 2", input_parameters: {} },
    ];
    
    const validationStatusResponse = await fetchWithTimeout(
      `/toolops/validation/generate_testcases?tool_id=${toolId}&mode=status`,
      {
        method: "POST",
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tool_id: toolId }),
      },
      toolTestState.requestTimeout, // Use the increased timeout
    );
    
    if (validationStatusResponse.ok) {
      const vsres = await validationStatusResponse.json();
      console.log(JSON.stringify(vsres));
      let validationStatus = await vsres;
      
      if (validationStatus.constructor === Array) {
        validationStatus = validationStatus[0].status;
        if (validationStatus === "not-initiated") {
          showErrorMessage(
            "Please generate test cases before running validation.",
          );
        } else if (validationStatus === "in-progress") {
          showErrorMessage(
            "Test case generation is in progress. Please try validation once it is complete.",
          );
        } else if (validationStatus === "failed") {
          showErrorMessage(
            "Test case generation failed. Please check your LLM connection and try again.",
          );
          console.log(
            "Previous error while generating test cases: ",
            vsres[0].error_message,
          );
        } else {
          const validationResponse = await fetchWithTimeout(
            `/toolops/validation/generate_testcases?tool_id=${toolId}&mode=query`,
            {
              method: "POST",
              headers: {
                "Cache-Control": "no-cache",
                Pragma: "no-cache",
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ tool_id: toolId }),
            },
            toolTestState.requestTimeout, // Use the increased timeout
          );
          
          if (validationResponse.ok) {
            const vres = await validationResponse.json();
            // console.log(JSON.stringify(vres))
            testCases = await vres;
          }
          
          // Render accordion-style test cases
          testCases.forEach((test, index) => {
            const inputParameters = test.input_parameters;
            const acc = document.createElement("div");
            acc.className =
            "border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden";
            
            const header = document.createElement("button");
            header.type = "button";
            header.className =
            "w-full flex justify-between items-center px-4 py-3 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium";
            header.innerHTML = `
                            <span>${`Test Case ${index + 1}`}</span>
                            <span class="toggle-icon">+</span>
                        `;
            
            const body = document.createElement("div");
            body.className =
            "hidden bg-white dark:bg-gray-900 px-4 py-4 space-y-3";
            
            // Toggle open/close
            header.addEventListener("click", () => {
              const isOpen = !body.classList.contains("hidden");
              body.classList.toggle("hidden", isOpen);
              header.querySelector(".toggle-icon").textContent =
              isOpen ? "+" : "−";
            });
            
            acc.appendChild(header);
            acc.appendChild(body);
            container.appendChild(acc);
            
            // Render fields
            const formDiv = document.createElement("form");
            formDiv.id = `tool-validation-form-${index}`;
            formDiv.className = "space-y-3";
            
            if (schema && schema.properties) {
              for (const key in schema.properties) {
                const prop = schema.properties[key];
                
                // Validate the property name
                const keyValidation = validateInputName(
                  key,
                  "schema property",
                );
                if (!keyValidation.valid) {
                  console.warn(
                    `Skipping invalid schema property: ${key}`,
                  );
                  continue;
                }
                
                const fieldDiv = document.createElement("div");
                fieldDiv.className = "mb-4";
                
                // Field label - use textContent to avoid double escaping
                const label = document.createElement("label");
                // label.textContent = key;
                label.className =
                "block text-sm font-medium text-gray-700 dark:text-gray-300";
                // Create span for label text
                const labelText =
                document.createElement("span");
                labelText.textContent = keyValidation.value;
                label.appendChild(labelText);
                let defaultValue = "";
                if (keyValidation.value in inputParameters) {
                  defaultValue =
                  inputParameters[keyValidation.value];
                }
                
                // Add red star if field is required
                if (
                  schema.required &&
                  schema.required.includes(key)
                ) {
                  const requiredMark =
                  document.createElement("span");
                  requiredMark.textContent = " *";
                  requiredMark.className = "text-red-500";
                  label.appendChild(requiredMark);
                }
                
                fieldDiv.appendChild(label);
                
                // Description help text - use textContent
                if (prop.description) {
                  const description =
                  document.createElement("small");
                  description.textContent = prop.description;
                  description.className =
                  "text-gray-500 block mb-1";
                  fieldDiv.appendChild(description);
                }
                
                // const input = document.createElement("input");
                // input.name = key;
                // input.className =
                // "mt-1 block w-full rounded-md border border-gray-300 dark:border-gray-600 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-800 text-gray-200";
                // input.value = test.inputs[key] || prop.default || "";
                // fieldDiv.appendChild(input);
                
                if (prop.type === "array") {
                  const arrayContainer =
                  document.createElement("div");
                  arrayContainer.className = "space-y-2";
                  
                  const createArrayInput = function (value = "") {
                    const wrapper =
                    document.createElement("div");
                    wrapper.className =
                    "flex items-center space-x-2";
                    
                    const input =
                    document.createElement("input");
                    input.name = keyValidation.value;
                    input.required =
                    schema.required &&
                    schema.required.includes(key);
                    input.className =
                    "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";
                    
                    const itemTypes = Array.isArray(
                      prop.items?.anyOf,
                    )
                      ? prop.items.anyOf.map(
                        (t) => t.type,
                      )
                      : [prop.items?.type];
                    
                    if (
                      itemTypes.includes("number") ||
                      itemTypes.includes("integer")
                    ) {
                      input.type = "number";
                      input.step = itemTypes.includes(
                        "integer",
                      )
                        ? "1"
                        : "any";
                    } else if (
                      itemTypes.includes("boolean")
                    ) {
                      input.type = "checkbox";
                      input.value = "true";
                      input.checked =
                      value === true ||
                      value === "true";
                    } else {
                      input.type = "text";
                    }
                    
                    if (
                      typeof value === "string" ||
                      typeof value === "number"
                    ) {
                      input.value = value;
                    }
                    
                    const delBtn =
                    document.createElement("button");
                    delBtn.type = "button";
                    delBtn.className =
                    "ml-2 text-red-600 hover:text-red-800 focus:outline-none";
                    delBtn.title = "Delete";
                    delBtn.textContent = "×";
                    delBtn.addEventListener("click", () => {
                      arrayContainer.removeChild(wrapper);
                    });
                    
                    wrapper.appendChild(input);
                    
                    if (itemTypes.includes("boolean")) {
                      const hidden =
                      document.createElement("input");
                      hidden.type = "hidden";
                      hidden.name = keyValidation.value;
                      hidden.value = "false";
                      wrapper.appendChild(hidden);
                    }
                    
                    wrapper.appendChild(delBtn);
                    return wrapper;
                  }
                  
                  const addBtn =
                  document.createElement("button");
                  addBtn.type = "button";
                  addBtn.className =
                  "mt-2 px-2 py-1 bg-indigo-500 text-white rounded hover:bg-indigo-600 focus:outline-none";
                  addBtn.textContent = "Add items";
                  addBtn.addEventListener("click", () => {
                    arrayContainer.appendChild(
                      createArrayInput(),
                    );
                  });
                  
                  defaultValue = defaultValue[0];
                  if (Array.isArray(defaultValue)) {
                    if (defaultValue.length > 0) {
                      defaultValue.forEach((val) => {
                        arrayContainer.appendChild(
                          createArrayInput(val),
                        );
                      });
                    } else {
                      // Create one empty input for empty default arrays
                      arrayContainer.appendChild(
                        createArrayInput(),
                      );
                    }
                  } else {
                    arrayContainer.appendChild(
                      createArrayInput(),
                    );
                  }
                  
                  fieldDiv.appendChild(arrayContainer);
                  fieldDiv.appendChild(addBtn);
                } else {
                  // Input field with validation (with multiline support)
                  let fieldInput;
                  const isTextType = prop.type === "text";
                  if (isTextType) {
                    fieldInput =
                    document.createElement("textarea");
                    fieldInput.rows = 4;
                  } else {
                    fieldInput =
                    document.createElement("input");
                    if (
                      prop.type === "number" ||
                      prop.type === "integer"
                    ) {
                      fieldInput.type = "number";
                    } else if (prop.type === "boolean") {
                      fieldInput.type = "checkbox";
                      fieldInput.value = "true";
                    } else {
                      fieldInput =
                      document.createElement(
                        "textarea",
                      );
                      fieldInput.rows = 1;
                    }
                  }
                  
                  fieldInput.name = keyValidation.value;
                  fieldInput.required =
                  schema.required &&
                  schema.required.includes(key);
                  fieldInput.className =
                  prop.type === "boolean"
                    ? "mt-1 h-4 w-4 text-indigo-600 dark:text-indigo-200 border border-gray-300 rounded"
                    : "mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 text-gray-700 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";
                  
                  // Set default values here
                  if (prop.default !== undefined) {
                    if (fieldInput.type === "checkbox") {
                      fieldInput.checked =
                      prop.default === true;
                    } else if (isTextType) {
                      fieldInput.value = prop.default;
                    } else {
                      fieldInput.value = prop.default;
                    }
                  }
                  fieldInput.value = defaultValue;
                  fieldDiv.appendChild(fieldInput);
                  if (prop.default !== undefined) {
                    if (fieldInput.type === "checkbox") {
                      const hiddenInput =
                      document.createElement("input");
                      hiddenInput.type = "hidden";
                      hiddenInput.value = "false";
                      hiddenInput.name =
                      keyValidation.value;
                      fieldDiv.appendChild(hiddenInput);
                    }
                  }
                }
                formDiv.appendChild(fieldDiv);
              }
            }
            
            // First section - Passthrough Headers
            const headerSection = document.createElement("div");
            headerSection.className = "mt-4 border-t pt-4";
            
            const headerDiv = document.createElement("div");
            
            const label = document.createElement("label");
            label.setAttribute(
              "for",
              "validation-passthrough-headers",
            );
            label.className =
            "block text-sm font-medium text-gray-700 dark:text-gray-400";
            label.textContent = "Passthrough Headers (Optional)";
            
            const small = document.createElement("small");
            small.className =
            "text-gray-500 dark:text-gray-400 block mb-2";
            small.textContent =
            'Additional headers to send with the request (format: "Header-Name: Value", one per line)';
            
            const textarea = document.createElement("textarea");
            textarea.id = "validation-passthrough-headers";
            textarea.name = "passthrough_headers";
            textarea.rows = 3;
            textarea.placeholder =
            "Authorization: Bearer your-token\nX-Tenant-Id: tenant-123\nX-Trace-Id: trace-456";
            textarea.className =
            "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-200";
            
            headerDiv.appendChild(label);
            headerDiv.appendChild(small);
            headerDiv.appendChild(textarea);
            headerSection.appendChild(headerDiv);
            
            const nlUtteranceSection =
            document.createElement("div");
            nlUtteranceSection.className = "mt-4 border-t pt-4";
            const nlUtteranceDiv = document.createElement("div");
            const nlUtterancelabel =
            document.createElement("label");
            nlUtterancelabel.setAttribute(
              "for",
              "test-passthrough-nlUtterances",
            );
            nlUtterancelabel.className =
            "block text-sm font-bold text-green-700 dark:text-green-400";
            nlUtterancelabel.textContent =
            "Generated Test Utterance";
            
            const nlUtterancesmall =
            document.createElement("small");
            nlUtterancesmall.className =
            "text-gray-500 dark:text-gray-400 block mb-2";
            nlUtterancesmall.textContent =
            "Modify or add new utterances to test using the agent.";
            
            const nlutextarea = document.createElement("textarea");
            nlutextarea.id = `validation-passthrough-nlUtterances-${index}`;
            nlutextarea.name = "passthrough_nlUtterances";
            nlutextarea.rows = 3;
            nlutextarea.value = test.nl_utterance.join("\n\n");
            nlutextarea.className =
            "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-200";
            
            nlUtteranceDiv.appendChild(nlUtterancelabel);
            nlUtteranceDiv.appendChild(nlUtterancesmall);
            nlUtteranceDiv.appendChild(nlutextarea);
            nlUtteranceSection.appendChild(nlUtteranceDiv);
            
            // // Result area
            // const resultBox = document.createElement("pre");
            // resultBox.id = `test-result-${index}`;
            // resultBox.className =
            // "bg-gray-50 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-200 p-3 rounded overflow-x-auto hidden border border-gray-200 dark:border-gray-700";
            
            // Run button
            const runBtn = document.createElement("button");
            runBtn.textContent = "Run Test";
            runBtn.className =
            "mt-2 mr-2 px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700";
            // Added: mr-2 for spacing
            runBtn.addEventListener("click", async () => {
              await runToolValidation(index);
            });
            
            // Run Agent button
            const runAgentBtn = document.createElement("button");
            runAgentBtn.textContent = "Run With Agent";
            runAgentBtn.className =
            "mt-2 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700";
            // Changed color to blue
            runAgentBtn.addEventListener("click", async () => {
              await runToolAgentValidation(index);
            });
            
            // Loading spinner
            const loadingDiv = document.createElement("div");
            loadingDiv.id = `tool-validation-loading-${index}`;
            loadingDiv.style.display = "none";
            
            const spinner = document.createElement("div");
            spinner.className = "spinner";
            loadingDiv.appendChild(spinner);
            
            // Result area
            const resultDiv = document.createElement("div");
            resultDiv.id = `tool-validation-result-${index}`;
            resultDiv.className =
            "mt-4 bg-gray-100 p-2 rounded overflow-auto dark:bg-gray-900 dark:text-gray-300";
            resultDiv.style.height = "400px";
            
            body.appendChild(formDiv);
            body.appendChild(headerSection);
            body.appendChild(nlUtteranceSection);
            body.appendChild(runBtn);
            body.appendChild(runAgentBtn);
            body.appendChild(loadingDiv);
            body.appendChild(resultDiv);
          });
          
          // Run All Tests button
          const runAllDiv = document.createElement("div");
          runAllDiv.className = "mt-6 text-center";
          runAllDiv.innerHTML = `
                        <button id="run-all-tests-btn"
                        class="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700">
                        Run All Tests
                        </button>`;
          container.appendChild(runAllDiv);
          
          // Run All Tests wit hAgent button
          // const runAGentAllDiv = document.createElement("div");
          // runAGentAllDiv.className = "mt-6 text-center";
          // runAGentAllDiv.innerHTML = `
          //     <button id="run-all-agent-tests-btn"
          //     class="px-4 py-2 bg-orange-600 text-white rounded hover:bg-orange-700">
          //     Run With Agent
          //     </button>`;
          // container.appendChild(runAGentAllDiv);
          
          // Hook up Run All button
          document
            .getElementById("run-all-tests-btn")
            ?.addEventListener("click", async () => {
              showSuccessMessage(
                "🔍 Validation in progress; View results by expanding each test case.",
              );
              const total = testCases.length;
              document
                .querySelectorAll(
                  "#tool-validation-form-fields > div",
                )
                .forEach((acc) => {
                  const body =
              acc.querySelector("div.hidden");
                  const icon =
              acc.querySelector(".toggle-icon");
                  if (body) {
                    body.classList.remove("hidden");
                  }
                  if (icon) {
                    icon.textContent = "−";
                  }
                });
              for (let i = 0; i < total; i++) {
                await runToolValidation(i);
              }
            });
          
          openModal("tool-validation-modal");
          console.log(
            "✓ Test modal with accordions loaded successfully",
          );
        }
      } else {
        showErrorMessage(
          "Test case generation failed. Please check your LLM connection and try again.",
        );
      }
    }
  } catch (error) {
    console.error("Error fetching tool details for testing:", error);
    showErrorMessage(error.message);
  } finally {
    const testButton = document.querySelector(
      `[onclick*="validateTool('${toolId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Validate";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
  }
};

export const runToolValidation = async function (testIndex) {
  const form = document.querySelector(`#tool-validation-form-${testIndex}`);
  const resultContainer = document.querySelector(
    `#tool-validation-result-${testIndex}`,
  );
  const loadingElement = safeGetElement(
    `tool-validation-loading-${testIndex}`,
  );
  const runButton = document.querySelector(
    'button[onclick="runToolValidation()"]',
  );
  
  if (!form || !AppState.currentTestTool) {
    console.error("Tool test form or current tool not found");
    showErrorMessage("Tool test form not available");
    return;
  }
  
  // Prevent multiple concurrent test runs
  if (runButton && runButton.disabled) {
    console.log("Tool test already running");
    return;
  }
  
  try {
    // Disable run button
    if (runButton) {
      runButton.disabled = true;
      runButton.textContent = "Running...";
      runButton.classList.add("opacity-50");
    }
    
    // Show loading
    if (loadingElement) {
      loadingElement.style.display = "block";
    }
    if (resultContainer) {
      resultContainer.innerHTML = "";
    }
    
    const formData = new FormData(form);
    // const formData = {};
    // form.querySelectorAll("input, textarea, select").forEach((input) => {
    // formData[input.name] =
    //     input.type === "checkbox" ? input.checked : input.value;
    // });
    const params = {};
    
    const schema = toolInputSchemaRegistry.inputSchema;
    
    if (schema && schema.properties) {
      for (const key in schema.properties) {
        const prop = schema.properties[key];
        const keyValidation = validateInputName(key, "parameter");
        if (!keyValidation.valid) {
          console.warn(`Skipping invalid parameter: ${key}`);
          continue;
        }
        let value;
        if (prop.type === "array") {
          const inputValues = formData.getAll(key);
          try {
            // Convert values based on the items schema type
            if (prop.items) {
              const itemType = Array.isArray(prop.items.anyOf)
                ? prop.items.anyOf.map((t) => t.type)
                : [prop.items.type];
              
              if (
                itemType.includes("number") ||
                itemType.includes("integer")
              ) {
                value = inputValues.map((v) => {
                  const num = Number(v);
                  if (isNaN(num)) {
                    throw new Error(`Invalid number: ${v}`);
                  }
                  return num;
                });
              } else if (itemType.includes("boolean")) {
                value = inputValues.map(
                  (v) => v === "true" || v === true,
                );
              } else if (itemType.includes("object")) {
                value = inputValues.map((v) => {
                  try {
                    const parsed = JSON.parse(v);
                    if (
                      typeof parsed !== "object" ||
                      Array.isArray(parsed)
                    ) {
                      throw new Error(
                        "Value must be an object",
                      );
                    }
                    return parsed;
                  } catch {
                    throw new Error(
                      `Invalid object format for ${key}`,
                    );
                  }
                });
              } else {
                value = inputValues;
              }
            }
            
            // Handle empty values
            if (
              value.length === 0 ||
              (value.length === 1 && value[0] === "")
            ) {
              if (
                schema.required &&
                schema.required.includes(key)
              ) {
                params[keyValidation.value] = [];
              }
              continue;
            }
            params[keyValidation.value] = value;
          } catch (error) {
            console.error(
              `Error parsing array values for ${key}:`,
              error,
            );
            showErrorMessage(
              `Invalid input format for ${key}. Please check the values are in correct format.`,
            );
            throw error;
          }
        } else {
          value = formData.get(key);
          if (value === null || value === undefined || value === "") {
            if (schema.required && schema.required.includes(key)) {
              params[keyValidation.value] = "";
            }
            continue;
          }
          if (prop.type === "number" || prop.type === "integer") {
            params[keyValidation.value] = Number(value);
          } else if (prop.type === "boolean") {
            params[keyValidation.value] =
            value === "true" || value === true;
          } else if (prop.enum) {
            if (prop.enum.includes(value)) {
              params[keyValidation.value] = value;
            }
          } else {
            params[keyValidation.value] = value;
          }
        }
      }
    }
    
    const payload = {
      jsonrpc: "2.0",
      id: Date.now(),
      method: AppState.currentTestTool.name,
      params,
    };
    
    // Parse custom headers from the passthrough headers field
    const requestHeaders = {
      "Content-Type": "application/json",
    };
    
    // Authentication will be handled automatically by the JWT cookie
    // that was set when the admin UI loaded. The 'credentials: "include"'
    // in the fetch request ensures the cookie is sent with the request.
    
    const passthroughHeadersField = safeGetElement(
      "validation-passthrough-headers",
    );
    if (passthroughHeadersField && passthroughHeadersField.value.trim()) {
      const headerLines = passthroughHeadersField.value
        .trim()
        .split("\n");
      for (const line of headerLines) {
        const trimmedLine = line.trim();
        if (trimmedLine) {
          const colonIndex = trimmedLine.indexOf(":");
          if (colonIndex > 0) {
            const headerName = trimmedLine
              .substring(0, colonIndex)
              .trim();
            const headerValue = trimmedLine
              .substring(colonIndex + 1)
              .trim();
            
            // Validate header name and value
            const validation = validatePassthroughHeader(
              headerName,
              headerValue,
            );
            if (!validation.valid) {
              showErrorMessage(
                `Invalid header: ${validation.error}`,
              );
              return;
            }
            
            if (headerName && headerValue) {
              requestHeaders[headerName] = headerValue;
            }
          } else if (colonIndex === -1) {
            showErrorMessage(
              `Invalid header format: "${trimmedLine}". Expected format: "Header-Name: Value"`,
            );
            return;
          }
        }
      }
    }
    
    // Use longer timeout for test execution
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/rpc`,
      {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify(payload),
        credentials: "include",
      },
      window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
    );
    
    const result = await response.json();
    const resultStr = JSON.stringify(result, null, 2);
    
    if (resultContainer && window.CodeMirror) {
      try {
        AppState.toolTestResultEditor = window.CodeMirror(
          resultContainer,
          {
            value: resultStr,
            mode: "application/json",
            theme: "monokai",
            readOnly: true,
            lineNumbers: true,
          },
        );
      } catch (editorError) {
        console.error("Error creating CodeMirror editor:", editorError);
        // Fallback to plain text
        const pre = document.createElement("pre");
        pre.className =
        "bg-gray-900 text-green-400 p-4 rounded overflow-auto max-h-96";
        pre.textContent = resultStr;
        resultContainer.appendChild(pre);
      }
    } else if (resultContainer) {
      const pre = document.createElement("pre");
      pre.className =
      "bg-gray-100 p-4 rounded overflow-auto max-h-96 dark:bg-gray-800 dark:text-gray-100";
      pre.textContent = resultStr;
      resultContainer.appendChild(pre);
    }
    
    console.log("✓ Tool test completed successfully");
  } catch (error) {
    console.error("Tool test error:", error);
    if (resultContainer) {
      const errorMessage = handleFetchError(error, "run tool test");
      const errorDiv = document.createElement("div");
      errorDiv.className = "text-red-600 p-4";
      errorDiv.textContent = `Error: ${errorMessage}`;
      resultContainer.appendChild(errorDiv);
    }
  } finally {
    // Always restore UI state
    if (loadingElement) {
      loadingElement.style.display = "none";
    }
    if (runButton) {
      runButton.disabled = false;
      runButton.textContent = "Run Tool";
      runButton.classList.remove("opacity-50");
    }
  }
};

export const runToolAgentValidation = async function (testIndex) {
  const form = document.querySelector(`#tool-validation-form-${testIndex}`);
  const resultContainer = document.querySelector(
    `#tool-validation-result-${testIndex}`,
  );
  const loadingElement = safeGetElement(
    `tool-validation-loading-${testIndex}`,
  );
  const runButton = document.querySelector(
    'button[onclick="runToolAgentValidation()"]',
  );
  
  if (!form || !AppState.currentTestTool) {
    console.error("Tool test form or current tool not found");
    showErrorMessage("Tool test form not available");
    return;
  }
  
  // Prevent multiple concurrent test runs
  if (runButton && runButton.disabled) {
    console.log("Tool test already running");
    return;
  }
  
  try {
    // Disable run button
    if (runButton) {
      runButton.disabled = true;
      runButton.textContent = "Running...";
      runButton.classList.add("opacity-50");
    }
    
    // Show loading
    if (loadingElement) {
      loadingElement.style.display = "block";
    }
    if (resultContainer) {
      resultContainer.innerHTML = "";
    }
    
    const nlTestCases = document
      .getElementById(`validation-passthrough-nlUtterances-${testIndex}`)
      .value.split(/\r?\n\r?\n/);
    const toolId = AppState.currentTestTool.id;
    
    console.log(nlTestCases);
    console.log(
      "Running validation for the Tool: ",
      AppState.currentTestTool.name,
    );
    console.log("Running validation for the Tool Id: ", toolId);
    
    const payload = { tool_id: toolId, tool_nl_test_cases: nlTestCases };
    
    // Parse custom headers from the passthrough headers field
    const requestHeaders = {
      "Content-Type": "application/json",
    };
    
    // Authentication will be handled automatically by the JWT cookie
    // that was set when the admin UI loaded. The 'credentials: "include"'
    // in the fetch request ensures the cookie is sent with the request.
    
    const passthroughHeadersField = safeGetElement(
      "validation-passthrough-headers",
    );
    if (passthroughHeadersField && passthroughHeadersField.value.trim()) {
      const headerLines = passthroughHeadersField.value
        .trim()
        .split("\n");
      for (const line of headerLines) {
        const trimmedLine = line.trim();
        if (trimmedLine) {
          const colonIndex = trimmedLine.indexOf(":");
          if (colonIndex > 0) {
            const headerName = trimmedLine
              .substring(0, colonIndex)
              .trim();
            const headerValue = trimmedLine
              .substring(colonIndex + 1)
              .trim();
            
            // Validate header name and value
            const validation = validatePassthroughHeader(
              headerName,
              headerValue,
            );
            if (!validation.valid) {
              showErrorMessage(
                `Invalid header: ${validation.error}`,
              );
              return;
            }
            
            if (headerName && headerValue) {
              requestHeaders[headerName] = headerValue;
            }
          } else if (colonIndex === -1) {
            showErrorMessage(
              `Invalid header format: "${trimmedLine}". Expected format: "Header-Name: Value"`,
            );
            return;
          }
        }
      }
    }
    
    const response = await fetchWithTimeout(
      "/toolops/validation/execute_tool_nl_testcases",
      {
        method: "POST",
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
      toolTestState.requestTimeout, // Use the increased timeout
    );
    
    const result = await response.json();
    const resultStr = JSON.stringify(result, null, 2);
    
    if (resultContainer && window.CodeMirror) {
      try {
        AppState.toolTestResultEditor = window.CodeMirror(
          resultContainer,
          {
            value: resultStr,
            mode: "application/json",
            theme: "monokai",
            readOnly: true,
            lineNumbers: true,
          },
        );
      } catch (editorError) {
        console.error("Error creating CodeMirror editor:", editorError);
        // Fallback to plain text
        const pre = document.createElement("pre");
        pre.className =
        "bg-gray-900 text-green-400 p-4 rounded overflow-auto max-h-96";
        pre.textContent = resultStr;
        resultContainer.appendChild(pre);
      }
    } else if (resultContainer) {
      const pre = document.createElement("pre");
      pre.className =
      "bg-gray-100 p-4 rounded overflow-auto max-h-96 dark:bg-gray-800 dark:text-gray-100";
      pre.textContent = resultStr;
      resultContainer.appendChild(pre);
    }
    
    console.log("✓ Tool test completed successfully");
  } catch (error) {
    console.error("Tool test error:", error);
    if (resultContainer) {
      const errorMessage = handleFetchError(error, "run tool test");
      const errorDiv = document.createElement("div");
      errorDiv.className = "text-red-600 p-4";
      errorDiv.textContent = `Error: ${errorMessage}`;
      resultContainer.appendChild(errorDiv);
    }
  } finally {
    // Always restore UI state
    if (loadingElement) {
      loadingElement.style.display = "none";
    }
    if (runButton) {
      runButton.disabled = false;
      runButton.textContent = "Run Tool";
      runButton.classList.remove("opacity-50");
    }
  }
};

export const runToolTest = async function () {
  const form = safeGetElement("tool-test-form");
  const loadingElement = safeGetElement("tool-test-loading");
  const resultContainer = safeGetElement("tool-test-result");
  const runButton = document.querySelector('button[onclick="runToolTest()"]');
  
  if (!form || !AppState.currentTestTool) {
    console.error("Tool test form or current tool not found");
    showErrorMessage("Tool test form not available");
    return;
  }
  
  // Prevent multiple concurrent test runs
  if (runButton && runButton.disabled) {
    console.log("Tool test already running");
    return;
  }
  
  try {
    // Disable run button
    if (runButton) {
      runButton.disabled = true;
      runButton.textContent = "Running...";
      runButton.classList.add("opacity-50");
    }
    
    // Show loading
    if (loadingElement) {
      loadingElement.style.display = "block";
    }
    if (resultContainer) {
      resultContainer.innerHTML = "";
    }
    
    const formData = new FormData(form);
    const params = {};
    
    const schema = toolInputSchemaRegistry.inputSchema;
    
    if (schema && schema.properties) {
      for (const key in schema.properties) {
        const prop = schema.properties[key];
        const keyValidation = validateInputName(key, "parameter");
        if (!keyValidation.valid) {
          console.warn(`Skipping invalid parameter: ${key}`);
          continue;
        }
        let value;
        if (prop.type === "array") {
          const inputValues = formData.getAll(key);
          try {
            // Convert values based on the items schema type
            if (prop.items) {
              const itemType = Array.isArray(prop.items.anyOf)
                ? prop.items.anyOf.map((t) => t.type)
                : [prop.items.type];
              
              if (
                itemType.includes("number") ||
                itemType.includes("integer")
              ) {
                value = inputValues.map((v) => {
                  const num = Number(v);
                  if (isNaN(num)) {
                    throw new Error(`Invalid number: ${v}`);
                  }
                  return num;
                });
              } else if (itemType.includes("boolean")) {
                value = inputValues.map(
                  (v) => v === "true" || v === true,
                );
              } else if (itemType.includes("object")) {
                value = inputValues.map((v) => {
                  try {
                    const parsed = JSON.parse(v);
                    if (
                      typeof parsed !== "object" ||
                      Array.isArray(parsed)
                    ) {
                      throw new Error(
                        "Value must be an object",
                      );
                    }
                    return parsed;
                  } catch {
                    throw new Error(
                      `Invalid object format for ${key}`,
                    );
                  }
                });
              } else {
                value = inputValues;
              }
            }
            
            // Handle empty values
            if (
              value.length === 0 ||
              (value.length === 1 && value[0] === "")
            ) {
              if (
                schema.required &&
                schema.required.includes(key)
              ) {
                params[keyValidation.value] = [];
              }
              continue;
            }
            params[keyValidation.value] = value;
          } catch (error) {
            console.error(
              `Error parsing array values for ${key}:`,
              error,
            );
            showErrorMessage(
              `Invalid input format for ${key}. Please check the values are in correct format.`,
            );
            throw error;
          }
        } else {
          value = formData.get(key);
          if (value === null || value === undefined || value === "") {
            if (schema.required && schema.required.includes(key)) {
              params[keyValidation.value] = "";
            }
            continue;
          }
          if (prop.type === "number" || prop.type === "integer") {
            params[keyValidation.value] = Number(value);
          } else if (prop.type === "boolean") {
            params[keyValidation.value] =
            value === "true" || value === true;
          } else if (prop.enum) {
            if (prop.enum.includes(value)) {
              params[keyValidation.value] = value;
            }
          } else {
            params[keyValidation.value] = value;
          }
        }
      }
    }
    
    const payload = {
      jsonrpc: "2.0",
      id: Date.now(),
      method: AppState.currentTestTool.name,
      params,
    };
    
    // Parse custom headers from the passthrough headers field
    const requestHeaders = {
      "Content-Type": "application/json",
    };
    
    // Authentication will be handled automatically by the JWT cookie
    // that was set when the admin UI loaded. The 'credentials: "include"'
    // in the fetch request ensures the cookie is sent with the request.
    
    const passthroughHeadersField = safeGetElement(
      "test-passthrough-headers",
    );
    if (passthroughHeadersField && passthroughHeadersField.value.trim()) {
      const headerLines = passthroughHeadersField.value
        .trim()
        .split("\n");
      for (const line of headerLines) {
        const trimmedLine = line.trim();
        if (trimmedLine) {
          const colonIndex = trimmedLine.indexOf(":");
          if (colonIndex > 0) {
            const headerName = trimmedLine
              .substring(0, colonIndex)
              .trim();
            const headerValue = trimmedLine
              .substring(colonIndex + 1)
              .trim();
            
            // Validate header name and value
            const validation = validatePassthroughHeader(
              headerName,
              headerValue,
            );
            if (!validation.valid) {
              showErrorMessage(
                `Invalid header: ${validation.error}`,
              );
              return;
            }
            
            if (headerName && headerValue) {
              requestHeaders[headerName] = headerValue;
            }
          } else if (colonIndex === -1) {
            showErrorMessage(
              `Invalid header format: "${trimmedLine}". Expected format: "Header-Name: Value"`,
            );
            return;
          }
        }
      }
    }
    
    // Use longer timeout for test execution
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/rpc`,
      {
        method: "POST",
        headers: requestHeaders,
        body: JSON.stringify(payload),
        credentials: "include",
      },
      window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000, // Use configurable timeout
    );
    
    const result = await response.json();
    const resultStr = JSON.stringify(result, null, 2);
    
    if (resultContainer && window.CodeMirror) {
      try {
        AppState.toolTestResultEditor = window.CodeMirror(
          resultContainer,
          {
            value: resultStr,
            mode: "application/json",
            theme: "monokai",
            readOnly: true,
            lineNumbers: true,
          },
        );
      } catch (editorError) {
        console.error("Error creating CodeMirror editor:", editorError);
        // Fallback to plain text
        const pre = document.createElement("pre");
        pre.className =
        "bg-gray-900 text-green-400 p-4 rounded overflow-auto max-h-96";
        pre.textContent = resultStr;
        resultContainer.appendChild(pre);
      }
    } else if (resultContainer) {
      const pre = document.createElement("pre");
      pre.className =
      "bg-gray-100 p-4 rounded overflow-auto max-h-96 dark:bg-gray-800 dark:text-gray-100";
      pre.textContent = resultStr;
      resultContainer.appendChild(pre);
    }
    
    console.log("✓ Tool test completed successfully");
  } catch (error) {
    console.error("Tool test error:", error);
    if (resultContainer) {
      const errorMessage = handleFetchError(error, "run tool test");
      const errorDiv = document.createElement("div");
      errorDiv.className = "text-red-600 p-4";
      errorDiv.textContent = `Error: ${errorMessage}`;
      resultContainer.appendChild(errorDiv);
    }
  } finally {
    // Always restore UI state
    if (loadingElement) {
      loadingElement.style.display = "none";
    }
    if (runButton) {
      runButton.disabled = false;
      runButton.textContent = "Run Tool";
      runButton.classList.remove("opacity-50");
    }
  }
};

/**
* Cleanup function for tool test state
*/
export const cleanupToolTestState = function () {
  // Cancel all active requests
  for (const [toolId, controller] of toolTestState.activeRequests) {
    try {
      controller.abort();
      console.log(`Cancelled request for tool ${toolId}`);
    } catch (error) {
      console.warn(`Error cancelling request for tool ${toolId}:`, error);
    }
  }
  
  // Clear all state
  toolTestState.activeRequests.clear();
  toolTestState.lastRequestTime.clear();
  
  console.log("✓ Tool test state cleaned up");
};

/**
* Tool test modal specific cleanup
*/
export const cleanupToolTestModal = function () {
  try {
    // Clear current test tool
    AppState.currentTestTool = null;
    
    // Clear result editor
    if (AppState.toolTestResultEditor) {
      try {
        AppState.toolTestResultEditor.toTextArea();
        AppState.toolTestResultEditor = null;
      } catch (error) {
        console.warn(
          "Error cleaning up tool test result editor:",
          error,
        );
      }
    }
    
    // Reset form
    const form = safeGetElement("tool-test-form");
    if (form) {
      form.reset();
    }
    
    // Clear result container
    const resultContainer = safeGetElement("tool-test-result");
    if (resultContainer) {
      resultContainer.innerHTML = "";
    }
    
    // Hide loading
    const loadingElement = safeGetElement("tool-test-loading");
    if (loadingElement) {
      loadingElement.style.display = "none";
    }
    
    console.log("✓ Tool test modal cleaned up");
  } catch (error) {
    console.error("Error cleaning up tool test modal:", error);
  }
};

// ===================================================================
// ENHANCED TOOL VIEWING with Secure Display
// ===================================================================

/**
* SECURE: View Tool function with safe display
*/
export const viewTool = async function (toolId) {
  try {
    console.log(`Fetching tool details for ID: ${toolId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/tools/${toolId}`,
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const tool = await response.json();
    // Build auth HTML safely with new styling
    let authHTML = "";
    if (tool.auth?.username && tool.auth?.password) {
      authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
        <div class="text-gray-600 dark:text-gray-400">Basic Authentication</div>
        <div class="mt-1">Username: <span class="auth-username font-medium"></span></div>
        <div>Password: <span class="font-medium">********</span></div>
        </div>
    `;
    } else if (tool.auth?.token) {
      authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
        <div class="text-gray-600 dark:text-gray-400">Bearer Token</div>
        <div class="mt-1">Token: <span class="font-medium">********</span></div>
        </div>
    `;
    } else if (tool.auth?.authHeaderKey && tool.auth?.authHeaderValue) {
      authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">
        <div class="text-gray-600 dark:text-gray-400">Custom Headers</div>
        <div class="mt-1">Header: <span class="auth-header-key font-medium"></span></div>
        <div>Value: <span class="font-medium">********</span></div>
        </div>
    `;
    } else {
      authHTML = `
        <span class="font-medium text-gray-700 dark:text-gray-300">Authentication Type:</span>
        <div class="mt-1 text-sm">None</div>
    `;
    }

    // Create annotation badges safely - NO ESCAPING since we're using textContent
    const renderAnnotations = (annotations) => {
      if (!annotations || Object.keys(annotations).length === 0) {
        return '<p><strong>Annotations:</strong> <span class="text-gray-600 dark:text-gray-300">None</span></p>';
      }

      const badges = [];

      // Show title if present
      if (annotations.title) {
        badges.push(
          '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mr-1 mb-1 annotation-title"></span>',
        );
      }

      // Show behavior hints with appropriate colors
      if (annotations.readOnlyHint === true) {
        badges.push(
          '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 mr-1 mb-1">📖 Read-Only</span>',
        );
      }

      if (annotations.destructiveHint === true) {
        badges.push(
          '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 mr-1 mb-1">⚠️ Destructive</span>',
        );
      }

      if (annotations.idempotentHint === true) {
        badges.push(
          '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 mr-1 mb-1">🔄 Idempotent</span>',
        );
      }

      if (annotations.openWorldHint === true) {
        badges.push(
          '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 mr-1 mb-1">🌐 External Access</span>',
        );
      }

      // Show any other custom annotations
      Object.keys(annotations).forEach((key) => {
        if (
          ![
            "title",
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
          ].includes(key)
        ) {
          const value = annotations[key];
          badges.push(
            `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:text-gray-200 mr-1 mb-1 custom-annotation" data-key="${key}" data-value="${value}"></span>`,
          );
        }
      });

      return `
        <div>
        <strong>Annotations:</strong>
        <div class="mt-1 flex flex-wrap">
            ${badges.join("")}
        </div>
        </div>
    `;
    };

    const toolDetailsDiv = safeGetElement("tool-details");
    if (toolDetailsDiv) {
      // Create structure safely without double-escaping
      const safeHTML = `
        <div class="bg-transparent dark:bg-transparent dark:text-gray-300">
        <!-- Two Column Layout for Main Info -->
        <div class="grid grid-cols-2 gap-6 mb-6">
            <!-- Left Column -->
            <div class="space-y-3">
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Display Name:</span>
                <div class="mt-1 tool-display-name font-medium"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Technical Name:</span>
                <div class="mt-1 tool-name text-sm"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">URL:</span>
                <div class="mt-1 tool-url text-sm"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Type:</span>
                <div class="mt-1 tool-type text-sm"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Visibility:</span>
                <div class="mt-1 tool-visibility text-sm"></div>
            </div>
            </div>
            <!-- Right Column -->
            <div class="space-y-3">
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Description:</span>
                <div class="mt-1 tool-description text-sm"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Tags:</span>
                <div class="mt-1 tool-tags text-sm"></div>
            </div>
            <div>
                <span class="font-medium text-gray-700 dark:text-gray-300">Request Type:</span>
                <div class="mt-1 tool-request-type text-sm"></div>
            </div>
            <div class="auth-info">
                ${authHTML}
            </div>
            </div>
        </div>

        <!-- Annotations Section -->
        <div class="mb-6">
            ${renderAnnotations(tool.annotations)}
        </div>

        <!-- Technical Details Section -->
        <div class="space-y-4">
            <div>
            <strong class="text-gray-700 dark:text-gray-300">Headers:</strong>
            <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-headers overflow-x-auto"></pre>
            </div>
            <div>
            <strong class="text-gray-700 dark:text-gray-300">Input Schema:</strong>
            <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-schema overflow-x-auto"></pre>
            </div>
            <div>
            <strong class="text-gray-700 dark:text-gray-300">Output Schema:</strong>
            <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 tool-output-schema overflow-x-auto"></pre>
            </div>
        </div>

        <!-- Metrics Section -->
        <div class="mt-6 pt-4 border-t border-gray-200 dark:border-gray-600">
            <strong class="text-gray-700 dark:text-gray-300">Metrics:</strong>
            <div class="grid grid-cols-2 gap-4 mt-3 text-sm">
            <div class="space-y-2">
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Total Executions:</span>
                <span class="metric-total font-medium"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Successful Executions:</span>
                <span class="metric-success font-medium text-green-600"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Failed Executions:</span>
                <span class="metric-failed font-medium text-red-600"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Failure Rate:</span>
                <span class="metric-failure-rate font-medium"></span>
                </div>
            </div>
            <div class="space-y-2">
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Min Response Time:</span>
                <span class="metric-min-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Max Response Time:</span>
                <span class="metric-max-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Average Response Time:</span>
                <span class="metric-avg-time font-medium"></span>
                </div>
                <div class="flex justify-between">
                <span class="text-gray-600 dark:text-gray-400">Last Execution Time:</span>
                <span class="metric-last-time font-medium"></span>
                </div>
            </div>
            </div>
        </div>
        <div class="mt-6 border-t pt-4">
        <!-- Metadata Section -->
            <strong>Metadata:</strong>
            <div class="grid grid-cols-2 gap-4 mt-2 text-sm">
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created By:</span>
                <span class="ml-2 metadata-created-by"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created At:</span>
                <span class="ml-2 metadata-created-at"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created From IP:</span>
                <span class="ml-2 metadata-created-from"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Created Via:</span>
                <span class="ml-2 metadata-created-via"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Last Modified By:</span>
                <span class="ml-2 metadata-modified-by"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Last Modified At:</span>
                <span class="ml-2 metadata-modified-at"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Modified From IP:</span>
                <span class="ml-2 modified-from"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Modified Via:</span>
                <span class="ml-2 metadata-modified-via"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Version:</span>
                <span class="ml-2 metadata-version"></span>
            </div>
            <div>
                <span class="font-medium text-gray-600 dark:text-gray-400">Import Batch:</span>
                <span class="ml-2 metadata-import-batch"></span>
            </div>
            </div>
        </div>
        </div>
    `;

      // Set structure first
      safeSetInnerHTML(toolDetailsDiv, safeHTML, true);

      // Now safely set text content - NO ESCAPING since textContent is safe
      const setTextSafely = (selector, value) => {
        const element = toolDetailsDiv.querySelector(selector);
        if (element) {
          element.textContent = value || "N/A";
        }
      };

      setTextSafely(
        ".tool-display-name",
        tool.displayName || tool.customName || tool.name,
      );
      tool.description = tool.description.slice(
        0,
        tool.description.indexOf("*"),
      );
      setTextSafely(".tool-name", tool.name);
      setTextSafely(".tool-url", tool.url);
      setTextSafely(".tool-type", tool.integrationType);
      setTextSafely(".tool-description", tool.description);
      setTextSafely(".tool-visibility", tool.visibility);

      // Set tags as HTML with badges
      const tagsElement = toolDetailsDiv.querySelector(".tool-tags");
      if (tagsElement) {
        if (tool.tags && tool.tags.length > 0) {
          tagsElement.innerHTML = tool.tags
            .map((tag) => {
              const raw =
                                typeof tag === "object" && tag !== null
                                  ? tag.id || tag.label || JSON.stringify(tag)
                                  : tag;
              return `<span class="inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200">${escapeHtml(raw)}</span>`;
            })
            .join("");
        } else {
          tagsElement.textContent = "None";
        }
      }

      setTextSafely(".tool-request-type", tool.requestType);
      setTextSafely(
        ".tool-headers",
        JSON.stringify(tool.headers || {}, null, 2),
      );
      setTextSafely(
        ".tool-schema",
        JSON.stringify(tool.inputSchema || {}, null, 2),
      );
      setTextSafely(
        ".tool-output-schema",
        JSON.stringify(tool.outputSchema || {}, null, 2),
      );

      // Set auth fields safely
      if (tool.auth?.username) {
        setTextSafely(".auth-username", tool.auth.username);
      }
      if (tool.auth?.authHeaderKey) {
        setTextSafely(".auth-header-key", tool.auth.authHeaderKey);
      }

      // Set annotation title safely
      if (tool.annotations?.title) {
        setTextSafely(".annotation-title", tool.annotations.title);
      }

      // Set custom annotations safely
      const customAnnotations =
                toolDetailsDiv.querySelectorAll(".custom-annotation");
      customAnnotations.forEach((element) => {
        const key = element.dataset.key;
        const value = element.dataset.value;
        element.textContent = `${key}: ${value}`;
      });

      // Set metrics safely
      setTextSafely(".metric-total", tool.metrics?.totalExecutions ?? 0);
      setTextSafely(
        ".metric-success",
        tool.metrics?.successfulExecutions ?? 0,
      );
      setTextSafely(
        ".metric-failed",
        tool.metrics?.failedExecutions ?? 0,
      );
      setTextSafely(
        ".metric-failure-rate",
        tool.metrics?.failureRate ?? 0,
      );
      setTextSafely(
        ".metric-min-time",
        tool.metrics?.minResponseTime ?? "N/A",
      );
      setTextSafely(
        ".metric-max-time",
        tool.metrics?.maxResponseTime ?? "N/A",
      );
      setTextSafely(
        ".metric-avg-time",
        tool.metrics?.avgResponseTime ?? "N/A",
      );
      setTextSafely(
        ".metric-last-time",
        tool.metrics?.lastExecutionTime ?? "N/A",
      );

      // Set metadata fields safely with appropriate fallbacks for legacy entities
      setTextSafely(
        ".metadata-created-by",
        tool.created_by || tool.createdBy || "Legacy Entity",
      );
      setTextSafely(
        ".metadata-created-at",
        tool.created_at
          ? new Date(tool.created_at).toLocaleString()
          : tool.createdAt
            ? new Date(tool.createdAt).toLocaleString()
            : "Pre-metadata",
      );
      setTextSafely(
        ".metadata-created-from",
        tool.created_from_ip || tool.createdFromIp || "Unknown",
      );
      setTextSafely(
        ".metadata-created-via",
        tool.created_via || tool.createdVia || "Unknown",
      );
      setTextSafely(
        ".metadata-modified-by",
        tool.modified_by || tool.modifiedBy || "N/A",
      );
      setTextSafely(
        ".metadata-modified-at",
        tool.updated_at
          ? new Date(tool.updated_at).toLocaleString()
          : tool.updatedAt
            ? new Date(tool.updatedAt).toLocaleString()
            : "N/A",
      );
      setTextSafely(
        ".metadata-modified-from",
        tool.modified_from_ip || tool.modifiedFromIp || "N/A",
      );
      setTextSafely(
        ".metadata-modified-via",
        tool.modified_via || tool.modifiedVia || "N/A",
      );
      setTextSafely(".metadata-version", tool.version || "1");
      setTextSafely(
        ".metadata-import-batch",
        tool.import_batch_id || tool.importBatchId || "N/A",
      );
    }

    openModal("tool-modal");
    console.log("✓ Tool details loaded successfully");
  } catch (error) {
    console.error("Error fetching tool details:", error);
    const errorMessage = handleFetchError(error, "load tool details");
    showErrorMessage(errorMessage);
  }
}

