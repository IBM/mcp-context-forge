  // ===================================================================
  // ENHANCED SCHEMA GENERATION with Safe State Access
  // ===================================================================

import { AppState } from "./appState";
import { validateInputName } from "./security";
import { safeGetElement } from "./utils";


export const generateSchema = function () {
  const schema = {
    title: "CustomInputSchema",
    type: "object",
    properties: {},
    required: [],
  };
  
  const paramCount = AppState.getParameterCount();
  
  for (let i = 1; i <= paramCount; i++) {
    try {
      const nameField = document.querySelector(
        `[name="param_name_${i}"]`,
      );
      const typeField = document.querySelector(
        `[name="param_type_${i}"]`,
      );
      const descField = document.querySelector(
        `[name="param_description_${i}"]`,
      );
      const requiredField = document.querySelector(
        `[name="param_required_${i}"]`,
      );
      
      if (nameField && nameField.value.trim() !== "") {
        // Validate parameter name
        const nameValidation = validateInputName(
          nameField.value.trim(),
          "parameter",
        );
        if (!nameValidation.valid) {
          console.warn(
            `Invalid parameter name at index ${i}: ${nameValidation.error}`,
          );
          continue;
        }
        
        schema.properties[nameValidation.value] = {
          type: typeField ? typeField.value : "string",
          description: descField ? descField.value.trim() : "",
        };
        
        if (requiredField && requiredField.checked) {
          schema.required.push(nameValidation.value);
        }
      }
    } catch (error) {
      console.error(`Error processing parameter ${i}:`, error);
    }
  }
  
  return JSON.stringify(schema, null, 2);
};

export const updateSchemaPreview = function () {
  try {
    const modeRadio = document.querySelector(
      'input[name="schema_input_mode"]:checked',
    );
    if (modeRadio && modeRadio.value === "json") {
      if (
        window.schemaEditor &&
        typeof window.schemaEditor.setValue === "function"
      ) {
        window.schemaEditor.setValue(generateSchema());
      }
    }
  } catch (error) {
    console.error("Error updating schema preview:", error);
  }
};

// ===================================================================
// ENHANCED PARAMETER HANDLING with Validation
// ===================================================================

