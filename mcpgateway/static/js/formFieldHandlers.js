  // ===================================================================
  // ENHANCED SCHEMA GENERATION with Safe State Access
  // ===================================================================

import { validateInputName } from "./security";

  
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