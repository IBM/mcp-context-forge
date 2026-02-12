import { AppState } from "./appState.js";
import { getSelectedGatewayIds } from "./gateway.js";
import { openModal } from "./modals";
import { escapeHtml } from "./security.js";
import { getCurrentTeamId, safeGetElement, showErrorMessage } from "./utils";

export const initPromptSelect = function (
  selectId,
  pillsId,
  warnId,
  max = 8,
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
      `Prompt select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
    );
    return;
  }
  
  const pillClasses =
  "inline-block px-3 py-1 text-xs font-semibold text-purple-700 bg-purple-100 rounded-full shadow dark:text-purple-300 dark:bg-purple-900";
  
  const update = function () {
    try {
      const checkboxes = container.querySelectorAll(
        'input[type="checkbox"]',
      );
      const checked = Array.from(checkboxes).filter((cb) => cb.checked);
      
      // Determine count: if Select All mode is active, use the stored allPromptIds
      const selectAllInput = container.querySelector(
        'input[name="selectAllPrompts"]',
      );
      const allIdsInput = container.querySelector(
        'input[name="allPromptIds"]',
      );
      
      // Get persisted selections for Add Server mode
      let persistedPromptIds = [];
      if (selectId === "associatedPrompts") {
        const dataAttr = container.getAttribute(
          "data-selected-prompts",
        );
        if (dataAttr) {
          try {
            persistedPromptIds = JSON.parse(dataAttr);
          } catch (e) {
            console.error(
              "Error parsing data-selected-prompts:",
              e,
            );
          }
        }
        if (
          (!persistedPromptIds || persistedPromptIds.length === 0) &&
          Array.isArray(window._selectedAssociatedPrompts)
        ) {
          persistedPromptIds =
          window._selectedAssociatedPrompts.slice();
        }
      }
      
      let count = checked.length;
      const pillsData = [];
      
      if (
        selectAllInput &&
        selectAllInput.value === "true" &&
        allIdsInput
      ) {
        try {
          const allIds = JSON.parse(allIdsInput.value);
          count = allIds.length;
        } catch (e) {
          console.error("Error parsing allPromptIds:", e);
        }
      }
      // If in Add Server mode with persisted selections, use persisted count and build pills from persisted data
      else if (
        selectId === "associatedPrompts" &&
        persistedPromptIds &&
        persistedPromptIds.length > 0
      ) {
        count = persistedPromptIds.length;
        // Build pill data from persisted IDs - find matching checkboxes or use ID as fallback
        const checkboxMap = new Map();
        checkboxes.forEach((cb) => {
          checkboxMap.set(
            cb.value,
            cb.nextElementSibling?.textContent?.trim() || cb.value,
          );
        });
        persistedPromptIds.forEach((id) => {
          const name = checkboxMap.get(id) || id;
          pillsData.push({ id, name });
        });
      }
      
      // Rebuild pills safely - show first 3, then summarize the rest
      pillsBox.innerHTML = "";
      const maxPillsToShow = 3;
      
      // Determine which pills to display based on mode
      if (selectId === "associatedPrompts" && pillsData.length > 0) {
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
        span.title = "Click to see all selected prompts";
        const remaining = count - maxPillsToShow;
        span.textContent = `+${remaining} more`;
        pillsBox.appendChild(span);
      }
      
      // Warning when > max
      if (count > max) {
        warnBox.textContent = `Selected ${count} prompts. Selecting more than ${max} prompts can degrade agent performance with the server.`;
      } else {
        warnBox.textContent = "";
      }
    } catch (error) {
      console.error("Error updating prompt select:", error);
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
      
      // Remove any select-all hidden inputs
      const selectAllInput = container.querySelector(
        'input[name="selectAllPrompts"]',
      );
      if (selectAllInput) {
        selectAllInput.remove();
      }
      const allIdsInput = container.querySelector(
        'input[name="allPromptIds"]',
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
      newSelectBtn.textContent = "Selecting all prompts...";
      
      try {
        // Prefer full-set selection when pagination/infinite-scroll is present
        const loadedCheckboxes = container.querySelectorAll(
          'input[type="checkbox"]',
        );
        const visibleCheckboxes = Array.from(loadedCheckboxes).filter(
          (cb) => cb.offsetParent !== null,
        );
        
        // Detect pagination/infinite-scroll controls for prompts
        const hasPaginationControls = !!safeGetElement(
          "prompts-pagination-controls",
        );
        const hasScrollTrigger = !!document.querySelector(
          "[id^='prompts-scroll-trigger']",
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
            `${window.ROOT_PATH}/admin/prompts/ids${queryString ? `?${queryString}` : ""}`,
          );
          if (!resp.ok) {
            throw new Error("Failed to fetch prompt IDs");
          }
          const data = await resp.json();
          allIds = data.prompt_ids || [];
          // If nothing visible (paginated), check loaded checkboxes
          loadedCheckboxes.forEach((cb) => (cb.checked = true));
        }
        
        // Add hidden select-all flag
        let selectAllInput = container.querySelector(
          'input[name="selectAllPrompts"]',
        );
        if (!selectAllInput) {
          selectAllInput = document.createElement("input");
          selectAllInput.type = "hidden";
          selectAllInput.name = "selectAllPrompts";
          container.appendChild(selectAllInput);
        }
        selectAllInput.value = "true";
        
        // Store IDs as JSON for backend handling
        let allIdsInput = container.querySelector(
          'input[name="allPromptIds"]',
        );
        if (!allIdsInput) {
          allIdsInput = document.createElement("input");
          allIdsInput.type = "hidden";
          allIdsInput.name = "allPromptIds";
          container.appendChild(allIdsInput);
        }
        allIdsInput.value = JSON.stringify(allIds);
        
        update();
        
        newSelectBtn.textContent = `✓ All ${allIds.length} prompts selected`;
        setTimeout(() => {
          newSelectBtn.textContent = originalText;
        }, 2000);
      } catch (error) {
        console.error("Error selecting all prompts:", error);
        alert("Failed to select all prompts. Please try again.");
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
          'input[name="selectAllPrompts"]',
        );
        const allIdsInput = container.querySelector(
          'input[name="allPromptIds"]',
        );
        
        if (
          selectAllInput &&
          selectAllInput.value === "true" &&
          allIdsInput
        ) {
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
            console.error("Error updating allPromptIds:", err);
          }
        }
        
        // If we're in the edit-server-prompts container, maintain the
        // `data-server-prompts` attribute so user selections persist
        // across gateway-filtered reloads.
        else if (selectId === "edit-server-prompts") {
          try {
            let serverPrompts = [];
            const dataAttr = container.getAttribute(
              "data-server-prompts",
            );
            if (dataAttr) {
              try {
                serverPrompts = JSON.parse(dataAttr);
              } catch (e) {
                console.error(
                  "Error parsing data-server-prompts:",
                  e,
                );
              }
            }
            
            const idVal = e.target.value;
            if (!Number.isNaN(idVal)) {
              if (e.target.checked) {
                if (!serverPrompts.includes(idVal)) {
                  serverPrompts.push(idVal);
                }
              } else {
                serverPrompts = serverPrompts.filter(
                  (x) => x !== idVal,
                );
              }
              
              container.setAttribute(
                "data-server-prompts",
                JSON.stringify(serverPrompts),
              );
            }
          } catch (err) {
            console.error(
              "Error updating data-server-prompts:",
              err,
            );
          }
        }
        
        // If we're in the Add Server prompts container, persist selected IDs incrementally
        else if (selectId === "associatedPrompts") {
          try {
            const changedEl = e.target;
            const changedId = changedEl.value;
            
            let persisted = [];
            const dataAttr = container.getAttribute(
              "data-selected-prompts",
            );
            if (dataAttr) {
              try {
                const parsed = JSON.parse(dataAttr);
                if (Array.isArray(parsed)) {
                  persisted = parsed.slice();
                }
              } catch (parseErr) {
                console.error(
                  "Error parsing existing data-selected-prompts:",
                  parseErr,
                );
              }
            } else if (
              Array.isArray(window._selectedAssociatedPrompts)
            ) {
              persisted =
              window._selectedAssociatedPrompts.slice();
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
            
            container.setAttribute(
              "data-selected-prompts",
              JSON.stringify(persisted),
            );
            try {
              window._selectedAssociatedPrompts =
              persisted.slice();
            } catch (err) {
              console.error(
                "Error persisting window._selectedAssociatedPrompts:",
                err,
              );
            }
          } catch (err) {
            console.error(
              "Error updating data-selected-prompts (incremental):",
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
// PROMPT TEST FUNCTIONALITY
// ===================================================================

// State management for prompt testing
const promptTestState = {
  lastRequestTime: new Map(),
  activeRequests: new Set(),
  currentTestPrompt: null,
};

/**
* Test a prompt by opening the prompt test modal
*/
export const testPrompt = async function (promptId) {
  try {
    console.log(`Testing prompt ID: ${promptId}`);
    
    // Debouncing to prevent rapid clicking
    const now = Date.now();
    const lastRequest = promptTestState.lastRequestTime.get(promptId) || 0;
    const timeSinceLastRequest = now - lastRequest;
    const debounceDelay = 1000;
    
    if (timeSinceLastRequest < debounceDelay) {
      console.log(`Prompt ${promptId} test request debounced`);
      return;
    }
    
    // Check if modal is already active
    if (AppState.isModalActive("prompt-test-modal")) {
      console.warn("Prompt test modal is already active");
      return;
    }
    
    // Update button state
    const testButton = document.querySelector(
      `[onclick*="testPrompt('${promptId}')"]`,
    );
    if (testButton) {
      if (testButton.disabled) {
        console.log(
          "Test button already disabled, request in progress",
        );
        return;
      }
      testButton.disabled = true;
      testButton.textContent = "Loading...";
      testButton.classList.add("opacity-50", "cursor-not-allowed");
    }
    
    // Record request time and mark as active
    promptTestState.lastRequestTime.set(promptId, now);
    promptTestState.activeRequests.add(promptId);
    
    // Fetch prompt details
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    
    try {
      // Fetch prompt details from the prompts endpoint (view mode)
      const response = await fetch(
        `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}`,
        {
          method: "GET",
          headers: {
            Accept: "application/json",
          },
          credentials: "include",
          signal: controller.signal,
        },
      );
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        throw new Error(
          `Failed to fetch prompt details: ${response.status} ${response.statusText}`,
        );
      }
      
      const prompt = await response.json();
      promptTestState.currentTestPrompt = prompt;
      
      // Set modal title and description
      const titleElement = safeGetElement("prompt-test-modal-title");
      const descElement = safeGetElement("prompt-test-modal-description");
      
      const promptLabel =
      prompt.displayName ||
      prompt.originalName ||
      prompt.name ||
      promptId;
      if (titleElement) {
        titleElement.textContent = `Test Prompt: ${promptLabel}`;
      }
      if (descElement) {
        if (prompt.description) {
          // Escape HTML and then replace newlines with <br/> tags
          descElement.innerHTML = escapeHtml(
            prompt.description,
          ).replace(/\n/g, "<br/>");
        } else {
          descElement.textContent = "No description available.";
        }
      }
      
      // Build form fields based on prompt arguments
      buildPromptTestForm(prompt);
      
      // Open the modal
      openModal("prompt-test-modal");
    } catch (error) {
      clearTimeout(timeoutId);
      
      if (error.name === "AbortError") {
        console.warn("Request was cancelled (timeout or user action)");
        showErrorMessage("Request timed out. Please try again.");
      } else {
        console.error("Error fetching prompt details:", error);
        const errorMessage =
        error.message || "Failed to load prompt details";
        showErrorMessage(`Error testing prompt: ${errorMessage}`);
      }
    }
  } catch (error) {
    console.error("Error in testPrompt:", error);
    showErrorMessage(`Error testing prompt: ${error.message}`);
  } finally {
    // Always restore button state
    const testButton = document.querySelector(
      `[onclick*="testPrompt('${promptId}')"]`,
    );
    if (testButton) {
      testButton.disabled = false;
      testButton.textContent = "Test";
      testButton.classList.remove("opacity-50", "cursor-not-allowed");
    }
    
    // Clean up state
    promptTestState.activeRequests.delete(promptId);
  }
};

/**
* Build the form fields for prompt testing based on prompt arguments
*/
export const buildPromptTestForm = function (prompt) {
  const fieldsContainer = safeGetElement("prompt-test-form-fields");
  if (!fieldsContainer) {
    console.error("Prompt test form fields container not found");
    return;
  }
  
  // Clear existing fields
  fieldsContainer.innerHTML = "";
  
  if (!prompt.arguments || prompt.arguments.length === 0) {
    fieldsContainer.innerHTML = `
                <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                    This prompt has no arguments - it will render as-is.
                </div>
            `;
    return;
  }
  
  // Create fields for each prompt argument
  prompt.arguments.forEach((arg, index) => {
    const fieldDiv = document.createElement("div");
    fieldDiv.className = "space-y-2";
    
    const label = document.createElement("label");
    label.className =
    "block text-sm font-medium text-gray-700 dark:text-gray-300";
    label.textContent = `${arg.name}${arg.required ? " *" : ""}`;
    
    const input = document.createElement("input");
    input.type = "text";
    input.id = `prompt-arg-${index}`;
    input.name = `arg-${arg.name}`;
    input.className =
    "mt-1 px-1.5 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-300";
    
    if (arg.description) {
      input.placeholder = arg.description;
    }
    
    if (arg.required) {
      input.required = true;
    }
    
    fieldDiv.appendChild(label);
    if (arg.description) {
      const description = document.createElement("div");
      description.className = "text-xs text-gray-500 dark:text-gray-400";
      description.textContent = arg.description;
      fieldDiv.appendChild(description);
    }
    fieldDiv.appendChild(input);
    
    fieldsContainer.appendChild(fieldDiv);
  });
};

/**
* Run the prompt test by calling the API with the provided arguments
*/
export const runPromptTest = async function () {
  const form = safeGetElement("prompt-test-form");
  const loadingElement = safeGetElement("prompt-test-loading");
  const resultContainer = safeGetElement("prompt-test-result");
  const runButton = document.querySelector(
    'button[onclick="runPromptTest()"]',
  );
  
  if (!form || !promptTestState.currentTestPrompt) {
    console.error("Prompt test form or current prompt not found");
    showErrorMessage("Prompt test form not available");
    return;
  }
  
  // Prevent multiple concurrent test runs
  if (runButton && runButton.disabled) {
    console.log("Prompt test already running");
    return;
  }
  
  try {
    // Disable button and show loading
    if (runButton) {
      runButton.disabled = true;
      runButton.textContent = "Rendering...";
    }
    if (loadingElement) {
      loadingElement.classList.remove("hidden");
    }
    if (resultContainer) {
      resultContainer.innerHTML = `
                    <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                        Rendering prompt...
                    </div>
                `;
    }
    
    // Collect form data (prompt arguments)
    const formData = new FormData(form);
    const args = {};
    
    // Parse the form data into arguments object
    for (const [key, value] of formData.entries()) {
      if (key.startsWith("arg-")) {
        const argName = key.substring(4); // Remove 'arg-' prefix
        args[argName] = value;
      }
    }
    
    // Call the prompt API endpoint
    const response = await fetch(
      `${window.ROOT_PATH}/prompts/${encodeURIComponent(promptTestState.currentTestPrompt.id)}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify(args),
      },
    );
    
    if (!response.ok) {
      let errorMessage;
      try {
        const errorData = await response.json();
        errorMessage =
        errorData.message ||
        `HTTP ${response.status}: ${response.statusText}`;
        
        // Show more detailed error information
        if (errorData.details) {
          errorMessage += `\nDetails: ${errorData.details}`;
        }
      } catch {
        errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      }
      throw new Error(errorMessage);
    }
    
    const result = await response.json();
    
    // Display the result
    if (resultContainer) {
      let resultHtml = "";
      
      if (result.messages && Array.isArray(result.messages)) {
        result.messages.forEach((message, index) => {
          resultHtml += `
                            <div class="mb-4 p-3 bg-white dark:bg-gray-700 rounded border">
                                <div class="text-sm font-medium text-gray-600 dark:text-gray-300 mb-2">
                                    Message ${index + 1} (${message.role || "unknown"})
                                </div>
                                <div class="text-gray-900 dark:text-gray-100 whitespace-pre-wrap">${escapeHtml(message.content?.text || JSON.stringify(message.content) || "")}</div>
                            </div>
                        `;
        });
      } else {
        resultHtml = `
                        <div class="text-gray-900 dark:text-gray-100 whitespace-pre-wrap">${escapeHtml(JSON.stringify(result, null, 2))}</div>
                    `;
      }
      
      resultContainer.innerHTML = resultHtml;
    }
    
    console.log("Prompt rendered successfully");
  } catch (error) {
    console.error("Error rendering prompt:", error);
    
    if (resultContainer) {
      resultContainer.innerHTML = `
                    <div class="text-red-600 dark:text-red-400 text-sm">
                        <strong>Error:</strong> ${escapeHtml(error.message)}
                    </div>
                `;
    }
    
    showErrorMessage(`Failed to render prompt: ${error.message}`);
  } finally {
    // Hide loading and restore button
    if (loadingElement) {
      loadingElement.classList.add("hidden");
    }
    if (runButton) {
      runButton.disabled = false;
      runButton.textContent = "Render Prompt";
    }
  }
};

/**
* Clean up prompt test modal state
*/
export const cleanupPromptTestModal = function () {
  try {
    // Clear current test prompt
    promptTestState.currentTestPrompt = null;
    
    // Reset form
    const form = safeGetElement("prompt-test-form");
    if (form) {
      form.reset();
    }
    
    // Clear form fields
    const fieldsContainer = safeGetElement("prompt-test-form-fields");
    if (fieldsContainer) {
      fieldsContainer.innerHTML = "";
    }
    
    // Clear result container
    const resultContainer = safeGetElement("prompt-test-result");
    if (resultContainer) {
      resultContainer.innerHTML = `
                    <div class="text-gray-500 dark:text-gray-400 text-sm italic">
                        Click "Render Prompt" to see the rendered output
                    </div>
                `;
    }
    
    // Hide loading
    const loadingElement = safeGetElement("prompt-test-loading");
    if (loadingElement) {
      loadingElement.classList.add("hidden");
    }
    
    console.log("✓ Prompt test modal cleaned up");
  } catch (error) {
    console.error("Error cleaning up prompt test modal:", error);
  }
};