export const createParameterForm = function (parameterCount) {
  const container = document.createElement("div");
  
  // Header with delete button
  const header = document.createElement("div");
  header.className = "flex justify-between items-center";
  
  const title = document.createElement("span");
  title.className = "font-semibold text-gray-800 dark:text-gray-200";
  title.textContent = `Parameter ${parameterCount}`;
  
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className =
  "delete-param text-red-600 hover:text-red-800 focus:outline-none text-xl";
  deleteBtn.title = "Delete Parameter";
  deleteBtn.textContent = "×";
  
  header.appendChild(title);
  header.appendChild(deleteBtn);
  container.appendChild(header);
  
  // Form fields grid
  const grid = document.createElement("div");
  grid.className = "grid grid-cols-1 md:grid-cols-2 gap-4 mt-4";
  
  // Parameter name field with validation
  const nameGroup = document.createElement("div");
  const nameLabel = document.createElement("label");
  nameLabel.className =
  "block text-sm font-medium text-gray-700 dark:text-gray-300";
  nameLabel.textContent = "Parameter Name";
  
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.name = `param_name_${parameterCount}`;
  nameInput.required = true;
  nameInput.className =
  "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";
  
  // Add validation to name input
  nameInput.addEventListener("blur", function () {
    const validation = validateInputName(this.value, "parameter");
    if (!validation.valid) {
      this.setCustomValidity(validation.error);
      this.reportValidity();
    } else {
      this.setCustomValidity("");
      this.value = validation.value; // Use cleaned value
    }
  });
  
  nameGroup.appendChild(nameLabel);
  nameGroup.appendChild(nameInput);
  
  // Type field
  const typeGroup = document.createElement("div");
  const typeLabel = document.createElement("label");
  typeLabel.className =
  "block text-sm font-medium text-gray-700 dark:text-gray-300";
  typeLabel.textContent = "Type";
  
  const typeSelect = document.createElement("select");
  typeSelect.name = `param_type_${parameterCount}`;
  typeSelect.className =
  "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";
  
  const typeOptions = [
    { value: "string", text: "String" },
    { value: "number", text: "Number" },
    { value: "boolean", text: "Boolean" },
    { value: "object", text: "Object" },
    { value: "array", text: "Array" },
  ];
  
  typeOptions.forEach((option) => {
    const optionElement = document.createElement("option");
    optionElement.value = option.value;
    optionElement.textContent = option.text;
    typeSelect.appendChild(optionElement);
  });
  
  typeGroup.appendChild(typeLabel);
  typeGroup.appendChild(typeSelect);
  
  grid.appendChild(nameGroup);
  grid.appendChild(typeGroup);
  container.appendChild(grid);
  
  // Description field
  const descGroup = document.createElement("div");
  descGroup.className = "mt-4";
  
  const descLabel = document.createElement("label");
  descLabel.className =
  "block text-sm font-medium text-gray-700 dark:text-gray-300";
  descLabel.textContent = "Description";
  
  const descTextarea = document.createElement("textarea");
  descTextarea.name = `param_description_${parameterCount}`;
  descTextarea.className =
  "mt-1 px-1.5 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200";
  descTextarea.rows = 2;
  
  descGroup.appendChild(descLabel);
  descGroup.appendChild(descTextarea);
  container.appendChild(descGroup);
  
  // Required checkbox
  const requiredGroup = document.createElement("div");
  requiredGroup.className = "mt-4 flex items-center";
  
  const requiredInput = document.createElement("input");
  requiredInput.type = "checkbox";
  requiredInput.name = `param_required_${parameterCount}`;
  requiredInput.checked = true;
  requiredInput.className =
  "h-4 w-4 text-indigo-600 border border-gray-300 rounded";
  
  const requiredLabel = document.createElement("label");
  requiredLabel.className =
  "ml-2 text-sm font-medium text-gray-700 dark:text-gray-300";
  requiredLabel.textContent = "Required";
  
  requiredGroup.appendChild(requiredInput);
  requiredGroup.appendChild(requiredLabel);
  container.appendChild(requiredGroup);
  
  return container;
};

export const handleAddParameter = function () {
  const parameterCount = AppState.incrementParameterCount();
  const parametersContainer = safeGetElement("parameters-container");
  
  if (!parametersContainer) {
    console.error("Parameters container not found");
    AppState.decrementParameterCount(); // Rollback
    return;
  }
  
  try {
    const paramDiv = document.createElement("div");
    paramDiv.classList.add(
      "border",
      "p-4",
      "mb-4",
      "rounded-md",
      "bg-gray-50",
      "shadow-sm",
    );
    
    // Create parameter form with validation
    const parameterForm = createParameterForm(parameterCount);
    paramDiv.appendChild(parameterForm);
    
    parametersContainer.appendChild(paramDiv);
    updateSchemaPreview();
    
    // Delete parameter functionality with safe state management
    const deleteButton = paramDiv.querySelector(".delete-param");
    if (deleteButton) {
      deleteButton.addEventListener("click", () => {
        try {
          paramDiv.remove();
          AppState.decrementParameterCount();
          updateSchemaPreview();
          console.log(
            `✓ Removed parameter, count now: ${AppState.getParameterCount()}`,
          );
        } catch (error) {
          console.error("Error removing parameter:", error);
        }
      });
    }
    
    console.log(`✓ Added parameter ${parameterCount}`);
  } catch (error) {
    console.error("Error adding parameter:", error);
    AppState.decrementParameterCount(); // Rollback on error
  }
};

// ===================================================================
// INTEGRATION TYPE HANDLING
// ===================================================================

const integrationRequestMap = {
  REST: ["GET", "POST", "PUT", "PATCH", "DELETE"],
  MCP: [],
};

export const updateRequestTypeOptions = function (preselectedValue = null) {
  const requestTypeSelect = safeGetElement("requestType");
  const integrationTypeSelect = safeGetElement("integrationType");
  
  if (!requestTypeSelect || !integrationTypeSelect) {
    return;
  }
  
  const selectedIntegration = integrationTypeSelect.value;
  const options = integrationRequestMap[selectedIntegration] || [];
  
  // Clear current options
  requestTypeSelect.innerHTML = "";
  
  // Add new options
  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    requestTypeSelect.appendChild(option);
  });
  
  // Set the value if preselected
  if (preselectedValue && options.includes(preselectedValue)) {
    requestTypeSelect.value = preselectedValue;
  }
};

export const updateEditToolRequestTypes = function (selectedMethod = null) {
  const editToolTypeSelect = safeGetElement("edit-tool-type");
  const editToolRequestTypeSelect = safeGetElement("edit-tool-request-type");
  if (!editToolTypeSelect || !editToolRequestTypeSelect) {
    return;
  }
  
  // Track previous value using a data attribute
  if (!editToolTypeSelect.dataset.prevValue) {
    editToolTypeSelect.dataset.prevValue = editToolTypeSelect.value;
  }
  
  // const prevType = editToolTypeSelect.dataset.prevValue;
  const selectedType = editToolTypeSelect.value;
  const allowedMethods = integrationRequestMap[selectedType] || [];
  
  // If this integration has no HTTP verbs (MCP), clear & disable the control
  if (allowedMethods.length === 0) {
    editToolRequestTypeSelect.innerHTML = "";
    editToolRequestTypeSelect.value = "";
    editToolRequestTypeSelect.disabled = true;
    return;
  }
  
  // Otherwise populate and enable
  editToolRequestTypeSelect.disabled = false;
  editToolRequestTypeSelect.innerHTML = "";
  allowedMethods.forEach((method) => {
    const option = document.createElement("option");
    option.value = method;
    option.textContent = method;
    editToolRequestTypeSelect.appendChild(option);
  });
  
  if (selectedMethod && allowedMethods.includes(selectedMethod)) {
    editToolRequestTypeSelect.value = selectedMethod;
  }
};

// ===================================================================
// ADVANCED TOOLS FIELDS
// ===================================================================

// Add three fields to passthrough section on Advanced button click
export const handleAddPassthrough = function () {
  const passthroughContainer = safeGetElement("passthrough-container");
  if (!passthroughContainer) {
    console.error("Passthrough container not found");
    return;
  }
  
  // Toggle visibility
  if (
    passthroughContainer.style.display === "none" ||
    passthroughContainer.style.display === ""
  ) {
    passthroughContainer.style.display = "block";
    // Add fields only if not already present
    if (!safeGetElement("query-mapping-field")) {
      const queryDiv = document.createElement("div");
      queryDiv.className = "mb-4";
      queryDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Query Mapping (JSON)</label>
          <textarea id="query-mapping-field" name="query_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
      `;
      passthroughContainer.appendChild(queryDiv);
    }
    if (!safeGetElement("header-mapping-field")) {
      const headerDiv = document.createElement("div");
      headerDiv.className = "mb-4";
      headerDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Header Mapping (JSON)</label>
          <textarea id="header-mapping-field" name="header_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-600 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
      `;
      passthroughContainer.appendChild(headerDiv);
    }
    if (!safeGetElement("timeout-ms-field")) {
      const timeoutDiv = document.createElement("div");
      timeoutDiv.className = "mb-4";
      timeoutDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">timeout_ms (number)</label>
          <input type="number" id="timeout-ms-field" name="timeout_ms" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="30000" min="0" />
      `;
      passthroughContainer.appendChild(timeoutDiv);
    }
    if (!safeGetElement("expose-passthrough-field")) {
      const exposeDiv = document.createElement("div");
      exposeDiv.className = "mb-4";
      exposeDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Expose Passthrough</label>
          <select id="expose-passthrough-field" name="expose_passthrough" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300">
              <option value="true" selected>True</option>
              <option value="false">False</option>
          </select>
      `;
      passthroughContainer.appendChild(exposeDiv);
    }
    if (!safeGetElement("allowlist-field")) {
      const allowlistDiv = document.createElement("div");
      allowlistDiv.className = "mb-4";
      allowlistDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Allowlist (comma-separated hosts/schemes)</label>
          <input type="text" id="allowlist-field" name="allowlist" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[example.com, https://api.example.com]" />
      `;
      passthroughContainer.appendChild(allowlistDiv);
    }
    if (!safeGetElement("plugin-chain-pre-field")) {
      const pluginPreDiv = document.createElement("div");
      pluginPreDiv.className = "mb-4";
      pluginPreDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Plugin Chain Pre</label>
          <input type="text" id="plugin-chain-pre-field" name="plugin_chain_pre" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[]" />
      `;
      passthroughContainer.appendChild(pluginPreDiv);
    }
    if (!safeGetElement("plugin-chain-post-field")) {
      const pluginPostDiv = document.createElement("div");
      pluginPostDiv.className = "mb-4";
      pluginPostDiv.innerHTML = `
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Plugin Chain Post (optional, override defaults)</label>
          <input type="text" id="plugin-chain-post-field" name="plugin_chain_post" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[]" />
      `;
      passthroughContainer.appendChild(pluginPostDiv);
    }
  } else {
    passthroughContainer.style.display = "none";
  }
}



// ============================================================================ //
//                    TEAM SELECTOR DROPDOWN FUNCTIONS                           //
// ============================================================================ //

/**
* Debounce timer for team selector search
*/
let teamSelectorSearchDebounceTimer = null;

/**
* Search teams in the team selector dropdown
* @param {string} searchTerm - The search query
*/
export const searchTeamSelector = function (searchTerm) {
  // Debounce the search
  if (teamSelectorSearchDebounceTimer) {
    clearTimeout(teamSelectorSearchDebounceTimer);
  }
  
  teamSelectorSearchDebounceTimer = setTimeout(() => {
    performTeamSelectorSearch(searchTerm);
  }, 300);
}

/**
* Perform the team selector search
* @param {string} searchTerm - The search query
*/
const performTeamSelectorSearch = function (searchTerm) {
  const container = safeGetElement("team-selector-items");
  if (!container) {
    console.error("team-selector-items container not found");
    return;
  }
  
  // Build URL
  const params = new URLSearchParams();
  params.set("page", "1");
  params.set("per_page", "20");
  params.set("render", "selector");
  
  if (searchTerm && searchTerm.trim() !== "") {
    params.set("q", searchTerm.trim());
  }
  
  const url = `${window.ROOT_PATH || ""}/admin/teams/partial?${params.toString()}`;
  
  // Use HTMX to load results
  if (window.htmx) {
    window.htmx.ajax("GET", url, {
      target: "#team-selector-items",
      swap: "innerHTML",
    });
  }
}

/**
* Select a team from the team selector dropdown
* @param {HTMLElement} button - The button element that was clicked
*/
export const selectTeamFromSelector = function (button) {
  const teamId = button.dataset.teamId;
  const teamName = button.dataset.teamName;
  const isPersonal = button.dataset.teamIsPersonal === "true";
  
  // Update the Alpine.js component state
  const selectorContainer = button.closest("[x-data]");
  if (selectorContainer && selectorContainer.__x) {
    const alpineData = selectorContainer.__x.$data;
    alpineData.selectedTeam = teamId;
    alpineData.selectedTeamName = (isPersonal ? "👤 " : "🏢 ") + teamName;
    alpineData.open = false;
  }
  
  // Clear the search input
  const searchInput = safeGetElement("team-selector-search");
  if (searchInput) {
    searchInput.value = "";
  }
  
  // Reset the loaded flag so next open reloads the list
  const itemsContainer = safeGetElement("team-selector-items");
  if (itemsContainer) {
    delete itemsContainer.dataset.loaded;
  }
  
  // Call the existing updateTeamContext function (defined in admin.html)
  if (typeof window.updateTeamContext === "function") {
    window.updateTeamContext(teamId);
  }
}