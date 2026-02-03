((Admin) => {
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
                        const editModal =
                            Admin.safeGetElement("server-edit-modal");
                        const isEditModalOpen =
                            editModal && !editModal.classList.contains("hidden");

                        if (isEditModalOpen) {
                            container =
                                Admin.safeGetElement("edit-server-tools");
                        } else {
                            container = Admin.safeGetElement("associatedTools");
                        }
                    }

                    // Final safety check - use direct lookup if still not found
                    if (!container) {
                        const addServerContainer =
                            Admin.safeGetElement("associatedTools");
                        const editServerContainer =
                            Admin.safeGetElement("edit-server-tools");

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
                            "input[data-auto-check=true]",
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
                            'input[name="selectAllTools"]',
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
                            const dataAttr =
                                container.getAttribute("data-server-tools");

                            if (dataAttr) {
                                try {
                                    serverTools = JSON.parse(dataAttr);
                                } catch (e) {
                                    console.error(
                                        "Failed to parse data-server-tools:",
                                        e,
                                    );
                                }
                            }

                            if (serverTools && serverTools.length > 0) {
                                newCheckboxes.forEach((cb) => {
                                    const toolId = cb.value;
                                    const toolName =
                                        cb.getAttribute("data-tool-name"); // Use the data attribute directly
                                    if (toolId && toolName) {
                                        // Check if this tool name exists in server associated tools
                                        if (serverTools.includes(toolName)) {
                                            cb.checked = true;
                                        }
                                    }
                                    cb.removeAttribute("data-auto-check");
                                });

                                // Trigger an update to display the correct count based on server.associatedTools
                                // This will make sure the pill counters reflect the total associated tools count
                                const event = new Event("change", {
                                    bubbles: true,
                                });
                                container.dispatchEvent(event);
                            }
                        }
                        // If we're in the Add Server tools container, restore persisted selections
                        else if (container.id === "associatedTools") {
                            try {
                                const dataAttr = container.getAttribute(
                                    "data-selected-tools",
                                );
                                if (dataAttr) {
                                    const selectedIds = JSON.parse(dataAttr);
                                    if (
                                        Array.isArray(selectedIds) &&
                                        selectedIds.length > 0
                                    ) {
                                        newCheckboxes.forEach((cb) => {
                                            if (selectedIds.includes(cb.value)) {
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
                            } catch (e) {
                                console.warn(
                                    "Error restoring associatedTools selections:",
                                    e,
                                );
                            }
                        }
                    }
                }, 10); // Small delay to ensure DOM is updated
            }
        });
    };

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
                        const editModal =
                            Admin.safeGetElement("server-edit-modal");
                        const isEditModalOpen =
                            editModal && !editModal.classList.contains("hidden");

                        if (isEditModalOpen) {
                            container = Admin.safeGetElement(
                                "edit-server-resources",
                            );
                        } else {
                            container = Admin.safeGetElement(
                                "associatedResources",
                            );
                        }
                    }

                    if (container) {
                        const newCheckboxes = container.querySelectorAll(
                            "input[data-auto-check=true]",
                        );

                        const selectAllInput = container.querySelector(
                            'input[name="selectAllResources"]',
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
                        const dataAttr = container.getAttribute(
                            "data-server-resources",
                        );
                        if (dataAttr) {
                            try {
                                const associatedResourceIds = JSON.parse(dataAttr);
                                newCheckboxes.forEach((cb) => {
                                    const checkboxValue = cb.value;
                                    if (
                                        associatedResourceIds.includes(
                                            checkboxValue,
                                        )
                                    ) {
                                        cb.checked = true;
                                    }
                                    cb.removeAttribute("data-auto-check");
                                });

                                if (newCheckboxes.length > 0) {
                                    const event = new Event("change", {
                                        bubbles: true,
                                    });
                                    container.dispatchEvent(event);
                                }
                            } catch (e) {
                                console.error(
                                    "Error parsing data-server-resources:",
                                    e,
                                );
                            }
                        }

                        // If we're in the Add Server resources container, restore persisted selections
                        else if (container.id === "associatedResources") {
                            try {
                                const dataAttr = container.getAttribute(
                                    "data-selected-resources",
                                );
                                if (dataAttr) {
                                    const selectedIds = JSON.parse(dataAttr);
                                    if (
                                        Array.isArray(selectedIds) &&
                                        selectedIds.length > 0
                                    ) {
                                        newCheckboxes.forEach((cb) => {
                                            if (selectedIds.includes(cb.value)) {
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
                            } catch (e) {
                                console.warn(
                                    "Error restoring associatedResources selections:",
                                    e,
                                );
                            }
                        }
                    }
                }, 10);
            }
        });
    };

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
                        const editModal =
                            Admin.safeGetElement("server-edit-modal");
                        const isEditModalOpen =
                            editModal && !editModal.classList.contains("hidden");

                        if (isEditModalOpen) {
                            container = Admin.safeGetElement(
                                "edit-server-prompts",
                            );
                        } else {
                            container =
                                Admin.safeGetElement("associatedPrompts");
                        }
                    }

                    if (container) {
                        const newCheckboxes = container.querySelectorAll(
                            "input[data-auto-check=true]",
                        );

                        const selectAllInput = container.querySelector(
                            'input[name="selectAllPrompts"]',
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
                        const dataAttr = container.getAttribute(
                            "data-server-prompts",
                        );
                        if (dataAttr) {
                            try {
                                const associatedPromptIds = JSON.parse(dataAttr);
                                newCheckboxes.forEach((cb) => {
                                    const checkboxValue = cb.value;
                                    if (
                                        associatedPromptIds.includes(checkboxValue)
                                    ) {
                                        cb.checked = true;
                                    }
                                    cb.removeAttribute("data-auto-check");
                                });

                                if (newCheckboxes.length > 0) {
                                    const event = new Event("change", {
                                        bubbles: true,
                                    });
                                    container.dispatchEvent(event);
                                }
                            } catch (e) {
                                console.error(
                                    "Error parsing data-server-prompts:",
                                    e,
                                );
                            }
                        }

                        // If we're in the Add Server prompts container, restore persisted selections
                        else if (container.id === "associatedPrompts") {
                            try {
                                const dataAttr = container.getAttribute(
                                    "data-selected-prompts",
                                );
                                if (dataAttr) {
                                    const selectedIds = JSON.parse(dataAttr);
                                    if (
                                        Array.isArray(selectedIds) &&
                                        selectedIds.length > 0
                                    ) {
                                        newCheckboxes.forEach((cb) => {
                                            if (selectedIds.includes(cb.value)) {
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
                            } catch (e) {
                                console.warn(
                                    "Error restoring associatedPrompts selections:",
                                    e,
                                );
                            }
                        }
                    }
                }, 10);
            }
        });
    };

    // ===================================================================
    // ENHANCED SCHEMA GENERATION with Safe State Access
    // ===================================================================

    Admin.generateSchema = function () {
        const schema = {
            title: "CustomInputSchema",
            type: "object",
            properties: {},
            required: [],
        };

        const paramCount = Admin.AppState.getParameterCount();

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
                    const nameValidation = Admin.validateInputName(
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

    Admin.updateSchemaPreview = function () {
        try {
            const modeRadio = document.querySelector(
                'input[name="schema_input_mode"]:checked',
            );
            if (modeRadio && modeRadio.value === "json") {
                if (
                    window.schemaEditor &&
                    typeof window.schemaEditor.setValue === "function"
                ) {
                    window.schemaEditor.setValue(Admin.generateSchema());
                }
            }
        } catch (error) {
            console.error("Error updating schema preview:", error);
        }
    };

    // ===================================================================
    // ENHANCED PARAMETER HANDLING with Validation
    // ===================================================================

    Admin.createParameterForm = function (parameterCount) {
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
            const validation = Admin.validateInputName(this.value, "parameter");
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

    Admin.handleAddParameter = function () {
        const parameterCount = Admin.AppState.incrementParameterCount();
        const parametersContainer = Admin.safeGetElement("parameters-container");

        if (!parametersContainer) {
            console.error("Parameters container not found");
            Admin.AppState.decrementParameterCount(); // Rollback
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
            const parameterForm = Admin.createParameterForm(parameterCount);
            paramDiv.appendChild(parameterForm);

            parametersContainer.appendChild(paramDiv);
            Admin.updateSchemaPreview();

            // Delete parameter functionality with safe state management
            const deleteButton = paramDiv.querySelector(".delete-param");
            if (deleteButton) {
                deleteButton.addEventListener("click", () => {
                    try {
                        paramDiv.remove();
                        Admin.AppState.decrementParameterCount();
                        Admin.updateSchemaPreview();
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
            Admin.AppState.decrementParameterCount(); // Rollback on error
        }
    };

    // ===================================================================
    // INTEGRATION TYPE HANDLING
    // ===================================================================

    const integrationRequestMap = {
        REST: ["GET", "POST", "PUT", "PATCH", "DELETE"],
        MCP: [],
    };

    Admin.updateRequestTypeOptions = function (preselectedValue = null) {
        const requestTypeSelect = Admin.safeGetElement("requestType");
        const integrationTypeSelect = Admin.safeGetElement("integrationType");

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

    Admin.updateEditToolRequestTypes = function (selectedMethod = null) {
        const editToolTypeSelect = Admin.safeGetElement("edit-tool-type");
        const editToolRequestTypeSelect = Admin.safeGetElement("edit-tool-request-type");
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
    // GATEWAY SELECT (Associated MCP Servers) - search/select/clear
    // ===================================================================
    Admin.initGatewaySelect = function (
        selectId = "associatedGateways",
        pillsId = "selectedGatewayPills",
        warnId = "selectedGatewayWarning",
        max = 12,
        selectBtnId = "selectAllGatewayBtn",
        clearBtnId = "clearAllGatewayBtn",
        searchInputId = "searchGateways",
    ) {
        const container = Admin.safeGetElement(selectId);
        const pillsBox = Admin.safeGetElement(pillsId);
        const warnBox = Admin.safeGetElement(warnId);
        const clearBtn = clearBtnId ? Admin.safeGetElement(clearBtnId) : null;
        const selectBtn = selectBtnId ? Admin.safeGetElement(selectBtnId) : null;
        const searchInput = searchInputId
            ? Admin.safeGetElement(searchInputId)
            : null;

        if (!container || !pillsBox || !warnBox) {
            console.warn(
                `Gateway select elements not found: ${selectId}, ${pillsId}, ${warnId}`,
            );
            return;
        }

        const pillClasses =
            "inline-block bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full dark:bg-indigo-900 dark:text-indigo-200";

        // Search functionality
    Admin.applySearch = function () {
            if (!searchInput) {
                return;
            }

            try {
                const query = searchInput.value.toLowerCase().trim();
                const items = container.querySelectorAll(".tool-item");
                let visibleCount = 0;

                items.forEach((item) => {
                    const text = item.textContent.toLowerCase();
                    if (!query || text.includes(query)) {
                        item.style.display = "";
                        visibleCount++;
                    } else {
                        item.style.display = "none";
                    }
                });

                // Update "no results" message if it exists
                const noMsg = Admin.safeGetElement("noGatewayMessage");
                const searchQuerySpan =
                    Admin.safeGetElement("searchQueryServers");

                if (noMsg) {
                    if (query && visibleCount === 0) {
                        noMsg.style.display = "block";
                        if (searchQuerySpan) {
                            searchQuerySpan.textContent = query;
                        }
                    } else {
                        noMsg.style.display = "none";
                    }
                }
            } catch (error) {
                console.error("Error applying gateway search:", error);
            }
        }

        // Bind search input
        if (searchInput && !searchInput.dataset.searchBound) {
            searchInput.addEventListener("input", Admin.applySearch);
            searchInput.dataset.searchBound = "true";
        }

    Admin.update = function () {
            try {
                const checkboxes = container.querySelectorAll(
                    'input[type="checkbox"]',
                );
                const checked = Array.from(checkboxes).filter((cb) => cb.checked);

                // Check if "Select All" mode is active
                const selectAllInput = container.querySelector(
                    'input[name="selectAllGateways"]',
                );
                const allIdsInput = container.querySelector(
                    'input[name="allGatewayIds"]',
                );

                let count = checked.length;

                // If Select All mode is active, use the count from allGatewayIds
                if (
                    selectAllInput &&
                    selectAllInput.value === "true" &&
                    allIdsInput
                ) {
                    try {
                        const allIds = JSON.parse(allIdsInput.value);
                        count = allIds.length;
                    } catch (e) {
                        console.error("Error parsing allGatewayIds:", e);
                    }
                }

                // Rebuild pills safely - show first 3, then summarize the rest
                pillsBox.innerHTML = "";
                const maxPillsToShow = 3;

                checked.slice(0, maxPillsToShow).forEach((cb) => {
                    const span = document.createElement("span");
                    span.className = pillClasses;
                    span.textContent =
                        cb.nextElementSibling?.textContent?.trim() || "Unnamed";
                    pillsBox.appendChild(span);
                });

                // If more than maxPillsToShow, show a summary pill
                if (count > maxPillsToShow) {
                    const span = document.createElement("span");
                    span.className = pillClasses + " cursor-pointer";
                    span.title = "Click to see all selected gateways";
                    const remaining = count - maxPillsToShow;
                    span.textContent = `+${remaining} more`;
                    pillsBox.appendChild(span);
                }

                // Warning when > max
                if (count > max) {
                    warnBox.textContent = `Selected ${count} MCP servers. Selecting more than ${max} servers may impact performance.`;
                } else {
                    warnBox.textContent = "";
                }
            } catch (error) {
                console.error("Error updating gateway select:", error);
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
                    'input[name="selectAllGateways"]',
                );
                if (selectAllInput) {
                    selectAllInput.remove();
                }
                const allIdsInput = container.querySelector(
                    'input[name="allGatewayIds"]',
                );
                if (allIdsInput) {
                    allIdsInput.remove();
                }

                Admin.update();

                // Reload associated items after clearing selection
                Admin.reloadAssociatedItems();
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
                newSelectBtn.textContent = "Selecting all gateways...";

                try {
                    // Fetch all gateway IDs from the server
                    const selectedTeamId = Admin.getCurrentTeamId();
                    const params = new URLSearchParams();
                    if (selectedTeamId) {
                        params.set("team_id", selectedTeamId);
                    }
                    const queryString = params.toString();
                    const response = await fetch(
                        `${window.ROOT_PATH}/admin/gateways/ids${queryString ? `?${queryString}` : ""}`,
                    );
                    if (!response.ok) {
                        throw new Error("Failed to fetch gateway IDs");
                    }

                    const data = await response.json();
                    const allGatewayIds = data.gateway_ids || [];

                    // Apply search filter first to determine which items are visible
                    Admin.applySearch();

                    // Check only currently visible checkboxes
                    const loadedCheckboxes = container.querySelectorAll(
                        'input[type="checkbox"]',
                    );
                    loadedCheckboxes.forEach((cb) => {
                        const parent = cb.closest(".tool-item") || cb.parentElement;
                        const isVisible =
                            parent && getComputedStyle(parent).display !== "none";
                        if (isVisible) {
                            cb.checked = true;
                        }
                    });

                    // Add a hidden input to indicate "select all" mode
                    // Remove any existing one first
                    let selectAllInput = container.querySelector(
                        'input[name="selectAllGateways"]',
                    );
                    if (!selectAllInput) {
                        selectAllInput = document.createElement("input");
                        selectAllInput.type = "hidden";
                        selectAllInput.name = "selectAllGateways";
                        container.appendChild(selectAllInput);
                    }
                    selectAllInput.value = "true";

                    // Also store the IDs as a JSON array for the backend
                    // Ensure the special 'null' sentinel is included when selecting all
                    try {
                        const nullCheckbox = container.querySelector(
                            'input[data-gateway-null="true"]',
                        );
                        if (nullCheckbox) {
                            // Include the literal string "null" so server-side
                            // `any(gid.lower() == 'null' ...)` evaluates to true.
                            if (!allGatewayIds.includes("null")) {
                                allGatewayIds.push("null");
                            }
                        }
                    } catch (err) {
                        console.error(
                            "Error ensuring null sentinel in gateway IDs:",
                            err,
                        );
                    }

                    let allIdsInput = container.querySelector(
                        'input[name="allGatewayIds"]',
                    );
                    if (!allIdsInput) {
                        allIdsInput = document.createElement("input");
                        allIdsInput.type = "hidden";
                        allIdsInput.name = "allGatewayIds";
                        container.appendChild(allIdsInput);
                    }
                    allIdsInput.value = JSON.stringify(allGatewayIds);

                    Admin.update();

                    newSelectBtn.textContent = `✓ All ${allGatewayIds.length} gateways selected`;
                    setTimeout(() => {
                        newSelectBtn.textContent = originalText;
                    }, 2000);

                    // Reload associated items after selecting all
                    Admin.reloadAssociatedItems();
                } catch (error) {
                    console.error("Error in Select All:", error);
                    alert("Failed to select all gateways. Please try again.");
                    newSelectBtn.disabled = false;
                    newSelectBtn.textContent = originalText;
                } finally {
                    newSelectBtn.disabled = false;
                }
            });
        }

        Admin.update(); // Initial render

        // Attach change listeners to checkboxes (using delegation for dynamic content)
        if (!container.dataset.changeListenerAttached) {
            container.dataset.changeListenerAttached = "true";
            container.addEventListener("change", (e) => {
                if (e.target.type === "checkbox") {
                    // Log gateway_id when checkbox is clicked
                    // Normalize the special null-gateway checkbox to the literal string "null"
                    let gatewayId = e.target.value;
                    if (
                        e.target.dataset &&
                        e.target.dataset.gatewayNull === "true"
                    ) {
                        gatewayId = "null";
                    }
                    const gatewayName =
                        e.target.nextElementSibling?.textContent?.trim() ||
                        "Unknown";
                    const isChecked = e.target.checked;

                    console.log(
                        `[MCP Server Selection] Gateway ID: ${gatewayId}, Name: ${gatewayName}, Checked: ${isChecked}`,
                    );

                    // Check if we're in "Select All" mode
                    const selectAllInput = container.querySelector(
                        'input[name="selectAllGateways"]',
                    );
                    const allIdsInput = container.querySelector(
                        'input[name="allGatewayIds"]',
                    );

                    if (
                        selectAllInput &&
                        selectAllInput.value === "true" &&
                        allIdsInput
                    ) {
                        // User is manually checking/unchecking after Select All
                        // Update the allGatewayIds array to reflect the change
                        try {
                            let allIds = JSON.parse(allIdsInput.value);

                            if (e.target.checked) {
                                // Add the ID if it's not already there
                                if (!allIds.includes(gatewayId)) {
                                    allIds.push(gatewayId);
                                }
                            } else {
                                // Remove the ID from the array
                                allIds = allIds.filter((id) => id !== gatewayId);
                            }

                            // Update the hidden field
                            allIdsInput.value = JSON.stringify(allIds);
                        } catch (error) {
                            console.error("Error updating allGatewayIds:", error);
                        }
                    }

                    // No exclusivity: allow the special 'null' gateway (RestTool/Prompts/Resources) to be
                    // selected together with real gateways. Server-side filtering already
                    // supports mixed lists like `gateway_id=abc,null`.

                    Admin.update();

                    // Trigger reload of associated tools, resources, and prompts with selected gateway filter
                    Admin.reloadAssociatedItems();
                }
            });
        }

        // Initial render
        Admin.applySearch();
        Admin.update();
    };

    /**
    * Get all selected gateway IDs from the gateway selection container
    * @returns {string[]} Array of selected gateway IDs
    */
    Admin.getSelectedGatewayIds = function () {
        // Prefer the gateway selection belonging to the currently active form.
        // If the edit-server modal is open, use the edit modal's gateway container
        // (`associatedEditGateways`). Otherwise use the create form container
        // (`associatedGateways`). This allows the same filtering logic to work
        // for both Add and Edit flows.
        let container = Admin.safeGetElement("associatedGateways");
        const editContainer = Admin.safeGetElement("associatedEditGateways");

        const editModal = Admin.safeGetElement("server-edit-modal");
        const isEditModalOpen =
            editModal && !editModal.classList.contains("hidden");

        if (isEditModalOpen && editContainer) {
            container = editContainer;
        } else if (
            editContainer &&
            editContainer.offsetParent !== null &&
            !container
        ) {
            // If edit container is visible (e.g. modal rendered) and associatedGateways
            // not present, prefer edit container.
            container = editContainer;
        }

        console.log(
            "[Gateway Selection DEBUG] Container used:",
            container ? container.id : null,
        );

        if (!container) {
            console.warn(
                "[Gateway Selection DEBUG] No gateway container found (associatedGateways or associatedEditGateways)",
            );
            return [];
        }

        // Check if "Select All" mode is active
        const selectAllInput = container.querySelector(
            "input[name='selectAllGateways']",
        );
        const allIdsInput = container.querySelector("input[name='allGatewayIds']");

        console.log(
            "[Gateway Selection DEBUG] Select All mode:",
            selectAllInput?.value === "true",
        );
        if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
            try {
                const allIds = JSON.parse(allIdsInput.value);
                console.log(
                    `[Gateway Selection DEBUG] Returning all gateway IDs (${allIds.length} total)`,
                );
                return allIds;
            } catch (error) {
                console.error(
                    "[Gateway Selection DEBUG] Error parsing allGatewayIds:",
                    error,
                );
            }
        }

        // Otherwise, get all checked checkboxes. If the special 'null' gateway
        // checkbox is selected, include the sentinel 'null' alongside any real
        // gateway ids. This allows requests like `gateway_id=abc,null` which the
        // server interprets as (gateway_id = abc) OR (gateway_id IS NULL).
        const checkboxes = container.querySelectorAll(
            "input[type='checkbox']:checked",
        );

        const selectedIds = Array.from(checkboxes)
            .map((cb) => {
                // Convert the special null-gateway checkbox to the literal 'null'
                if (cb.dataset?.gatewayNull === "true") {
                    return "null";
                }
                return cb.value;
            })
            // Filter out any empty values to avoid sending empty CSV entries
            .filter((id) => id !== "" && id !== null && id !== undefined);

        console.log(
            `[Gateway Selection DEBUG] Found ${selectedIds.length} checked gateway checkboxes`,
        );
        console.log("[Gateway Selection DEBUG] Selected gateway IDs:", selectedIds);

        return selectedIds;
    };

    /**
    * Reload associated tools, resources, and prompts filtered by selected gateway IDs
    */
    Admin.reloadAssociatedItems = function () {
        const selectedGatewayIds = Admin.getSelectedGatewayIds();
        // Join all selected IDs (including the special 'null' sentinel if present)
        // so the server receives a combined filter like `gateway_id=abc,null`.
        let gatewayIdParam = "";
        if (selectedGatewayIds.length > 0) {
            gatewayIdParam = selectedGatewayIds.join(",");
        }

        console.log(
            `[Filter Update] Reloading associated items for gateway IDs: ${gatewayIdParam || "none (showing all)"}`,
        );
        console.log(
            "[Filter Update DEBUG] Selected gateway IDs array:",
            selectedGatewayIds,
        );

        // Determine whether to reload the 'create server' containers (associated*)
        // or the 'edit server' containers (edit-server-*). Prefer the edit
        // containers when the edit modal is open or the edit-gateway selector
        // exists and is visible.
        const editModal = Admin.safeGetElement("server-edit-modal");
        const isEditModalOpen =
            editModal && !editModal.classList.contains("hidden");
        const editGateways = Admin.safeGetElement("associatedEditGateways");

        const useEditContainers =
            isEditModalOpen || (editGateways && editGateways.offsetParent !== null);

        const toolsContainerId = useEditContainers
            ? "edit-server-tools"
            : "associatedTools";
        const resourcesContainerId = useEditContainers
            ? "edit-server-resources"
            : "associatedResources";
        const promptsContainerId = useEditContainers
            ? "edit-server-prompts"
            : "associatedPrompts";

        // Reload tools
        const toolsContainer = Admin.safeGetElement(toolsContainerId);
        if (toolsContainer) {
            const toolsUrl = gatewayIdParam
                ? `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                : `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`;

            console.log(
                "[Filter Update DEBUG] Tools URL:",
                toolsUrl,
                "-> target:",
                `#${toolsContainerId}`,
            );

            // Use HTMX to reload the content into the chosen container
            if (window.htmx) {
                htmx.ajax("GET", toolsUrl, {
                    target: `#${toolsContainerId}`,
                    swap: "innerHTML",
                })
                    .then(() => {
                        console.log(
                            "[Filter Update DEBUG] Tools reloaded successfully",
                        );
                        // Re-initialize the tool select after content is loaded
                        const pillsId = useEditContainers
                            ? "selectedEditToolsPills"
                            : "selectedToolsPills";
                        const warnId = useEditContainers
                            ? "selectedEditToolsWarning"
                            : "selectedToolsWarning";
                        const selectBtn = useEditContainers
                            ? "selectAllEditToolsBtn"
                            : "selectAllToolsBtn";
                        const clearBtn = useEditContainers
                            ? "clearAllEditToolsBtn"
                            : "clearAllToolsBtn";

                        Admin.initToolSelect(
                            toolsContainerId,
                            pillsId,
                            warnId,
                            6,
                            selectBtn,
                            clearBtn,
                        );
                    })
                    .catch((err) => {
                        console.error(
                            "[Filter Update DEBUG] Tools reload failed:",
                            err,
                        );
                    });
            } else {
                console.error(
                    "[Filter Update DEBUG] HTMX not available for tools reload",
                );
            }
        } else {
            console.warn(
                "[Filter Update DEBUG] Tools container not found ->",
                toolsContainerId,
            );
        }

        // Reload resources - use fetch directly to avoid HTMX race conditions
        const resourcesContainer = Admin.safeGetElement(resourcesContainerId);
        if (resourcesContainer) {
            const resourcesUrl = gatewayIdParam
                ? `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                : `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector`;

            console.log("[Filter Update DEBUG] Resources URL:", resourcesUrl);

            // Use fetch() directly instead of htmx.ajax() to avoid race conditions
            fetch(resourcesUrl, {
                method: "GET",
                headers: {
                    "HX-Request": "true",
                    "HX-Current-URL": window.location.href,
                },
            })
                .then((response) => {
                    if (!response.ok) {
                        throw new Error(
                            `HTTP ${response.status}: ${response.statusText}`,
                        );
                    }
                    return response.text();
                })
                .then((html) => {
                    console.log(
                        "[Filter Update DEBUG] Resources fetch successful, HTML length:",
                        html.length,
                    );
                    // Persist current selections to window fallback before replacing container
                    // AND preserve the data-selected-resources attribute
                    let persistedResourceIds = [];
                    try {
                        // First, try to get from the container's data attribute
                        const dataAttr = resourcesContainer.getAttribute(
                            "data-selected-resources",
                        );
                        if (dataAttr) {
                            try {
                                const parsed = JSON.parse(dataAttr);
                                if (Array.isArray(parsed)) {
                                    persistedResourceIds = parsed.slice();
                                }
                            } catch (e) {
                                console.error(
                                    "Error parsing data-selected-resources:",
                                    e,
                                );
                            }
                        }

                        // Merge with currently checked items
                        const currentChecked = Array.from(
                            resourcesContainer.querySelectorAll(
                                'input[type="checkbox"]:checked',
                            ),
                        ).map((cb) => cb.value);
                        const merged = new Set([
                            ...persistedResourceIds,
                            ...currentChecked,
                        ]);
                        persistedResourceIds = Array.from(merged);

                        // Update window fallback
                        Admin._selectedAssociatedResources =
                            persistedResourceIds.slice();
                    } catch (e) {
                        console.error(
                            "Error capturing current resource selections before reload:",
                            e,
                        );
                    }

                    resourcesContainer.innerHTML = html;

                    // Immediately restore the data-selected-resources attribute after innerHTML replacement
                    if (persistedResourceIds.length > 0) {
                        resourcesContainer.setAttribute(
                            "data-selected-resources",
                            JSON.stringify(persistedResourceIds),
                        );
                    }
                    // If HTMX is available, process the newly-inserted HTML so hx-*
                    // triggers (like the infinite-scroll 'intersect' trigger) are
                    // initialized. To avoid HTMX re-triggering the container's
                    // own `hx-get`/`hx-trigger="load"` (which would issue a second
                    // request without the gateway filter), temporarily remove those
                    // attributes from the container while we call `htmx.process`.
                    if (window.htmx && typeof window.htmx.process === "function") {
                        try {
                            // Backup and remove attributes that could auto-fire
                            const hadHxGet =
                                resourcesContainer.hasAttribute("hx-get");
                            const hadHxTrigger =
                                resourcesContainer.hasAttribute("hx-trigger");
                            const oldHxGet =
                                resourcesContainer.getAttribute("hx-get");
                            const oldHxTrigger =
                                resourcesContainer.getAttribute("hx-trigger");

                            if (hadHxGet) {
                                resourcesContainer.removeAttribute("hx-get");
                            }
                            if (hadHxTrigger) {
                                resourcesContainer.removeAttribute("hx-trigger");
                            }

                            // Process only the newly-inserted inner nodes to initialize
                            // any hx-* behavior (infinite scroll, after-swap hooks, etc.)
                            window.htmx.process(resourcesContainer);

                            // Restore original attributes so the container retains its
                            // declarative behavior for future operations, but don't
                            // re-process (we already processed child nodes).
                            if (hadHxGet && oldHxGet !== null) {
                                resourcesContainer.setAttribute("hx-get", oldHxGet);
                            }
                            if (hadHxTrigger && oldHxTrigger !== null) {
                                resourcesContainer.setAttribute(
                                    "hx-trigger",
                                    oldHxTrigger,
                                );
                            }

                            console.log(
                                "[Filter Update DEBUG] htmx.process called on resources container (attributes temporarily removed)",
                            );
                        } catch (e) {
                            console.warn(
                                "[Filter Update DEBUG] htmx.process failed:",
                                e,
                            );
                        }
                    }

                    // Re-initialize the resource select after content is loaded
                    const resPills = useEditContainers
                        ? "selectedEditResourcesPills"
                        : "selectedResourcesPills";
                    const resWarn = useEditContainers
                        ? "selectedEditResourcesWarning"
                        : "selectedResourcesWarning";
                    const resSelectBtn = useEditContainers
                        ? "selectAllEditResourcesBtn"
                        : "selectAllResourcesBtn";
                    const resClearBtn = useEditContainers
                        ? "clearAllEditResourcesBtn"
                        : "clearAllResourcesBtn";

                    // The data-selected-resources attribute should already be restored above,
                    // but double-check and merge with window fallback if needed
                    try {
                        const dataAttr = resourcesContainer.getAttribute(
                            "data-selected-resources",
                        );
                        let selectedIds = [];
                        if (dataAttr) {
                            try {
                                const parsed = JSON.parse(dataAttr);
                                if (Array.isArray(parsed)) {
                                    selectedIds = parsed.slice();
                                }
                            } catch (e) {
                                console.error(
                                    "Error parsing data-selected-resources:",
                                    e,
                                );
                            }
                        }

                        // Merge with window fallback if it has additional selections
                        if (
                            Array.isArray(Admin._selectedAssociatedResources) &&
                            Admin._selectedAssociatedResources.length > 0
                        ) {
                            const merged = new Set([
                                ...selectedIds,
                                ...Admin._selectedAssociatedResources,
                            ]);
                            const mergedArray = Array.from(merged);
                            if (mergedArray.length > selectedIds.length) {
                                resourcesContainer.setAttribute(
                                    "data-selected-resources",
                                    JSON.stringify(mergedArray),
                                );
                                console.log(
                                    "[Filter Update DEBUG] Merged additional selections from window fallback",
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring data-selected-resources after fetch reload:",
                            e,
                        );
                    }

                    // First restore persisted selections from data-selected-resources (Add Server mode)
                    try {
                        const dataAttr = resourcesContainer.getAttribute(
                            "data-selected-resources",
                        );
                        if (
                            dataAttr &&
                            resourcesContainerId === "associatedResources"
                        ) {
                            const selectedIds = JSON.parse(dataAttr);
                            if (
                                Array.isArray(selectedIds) &&
                                selectedIds.length > 0
                            ) {
                                const resourceCheckboxes =
                                    resourcesContainer.querySelectorAll(
                                        'input[type="checkbox"][name="associatedResources"]',
                                    );
                                resourceCheckboxes.forEach((cb) => {
                                    if (selectedIds.includes(cb.value)) {
                                        cb.checked = true;
                                    }
                                });
                                console.log(
                                    "[Filter Update DEBUG] Restored",
                                    selectedIds.length,
                                    "persisted resource selections",
                                );
                            }
                        }
                    } catch (e) {
                        console.warn(
                            "Error restoring persisted resource selections:",
                            e,
                        );
                    }

                    Admin.initResourceSelect(
                        resourcesContainerId,
                        resPills,
                        resWarn,
                        6,
                        resSelectBtn,
                        resClearBtn,
                    );

                    // Re-apply server-associated resource selections so selections
                    // persist across gateway-filtered reloads (Edit Server mode).
                    // The resources partial replaces checkbox inputs; use the container's
                    // `data-server-resources` attribute (set when opening edit modal)
                    // to restore checked state.
                    try {
                        const dataAttr = resourcesContainer.getAttribute(
                            "data-server-resources",
                        );
                        if (dataAttr) {
                            const associated = JSON.parse(dataAttr);
                            if (
                                Array.isArray(associated) &&
                                associated.length > 0
                            ) {
                                const resourceCheckboxes =
                                    resourcesContainer.querySelectorAll(
                                        'input[type="checkbox"][name="associatedResources"]',
                                    );
                                resourceCheckboxes.forEach((cb) => {
                                    const val = cb.value;
                                    if (
                                        !Number.isNaN(val) &&
                                        associated.includes(val)
                                    ) {
                                        cb.checked = true;
                                    }
                                });

                                // Trigger change so pills and counts update
                                const event = new Event("change", {
                                    bubbles: true,
                                });
                                resourcesContainer.dispatchEvent(event);
                            }
                        }
                    } catch (e) {
                        console.warn("Error restoring associated resources:", e);
                    }
                    console.log(
                        "[Filter Update DEBUG] Resources reloaded successfully via fetch",
                    );
                })
                .catch((err) => {
                    console.error(
                        "[Filter Update DEBUG] Resources reload failed:",
                        err,
                    );
                });
        } else {
            console.warn("[Filter Update DEBUG] Resources container not found");
        }

        // Reload prompts
        const promptsContainer = Admin.safeGetElement(promptsContainerId);
        if (promptsContainer) {
            const promptsUrl = gatewayIdParam
                ? `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                : `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`;

            // Persist current prompt selections before HTMX replaces the container
            try {
                const currentCheckedPrompts = Array.from(
                    promptsContainer.querySelectorAll(
                        'input[type="checkbox"]:checked',
                    ),
                ).map((cb) => cb.value);
                if (
                    !Array.isArray(window._selectedAssociatedPrompts) ||
                    window._selectedAssociatedPrompts.length === 0
                ) {
                    window._selectedAssociatedPrompts =
                        currentCheckedPrompts.slice();
                } else {
                    const merged = new Set([
                        ...(window._selectedAssociatedPrompts || []),
                        ...currentCheckedPrompts,
                    ]);
                    Admin._selectedAssociatedPrompts = Array.from(merged);
                }
            } catch (e) {
                console.error(
                    "Error capturing current prompt selections before reload:",
                    e,
                );
            }

            if (window.htmx) {
                htmx.ajax("GET", promptsUrl, {
                    target: `#${promptsContainerId}`,
                    swap: "innerHTML",
                }).then(() => {
                    try {
                        const containerEl =
                            Admin.safeGetElement(promptsContainerId);
                        if (containerEl) {
                            const existingAttr = containerEl.getAttribute(
                                "data-selected-prompts",
                            );
                            let existingIds = null;
                            if (existingAttr) {
                                try {
                                    existingIds = JSON.parse(existingAttr);
                                } catch (e) {
                                    console.error(
                                        "Error parsing existing data-selected-prompts after reload:",
                                        e,
                                    );
                                }
                            }

                            if (
                                (!existingIds ||
                                    !Array.isArray(existingIds) ||
                                    existingIds.length === 0) &&
                                Array.isArray(window._selectedAssociatedPrompts) &&
                                window._selectedAssociatedPrompts.length > 0
                            ) {
                                containerEl.setAttribute(
                                    "data-selected-prompts",
                                    JSON.stringify(
                                        window._selectedAssociatedPrompts.slice(),
                                    ),
                                );
                            } else if (
                                Array.isArray(existingIds) &&
                                Array.isArray(window._selectedAssociatedPrompts) &&
                                window._selectedAssociatedPrompts.length > 0
                            ) {
                                const merged = new Set([
                                    ...(existingIds || []),
                                    ...window._selectedAssociatedPrompts,
                                ]);
                                containerEl.setAttribute(
                                    "data-selected-prompts",
                                    JSON.stringify(Array.from(merged)),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring data-selected-prompts after HTMX reload:",
                            e,
                        );
                    }
                    // Re-initialize the prompt select after content is loaded
                    const pPills = useEditContainers
                        ? "selectedEditPromptsPills"
                        : "selectedPromptsPills";
                    const pWarn = useEditContainers
                        ? "selectedEditPromptsWarning"
                        : "selectedPromptsWarning";
                    const pSelectBtn = useEditContainers
                        ? "selectAllEditPromptsBtn"
                        : "selectAllPromptsBtn";
                    const pClearBtn = useEditContainers
                        ? "clearAllEditPromptsBtn"
                        : "clearAllPromptsBtn";

                    Admin.initPromptSelect(
                        promptsContainerId,
                        pPills,
                        pWarn,
                        6,
                        pSelectBtn,
                        pClearBtn,
                    );
                });
            }
        }
    };

    // ===================================================================
    // ENHANCED GATEWAY TEST FUNCTIONALITY
    // ===================================================================

    Admin.gatewayTestHeadersEditor = null;
    Admin.gatewayTestBodyEditor = null;
    Admin.gatewayTestFormHandler = null;
    Admin.gatewayTestCloseHandler = null;

    Admin.testGateway = async function (gatewayURL) {
        try {
            console.log("Opening gateway test modal for:", gatewayURL);

            // Validate URL
            const urlValidation = Admin.validateUrl(gatewayURL);
            if (!urlValidation.valid) {
                Admin.showErrorMessage(`Invalid gateway URL: ${urlValidation.error}`);
                return;
            }

            // Clean up any existing event listeners first
            Admin.cleanupGatewayTestModal();

            // Open the modal
            Admin.openModal("gateway-test-modal");

            // Initialize CodeMirror editors if they don't exist
            if (!Admin.gatewayTestHeadersEditor) {
                const headersElement = Admin.safeGetElement("gateway-test-headers");
                if (headersElement && window.CodeMirror) {
                    Admin.gatewayTestHeadersEditor = window.CodeMirror.fromTextArea(
                        headersElement,
                        {
                            mode: "application/json",
                            lineNumbers: true,
                            lineWrapping: true,
                        },
                    );
                    Admin.gatewayTestHeadersEditor.setSize(null, 100);
                    console.log("✓ Initialized gateway test headers editor");
                }
            }

            if (!Admin.gatewayTestBodyEditor) {
                const bodyElement = Admin.safeGetElement("gateway-test-body");
                if (bodyElement && window.CodeMirror) {
                    Admin.gatewayTestBodyEditor = window.CodeMirror.fromTextArea(
                        bodyElement,
                        {
                            mode: "application/json",
                            lineNumbers: true,
                            lineWrapping: true,
                        },
                    );
                    Admin.gatewayTestBodyEditor.setSize(null, 100);
                    console.log("✓ Initialized gateway test body editor");
                }
            }

            // Set form action and URL
            const form = Admin.safeGetElement("gateway-test-form");
            const urlInput = Admin.safeGetElement("gateway-test-url");

            if (form) {
                form.action = `${window.ROOT_PATH}/admin/gateways/test`;
            }
            if (urlInput) {
                urlInput.value = urlValidation.value;
            }

            // Set up form submission handler
            if (form) {
                Admin.gatewayTestFormHandler = async (e) => {
                    await Admin.handleGatewayTestSubmit(e);
                };
                form.addEventListener("submit", Admin.gatewayTestFormHandler);
            }

            // Set up close button handler
            const closeButton = Admin.safeGetElement("gateway-test-close");
            if (closeButton) {
                Admin.gatewayTestCloseHandler = () => {
                    Admin.handleGatewayTestClose();
                };
                closeButton.addEventListener("click", Admin.gatewayTestCloseHandler);
            }
        } catch (error) {
            console.error("Error setting up gateway test modal:", error);
            Admin.showErrorMessage("Failed to open gateway test modal");
        }
    }

    Admin.handleGatewayTestSubmit = async function (e) {
        e.preventDefault();

        const loading = Admin.safeGetElement("gateway-test-loading");
        const responseDiv = Admin.safeGetElement("gateway-test-response-json");
        const resultDiv = Admin.safeGetElement("gateway-test-result");
        const testButton = Admin.safeGetElement("gateway-test-submit");

        try {
            // Show loading
            if (loading) {
                loading.classList.remove("hidden");
            }
            if (resultDiv) {
                resultDiv.classList.add("hidden");
            }
            if (testButton) {
                testButton.disabled = true;
                testButton.textContent = "Testing...";
            }

            const form = e.target;
            const url = form.action;

            // Get form data with validation
            const formData = new FormData(form);
            const baseUrl = formData.get("url");
            const method = formData.get("method");
            const path = formData.get("path");
            const contentType = formData.get("content_type") || "application/json";

            // Validate URL
            const urlValidation = Admin.validateUrl(baseUrl);
            if (!urlValidation.valid) {
                throw new Error(`Invalid URL: ${urlValidation.error}`);
            }

            // Get CodeMirror content safely
            let headersRaw = "";
            let bodyRaw = "";

            if (Admin.gatewayTestHeadersEditor) {
                try {
                    headersRaw = Admin.gatewayTestHeadersEditor.getValue() || "";
                } catch (error) {
                    console.error("Error getting headers value:", error);
                }
            }

            if (Admin.gatewayTestBodyEditor) {
                try {
                    bodyRaw = Admin.gatewayTestBodyEditor.getValue() || "";
                } catch (error) {
                    console.error("Error getting body value:", error);
                }
            }

            // Validate and parse JSON safely
            const headersValidation = Admin.validateJson(headersRaw, "Headers");
            const bodyValidation = Admin.validateJson(bodyRaw, "Body");

            if (!headersValidation.valid) {
                throw new Error(headersValidation.error);
            }

            if (!bodyValidation.valid) {
                throw new Error(bodyValidation.error);
            }

            // Process body based on content type
            let processedBody = bodyValidation.value;
            if (
                contentType === "application/x-www-form-urlencoded" &&
                bodyValidation.value &&
                typeof bodyValidation.value === "object"
            ) {
                // Convert JSON object to URL-encoded string
                const params = new URLSearchParams();
                Object.entries(bodyValidation.value).forEach(([key, value]) => {
                    params.append(key, String(value));
                });
                processedBody = params.toString();
            }

            const payload = {
                base_url: urlValidation.value,
                method,
                path,
                headers: headersValidation.value,
                body: processedBody,
                content_type: contentType,
            };

            // Make the request with timeout
            const response = await Admin.fetchWithTimeout(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const result = await response.json();

            const isSuccess =
                result.statusCode &&
                result.statusCode >= 200 &&
                result.statusCode < 300;

            const alertType = isSuccess ? "success" : "error";
            const icon = isSuccess ? "✅" : "❌";
            const title = isSuccess ? "Connection Successful" : "Connection Failed";
            const statusCode = result.statusCode || "Unknown";
            const latency =
                result.latencyMs != null ? `${result.latencyMs}ms` : "NA";
            const body = result.body
                ? `<details open>
                    <summary class='cursor-pointer'><strong>Response Body</strong></summary>
                    <pre class="text-sm px-4 max-h-96 dark:bg-gray-800 dark:text-gray-100 overflow-auto">${JSON.stringify(result.body, null, 2)}</pre>
                </details>`
                : "";

            responseDiv.innerHTML = `
            <div class="alert alert-${alertType}">
                <h4><strong>${icon} ${title}</strong></h4>
                <p><strong>Status Code:</strong> ${statusCode}</p>
                <p><strong>Response Time:</strong> ${latency}</p>
                ${body}
            </div>
            `;
        } catch (error) {
            console.error("Gateway test error:", error);
            if (responseDiv) {
                const errorDiv = document.createElement("div");
                errorDiv.className = "text-red-600 p-4";
                errorDiv.textContent = `❌ Error: ${error.message}`;
                responseDiv.innerHTML = "";
                responseDiv.appendChild(errorDiv);
            }
        } finally {
            if (loading) {
                loading.classList.add("hidden");
            }
            if (resultDiv) {
                resultDiv.classList.remove("hidden");
            }

            testButton.disabled = false;
            testButton.textContent = "Test";
        }
    }

    Admin.handleGatewayTestClose = function () {
        try {
            // Reset form
            const form = Admin.safeGetElement("gateway-test-form");
            if (form) {
                form.reset();
            }

            // Clear editors
            if (Admin.gatewayTestHeadersEditor) {
                try {
                    Admin.gatewayTestHeadersEditor.setValue("");
                } catch (error) {
                    console.error("Error clearing headers editor:", error);
                }
            }

            if (Admin.gatewayTestBodyEditor) {
                try {
                    Admin.gatewayTestBodyEditor.setValue("");
                } catch (error) {
                    console.error("Error clearing body editor:", error);
                }
            }

            // Clear response
            const responseDiv = Admin.safeGetElement("gateway-test-response-json");
            const resultDiv = Admin.safeGetElement("gateway-test-result");

            if (responseDiv) {
                responseDiv.innerHTML = "";
            }
            if (resultDiv) {
                resultDiv.classList.add("hidden");
            }

            // Close modal
            Admin.closeModal("gateway-test-modal");
        } catch (error) {
            console.error("Error closing gateway test modal:", error);
        }
    }

    Admin.cleanupGatewayTestModal = function () {
        try {
            const form = Admin.safeGetElement("gateway-test-form");
            const closeButton = Admin.safeGetElement("gateway-test-close");

            // Remove existing event listeners
            if (form && Admin.gatewayTestFormHandler) {
                form.removeEventListener("submit", Admin.gatewayTestFormHandler);
                Admin.gatewayTestFormHandler = null;
            }

            if (closeButton && Admin.gatewayTestCloseHandler) {
                closeButton.removeEventListener("click", Admin.gatewayTestCloseHandler);
                Admin.gatewayTestCloseHandler = null;
            }

            console.log("✓ Cleaned up gateway test modal listeners");
        } catch (error) {
            console.error("Error cleaning up gateway test modal:", error);
        }
    }

    // ===================================================================
    // ENHANCED FORM HANDLERS with Input Validation
    // ===================================================================

    Admin.handleGatewayFormSubmit = async function (e) {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);
        const status = Admin.safeGetElement("status-gateways");
        const loading = Admin.safeGetElement("add-gateway-loading");

        try {
            // Validate form inputs
            const name = formData.get("name");
            const url = formData.get("url");

            const nameValidation = Admin.validateInputName(name, "gateway");
            const urlValidation = Admin.validateUrl(url);

            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (!urlValidation.valid) {
                throw new Error(urlValidation.error);
            }

            if (loading) {
                loading.style.display = "block";
            }
            if (status) {
                status.textContent = "";
                status.classList.remove("error-status");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("gateways");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            // Process passthrough headers - convert comma-separated string to array
            const passthroughHeadersString = formData.get("passthrough_headers");
            if (passthroughHeadersString && passthroughHeadersString.trim()) {
                // Split by comma and clean up each header name
                const passthroughHeaders = passthroughHeadersString
                    .split(",")
                    .map((header) => header.trim())
                    .filter((header) => header.length > 0);

                // Validate each header name
                for (const headerName of passthroughHeaders) {
                    if (!Admin.HEADER_NAME_REGEX.test(headerName)) {
                        Admin.showErrorMessage(
                            `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                        );
                        return;
                    }
                }

                // Remove the original string and add as JSON array
                formData.delete("passthrough_headers");
                formData.append(
                    "passthrough_headers",
                    JSON.stringify(passthroughHeaders),
                );
            }

            // Handle auth_headers JSON field
            const authHeadersJson = formData.get("auth_headers");
            if (authHeadersJson) {
                try {
                    const authHeaders = JSON.parse(authHeadersJson);
                    if (Array.isArray(authHeaders) && authHeaders.length > 0) {
                        // Remove the JSON string and add as parsed data for backend processing
                        formData.delete("auth_headers");
                        formData.append(
                            "auth_headers",
                            JSON.stringify(authHeaders),
                        );
                    }
                } catch (e) {
                    console.error("Invalid auth_headers JSON:", e);
                }
            }

            // Handle OAuth configuration
            // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
            // The backend assembles individual form fields into oauth_config with proper field names
            // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
            //
            // Leaving this commented for reference:
            // const authType = formData.get("auth_type");
            // if (authType === "oauth") {
            //     ... backend handles this now ...
            // }
            const authType = formData.get("auth_type");
            if (authType !== "oauth") {
                formData.set("oauth_grant_type", "");
            }

            formData.append("visibility", formData.get("visibility"));

            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);

            const response = await fetch(`${window.ROOT_PATH}/admin/gateways`, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();

            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add gateway");
            } else {
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );
                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }

                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#gateways`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Error:", error);
            if (status) {
                status.textContent = error.message || "An error occurred!";
                status.classList.add("error-status");
            }
            Admin.showErrorMessage(error.message);
        } finally {
            if (loading) {
                loading.style.display = "none";
            }
        }
    }
    Admin.handleResourceFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        const status = Admin.safeGetElement("status-resources");
        const loading = Admin.safeGetElement("add-resource-loading");
        try {
            // Validate inputs
            const name = formData.get("name");
            const uri = formData.get("uri");
            let template = null;
            // Check if URI contains '{' and '}'
            if (uri && uri.includes("{") && uri.includes("}")) {
                template = uri;
                // append uri_template only when uri is a templatized resource
                formData.append("uri_template", template);
            }

            const nameValidation = Admin.validateInputName(name, "resource");
            const uriValidation = Admin.validateInputName(uri, "resource URI");

            if (!nameValidation.valid) {
                Admin.showErrorMessage(nameValidation.error);
                return;
            }

            if (!uriValidation.valid) {
                Admin.showErrorMessage(uriValidation.error);
                return;
            }

            if (loading) {
                loading.style.display = "block";
            }
            if (status) {
                status.textContent = "";
                status.classList.remove("error-status");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("resources");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            formData.append("visibility", formData.get("visibility"));
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);
            const response = await fetch(`${window.ROOT_PATH}/admin/resources`, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add Resource");
            } else {
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }
                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#resources`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Error:", error);
            if (status) {
                status.textContent = error.message || "An error occurred!";
                status.classList.add("error-status");
            }
            Admin.showErrorMessage(error.message);
        } finally {
            // location.reload();
            if (loading) {
                loading.style.display = "none";
            }
        }
    }

    Admin.handlePromptFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        const status = Admin.safeGetElement("status-prompts");
        const loading = Admin.safeGetElement("add-prompts-loading");
        try {
            // Validate inputs
            const name = formData.get("name");
            const nameValidation = Admin.validateInputName(name, "prompt");

            if (!nameValidation.valid) {
                Admin.showErrorMessage(nameValidation.error);
                return;
            }

            if (loading) {
                loading.style.display = "block";
            }
            if (status) {
                status.textContent = "";
                status.classList.remove("error-status");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("prompts");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            formData.append("visibility", formData.get("visibility"));
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);
            const response = await fetch(`${window.ROOT_PATH}/admin/prompts`, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add prompt");
            }

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#prompts`;
            window.location.href = redirectUrl;
        } catch (error) {
            console.error("Error:", error);
            if (status) {
                status.textContent = error.message || "An error occurred!";
                status.classList.add("error-status");
            }
            Admin.showErrorMessage(error.message);
        } finally {
            // location.reload();
            if (loading) {
                loading.style.display = "none";
            }
        }
    }

    Admin.handleEditPromptFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;

        const formData = new FormData(form);
        // Add team_id from URL if present (like handleEditToolFormSubmit)
        const teamId = new URL(window.location.href).searchParams.get("team_id");
        if (teamId) {
            formData.set("team_id", teamId);
        }

        try {
            // Validate inputs
            const name = formData.get("name");
            const nameValidation = Admin.validateInputName(name, "prompt");
            if (!nameValidation.valid) {
                Admin.showErrorMessage(nameValidation.error);
                return;
            }

            // Save CodeMirror editors' contents if present
            if (window.promptToolHeadersEditor) {
                window.promptToolHeadersEditor.save();
            }
            if (window.promptToolSchemaEditor) {
                window.promptToolSchemaEditor.save();
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("prompts");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
            });

            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit Prompt");
            }
            // Only redirect on success
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#prompts`;
            window.location.href = redirectUrl;
        } catch (error) {
            console.error("Error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    Admin.handleServerFormSubmit = async function (e) {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);
        const status = Admin.safeGetElement("serverFormError");
        const loading = Admin.safeGetElement("add-server-loading"); // Add a loading spinner if needed

        try {
            const name = formData.get("name");

            // Basic validation
            const nameValidation = Admin.validateInputName(name, "server");
            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (loading) {
                loading.style.display = "block";
            }

            if (status) {
                status.textContent = "";
                status.classList.remove("error-status");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("servers");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            formData.append("visibility", formData.get("visibility"));
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);

            const response = await fetch(`${window.ROOT_PATH}/admin/servers`, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add server.");
            } else {
                // Success redirect
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }

                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#catalog`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Add Server Error:", error);
            if (status) {
                status.textContent = error.message || "An error occurred.";
                status.classList.add("error-status");
            }
            Admin.showErrorMessage(error.message); // Optional if you use global popup/snackbar
        } finally {
            if (loading) {
                loading.style.display = "none";
            }
        }
    }

    // Handle Add A2A Form Submit
    Admin.handleA2AFormSubmit = async function (e) {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);
        const status = Admin.safeGetElement("a2aFormError");
        const loading = Admin.safeGetElement("add-a2a-loading");

        try {
            // Basic validation
            const name = formData.get("name");
            const nameValidation = Admin.validateInputName(name, "A2A Agent");
            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (loading) {
                loading.style.display = "block";
            }
            if (status) {
                status.textContent = "";
                status.classList.remove("error-status");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("a2a-agents");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            // Process passthrough headers - convert comma-separated string to array
            const passthroughHeadersString = formData.get("passthrough_headers");
            if (passthroughHeadersString && passthroughHeadersString.trim()) {
                // Split by comma and clean up each header name
                const passthroughHeaders = passthroughHeadersString
                    .split(",")
                    .map((header) => header.trim())
                    .filter((header) => header.length > 0);

                // Validate each header name
                for (const headerName of passthroughHeaders) {
                    if (!Admin.HEADER_NAME_REGEX.test(headerName)) {
                        Admin.showErrorMessage(
                            `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                        );
                        return;
                    }
                }

                // Remove the original string and add as JSON array
                formData.delete("passthrough_headers");
                formData.append(
                    "passthrough_headers",
                    JSON.stringify(passthroughHeaders),
                );
            }

            // Handle auth_headers JSON field
            const authHeadersJson = formData.get("auth_headers");
            if (authHeadersJson) {
                try {
                    const authHeaders = JSON.parse(authHeadersJson);
                    if (Array.isArray(authHeaders) && authHeaders.length > 0) {
                        // Remove the JSON string and add as parsed data for backend processing
                        formData.delete("auth_headers");
                        formData.append(
                            "auth_headers",
                            JSON.stringify(authHeaders),
                        );
                    }
                } catch (e) {
                    console.error("Invalid auth_headers JSON:", e);
                }
            }

            const authType = formData.get("auth_type");
            if (authType !== "oauth") {
                formData.set("oauth_grant_type", "");
            }

            // ✅ Ensure visibility is captured from checked radio button
            // formData.set("visibility", visibility);
            formData.append("visibility", formData.get("visibility"));
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);

            // Submit to backend
            // specifically log agentType only
            console.log("agentType:", formData.get("agentType"));

            const response = await fetch(`${window.ROOT_PATH}/admin/a2a`, {
                method: "POST",
                body: formData,
            });

            const result = await response.json();

            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add A2A Agent.");
            } else {
                // Success redirect
                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }

                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#a2a-agents`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Add A2A Agent Error:", error);
            if (status) {
                status.textContent = error.message || "An error occurred.";
                status.classList.add("error-status");
            }
            Admin.showErrorMessage(error.message); // global popup/snackbar if available
        } finally {
            if (loading) {
                loading.style.display = "none";
            }
        }
    }

    Admin.handleToolFormSubmit = async function (event) {
        event.preventDefault();

        try {
            const form = event.target;
            const formData = new FormData(form);

            // Validate form inputs
            const name = formData.get("name");
            const url = formData.get("url");

            const nameValidation = Admin.validateInputName(name, "tool");
            const urlValidation = Admin.validateUrl(url);

            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (!urlValidation.valid) {
                throw new Error(urlValidation.error);
            }

            // If in UI mode, update schemaEditor with generated schema
            const mode = document.querySelector(
                'input[name="schema_input_mode"]:checked',
            );
            if (mode && mode.value === "ui") {
                if (window.schemaEditor) {
                    const generatedSchema = Admin.generateSchema();
                    const schemaValidation = Admin.validateJson(
                        generatedSchema,
                        "Generated Schema",
                    );
                    if (!schemaValidation.valid) {
                        throw new Error(schemaValidation.error);
                    }
                    window.schemaEditor.setValue(generatedSchema);
                }
            }

            // Save CodeMirror editors' contents
            if (window.headersEditor) {
                window.headersEditor.save();
            }
            if (window.schemaEditor) {
                window.schemaEditor.save();
            }
            if (window.outputSchemaEditor) {
                window.outputSchemaEditor.save();
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("tools");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            formData.append("visibility", formData.get("visibility"));
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );
            teamId && formData.append("team_id", teamId);

            const response = await fetch(`${window.ROOT_PATH}/admin/tools`, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to add tool");
            } else {
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }
                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#tools`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Fetch error:", error);
            Admin.showErrorMessage(error.message);
        }
    }
    Admin.handleEditToolFormSubmit = async function (event) {
        event.preventDefault();

        const form = event.target;

        try {
            const formData = new FormData(form);

            // Basic validation (customize as needed)
            const name = formData.get("name");
            const url = formData.get("url");
            const nameValidation = Admin.validateInputName(name, "tool");
            const urlValidation = Admin.validateUrl(url);

            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }
            if (!urlValidation.valid) {
                throw new Error(urlValidation.error);
            }

            // // Save CodeMirror editors' contents if present

            if (window.editToolHeadersEditor) {
                window.editToolHeadersEditor.save();
            }
            if (window.editToolSchemaEditor) {
                window.editToolSchemaEditor.save();
            }
            if (window.editToolOutputSchemaEditor) {
                window.editToolOutputSchemaEditor.save();
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("tools");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });

            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit tool");
            } else {
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }
                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#tools`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Fetch error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    // Handle Gateway Edit Form
    Admin.handleEditGatewayFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        try {
            // Validate form inputs
            const name = formData.get("name");
            const url = formData.get("url");

            const nameValidation = Admin.validateInputName(name, "gateway");
            const urlValidation = Admin.validateUrl(url);

            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (!urlValidation.valid) {
                throw new Error(urlValidation.error);
            }

            // Handle passthrough headers
            const passthroughHeadersString =
                formData.get("passthrough_headers") || "";
            const passthroughHeaders = passthroughHeadersString
                .split(",")
                .map((header) => header.trim())
                .filter((header) => header.length > 0);

            // Validate each header name
            for (const headerName of passthroughHeaders) {
                if (headerName && !Admin.HEADER_NAME_REGEX.test(headerName)) {
                    Admin.showErrorMessage(
                        `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                    );
                    return;
                }
            }

            formData.append(
                "passthrough_headers",
                JSON.stringify(passthroughHeaders),
            );

            // Handle OAuth configuration
            // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
            // The backend assembles individual form fields into oauth_config with proper field names
            // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
            //
            // Leaving this commented for reference:
            // const authType = formData.get("auth_type");
            // if (authType === "oauth") {
            //     ... backend handles this now ...
            // }
            const authType = formData.get("auth_type");
            if (authType !== "oauth") {
                formData.set("oauth_grant_type", "");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("gateways");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit gateway");
            }
            // Only redirect on success
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#gateways`;
            window.location.href = redirectUrl;
        } catch (error) {
            console.error("Error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    // Handle A2A Agent Edit Form
    Admin.handleEditA2AAgentFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);

        console.log("Edit A2A Agent Form Details: ");
        console.log(
            JSON.stringify(Object.fromEntries(formData.entries()), null, 2),
        );

        try {
            // Validate form inputs
            const name = formData.get("name");
            const url = formData.get("endpoint_url");
            console.log("Original A2A URL: ", url);
            const nameValidation = Admin.validateInputName(name, "a2a_agent");
            const urlValidation = Admin.validateUrl(url);

            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            if (!urlValidation.valid) {
                throw new Error(urlValidation.error);
            }

            // Handle passthrough headers
            const passthroughHeadersString =
                formData.get("passthrough_headers") || "";
            const passthroughHeaders = passthroughHeadersString
                .split(",")
                .map((header) => header.trim())
                .filter((header) => header.length > 0);

            // Validate each header name
            for (const headerName of passthroughHeaders) {
                if (headerName && !Admin.HEADER_NAME_REGEX.test(headerName)) {
                    Admin.showErrorMessage(
                        `Invalid passthrough header name: "${headerName}". Only letters, numbers, and hyphens are allowed.`,
                    );
                    return;
                }
            }

            formData.append(
                "passthrough_headers",
                JSON.stringify(passthroughHeaders),
            );

            // Handle OAuth configuration
            // NOTE: OAuth config assembly is now handled by the backend (mcpgateway/admin.py)
            // The backend assembles individual form fields into oauth_config with proper field names
            // and supports DCR (Dynamic Client Registration) when client_id/client_secret are empty
            //
            // Leaving this commented for reference:
            // const authType = formData.get("auth_type");
            // if (authType === "oauth") {
            //     ... backend handles this now ...
            // }

            const authType = formData.get("auth_type");
            if (authType !== "oauth") {
                formData.set("oauth_grant_type", "");
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("a2a-agents");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit a2a agent");
            }
            // Only redirect on success
            const teamId = new URL(window.location.href).searchParams.get(
                "team_id",
            );

            const searchParams = new URLSearchParams();
            if (isInactiveCheckedBool) {
                searchParams.set("include_inactive", "true");
            }
            if (teamId) {
                searchParams.set("team_id", teamId);
            }
            const queryString = searchParams.toString();
            const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#a2a-agents`;
            window.location.href = redirectUrl;
        } catch (error) {
            console.error("Error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    Admin.handleEditServerFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);

        try {
            // Validate inputs
            const name = formData.get("name");
            const nameValidation = Admin.validateInputName(name, "server");
            if (!nameValidation.valid) {
                throw new Error(nameValidation.error);
            }

            // Save CodeMirror editors' contents if present
            if (window.promptToolHeadersEditor) {
                window.promptToolHeadersEditor.save();
            }
            if (window.promptToolSchemaEditor) {
                window.promptToolSchemaEditor.save();
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("servers");
            formData.append("is_inactive_checked", isInactiveCheckedBool);

            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
            });
            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit server");
            }
            // Only redirect on success
            else {
                // Redirect to the appropriate page based on inactivity checkbox
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }
                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#catalog`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    Admin.handleEditResFormSubmit = async function (e) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);

        try {
            // Validate inputs
            const name = formData.get("name");
            const uri = formData.get("uri");
            let template = null;
            // Check if URI contains '{' and '}'
            if (uri && uri.includes("{") && uri.includes("}")) {
                template = uri;
            }
            formData.append("uri_template", template);
            const nameValidation = Admin.validateInputName(name, "resource");
            const uriValidation = Admin.validateInputName(uri, "resource URI");

            if (!nameValidation.valid) {
                Admin.showErrorMessage(nameValidation.error);
                return;
            }

            if (!uriValidation.valid) {
                Admin.showErrorMessage(uriValidation.error);
                return;
            }

            // Save CodeMirror editors' contents if present
            if (window.promptToolHeadersEditor) {
                window.promptToolHeadersEditor.save();
            }
            if (window.promptToolSchemaEditor) {
                window.promptToolSchemaEditor.save();
            }

            const isInactiveCheckedBool = Admin.isInactiveChecked("resources");
            formData.append("is_inactive_checked", isInactiveCheckedBool);
            // Submit via fetch
            const response = await fetch(form.action, {
                method: "POST",
                body: formData,
            });

            const result = await response.json();
            if (!result || !result.success) {
                throw new Error(result?.message || "Failed to edit resource");
            }
            // Only redirect on success
            else {
                // Redirect to the appropriate page based on inactivity checkbox
                const teamId = new URL(window.location.href).searchParams.get(
                    "team_id",
                );

                const searchParams = new URLSearchParams();
                if (isInactiveCheckedBool) {
                    searchParams.set("include_inactive", "true");
                }
                if (teamId) {
                    searchParams.set("team_id", teamId);
                }
                const queryString = searchParams.toString();
                const redirectUrl = `${window.ROOT_PATH}/admin${queryString ? `?${queryString}` : ""}#resources`;
                window.location.href = redirectUrl;
            }
        } catch (error) {
            console.error("Error:", error);
            Admin.showErrorMessage(error.message);
        }
    }

    // ===================================================================
    // ENHANCED FORM VALIDATION for All Forms
    // ===================================================================

    Admin.setupFormValidation = function () {
        // Add validation to all forms on the page
        const forms = document.querySelectorAll("form");

        forms.forEach((form) => {
            // Add validation to name fields
            const nameFields = form.querySelectorAll(
                'input[name*="name"], input[name*="Name"]',
            );
            nameFields.forEach((field) => {
                field.addEventListener("blur", function () {
                    const parentNode = this.parentNode;
                    const inputLabel = parentNode?.querySelector(
                        `label[for="${this.id}"]`,
                    );
                    const errorMessageElement = parentNode?.querySelector(
                        'p[data-error-message-for="name"]',
                    );
                    const validation = Admin.validateInputName(
                        this.value,
                        inputLabel?.innerText,
                    );
                    if (!validation.valid) {
                        this.setCustomValidity(validation.error);
                        this.classList.add(
                            "border-red-500",
                            "focus:ring-red-500",
                            "dark:border-red-500",
                            "dark:ring-red-500",
                        );
                        if (errorMessageElement) {
                            errorMessageElement.innerText = validation.error;
                            errorMessageElement.classList.remove("invisible");
                        }
                    } else {
                        this.setCustomValidity("");
                        this.value = validation.value;
                        this.classList.remove(
                            "border-red-500",
                            "focus:ring-red-500",
                            "dark:border-red-500",
                            "dark:ring-red-500",
                        );
                        if (errorMessageElement) {
                            errorMessageElement.classList.add("invisible");
                        }
                    }
                });
            });

            // Add validation to URL fields
            const urlFields = form.querySelectorAll(
                'input[name*="url"], input[name*="URL"]',
            );
            urlFields.forEach((field) => {
                field.addEventListener("blur", function () {
                    // Skip validation for empty optional URL fields
                    if (!this.value && !this.required) {
                        this.setCustomValidity("");
                        this.classList.remove(
                            "border-red-500",
                            "focus:ring-red-500",
                            "dark:border-red-500",
                            "dark:ring-red-500",
                        );
                        const errorMessageElement = this.parentNode?.querySelector(
                            'p[data-error-message-for="url"]',
                        );
                        if (errorMessageElement) {
                            errorMessageElement.classList.add("invisible");
                        }
                        return;
                    }
                    const parentNode = this.parentNode;
                    const inputLabel = parentNode?.querySelector(
                        `label[for="${this.id}"]`,
                    );
                    const errorMessageElement = parentNode?.querySelector(
                        'p[data-error-message-for="url"]',
                    );
                    const validation = Admin.validateUrl(
                        this.value,
                        inputLabel?.innerText,
                    );
                    if (!validation.valid) {
                        this.setCustomValidity(validation.error);
                        this.classList.add(
                            "border-red-500",
                            "focus:ring-red-500",
                            "dark:border-red-500",
                            "dark:ring-red-500",
                        );
                        if (errorMessageElement) {
                            errorMessageElement.innerText = validation.error;
                            errorMessageElement.classList.remove("invisible");
                        }
                    } else {
                        this.setCustomValidity("");
                        this.value = validation.value;
                        this.classList.remove(
                            "border-red-500",
                            "focus:ring-red-500",
                            "dark:border-red-500",
                            "dark:ring-red-500",
                        );
                        if (errorMessageElement) {
                            errorMessageElement.classList.add("invisible");
                        }
                    }
                });
            });
        });
    }

    // ===================================================================
    // ENHANCED EDITOR REFRESH with Safety Checks
    // ===================================================================

    Admin.refreshEditors = function () {
        setTimeout(() => {
            if (
                window.headersEditor &&
                typeof window.headersEditor.refresh === "function"
            ) {
                try {
                    window.headersEditor.refresh();
                    console.log("✓ Refreshed headersEditor");
                } catch (error) {
                    console.error("Failed to refresh headersEditor:", error);
                }
            }

            if (
                window.schemaEditor &&
                typeof window.schemaEditor.refresh === "function"
            ) {
                try {
                    window.schemaEditor.refresh();
                    console.log("✓ Refreshed schemaEditor");
                } catch (error) {
                    console.error("Failed to refresh schemaEditor:", error);
                }
            }
        }, 100);
    }

    // ===================================================================
    // Tool Tips for components with Alpine.js
    // ===================================================================

    /* global Alpine, htmx */
    Admin.setupTooltipsWithAlpine = function () {
        document.addEventListener("alpine:init", () => {
            console.log("Initializing Alpine tooltip directive...");

            Alpine.directive("tooltip", (el, { expression }, { evaluate }) => {
                let tooltipEl = null;
                let animationFrameId = null; // Track animation frame

                const moveTooltip = (e) => {
                    if (!tooltipEl) {
                        return;
                    }

                    const paddingX = 12;
                    const paddingY = 20;
                    const tipRect = tooltipEl.getBoundingClientRect();

                    let left = e.clientX + paddingX;
                    let top = e.clientY + paddingY;

                    if (left + tipRect.width > window.innerWidth - 8) {
                        left = e.clientX - tipRect.width - paddingX;
                    }
                    if (top + tipRect.height > window.innerHeight - 8) {
                        top = e.clientY - tipRect.height - paddingY;
                    }

                    tooltipEl.style.left = `${left}px`;
                    tooltipEl.style.top = `${top}px`;
                };

                const showTooltip = (event) => {
                    const text = evaluate(expression);
                    if (!text) {
                        return;
                    }

                    hideTooltip(); // Clean up any existing tooltip

                    tooltipEl = document.createElement("div");
                    tooltipEl.textContent = text;
                    tooltipEl.setAttribute("role", "tooltip");
                    tooltipEl.className =
                        "fixed z-50 max-w-xs px-3 py-2 text-sm text-white bg-black/80 rounded-lg shadow-lg pointer-events-none opacity-0 transition-opacity duration-200";

                    document.body.appendChild(tooltipEl);

                    if (event?.clientX && event?.clientY) {
                        moveTooltip(event);
                        el.addEventListener("mousemove", moveTooltip);
                    } else {
                        const rect = el.getBoundingClientRect();
                        const scrollY = window.scrollY || window.pageYOffset;
                        const scrollX = window.scrollX || window.pageXOffset;
                        tooltipEl.style.left = `${rect.left + scrollX}px`;
                        tooltipEl.style.top = `${rect.bottom + scrollY + 10}px`;
                    }

                    // FIX: Cancel any pending animation frame before setting a new one
                    if (animationFrameId) {
                        cancelAnimationFrame(animationFrameId);
                    }

                    animationFrameId = requestAnimationFrame(() => {
                        // FIX: Check if tooltipEl still exists before accessing its style
                        if (tooltipEl) {
                            tooltipEl.style.opacity = "1";
                        }
                        animationFrameId = null;
                    });

                    window.addEventListener("scroll", hideTooltip, {
                        passive: true,
                    });
                    window.addEventListener("resize", hideTooltip, {
                        passive: true,
                    });
                };

                const hideTooltip = () => {
                    if (!tooltipEl) {
                        return;
                    }

                    // FIX: Cancel any pending animation frame
                    if (animationFrameId) {
                        cancelAnimationFrame(animationFrameId);
                        animationFrameId = null;
                    }

                    tooltipEl.style.opacity = "0";
                    el.removeEventListener("mousemove", moveTooltip);
                    window.removeEventListener("scroll", hideTooltip);
                    window.removeEventListener("resize", hideTooltip);
                    el.removeEventListener("click", hideTooltip);

                    const toRemove = tooltipEl;
                    tooltipEl = null; // Set to null immediately

                    setTimeout(() => {
                        if (toRemove && toRemove.parentNode) {
                            toRemove.parentNode.removeChild(toRemove);
                        }
                    }, 200);
                };

                el.addEventListener("mouseenter", showTooltip);
                el.addEventListener("mouseleave", hideTooltip);
                el.addEventListener("focus", showTooltip);
                el.addEventListener("blur", hideTooltip);
                el.addEventListener("click", hideTooltip);
            });
        });
    }

    Admin.setupTooltipsWithAlpine();

    // ===================================================================
    // SINGLE CONSOLIDATED INITIALIZATION SYSTEM
    // ===================================================================

    // Separate initialization functions
    Admin.initializeCodeMirrorEditors = function () {
        console.log("Initializing CodeMirror editors...");

        const editorConfigs = [
            {
                id: "headers-editor",
                mode: "application/json",
                varName: "headersEditor",
            },
            {
                id: "schema-editor",
                mode: "application/json",
                varName: "schemaEditor",
            },
            {
                id: "resource-content-editor",
                mode: "text/plain",
                varName: "resourceContentEditor",
            },
            {
                id: "prompt-template-editor",
                mode: "text/plain",
                varName: "promptTemplateEditor",
            },
            {
                id: "prompt-args-editor",
                mode: "application/json",
                varName: "promptArgsEditor",
            },
            {
                id: "edit-tool-headers",
                mode: "application/json",
                varName: "editToolHeadersEditor",
            },
            {
                id: "edit-tool-schema",
                mode: "application/json",
                varName: "editToolSchemaEditor",
            },
            {
                id: "output-schema-editor",
                mode: "application/json",
                varName: "outputSchemaEditor",
            },
            {
                id: "edit-tool-output-schema",
                mode: "application/json",
                varName: "editToolOutputSchemaEditor",
            },
            {
                id: "edit-resource-content",
                mode: "text/plain",
                varName: "editResourceContentEditor",
            },
            {
                id: "edit-prompt-template",
                mode: "text/plain",
                varName: "editPromptTemplateEditor",
            },
            {
                id: "edit-prompt-arguments",
                mode: "application/json",
                varName: "editPromptArgumentsEditor",
            },
        ];

        editorConfigs.forEach((config) => {
            const element = Admin.safeGetElement(config.id);
            if (element && window.CodeMirror) {
                try {
                    window[config.varName] = window.CodeMirror.fromTextArea(
                        element,
                        {
                            mode: config.mode,
                            theme: "monokai",
                            lineNumbers: false,
                            autoCloseBrackets: true,
                            matchBrackets: true,
                            tabSize: 2,
                            lineWrapping: true,
                        },
                    );
                    console.log(`✓ Initialized ${config.varName}`);
                } catch (error) {
                    console.error(`Failed to initialize ${config.varName}:`, error);
                }
            } else {
                console.warn(
                    `Element ${config.id} not found or CodeMirror not available`,
                );
            }
        });
    }

    Admin.initializeToolSelects = function () {
        console.log("Initializing tool selects...");

        // Add Server form
        Admin.initToolSelect(
            "associatedTools",
            "selectedToolsPills",
            "selectedToolsWarning",
            6,
            "selectAllToolsBtn",
            "clearAllToolsBtn",
        );

        Admin.initResourceSelect(
            "associatedResources",
            "selectedResourcesPills",
            "selectedResourcesWarning",
            10,
            "selectAllResourcesBtn",
            "clearAllResourcesBtn",
        );

        Admin.initPromptSelect(
            "associatedPrompts",
            "selectedPromptsPills",
            "selectedPromptsWarning",
            8,
            "selectAllPromptsBtn",
            "clearAllPromptsBtn",
        );

        // Edit Server form
        Admin.initToolSelect(
            "edit-server-tools",
            "selectedEditToolsPills",
            "selectedEditToolsWarning",
            6,
            "selectAllEditToolsBtn",
            "clearAllEditToolsBtn",
        );

        // Initialize resource selector
        Admin.initResourceSelect(
            "edit-server-resources",
            "selectedEditResourcesPills",
            "selectedEditResourcesWarning",
            10,
            "selectAllEditResourcesBtn",
            "clearAllEditResourcesBtn",
        );

        // Initialize prompt selector
        Admin.initPromptSelect(
            "edit-server-prompts",
            "selectedEditPromptsPills",
            "selectedEditPromptsWarning",
            8,
            "selectAllEditPromptsBtn",
            "clearAllEditPromptsBtn",
        );
    }

    Admin.initializeEventListeners = function () {
        console.log("🎯 Setting up event listeners...");

        Admin.setupTabNavigation();
        Admin.setupHTMXHooks();
        console.log("✅ HTMX hooks registered");
        Admin.setupAuthenticationToggles();
        Admin.setupFormHandlers();
        Admin.setupSchemaModeHandlers();
        Admin.setupIntegrationTypeHandlers();
        console.log("✅ All event listeners initialized");
    }

    Admin.setupTabNavigation = function () {
        const tabs = [
            "catalog",
            "tools",
            "resources",
            "prompts",
            "gateways",
            "a2a-agents",
            "roots",
            "metrics",
            "plugins",
            "logs",
            "export-import",
            "version-info",
        ];

        const visibleTabs = Admin.isAdminUser()
            ? tabs
            : tabs.filter((tabName) => !Admin.ADMIN_ONLY_TABS.has(tabName));

        visibleTabs.forEach((tabName) => {
            // Suppress warnings for optional tabs that might not be enabled
            const optionalTabs = [
                "roots",
                "metrics",
                "logs",
                "export-import",
                "version-info",
                "plugins",
            ];
            const suppressWarning = optionalTabs.includes(tabName);

            const tabElement = Admin.safeGetElement(`tab-${tabName}`, suppressWarning);
            if (tabElement) {
                tabElement.addEventListener("click", () => Admin.showTab(tabName));
            }
        });
    }

    Admin.setupHTMXHooks = function () {
        document.body.addEventListener("htmx:beforeRequest", (event) => {
            if (event.detail.elt.id === "tab-version-info") {
                console.log("HTMX: Sending request for version info partial");
            }
        });

        document.body.addEventListener("htmx:afterSwap", (event) => {
            if (event.detail.target.id === "version-info-panel") {
                console.log("HTMX: Content swapped into version-info-panel");
            }
        });
    }

    Admin.setupAuthenticationToggles = function () {
        const authHandlers = [
            {
                id: "auth-type",
                basicId: "auth-basic-fields",
                bearerId: "auth-bearer-fields",
                headersId: "auth-headers-fields",
            },

            // Gateway Add Form auth fields

            {
                id: "auth-type-gw",
                basicId: "auth-basic-fields-gw",
                bearerId: "auth-bearer-fields-gw",
                headersId: "auth-headers-fields-gw",
                queryParamId: "auth-query_param-fields-gw",
            },

            // A2A Add Form auth fields

            {
                id: "auth-type-a2a",
                basicId: "auth-basic-fields-a2a",
                bearerId: "auth-bearer-fields-a2a",
                headersId: "auth-headers-fields-a2a",
                queryParamId: "auth-query_param-fields-a2a",
            },

            // Gateway Edit Form auth fields

            {
                id: "auth-type-gw-edit",
                basicId: "auth-basic-fields-gw-edit",
                bearerId: "auth-bearer-fields-gw-edit",
                headersId: "auth-headers-fields-gw-edit",
                oauthId: "auth-oauth-fields-gw-edit",
                queryParamId: "auth-query_param-fields-gw-edit",
            },

            // A2A Edit Form auth fields

            {
                id: "auth-type-a2a-edit",
                basicId: "auth-basic-fields-a2a-edit",
                bearerId: "auth-bearer-fields-a2a-edit",
                headersId: "auth-headers-fields-a2a-edit",
                oauthId: "auth-oauth-fields-a2a-edit",
                queryParamId: "auth-query_param-fields-a2a-edit",
            },

            {
                id: "edit-auth-type",
                basicId: "edit-auth-basic-fields",
                bearerId: "edit-auth-bearer-fields",
                headersId: "edit-auth-headers-fields",
            },
        ];

        authHandlers.forEach((handler) => {
            const element = Admin.safeGetElement(handler.id);
            if (element) {
                element.addEventListener("change", function () {
                    const basicFields = Admin.safeGetElement(handler.basicId);
                    const bearerFields = Admin.safeGetElement(handler.bearerId);
                    const headersFields = Admin.safeGetElement(handler.headersId);
                    const oauthFields = handler.oauthId
                        ? Admin.safeGetElement(handler.oauthId)
                        : null;
                    const queryParamFields = handler.queryParamId
                        ? Admin.safeGetElement(handler.queryParamId)
                        : null;
                    Admin.handleAuthTypeSelection(
                        this.value,
                        basicFields,
                        bearerFields,
                        headersFields,
                        oauthFields,
                        queryParamFields,
                    );
                });
            }
        });
    }

    Admin.setupFormHandlers = function () {
        const gatewayForm = Admin.safeGetElement("add-gateway-form");
        if (gatewayForm) {
            gatewayForm.addEventListener("submit", Admin.handleGatewayFormSubmit);

            // Add OAuth authentication type change handler
            const authTypeField = Admin.safeGetElement("auth-type-gw");
            if (authTypeField) {
                authTypeField.addEventListener("change", Admin.handleAuthTypeChange);
            }

            // Add OAuth grant type change handler for Gateway
            const oauthGrantTypeField = Admin.safeGetElement("oauth-grant-type-gw");
            if (oauthGrantTypeField) {
                oauthGrantTypeField.addEventListener(
                    "change",
                    Admin.handleOAuthGrantTypeChange,
                );
            }
        }

        // Add A2A Form
        const a2aForm = Admin.safeGetElement("add-a2a-form");

        if (a2aForm) {
            a2aForm.addEventListener("submit", Admin.handleA2AFormSubmit);

            // Add OAuth authentication type change handler
            const authTypeField = Admin.safeGetElement("auth-type-a2a");
            if (authTypeField) {
                authTypeField.addEventListener("change", Admin.handleAuthTypeChange);
            }

            const oauthGrantTypeField = Admin.safeGetElement("oauth-grant-type-a2a");
            if (oauthGrantTypeField) {
                oauthGrantTypeField.addEventListener(
                    "change",
                    Admin.handleOAuthGrantTypeChange,
                );
            }
        }

        const resourceForm = Admin.safeGetElement("add-resource-form");
        if (resourceForm) {
            resourceForm.addEventListener("submit", Admin.handleResourceFormSubmit);
        }

        const promptForm = Admin.safeGetElement("add-prompt-form");
        if (promptForm) {
            promptForm.addEventListener("submit", Admin.handlePromptFormSubmit);
        }

        const editPromptForm = Admin.safeGetElement("edit-prompt-form");
        if (editPromptForm) {
            editPromptForm.addEventListener("submit", Admin.handleEditPromptFormSubmit);
            editPromptForm.addEventListener("click", () => {
                if (getComputedStyle(editPromptForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        // Add OAuth grant type change handler for Edit Gateway modal
        // Checkpoint commented
        /*
        const editOAuthGrantTypeField = Admin.safeGetElement("oauth-grant-type-gw-edit");
        if (editOAuthGrantTypeField) {
            editOAuthGrantTypeField.addEventListener(
                "change",
                Admin.handleEditOAuthGrantTypeChange,
            );
        }

        */

        // Checkpoint Started
        ["oauth-grant-type-gw-edit", "oauth-grant-type-a2a-edit"].forEach((id) => {
            const field = Admin.safeGetElement(id);
            if (field) {
                field.addEventListener("change", Admin.handleEditOAuthGrantTypeChange);
            }
        });
        // Checkpoint Ended

        const toolForm = Admin.safeGetElement("add-tool-form");
        if (toolForm) {
            toolForm.addEventListener("submit", Admin.handleToolFormSubmit);
            toolForm.addEventListener("click", () => {
                if (getComputedStyle(toolForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        const paramButton = Admin.safeGetElement("add-parameter-btn");
        if (paramButton) {
            paramButton.addEventListener("click", Admin.handleAddParameter);
        }

        const passthroughButton = Admin.safeGetElement("add-passthrough-btn");
        if (passthroughButton) {
            passthroughButton.addEventListener("click", Admin.handleAddPassthrough);
        }

        const serverForm = Admin.safeGetElement("add-server-form");
        if (serverForm) {
            serverForm.addEventListener("submit", Admin.handleServerFormSubmit);
        }

        const editServerForm = Admin.safeGetElement("edit-server-form");
        if (editServerForm) {
            editServerForm.addEventListener("submit", Admin.handleEditServerFormSubmit);
            editServerForm.addEventListener("click", () => {
                if (getComputedStyle(editServerForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        const editResourceForm = Admin.safeGetElement("edit-resource-form");
        if (editResourceForm) {
            editResourceForm.addEventListener("submit", Admin.handleEditResFormSubmit);
            editResourceForm.addEventListener("click", () => {
                if (getComputedStyle(editResourceForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        const editToolForm = Admin.safeGetElement("edit-tool-form");
        if (editToolForm) {
            editToolForm.addEventListener("submit", Admin.handleEditToolFormSubmit);
            editToolForm.addEventListener("click", () => {
                if (getComputedStyle(editToolForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        const editGatewayForm = Admin.safeGetElement("edit-gateway-form");
        if (editGatewayForm) {
            editGatewayForm.addEventListener("submit", Admin.handleEditGatewayFormSubmit);
            editGatewayForm.addEventListener("click", () => {
                if (getComputedStyle(editGatewayForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        const editA2AAgentForm = Admin.safeGetElement("edit-a2a-agent-form");
        if (editA2AAgentForm) {
            editA2AAgentForm.addEventListener(
                "submit",
                Admin.handleEditA2AAgentFormSubmit,
            );
            editA2AAgentForm.addEventListener("click", () => {
                if (getComputedStyle(editA2AAgentForm).display !== "none") {
                    Admin.refreshEditors();
                }
            });
        }

        // Setup search functionality for selectors
        Admin.setupSelectorSearch();
    }

    /**
    * Setup search functionality for multi-select dropdowns
    */
    Admin.setupSelectorSearch = function () {
        // Tools search - server-side search
        const searchTools = Admin.safeGetElement("searchTools", true);
        if (searchTools) {
            let searchTimeout;
            searchTools.addEventListener("input", function () {
                const searchTerm = this.value;

                // Clear previous timeout
                if (searchTimeout) {
                    clearTimeout(searchTimeout);
                }

                // Debounce search to avoid too many API calls
                searchTimeout = setTimeout(() => {
                    Admin.serverSideToolSearch(searchTerm);
                }, 300);
            });
        }

        // Edit-server tools search (server-side, mirror of searchTools)
        const searchEditTools = Admin.safeGetElement("searchEditTools", true);
        if (searchEditTools) {
            let editSearchTimeout;
            searchEditTools.addEventListener("input", function () {
                const searchTerm = this.value;
                if (editSearchTimeout) {
                    clearTimeout(editSearchTimeout);
                }
                editSearchTimeout = setTimeout(() => {
                    Admin.serverSideEditToolSearch(searchTerm);
                }, 300);
            });

            // If HTMX swaps/paginates the edit tools container, re-run server-side search
            const editToolsContainer = Admin.safeGetElement("edit-server-tools");
            if (editToolsContainer) {
                editToolsContainer.addEventListener("htmx:afterSwap", function () {
                    try {
                        const current = searchEditTools.value || "";
                        if (current && current.trim() !== "") {
                            Admin.serverSideEditToolSearch(current);
                        } else {
                            // No active search — ensure the selector is initialized
                            Admin.initToolSelect(
                                "edit-server-tools",
                                "selectedEditToolsPills",
                                "selectedEditToolsWarning",
                                6,
                                "selectAllEditToolsBtn",
                                "clearAllEditToolsBtn",
                            );
                        }
                    } catch (err) {
                        console.error("Error handling edit-tools afterSwap:", err);
                    }
                });
            }
        }

        // Prompts search (server-side)
        const searchPrompts = Admin.safeGetElement("searchPrompts", true);
        if (searchPrompts) {
            let promptSearchTimeout;
            searchPrompts.addEventListener("input", function () {
                const searchTerm = this.value;
                if (promptSearchTimeout) {
                    clearTimeout(promptSearchTimeout);
                }
                promptSearchTimeout = setTimeout(() => {
                    Admin.serverSidePromptSearch(searchTerm);
                }, 300);
            });
        }

        // Edit-server prompts search (server-side, mirror of searchPrompts)
        const searchEditPrompts = Admin.safeGetElement("searchEditPrompts", true);
        if (searchEditPrompts) {
            let editSearchTimeout;
            searchEditPrompts.addEventListener("input", function () {
                const searchTerm = this.value;
                if (editSearchTimeout) {
                    clearTimeout(editSearchTimeout);
                }
                editSearchTimeout = setTimeout(() => {
                    Admin.serverSideEditPromptsSearch(searchTerm);
                }, 300);
            });

            // If HTMX swaps/paginates the edit prompts container, re-run server-side search
            const editPromptsContainer = Admin.safeGetElement(
                "edit-server-prompts",
            );
            if (editPromptsContainer) {
                editPromptsContainer.addEventListener(
                    "htmx:afterSwap",
                    function () {
                        try {
                            const current = searchEditPrompts.value || "";
                            if (current && current.trim() !== "") {
                                Admin.serverSideEditPromptsSearch(current);
                            } else {
                                // No active search — ensure the selector is initialized
                                Admin.initPromptSelect(
                                    "edit-server-prompts",
                                    "selectedEditPromptsPills",
                                    "selectedEditPromptsWarning",
                                    6,
                                    "selectAllEditPromptsBtn",
                                    "clearAllEditPromptsBtn",
                                );
                            }
                        } catch (err) {
                            console.error(
                                "Error handling edit-prompts afterSwap:",
                                err,
                            );
                        }
                    },
                );
            }
        }

        // Resources search (server-side)
        const searchResources = Admin.safeGetElement("searchResources", true);
        if (searchResources) {
            let resourceSearchTimeout;
            searchResources.addEventListener("input", function () {
                const searchTerm = this.value;
                if (resourceSearchTimeout) {
                    clearTimeout(resourceSearchTimeout);
                }
                resourceSearchTimeout = setTimeout(() => {
                    Admin.serverSideResourceSearch(searchTerm);
                }, 300);
            });
        }

        // Edit-server resources search (server-side, mirror of searchResources)
        const searchEditResources = Admin.safeGetElement("searchEditResources", true);
        if (searchEditResources) {
            let editSearchTimeout;
            searchEditResources.addEventListener("input", function () {
                const searchTerm = this.value;
                if (editSearchTimeout) {
                    clearTimeout(editSearchTimeout);
                }
                editSearchTimeout = setTimeout(() => {
                    Admin.serverSideEditResourcesSearch(searchTerm);
                }, 300);
            });

            // If HTMX swaps/paginates the edit resources container, re-run server-side search
            const editResourcesContainer = Admin.safeGetElement(
                "edit-server-resources",
            );
            if (editResourcesContainer) {
                editResourcesContainer.addEventListener(
                    "htmx:afterSwap",
                    function () {
                        try {
                            const current = searchEditResources.value || "";
                            if (current && current.trim() !== "") {
                                Admin.serverSideEditResourcesSearch(current);
                            } else {
                                // No active search — ensure the selector is initialized
                                Admin.initResourceSelect(
                                    "edit-server-resources",
                                    "selectedEditResourcesPills",
                                    "selectedEditResourcesWarning",
                                    6,
                                    "selectAllEditResourcesBtn",
                                    "clearAllEditResourcesBtn",
                                );
                            }
                        } catch (err) {
                            console.error(
                                "Error handling edit-resources afterSwap:",
                                err,
                            );
                        }
                    },
                );
            }
        }
    }

    /**
    * Initialize search inputs for all entity types
    * This function also handles re-initialization after HTMX content loads
    */
    Admin.initializeSearchInputs = function () {
        console.log("🔍 Initializing search inputs...");

        // Clone inputs to remove existing event listeners before re-adding.
        // This prevents duplicate listeners when re-initializing after reset.
        const searchInputIds = [
            "catalog-search-input",
            "gateways-search-input",
            "tools-search-input",
            "resources-search-input",
            "prompts-search-input",
            "a2a-agents-search-input",
        ];

        searchInputIds.forEach((inputId) => {
            const input = Admin.safeGetElement(inputId);
            if (input) {
                const newInput = input.cloneNode(true);
                input.parentNode.replaceChild(newInput, input);
            }
        });

        // Virtual Servers search
        const catalogSearchInput = Admin.safeGetElement("catalog-search-input");
        if (catalogSearchInput) {
            catalogSearchInput.addEventListener("input", function () {
                Admin.filterServerTable(this.value);
            });
            console.log("✅ Virtual Servers search initialized");
            // Reapply current search term if any (preserves search after HTMX swap)
            const currentSearch = catalogSearchInput.value || "";
            if (currentSearch) {
                Admin.filterServerTable(currentSearch);
            }
        }

        // MCP Servers (Gateways) search
        const gatewaysSearchInput = Admin.safeGetElement(
            "gateways-search-input",
        );
        if (gatewaysSearchInput) {
            console.log("✅ Found MCP Servers search input");

            // Use addEventListener instead of direct assignment
            gatewaysSearchInput.addEventListener("input", function (e) {
                const searchValue = e.target.value;
                console.log("🔍 MCP Servers search triggered:", searchValue);
                Admin.filterGatewaysTable(searchValue);
            });

            // Add keyup as backup
            gatewaysSearchInput.addEventListener("keyup", function (e) {
                const searchValue = e.target.value;
                Admin.filterGatewaysTable(searchValue);
            });

            // Add change as backup
            gatewaysSearchInput.addEventListener("change", function (e) {
                const searchValue = e.target.value;
                Admin.filterGatewaysTable(searchValue);
            });

            console.log("✅ MCP Servers search events attached");

            // Reapply current search term if any (preserves search after HTMX swap)
            const currentSearch = gatewaysSearchInput.value || "";
            if (currentSearch) {
                Admin.filterGatewaysTable(currentSearch);
            }
        } else {
            console.error("❌ MCP Servers search input not found!");

            // Debug available inputs
            const allInputs = document.querySelectorAll('input[type="text"]');
            console.log(
                "Available text inputs:",
                Array.from(allInputs).map((input) => ({
                    id: input.id,
                    placeholder: input.placeholder,
                    className: input.className,
                })),
            );
        }

        // Tools search
        const toolsSearchInput = Admin.safeGetElement("tools-search-input");
        if (toolsSearchInput) {
            toolsSearchInput.addEventListener("input", function () {
                Admin.filterToolsTable(this.value);
            });
            console.log("✅ Tools search initialized");
        }

        // Resources search
        const resourcesSearchInput = Admin.safeGetElement(
            "resources-search-input",
        );
        if (resourcesSearchInput) {
            resourcesSearchInput.addEventListener("input", function () {
                Admin.filterResourcesTable(this.value);
            });
            console.log("✅ Resources search initialized");
        }

        // Prompts search
        const promptsSearchInput = Admin.safeGetElement("prompts-search-input");
        if (promptsSearchInput) {
            promptsSearchInput.addEventListener("input", function () {
                Admin.filterPromptsTable(this.value);
            });
            console.log("✅ Prompts search initialized");
        }

        // A2A Agents search
        const agentsSearchInput = Admin.safeGetElement(
            "a2a-agents-search-input",
        );
        if (agentsSearchInput) {
            agentsSearchInput.addEventListener("input", function () {
                Admin.filterA2AAgentsTable(this.value);
            });
            console.log("✅ A2A Agents search initialized");
        }
    }

    Admin.initializeTabState = function () {
        console.log("Initializing tab state...");

        const hash = window.location.hash;
        if (hash) {
            Admin.showTab(hash.slice(1));
        } else {
            Admin.showTab("gateways");
        }

        // Pre-load version info if that's the initial tab
        if (Admin.isAdminUser() && window.location.hash === "#version-info") {
            setTimeout(() => {
                const panel = Admin.safeGetElement("version-info-panel");
                if (panel && panel.innerHTML.trim() === "") {
                    Admin.fetchWithTimeout(`${window.ROOT_PATH}/version?partial=true`)
                        .then((resp) => {
                            if (!resp.ok) {
                                throw new Error("Network response was not ok");
                            }
                            return resp.text();
                        })
                        .then((html) => {
                            Admin.safeSetInnerHTML(panel, html, true);
                        })
                        .catch((err) => {
                            console.error("Failed to preload version info:", err);
                            const errorDiv = document.createElement("div");
                            errorDiv.className = "text-red-600 p-4";
                            errorDiv.textContent = "Failed to load version info.";
                            panel.innerHTML = "";
                            panel.appendChild(errorDiv);
                        });
                }
            }, 100);
        }

        // Pre-load maintenance panel if that's the initial tab
        if (Admin.isAdminUser() && window.location.hash === "#maintenance") {
            setTimeout(() => {
                const panel = Admin.safeGetElement("maintenance-panel");
                if (panel && panel.innerHTML.trim() === "") {
                    Admin.fetchWithTimeout(
                        `${window.ROOT_PATH}/admin/maintenance/partial`,
                    )
                        .then((resp) => {
                            if (!resp.ok) {
                                if (resp.status === 403) {
                                    throw new Error(
                                        "Platform administrator access required",
                                    );
                                }
                                throw new Error("Network response was not ok");
                            }
                            return resp.text();
                        })
                        .then((html) => {
                            Admin.safeSetInnerHTML(panel, html, true);
                        })
                        .catch((err) => {
                            console.error(
                                "Failed to preload maintenance panel:",
                                err,
                            );
                            const errorDiv = document.createElement("div");
                            errorDiv.className = "text-red-600 p-4";
                            errorDiv.textContent =
                                err.message || "Failed to load maintenance panel.";
                            panel.innerHTML = "";
                            panel.appendChild(errorDiv);
                        });
                }
            }, 100);
        }

        // Set checkbox states based on URL parameters (namespaced per table, with legacy fallback)
        const urlParams = new URLSearchParams(window.location.search);
        const legacyIncludeInactive = urlParams.get("include_inactive") === "true";

        // Map checkbox IDs to their table names for namespaced URL params
        const checkboxTableMap = {
            "show-inactive-tools": "tools",
            "show-inactive-resources": "resources",
            "show-inactive-prompts": "prompts",
            "show-inactive-gateways": "gateways",
            "show-inactive-servers": "servers",
            "show-inactive-a2a-agents": "agents",
            "show-inactive-tools-toolops": "toolops",
        };
        Object.entries(checkboxTableMap).forEach(([id, tableName]) => {
            const checkbox = Admin.safeGetElement(id);
            if (checkbox) {
                // Prefer namespaced param, fall back to legacy for backwards compatibility
                const namespacedValue = urlParams.get(tableName + "_inactive");
                if (namespacedValue !== null) {
                    checkbox.checked = namespacedValue === "true";
                } else {
                    checkbox.checked = legacyIncludeInactive;
                }
            }
        });

        // Note: URL state persistence for show-inactive toggles is now handled by
        // Admin.updateInactiveUrlState() in admin.html via @change handlers on checkboxes.
        // The handlers write namespaced params (e.g., servers_inactive, tools_inactive).

        // Disable toggle until its target exists (prevents race with initial HTMX load)
        document.querySelectorAll(".show-inactive-toggle").forEach((checkbox) => {
            const targetSelector = checkbox.getAttribute("hx-target");
            if (targetSelector && !document.querySelector(targetSelector)) {
                checkbox.disabled = true;
            }
        });

        // Enable toggles after HTMX swaps complete
        document.body.addEventListener("htmx:afterSettle", (event) => {
            document
                .querySelectorAll(".show-inactive-toggle[disabled]")
                .forEach((checkbox) => {
                    const targetSelector = checkbox.getAttribute("hx-target");
                    if (targetSelector && document.querySelector(targetSelector)) {
                        checkbox.disabled = false;
                    }
                });
        });
    }

    // ===================================================================
    // SEARCH & FILTERING FUNCTIONS
    // ===================================================================

    /**
    * Filter server table rows based on search text
    */
    Admin.filterServerTable = function (searchText) {
        try {
            // Try to find the table using multiple strategies
            let tbody = document.querySelector("#servers-table-body");

            // Fallback to data-testid selector for backward compatibility
            if (!tbody) {
                tbody = document.querySelector('tbody[data-testid="server-list"]');
            }

            if (!tbody) {
                console.warn("Server table not found");
                return;
            }

            const rows = tbody.querySelectorAll('tr[data-testid="server-item"]');
            const search = searchText.toLowerCase().trim();

            rows.forEach((row) => {
                let textContent = "";

                // Get text from all searchable cells (exclude Actions, Icon, and S.No. columns)
                // Table columns: Admin.Actions(0), Admin.Icon(1), S.No.(2), Admin.UUID(3), Admin.Name(4), Admin.Description(5), Admin.Tools(6), Admin.Resources(7), Admin.Prompts(8), Admin.Tags(9), Admin.Owner(10), Admin.Team(11), Admin.Visibility(12)
                const cells = row.querySelectorAll("td");
                // Search all columns except Admin.Actions(0), Admin.Icon(1), and S.No.(2) columns
                const searchableColumnIndices = [];
                for (let i = 3; i < cells.length; i++) {
                    searchableColumnIndices.push(i);
                }

                searchableColumnIndices.forEach((index) => {
                    if (cells[index]) {
                        // Clean the text content and make it searchable
                        const cellText = cells[index].textContent
                            .replace(/\s+/g, " ")
                            .trim();
                        textContent += " " + cellText;
                    }
                });

                if (search === "" || textContent.toLowerCase().includes(search)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        } catch (error) {
            console.error("Error filtering server table:", error);
        }
    }

    /**
    * Filter Tools table based on search text
    */
    Admin.filterToolsTable = function (searchText) {
        try {
            const tbody = document.querySelector("#tools-table-body");
            if (!tbody) {
                console.warn("Tools table body not found");
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            const search = searchText.toLowerCase().trim();

            rows.forEach((row) => {
                let textContent = "";

                // Get text from searchable cells (exclude Actions and S.No. columns)
                // Tools columns: Admin.Actions(0), S.No.(1), Admin.Source(2), Admin.Name(3), Admin.RequestType(4), Admin.Description(5), Admin.Annotations(6), Admin.Tags(7), Admin.Owner(8), Admin.Team(9), Admin.Status(10)
                const cells = row.querySelectorAll("td");
                const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10]; // Exclude Admin.Actions(0) and S.No.(1)

                searchableColumns.forEach((index) => {
                    if (cells[index]) {
                        // Clean the text content and make it searchable
                        const cellText = cells[index].textContent
                            .replace(/\s+/g, " ")
                            .trim();
                        textContent += " " + cellText;
                    }
                });

                const isMatch =
                    search === "" || textContent.toLowerCase().includes(search);
                if (isMatch) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        } catch (error) {
            console.error("Error filtering tools table:", error);
        }
    }

    /**
    * Filter Resources table based on search text
    */
    Admin.filterResourcesTable = function (searchText) {
        try {
            const tbody = document.querySelector("#resources-table-body");
            if (!tbody) {
                console.warn("Resources table body not found");
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            const search = searchText.toLowerCase().trim();

            rows.forEach((row) => {
                let textContent = "";

                // Get text from searchable cells (exclude Actions column)
                // Resources columns: Admin.Actions(0), Admin.Source(1), Admin.Name(2), Admin.Description(3), Admin.Tags(4), Admin.Owner(5), Admin.Team(6), Admin.Status(7)
                const cells = row.querySelectorAll("td");
                const searchableColumns = [1, 2, 3, 4, 5, 6, 7]; // All except Admin.Actions(0)

                searchableColumns.forEach((index) => {
                    if (cells[index]) {
                        textContent += " " + cells[index].textContent;
                    }
                });

                if (search === "" || textContent.toLowerCase().includes(search)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        } catch (error) {
            console.error("Error filtering resources table:", error);
        }
    }

    /**
    * Filter Prompts table based on search text
    */
    Admin.filterPromptsTable = function (searchText) {
        try {
            const tbody = document.querySelector("#prompts-table-body");
            if (!tbody) {
                console.warn("Prompts table body not found");
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            const search = searchText.toLowerCase().trim();

            rows.forEach((row) => {
                let textContent = "";

                // Get text from searchable cells (exclude Actions and S.No. columns)
                // Prompts columns: Admin.Actions(0), S.No.(1), Admin.GatewayName(2), Admin.Name(3), Admin.Description(4), Admin.Tags(5), Admin.Owner(6), Admin.Team(7), Admin.Status(8)
                const cells = row.querySelectorAll("td");
                const searchableColumns = [2, 3, 4, 5, 6, 7, 8]; // All except Admin.Actions(0) and S.No.(1)

                searchableColumns.forEach((index) => {
                    if (cells[index]) {
                        textContent += " " + cells[index].textContent;
                    }
                });

                if (search === "" || textContent.toLowerCase().includes(search)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        } catch (error) {
            console.error("Error filtering prompts table:", error);
        }
    }

    /**
    * Filter A2A Agents table based on search text
    */
    Admin.filterA2AAgentsTable = function (searchText) {
        try {
            // Try to find the table using multiple strategies
            let tbody = document.querySelector("#agents-table tbody");

            // Fallback to panel selector for backward compatibility
            if (!tbody) {
                tbody = document.querySelector("#a2a-agents-panel tbody");
            }

            if (!tbody) {
                console.warn("A2A Agents table body not found");
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            const search = searchText.toLowerCase().trim();

            rows.forEach((row) => {
                let textContent = "";

                // Get text from searchable cells (exclude Actions and ID columns)
                // A2A Agents columns: Admin.Actions(0), Admin.ID(1), Admin.Name(2), Admin.Description(3), Admin.Endpoint(4), Admin.Tags(5), Admin.Type(6), Admin.Status(7), Admin.Reachability(8), Admin.Owner(9), Admin.Team(10), Admin.Visibility(11)
                const cells = row.querySelectorAll("td");
                const searchableColumns = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]; // Exclude Admin.Actions(0) and Admin.ID(1)

                searchableColumns.forEach((index) => {
                    if (cells[index]) {
                        textContent += " " + cells[index].textContent;
                    }
                });

                if (search === "" || textContent.toLowerCase().includes(search)) {
                    row.style.display = "";
                } else {
                    row.style.display = "none";
                }
            });
        } catch (error) {
            console.error("Error filtering A2A agents table:", error);
        }
    }

    /**
    * Filter MCP Servers (Gateways) table based on search text
    */
    Admin.filterGatewaysTable = function (searchText) {
        try {
            console.log("🔍 Starting MCP Servers search for:", searchText);

            // Find the MCP servers table - use multiple strategies
            let table = null;

            // Strategy 1: Direct selector for gateways panel
            const gatewaysPanel = document.querySelector("#gateways-panel");
            if (gatewaysPanel) {
                table = gatewaysPanel.querySelector("table");
                console.log("✅ Found table in gateways panel");
            }

            // Strategy 2: Look for table in currently visible tab
            if (!table) {
                const visiblePanel = document.querySelector(
                    ".tab-panel:not(.hidden)",
                );
                if (visiblePanel) {
                    table = visiblePanel.querySelector("table");
                    console.log("✅ Found table in visible panel");
                }
            }

            // Strategy 3: Just look for any table with MCP server structure
            if (!table) {
                const allTables = document.querySelectorAll("table");
                for (const t of allTables) {
                    const headers = t.querySelectorAll("thead th");
                    if (headers.length >= 8) {
                        // Check for MCP server specific headers
                        const headerTexts = Array.from(headers).map((h) =>
                            h.textContent.toLowerCase().trim(),
                        );
                        if (
                            headerTexts.includes("name") &&
                            headerTexts.includes("url") &&
                            headerTexts.includes("status")
                        ) {
                            table = t;
                            console.log("✅ Found MCP table by header matching");
                            break;
                        }
                    }
                }
            }

            if (!table) {
                console.warn("❌ No MCP servers table found");
                return;
            }

            const tbody = table.querySelector("tbody");
            if (!tbody) {
                console.warn("❌ No tbody found");
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            if (rows.length === 0) {
                console.warn("❌ No rows found");
                return;
            }

            const search = searchText.toLowerCase().trim();
            console.log(`🔍 Searching ${rows.length} rows for: "${search}"`);

            let visibleCount = 0;

            rows.forEach((row, index) => {
                const cells = row.querySelectorAll("td");

                if (cells.length === 0) {
                    return;
                }

                // Combine text from all cells except Admin.Actions(0) and S.No.(1) columns
                // Gateways columns: Admin.Actions(0), S.No.(1), Admin.Name(2), Admin.URL(3), Admin.Tags(4), Admin.Status(5), Admin.LastSeen(6), Admin.Owner(7), Admin.Team(8), Admin.Visibility(9)
                let searchContent = "";
                for (let i = 2; i < cells.length; i++) {
                    if (cells[i]) {
                        const cellText = cells[i].textContent.trim();
                        searchContent += " " + cellText;
                    }
                }

                const fullText = searchContent.trim().toLowerCase();
                const matchesSearch = search === "" || fullText.includes(search);

                // Check if row should be visible based on inactive filter
                const checkbox = Admin.safeGetElement("show-inactive-gateways");
                const showInactive = checkbox ? checkbox.checked : true;
                const isEnabled = row.getAttribute("data-enabled") === "true";
                const matchesFilter = showInactive || isEnabled;

                // Only show row if it matches BOTH search AND filter
                const shouldShow = matchesSearch && matchesFilter;

                // Debug first few rows
                if (index < 3) {
                    console.log(
                        `Row ${index + 1}: "${fullText.substring(0, 50)}..." -> Search: ${matchesSearch}, Filter: ${matchesFilter}, Show: ${shouldShow}`,
                    );
                }

                // Show/hide the row
                if (shouldShow) {
                    row.style.removeProperty("display");
                    row.style.removeProperty("visibility");
                    visibleCount++;
                } else {
                    row.style.display = "none";
                    row.style.visibility = "hidden";
                }
            });

            console.log(
                `✅ Search complete: ${visibleCount}/${rows.length} rows visible`,
            );
        } catch (error) {
            console.error("❌ Error in filterGatewaysTable:", error);
        }
    }

    // Add a test function for debugging
    Admin.testGatewaySearch = function (searchTerm = "Cou") {
        console.log("🧪 Testing gateway search with:", searchTerm);
        console.log("Available tables:", document.querySelectorAll("table").length);

        // Test the search input exists
        const searchInput = Admin.safeGetElement("gateways-search-input");
        console.log("Search input found:", !!searchInput);

        if (searchInput) {
            searchInput.value = searchTerm;
            console.log("Set search input value to:", searchInput.value);
        }

        Admin.filterGatewaysTable(searchTerm);
    };

    // Simple fallback search function
    Admin.simpleGatewaySearch = function (searchTerm) {
        console.log("🔧 Simple gateway search for:", searchTerm);

        // Find any table in the current tab/page
        const tables = document.querySelectorAll("table");
        console.log("Found tables:", tables.length);

        tables.forEach((table, tableIndex) => {
            const tbody = table.querySelector("tbody");
            if (!tbody) {
                return;
            }

            const rows = tbody.querySelectorAll("tr");
            console.log(`Table ${tableIndex}: ${rows.length} rows`);

            if (rows.length > 0) {
                // Check if this looks like the MCP servers table
                const firstRow = rows[0];
                const cells = firstRow.querySelectorAll("td");

                if (cells.length >= 8) {
                    // MCP servers table should have many columns
                    console.log(
                        `Table ${tableIndex} looks like MCP servers table with ${cells.length} columns`,
                    );

                    const search = searchTerm.toLowerCase().trim();
                    let visibleCount = 0;

                    rows.forEach((row) => {
                        const cells = row.querySelectorAll("td");
                        let rowText = "";

                        // Get text from all cells except Admin.Actions(0) and S.No.(1)
                        for (let i = 2; i < cells.length; i++) {
                            rowText += " " + cells[i].textContent.trim();
                        }

                        const shouldShow =
                            search === "" || rowText.toLowerCase().includes(search);

                        if (shouldShow) {
                            row.style.display = "";
                            visibleCount++;
                        } else {
                            row.style.display = "none";
                        }
                    });

                    console.log(
                        `✅ Simple search complete: ${visibleCount}/${rows.length} rows visible`,
                    );
                    // Found the table, stop searching
                }
            }
        });
    };

    // Add initialization test function
    Admin.testSearchInit = function () {
        console.log("🧪 Testing search initialization...");
        Admin.initializeSearchInputs();
    };

    /**
    * Clear search functionality for different entity types
    */
    Admin.clearSearch = function (entityType) {
        try {
            if (entityType === "catalog") {
                const searchInput = Admin.safeGetElement("catalog-search-input");
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterServerTable(""); // Clear the filter
                }
            } else if (entityType === "tools") {
                const searchInput = Admin.safeGetElement("tools-search-input");
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterToolsTable(""); // Clear the filter
                }
            } else if (entityType === "resources") {
                const searchInput = Admin.safeGetElement(
                    "resources-search-input",
                );
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterResourcesTable(""); // Clear the filter
                }
            } else if (entityType === "prompts") {
                const searchInput = Admin.safeGetElement("prompts-search-input");
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterPromptsTable(""); // Clear the filter
                }
            } else if (entityType === "a2a-agents") {
                const searchInput = Admin.safeGetElement(
                    "a2a-agents-search-input",
                );
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterA2AAgentsTable(""); // Clear the filter
                }
            } else if (entityType === "gateways") {
                const searchInput = Admin.safeGetElement(
                    "gateways-search-input",
                );
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterGatewaysTable(""); // Clear the filter
                }
            } else if (entityType === "gateways") {
                const searchInput = Admin.safeGetElement(
                    "gateways-search-input",
                );
                if (searchInput) {
                    searchInput.value = "";
                    Admin.filterGatewaysTable(""); // Clear the filter
                }
            }
        } catch (error) {
            console.error("Error clearing search:", error);
        }
    }

    /**
    * Create memoized version of search inputs initialization
    * This prevents repeated initialization and provides explicit reset capability
    */
    const {
        init: initializeSearchInputsMemoized,
        debouncedInit: initializeSearchInputsDebounced,
        reset: resetSearchInputsState,
    } = Admin.createMemoizedInit(Admin.initializeSearchInputs, 300, "SearchInputs");

    Admin.handleAuthTypeChange = function () {
        const authType = this.value;

        // Detect form type based on the element ID
        // e.g., "auth-type-a2a" or "auth-type-gw"
        const isA2A = this.id.includes("a2a");
        const prefix = isA2A ? "a2a" : "gw";

        // Select the correct field groups dynamically
        const basicFields = Admin.safeGetElement(`auth-basic-fields-${prefix}`);
        const bearerFields = Admin.safeGetElement(`auth-bearer-fields-${prefix}`);
        const headersFields = Admin.safeGetElement(`auth-headers-fields-${prefix}`);
        const oauthFields = Admin.safeGetElement(`auth-oauth-fields-${prefix}`);
        const queryParamFields = Admin.safeGetElement(
            `auth-query_param-fields-${prefix}`,
        );

        // Hide all auth sections first
        [
            basicFields,
            bearerFields,
            headersFields,
            oauthFields,
            queryParamFields,
        ].forEach((section) => {
            if (section) {
                section.style.display = "none";
            }
        });

        // Show the appropriate section
        switch (authType) {
            case "basic":
                if (basicFields) {
                    basicFields.style.display = "block";
                }
                break;
            case "bearer":
                if (bearerFields) {
                    bearerFields.style.display = "block";
                }
                break;
            case "authheaders":
                if (headersFields) {
                    headersFields.style.display = "block";
                }
                break;
            case "oauth":
                if (oauthFields) {
                    oauthFields.style.display = "block";
                }
                break;
            case "query_param":
                if (queryParamFields) {
                    queryParamFields.style.display = "block";
                }
                break;
            default:
                // "none" or unknown type — keep everything hidden
                break;
        }
    }

    Admin.handleOAuthGrantTypeChange = function () {
        const grantType = this.value;

        // Detect form type (a2a or gw) from the triggering element ID
        const isA2A = this.id.includes("a2a");
        const prefix = isA2A ? "a2a" : "gw";

        // Select the correct fields dynamically based on prefix
        const authCodeFields = Admin.safeGetElement(`oauth-auth-code-fields-${prefix}`);
        const usernameField = Admin.safeGetElement(`oauth-username-field-${prefix}`);
        const passwordField = Admin.safeGetElement(`oauth-password-field-${prefix}`);

        // Handle Authorization Code flow
        if (authCodeFields) {
            if (grantType === "authorization_code") {
                authCodeFields.style.display = "block";

                // Make URL fields required
                const requiredFields =
                    authCodeFields.querySelectorAll('input[type="url"]');
                requiredFields.forEach((field) => (field.required = true));

                console.log(
                    `(${prefix.toUpperCase()}) Authorization Code flow selected - fields are now required`,
                );
            } else {
                authCodeFields.style.display = "none";

                // Remove required validation
                const requiredFields =
                    authCodeFields.querySelectorAll('input[type="url"]');
                requiredFields.forEach((field) => (field.required = false));
            }
        }

        // Handle Password Grant flow
        if (usernameField && passwordField) {
            const usernameInput = Admin.safeGetElement(`oauth-username-${prefix}`);
            const passwordInput = Admin.safeGetElement(`oauth-password-${prefix}`);

            if (grantType === "password") {
                usernameField.style.display = "block";
                passwordField.style.display = "block";

                if (usernameInput) {
                    usernameInput.required = true;
                }
                if (passwordInput) {
                    passwordInput.required = true;
                }

                console.log(
                    `(${prefix.toUpperCase()}) Password grant flow selected - username and password are now required`,
                );
            } else {
                usernameField.style.display = "none";
                passwordField.style.display = "none";

                if (usernameInput) {
                    usernameInput.required = false;
                }
                if (passwordInput) {
                    passwordInput.required = false;
                }
            }
        }
    }

    Admin.handleEditOAuthGrantTypeChange = function () {
        const grantType = this.value;

        // Detect prefix dynamically (supports both gw-edit and a2a-edit)
        const id = this.id || "";
        const prefix = id.includes("a2a") ? "a2a-edit" : "gw-edit";

        const authCodeFields = Admin.safeGetElement(`oauth-auth-code-fields-${prefix}`);
        const usernameField = Admin.safeGetElement(`oauth-username-field-${prefix}`);
        const passwordField = Admin.safeGetElement(`oauth-password-field-${prefix}`);

        // === Handle Authorization Code grant ===
        if (authCodeFields) {
            const urlInputs = authCodeFields.querySelectorAll('input[type="url"]');
            if (grantType === "authorization_code") {
                authCodeFields.style.display = "block";
                urlInputs.forEach((field) => (field.required = true));
                console.log(
                    `Authorization Code flow selected (${prefix}) - additional fields are now required`,
                );
            } else {
                authCodeFields.style.display = "none";
                urlInputs.forEach((field) => (field.required = false));
            }
        }

        // === Handle Password grant ===
        if (usernameField && passwordField) {
            const usernameInput = Admin.safeGetElement(`oauth-username-${prefix}`);
            const passwordInput = Admin.safeGetElement(`oauth-password-${prefix}`);

            if (grantType === "password") {
                usernameField.style.display = "block";
                passwordField.style.display = "block";

                if (usernameInput) {
                    usernameInput.required = true;
                }
                if (passwordInput) {
                    passwordInput.required = true;
                }

                console.log(
                    `Password grant flow selected (${prefix}) - username and password are now required`,
                );
            } else {
                usernameField.style.display = "none";
                passwordField.style.display = "none";

                if (usernameInput) {
                    usernameInput.required = false;
                }
                if (passwordInput) {
                    passwordInput.required = false;
                }
            }
        }
    }

    Admin.setupSchemaModeHandlers = function () {
        const schemaModeRadios = document.getElementsByName("schema_input_mode");
        const uiBuilderDiv = Admin.safeGetElement("ui-builder");
        const jsonInputContainer = Admin.safeGetElement("json-input-container");

        if (schemaModeRadios.length === 0) {
            console.warn("Schema mode radios not found");
            return;
        }

        Array.from(schemaModeRadios).forEach((radio) => {
            radio.addEventListener("change", () => {
                try {
                    if (radio.value === "ui" && radio.checked) {
                        if (uiBuilderDiv) {
                            uiBuilderDiv.style.display = "block";
                        }
                        if (jsonInputContainer) {
                            jsonInputContainer.style.display = "none";
                        }
                    } else if (radio.value === "json" && radio.checked) {
                        if (uiBuilderDiv) {
                            uiBuilderDiv.style.display = "none";
                        }
                        if (jsonInputContainer) {
                            jsonInputContainer.style.display = "block";
                        }
                        Admin.updateSchemaPreview();
                    }
                } catch (error) {
                    console.error("Error handling schema mode change:", error);
                }
            });
        });

        console.log("✓ Schema mode handlers set up successfully");
    }

    Admin.setupIntegrationTypeHandlers = function () {
        const integrationTypeSelect = Admin.safeGetElement("integrationType");
        if (integrationTypeSelect) {
            const defaultIntegration =
                integrationTypeSelect.dataset.default ||
                integrationTypeSelect.options[0].value;
            integrationTypeSelect.value = defaultIntegration;
            Admin.updateRequestTypeOptions();
            integrationTypeSelect.addEventListener("change", () =>
                Admin.updateRequestTypeOptions(),
            );
        }

        const editToolTypeSelect = Admin.safeGetElement("edit-tool-type");
        if (editToolTypeSelect) {
            editToolTypeSelect.addEventListener(
                "change",
                () => Admin.updateEditToolRequestTypes(),
                // Admin.updateEditToolUrl(),
            );
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        console.log("🔐 DOM loaded - initializing secure admin interface...");

        try {
            // Admin.initializeTooltips();

            // 1. Initialize CodeMirror editors first
            Admin.initializeCodeMirrorEditors();

            // 2. Initialize tool selects
            Admin.initializeToolSelects();

            // 3. Set up all event listeners
            Admin.initializeEventListeners();

            // 4. Handle initial tab/state
            Admin.initializeTabState();

            // 5. Set up form validation
            Admin.setupFormValidation();

            // 6. Setup bulk import modal
            try {
                Admin.setupBulkImportModal();
            } catch (error) {
                console.error("Error setting up bulk import modal:", error);
            }

            // 7. Initialize export/import functionality
            try {
                Admin.initializeExportImport();
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

            //         Admin.safeGetElement(tabId).classList.remove('hidden');
            //     });
            // });

            // Mark as initialized
            Admin.AppState.isInitialized = true;

            console.log(
                "✅ Secure initialization complete - XSS protection active",
            );
        } catch (error) {
            console.error("❌ Initialization failed:", error);
            Admin.showErrorMessage(
                "Failed to initialize the application. Please refresh the page.",
            );
        }
    });

    // ===============================================
    // TAG FILTERING FUNCTIONALITY
    // ===============================================

    /**
    * Extract all unique tags from entities in a given entity type
    * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
    * @returns {Array<string>} - Array of unique tags
    */
    Admin.extractAvailableTags = function (entityType) {
        const tags = new Set();
        const tableSelector = `#${entityType}-panel tbody tr:not(.inactive-row)`;
        const rows = document.querySelectorAll(tableSelector);

        console.log(
            `[DEBUG] extractAvailableTags for ${entityType}: Found ${rows.length} rows`,
        );

        // Find the Tags column index by examining the table header
        const tableHeaderSelector = `#${entityType}-panel thead tr th`;
        const headerCells = document.querySelectorAll(tableHeaderSelector);
        let tagsColumnIndex = -1;

        headerCells.forEach((header, index) => {
            const headerText = header.textContent.trim().toLowerCase();
            if (headerText === "tags") {
                tagsColumnIndex = index;
                console.log(
                    `[DEBUG] Found Tags column at index ${index} for ${entityType}`,
                );
            }
        });

        if (tagsColumnIndex === -1) {
            console.log(`[DEBUG] Could not find Tags column for ${entityType}`);
            return [];
        }

        rows.forEach((row, index) => {
            const cells = row.querySelectorAll("td");

            if (tagsColumnIndex < cells.length) {
                const tagsCell = cells[tagsColumnIndex];

                // Look for tag badges ONLY within the Tags column
                const tagElements = tagsCell.querySelectorAll(`
                    span.inline-flex.items-center.px-2.py-0\\.5.rounded.text-xs.font-medium.bg-blue-100.text-blue-800,
                    span.inline-block.bg-blue-100.text-blue-800.text-xs.px-2.py-1.rounded-full
                `);

                console.log(
                    `[DEBUG] Row ${index}: Found ${tagElements.length} tag elements in Tags column`,
                );

                tagElements.forEach((tagEl) => {
                    const tagText = tagEl.textContent.trim();
                    console.log(
                        `[DEBUG] Row ${index}: Tag element text: "${tagText}"`,
                    );

                    // Basic validation for tag content
                    if (
                        tagText &&
                        tagText !== "No tags" &&
                        tagText !== "None" &&
                        tagText !== "N/A" &&
                        tagText.length >= 2 &&
                        tagText.length <= 50
                    ) {
                        tags.add(tagText);
                        console.log(
                            `[DEBUG] Row ${index}: Added tag: "${tagText}"`,
                        );
                    } else {
                        console.log(
                            `[DEBUG] Row ${index}: Filtered out: "${tagText}"`,
                        );
                    }
                });
            }
        });

        const result = Array.from(tags).sort();
        console.log(
            `[DEBUG] extractAvailableTags for ${entityType}: Final result:`,
            result,
        );
        return result;
    }

    /**
    * Update the available tags display for an entity type
    * @param {string} entityType - The entity type
    */
    Admin.updateAvailableTags = function (entityType) {
        const availableTagsContainer = Admin.safeGetElement(
            `${entityType}-available-tags`,
        );
        if (!availableTagsContainer) {
            return;
        }

        const tags = Admin.extractAvailableTags(entityType);
        availableTagsContainer.innerHTML = "";

        if (tags.length === 0) {
            availableTagsContainer.innerHTML =
                '<span class="text-sm text-gray-500">No tags found</span>';
            return;
        }

        tags.forEach((tag) => {
            const tagButton = document.createElement("button");
            tagButton.type = "button";
            tagButton.className =
                "inline-flex items-center px-2 py-1 text-xs font-medium rounded-full text-blue-700 bg-blue-100 hover:bg-blue-200 cursor-pointer";
            tagButton.textContent = tag;
            tagButton.title = `Click to filter by "${tag}"`;
            tagButton.onclick = () => Admin.addTagToFilter(entityType, tag);
            availableTagsContainer.appendChild(tagButton);
        });
    }

    /**
    * Filter entities by tags
    * @param {string} entityType - The entity type (tools, resources, prompts, servers, gateways)
    * @param {string} tagsInput - Comma-separated string of tags to filter by
    */
    Admin.filterEntitiesByTags = function (entityType, tagsInput) {
        const filterTags = tagsInput
            .split(",")
            .map((tag) => tag.trim().toLowerCase())
            .filter((tag) => tag);

        const tableSelector = `#${entityType}-panel tbody tr`;
        const rows = document.querySelectorAll(tableSelector);

        let visibleCount = 0;

        rows.forEach((row) => {
            if (filterTags.length === 0) {
                // Show all rows when no filter is applied
                row.style.display = "";
                visibleCount++;
                return;
            }

            // Extract tags from this row using specific tag selectors (not status badges)
            const rowTags = new Set();

            const tagElements = row.querySelectorAll(`
                /* Gateways */
                span.inline-block.bg-blue-100.text-blue-800.text-xs.px-2.py-1.rounded-full,
                /* A2A Agents */
                span.inline-flex.items-center.px-2.py-1.rounded.text-xs.bg-gray-100.text-gray-700,
                /* Prompts & Resources */
                span.inline-flex.items-center.px-2.py-0\\.5.rounded.text-xs.font-medium.bg-blue-100.text-blue-800,
                /* Gray tags for A2A agent metadata */
                span.inline-flex.items-center.px-2\\.5.py-0\\.5.rounded-full.text-xs.font-medium.bg-gray-100.text-gray-700
            `);

            tagElements.forEach((tagEl) => {
                const tagText = tagEl.textContent.trim().toLowerCase();
                // Filter out any remaining non-tag content
                if (
                    tagText &&
                    tagText !== "no tags" &&
                    tagText !== "none" &&
                    tagText !== "active" &&
                    tagText !== "inactive" &&
                    tagText !== "online" &&
                    tagText !== "offline"
                ) {
                    rowTags.add(tagText);
                }
            });

            // Check if any of the filter tags match any of the row tags (OR logic)
            const hasMatchingTag = filterTags.some((filterTag) =>
                Array.from(rowTags).some(
                    (rowTag) =>
                        rowTag.includes(filterTag) || filterTag.includes(rowTag),
                ),
            );

            if (hasMatchingTag) {
                row.style.display = "";
                visibleCount++;
            } else {
                row.style.display = "none";
            }
        });

        // Update empty state message
        Admin.updateFilterEmptyState(entityType, visibleCount, filterTags.length > 0);
    }

    /**
    * Add a tag to the filter input
    * @param {string} entityType - The entity type
    * @param {string} tag - The tag to add
    */
    Admin.addTagToFilter = function (entityType, tag) {
        const filterInput = Admin.safeGetElement(`${entityType}-tag-filter`);
        if (!filterInput) {
            return;
        }

        const currentTags = filterInput.value
            .split(",")
            .map((t) => t.trim())
            .filter((t) => t);
        if (!currentTags.includes(tag)) {
            currentTags.push(tag);
            filterInput.value = currentTags.join(", ");
            Admin.filterEntitiesByTags(entityType, filterInput.value);
        }
    }

    /**
    * Update empty state message when filtering
    * @param {string} entityType - The entity type
    * @param {number} visibleCount - Number of visible entities
    * @param {boolean} isFiltering - Whether filtering is active
    */
    Admin.updateFilterEmptyState = function (entityType, visibleCount, isFiltering) {
        const tableContainer = document.querySelector(
            `#${entityType}-panel .overflow-x-auto`,
        );
        if (!tableContainer) {
            return;
        }

        let emptyMessage = tableContainer.querySelector(
            ".tag-filter-empty-message",
        );

        if (visibleCount === 0 && isFiltering) {
            if (!emptyMessage) {
                emptyMessage = document.createElement("div");
                emptyMessage.className =
                    "tag-filter-empty-message text-center py-8 text-gray-500";
                emptyMessage.innerHTML = `
                    <div class="flex flex-col items-center">
                        <svg class="w-12 h-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                        </svg>
                        <h3 class="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">No matching ${entityType}</h3>
                        <p class="text-gray-500 dark:text-gray-400">No ${entityType} found with the specified tags. Try adjusting your filter or <button onclick="Admin.clearTagFilter('${entityType}')" class="text-indigo-600 hover:text-indigo-500 underline">clear the filter</button>.</p>
                    </div>
                `;
                tableContainer.appendChild(emptyMessage);
            }
            emptyMessage.style.display = "block";
        } else if (emptyMessage) {
            emptyMessage.style.display = "none";
        }
    }

    /**
    * Clear the tag filter for an entity type
    * @param {string} entityType - The entity type
    */
    Admin.clearTagFilter = function (entityType) {
        const filterInput = Admin.safeGetElement(`${entityType}-tag-filter`);
        if (filterInput) {
            filterInput.value = "";
            Admin.filterEntitiesByTags(entityType, "");
        }
    }

    /**
    * Initialize tag filtering for all entity types on page load
    */
    Admin.initializeTagFiltering = function () {
        const entityTypes = [
            "catalog",
            "tools",
            "resources",
            "prompts",
            "servers",
            "gateways",
            "a2a-agents",
        ];

        entityTypes.forEach((entityType) => {
            // Update available tags on page load
            Admin.updateAvailableTags(entityType);

            // Set up event listeners for tab switching to refresh tags
            const tabButton = Admin.safeGetElement(`tab-${entityType}`);
            if (tabButton) {
                tabButton.addEventListener("click", () => {
                    // Delay to ensure tab content is visible
                    setTimeout(() => Admin.updateAvailableTags(entityType), 100);
                });
            }
        });
    }

    // Initialize tag filtering when page loads
    document.addEventListener("DOMContentLoaded", function () {
        Admin.initializeTagFiltering();

        if (typeof initializeTeamScopingMonitor === "function") {
            Admin.initializeTeamScopingMonitor();
        }
    });

    // ===================================================================
    // BULK IMPORT TOOLS — MODAL WIRING
    // ===================================================================

    Admin.setupBulkImportModal = function () {
        const openBtn = Admin.safeGetElement("open-bulk-import", true);
        const modalId = "bulk-import-modal";
        const modal = Admin.safeGetElement(modalId, true);

        if (!openBtn || !modal) {
            // Bulk import feature not available - skip silently
            return;
        }

        // avoid double-binding if admin.js gets evaluated more than once
        if (openBtn.dataset.wired === "1") {
            return;
        }
        openBtn.dataset.wired = "1";

        const closeBtn = Admin.safeGetElement("close-bulk-import", true);
        const backdrop = Admin.safeGetElement("bulk-import-backdrop", true);
        const resultEl = Admin.safeGetElement("import-result", true);

        const focusTarget =
            modal?.querySelector("#tools_json") ||
            modal?.querySelector("#tools_file") ||
            modal?.querySelector("[data-autofocus]");

        // helpers
        const open = (e) => {
            if (e) {
                e.preventDefault();
            }
            // clear previous results each time we open
            if (resultEl) {
                resultEl.innerHTML = "";
            }
            Admin.openModal(modalId);
            // prevent background scroll
            document.documentElement.classList.add("overflow-hidden");
            document.body.classList.add("overflow-hidden");
            if (focusTarget) {
                setTimeout(() => focusTarget.focus(), 0);
            }
            return false;
        };

        const close = () => {
            // also clear results on close to keep things tidy
            Admin.closeModal(modalId, "import-result");
            document.documentElement.classList.remove("overflow-hidden");
            document.body.classList.remove("overflow-hidden");
        };

        // wire events
        openBtn.addEventListener("click", open);

        if (closeBtn) {
            closeBtn.addEventListener("click", (e) => {
                e.preventDefault();
                close();
            });
        }

        // click on backdrop only (not the dialog content) closes the modal
        if (backdrop) {
            backdrop.addEventListener("click", (e) => {
                if (e.target === backdrop) {
                    close();
                }
            });
        }

        // ESC to close
        modal.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                close();
            }
        });

        // FORM SUBMISSION → handle bulk import
        const form = Admin.safeGetElement("bulk-import-form", true);
        if (form) {
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const resultEl = Admin.safeGetElement("import-result", true);
                const indicator = Admin.safeGetElement("bulk-import-indicator", true);

                try {
                    const formData = new FormData();

                    // Get JSON from textarea or file
                    const jsonTextarea = form?.querySelector('[name="tools_json"]');
                    const fileInput = form?.querySelector('[name="tools_file"]');

                    let hasData = false;

                    // Check for file upload first (takes precedence)
                    if (fileInput && fileInput.files.length > 0) {
                        formData.append("tools_file", fileInput.files[0]);
                        hasData = true;
                    } else if (jsonTextarea && jsonTextarea.value.trim()) {
                        // Validate JSON before sending
                        try {
                            const toolsData = JSON.parse(jsonTextarea.value);
                            if (!Array.isArray(toolsData)) {
                                throw new Error("JSON must be an array of tools");
                            }
                            formData.append("tools", jsonTextarea.value);
                            hasData = true;
                        } catch (err) {
                            if (resultEl) {
                                resultEl.innerHTML = `
                                    <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                                        <p class="font-semibold">Invalid JSON</p>
                                        <p class="text-sm mt-1">${escapeHtml(err.message)}</p>
                                    </div>
                                `;
                            }
                            return;
                        }
                    }

                    if (!hasData) {
                        if (resultEl) {
                            resultEl.innerHTML = `
                                <div class="mt-2 p-3 bg-yellow-100 border border-yellow-400 text-yellow-700 rounded">
                                    <p class="text-sm">Please provide JSON data or upload a file</p>
                                </div>
                            `;
                        }
                        return;
                    }

                    // Show loading state
                    if (indicator) {
                        indicator.style.display = "flex";
                    }

                    // Submit to backend
                    const response = await Admin.fetchWithTimeout(
                        `${window.ROOT_PATH}/admin/tools/import`,
                        {
                            method: "POST",
                            body: formData,
                        },
                    );

                    const result = await response.json();

                    // Display results
                    if (resultEl) {
                        if (result.success) {
                            resultEl.innerHTML = `
                                <div class="mt-2 p-3 bg-green-100 border border-green-400 text-green-700 rounded">
                                    <p class="font-semibold">Import Successful</p>
                                    <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                                </div>
                            `;

                            // Close modal and refresh page after delay
                            setTimeout(() => {
                                Admin.closeModal("bulk-import-modal");
                                window.location.reload();
                            }, 2000);
                        } else if (result.imported > 0) {
                            // Partial success
                            let detailsHtml = "";
                            if (result.details && result.details.failed) {
                                detailsHtml =
                                    '<ul class="mt-2 text-sm list-disc list-inside">';
                                result.details.failed.forEach((item) => {
                                    detailsHtml += `<li><strong>${escapeHtml(item.name)}:</strong> ${escapeHtml(item.error)}</li>`;
                                });
                                detailsHtml += "</ul>";
                            }

                            resultEl.innerHTML = `
                                <div class="mt-2 p-3 bg-yellow-100 border border-yellow-400 text-yellow-700 rounded">
                                    <p class="font-semibold">Partial Import</p>
                                    <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                                    ${detailsHtml}
                                </div>
                            `;
                        } else {
                            // Complete failure
                            resultEl.innerHTML = `
                                <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                                    <p class="font-semibold">Import Failed</p>
                                    <p class="text-sm mt-1">${escapeHtml(result.message)}</p>
                                </div>
                            `;
                        }
                    }
                } catch (error) {
                    console.error("Bulk import error:", error);
                    if (resultEl) {
                        resultEl.innerHTML = `
                            <div class="mt-2 p-3 bg-red-100 border border-red-400 text-red-700 rounded">
                                <p class="font-semibold">Import Error</p>
                                <p class="text-sm mt-1">${escapeHtml(error.message || "An unexpected error occurred")}</p>
                            </div>
                        `;
                    }
                } finally {
                    // Hide loading state
                    if (indicator) {
                        indicator.style.display = "none";
                    }
                }

                return false;
            });
        }
    }

    // ===================================================================
    // EXPORT/IMPORT FUNCTIONALITY
    // ===================================================================

    /**
    * Initialize export/import functionality
    */
    Admin.initializeExportImport = function () {
        // Prevent double initialization
        if (window.exportImportInitialized) {
            console.log("🔄 Export/import already initialized, skipping");
            return;
        }

        console.log("🔄 Initializing export/import functionality");

        // Export button handlers
        const exportAllBtn = Admin.safeGetElement("export-all-btn");
        const exportSelectedBtn = Admin.safeGetElement("export-selected-btn");

        if (exportAllBtn) {
            exportAllBtn.addEventListener("click", Admin.handleExportAll);
        }

        if (exportSelectedBtn) {
            exportSelectedBtn.addEventListener("click", Admin.handleExportSelected);
        }

        // Import functionality
        const importDropZone = Admin.safeGetElement("import-drop-zone");
        const importFileInput = Admin.safeGetElement("import-file-input");
        const importValidateBtn = Admin.safeGetElement("import-validate-btn");
        const importExecuteBtn = Admin.safeGetElement("import-execute-btn");

        if (importDropZone && importFileInput) {
            // File input handler
            importDropZone.addEventListener("click", () => importFileInput.click());
            importFileInput.addEventListener("change", Admin.handleFileSelect);

            // Drag and drop handlers
            importDropZone.addEventListener("dragover", Admin.handleDragOver);
            importDropZone.addEventListener("drop", Admin.handleFileDrop);
            importDropZone.addEventListener("dragleave", Admin.handleDragLeave);
        }

        if (importValidateBtn) {
            importValidateBtn.addEventListener("click", () => Admin.handleImport(true));
        }

        if (importExecuteBtn) {
            importExecuteBtn.addEventListener("click", () => Admin.handleImport(false));
        }

        // Load recent imports when tab is shown
        Admin.loadRecentImports();

        // Mark as initialized
        Admin.exportImportInitialized = true;
    }

    /**
    * Handle export all configuration
    */
    Admin.handleExportAll = async function () {
        console.log("📤 Starting export all configuration");

        try {
            Admin.showExportProgress(true);

            const options = Admin.getExportOptions();
            const params = new URLSearchParams();

            if (options.types.length > 0) {
                params.append("types", options.types.join(","));
            }
            if (options.tags) {
                params.append("tags", options.tags);
            }
            if (options.includeInactive) {
                params.append("include_inactive", "true");
            }
            if (!options.includeDependencies) {
                params.append("include_dependencies", "false");
            }

            const response = await fetch(
                `${window.ROOT_PATH}/admin/export/configuration?${params}`,
                {
                    method: "GET",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                throw new Error(`Export failed: ${response.statusText}`);
            }

            // Create download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `mcpgateway-export-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            Admin.showNotification("✅ Export completed successfully!", "success");
        } catch (error) {
            console.error("Export error:", error);
            Admin.showNotification(`❌ Export failed: ${error.message}`, "error");
        } finally {
            Admin.showExportProgress(false);
        }
    }

    /**
    * Handle export selected configuration
    */
    Admin.handleExportSelected = async function () {
        console.log("📋 Starting selective export");

        try {
            Admin.showExportProgress(true);

            // This would need entity selection logic - for now, just do a filtered export
            await Admin.handleExportAll(); // Simplified implementation
        } catch (error) {
            console.error("Selective export error:", error);
            Admin.showNotification(
                `❌ Selective export failed: ${error.message}`,
                "error",
            );
        } finally {
            Admin.showExportProgress(false);
        }
    }

    /**
    * Get export options from form
    */
    Admin.getExportOptions = function () {
        const types = [];

        if (Admin.safeGetElement("export-tools")?.checked) {
            types.push("tools");
        }
        if (Admin.safeGetElement("export-gateways")?.checked) {
            types.push("gateways");
        }
        if (Admin.safeGetElement("export-servers")?.checked) {
            types.push("servers");
        }
        if (Admin.safeGetElement("export-prompts")?.checked) {
            types.push("prompts");
        }
        if (Admin.safeGetElement("export-resources")?.checked) {
            types.push("resources");
        }
        if (Admin.safeGetElement("export-roots")?.checked) {
            types.push("roots");
        }

        return {
            types,
            tags: Admin.safeGetElement("export-tags")?.value || "",
            includeInactive:
                Admin.safeGetElement("export-include-inactive")?.checked ||
                false,
            includeDependencies:
                Admin.safeGetElement("export-include-dependencies")?.checked ||
                true,
        };
    }

    /**
    * Show/hide export progress
    */
    Admin.showExportProgress = function (show) {
        const progressEl = Admin.safeGetElement("export-progress");
        if (progressEl) {
            progressEl.classList.toggle("hidden", !show);
            if (show) {
                let progress = 0;
                const progressBar = Admin.safeGetElement("export-progress-bar");
                const interval = setInterval(() => {
                    progress += 10;
                    if (progressBar) {
                        progressBar.style.width = `${Math.min(progress, 90)}%`;
                    }
                    if (progress >= 100) {
                        clearInterval(interval);
                    }
                }, 200);
            }
        }
    }

    /**
    * Handle file selection for import
    */
    Admin.handleFileSelect = function (event) {
        const file = event.target.files[0];
        if (file) {
            Admin.processImportFile(file);
        }
    }

    /**
    * Handle drag over for file drop
    */
    Admin.handleDragOver = function (event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        event.currentTarget.classList.add(
            "border-blue-500",
            "bg-blue-50",
            "dark:bg-blue-900",
        );
    }

    /**
    * Handle drag leave
    */
    Admin.handleDragLeave = function (event) {
        event.preventDefault();
        event.currentTarget.classList.remove(
            "border-blue-500",
            "bg-blue-50",
            "dark:bg-blue-900",
        );
    }

    /**
    * Handle file drop
    */
    Admin.handleFileDrop = function (event) {
        event.preventDefault();
        event.currentTarget.classList.remove(
            "border-blue-500",
            "bg-blue-50",
            "dark:bg-blue-900",
        );

        const files = event.dataTransfer.files;
        if (files.length > 0) {
            Admin.processImportFile(files[0]);
        }
    }

    /**
    * Process selected import file
    */
    Admin.processImportFile = function (file) {
        console.log("📁 Processing import file:", file.name);

        if (!file.type.includes("json")) {
            Admin.showNotification("❌ Please select a JSON file", "error");
            return;
        }

        const reader = new FileReader();
        reader.onload = function (e) {
            try {
                const importData = JSON.parse(e.target.result);

                // Validate basic structure
                if (!importData.version || !importData.entities) {
                    throw new Error("Invalid import file format");
                }

                // Store import data and enable buttons
                Admin.currentImportData = importData;

                const previewBtn = Admin.safeGetElement("import-preview-btn");
                const validateBtn = Admin.safeGetElement("import-validate-btn");
                const executeBtn = Admin.safeGetElement("import-execute-btn");

                if (previewBtn) {
                    previewBtn.disabled = false;
                }
                if (validateBtn) {
                    validateBtn.disabled = false;
                }
                if (executeBtn) {
                    executeBtn.disabled = false;
                }

                // Update drop zone to show file loaded
                Admin.updateDropZoneStatus(file.name, importData);

                Admin.showNotification(`✅ Import file loaded: ${file.name}`, "success");
            } catch (error) {
                console.error("File processing error:", error);
                Admin.showNotification(`❌ Invalid JSON file: ${error.message}`, "error");
            }
        };

        reader.readAsText(file);
    }

    /**
    * Update drop zone to show loaded file
    */
    Admin.updateDropZoneStatus = function (fileName, importData) {
        const dropZone = Admin.safeGetElement("import-drop-zone");
        if (dropZone) {
            const entityCounts = importData.metadata?.entity_counts || {};
            const totalEntities = Object.values(entityCounts).reduce(
                (sum, count) => sum + count,
                0,
            );

            dropZone.innerHTML = `
                <div class="space-y-2">
                    <svg class="mx-auto h-8 w-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                    </svg>
                    <div class="text-sm text-gray-900 dark:text-white font-medium">
                        📁 ${escapeHtml(fileName)}
                    </div>
                    <div class="text-xs text-gray-500 dark:text-gray-400">
                        ${totalEntities} entities • Version ${escapeHtml(importData.version || "unknown")}
                    </div>
                    <button class="text-xs text-blue-600 dark:text-blue-400 hover:underline" onclick="Admin.resetImportFile()">
                        Choose different file
                    </button>
                </div>
            `;
        }
    }

    /**
    * Reset import file selection
    */
    Admin.resetImportFile = function () {
        Admin.currentImportData = null;

        const dropZone = Admin.safeGetElement("import-drop-zone");
        if (dropZone) {
            dropZone.innerHTML = `
                <div class="space-y-2">
                    <svg class="mx-auto h-12 w-12 text-gray-400" stroke="currentColor" fill="none" viewBox="0 0 48 48">
                        <path d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3-3m-3 3l3 3m-3-3V8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    <div class="text-sm text-gray-600 dark:text-gray-300">
                        <span class="font-medium text-blue-600 dark:text-blue-400">Click to upload</span>
                        or drag and drop
                    </div>
                    <p class="text-xs text-gray-500 dark:text-gray-400">JSON export files only</p>
                </div>
            `;
        }

        const previewBtn = Admin.safeGetElement("import-preview-btn");
        const validateBtn = Admin.safeGetElement("import-validate-btn");
        const executeBtn = Admin.safeGetElement("import-execute-btn");

        if (previewBtn) {
            previewBtn.disabled = true;
        }
        if (validateBtn) {
            validateBtn.disabled = true;
        }
        if (executeBtn) {
            executeBtn.disabled = true;
        }

        // Hide status section
        const statusSection = Admin.safeGetElement("import-status-section");
        if (statusSection) {
            statusSection.classList.add("hidden");
        }
    }

    /**
    * Preview import file for selective import
    */
    Admin.previewImport = async function () {
        console.log("🔍 Generating import preview...");

        if (!window.currentImportData) {
            Admin.showNotification("❌ Please select an import file first", "error");
            return;
        }

        try {
            Admin.showImportProgress(true);

            const response = await fetch(
                (window.ROOT_PATH || "") + "/admin/import/preview",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                    body: JSON.stringify({ data: window.currentImportData }),
                },
            );

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || `Preview failed: ${response.statusText}`,
                );
            }

            const result = await response.json();
            Admin.displayImportPreview(result.preview);

            Admin.showNotification("✅ Import preview generated successfully", "success");
        } catch (error) {
            console.error("Import preview error:", error);
            Admin.showNotification(`❌ Preview failed: ${error.message}`, "error");
        } finally {
            Admin.showImportProgress(false);
        }
    }

    /**
    * Handle import (validate or execute)
    */
    Admin.handleImport = async function (dryRun = false) {
        console.log(`🔄 Starting import (dry_run=${dryRun})`);

        if (!window.currentImportData) {
            Admin.showNotification("❌ Please select an import file first", "error");
            return;
        }

        try {
            Admin.showImportProgress(true);

            const conflictStrategy =
                Admin.safeGetElement("import-conflict-strategy")?.value ||
                "update";
            const rekeySecret =
                Admin.safeGetElement("import-rekey-secret")?.value || null;

            const requestData = {
                import_data: window.currentImportData,
                conflict_strategy: conflictStrategy,
                dry_run: dryRun,
                rekey_secret: rekeySecret,
            };

            const response = await fetch(
                (window.ROOT_PATH || "") + "/admin/import/configuration",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                    body: JSON.stringify(requestData),
                },
            );

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || `Import failed: ${response.statusText}`,
                );
            }

            const result = await response.json();
            Admin.displayImportResults(result, dryRun);

            if (!dryRun) {
                // Refresh the current tab data if import was successful
                Admin.refreshCurrentTabData();
            }
        } catch (error) {
            console.error("Import error:", error);
            Admin.showNotification(`❌ Import failed: ${error.message}`, "error");
        } finally {
            Admin.showImportProgress(false);
        }
    }

    /**
    * Display import results
    */
    Admin.displayImportResults = function (result, isDryRun) {
        const statusSection = Admin.safeGetElement("import-status-section");
        if (statusSection) {
            statusSection.classList.remove("hidden");
        }

        const progress = result.progress || {};

        // Update progress bars and counts
        Admin.updateImportCounts(progress);

        // Show messages
        Admin.displayImportMessages(result.errors || [], result.warnings || [], isDryRun);

        const action = isDryRun ? "validation" : "import";
        const statusText = result.status || "completed";
        Admin.showNotification(`✅ ${action} ${statusText}!`, "success");
    }

    /**
    * Update import progress counts
    */
    Admin.updateImportCounts = function (progress) {
        const total = progress.total || 0;
        const processed = progress.processed || 0;
        const created = progress.created || 0;
        const updated = progress.updated || 0;
        const failed = progress.failed || 0;

        Admin.safeGetElement("import-total").textContent = total;
        Admin.safeGetElement("import-created").textContent = created;
        Admin.safeGetElement("import-updated").textContent = updated;
        Admin.safeGetElement("import-failed").textContent = failed;

        // Update progress bar
        const progressBar = Admin.safeGetElement("import-progress-bar");
        const progressText = Admin.safeGetElement("import-progress-text");

        if (progressBar && progressText && total > 0) {
            const percentage = Math.round((processed / total) * 100);
            progressBar.style.width = `${percentage}%`;
            progressText.textContent = `${percentage}%`;
        }
    }

    /**
    * Display import messages (errors and warnings)
    */
    Admin.displayImportMessages = function (errors, warnings, isDryRun) {
        const messagesContainer = Admin.safeGetElement("import-messages");
        if (!messagesContainer) {
            return;
        }

        messagesContainer.innerHTML = "";

        // Show errors
        if (errors.length > 0) {
            const errorDiv = document.createElement("div");
            errorDiv.className =
                "bg-red-100 dark:bg-red-900 border border-red-400 dark:border-red-600 text-red-700 dark:text-red-300 px-4 py-3 rounded";
            errorDiv.innerHTML = `
                <div class="font-bold">❌ Errors (${errors.length})</div>
                <ul class="mt-2 text-sm list-disc list-inside">
                    ${errors
                        .slice(0, 5)
                        .map((error) => `<li>${escapeHtml(error)}</li>`)
                        .join("")}
                    ${errors.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${errors.length - 5} more errors</li>` : ""}
                </ul>
            `;
            messagesContainer.appendChild(errorDiv);
        }

        // Show warnings
        if (warnings.length > 0) {
            const warningDiv = document.createElement("div");
            warningDiv.className =
                "bg-yellow-100 dark:bg-yellow-900 border border-yellow-400 dark:border-yellow-600 text-yellow-700 dark:text-yellow-300 px-4 py-3 rounded";
            const warningTitle = isDryRun ? "🔍 Would Import" : "⚠️ Warnings";
            warningDiv.innerHTML = `
                <div class="font-bold">${warningTitle} (${warnings.length})</div>
                <ul class="mt-2 text-sm list-disc list-inside">
                    ${warnings
                        .slice(0, 5)
                        .map((warning) => `<li>${escapeHtml(warning)}</li>`)
                        .join("")}
                    ${warnings.length > 5 ? `<li class="text-gray-600 dark:text-gray-400">... and ${warnings.length - 5} more warnings</li>` : ""}
                </ul>
            `;
            messagesContainer.appendChild(warningDiv);
        }
    }

    /**
    * Show/hide import progress
    */
    Admin.showImportProgress = function (show) {
        // Disable/enable buttons during operation
        const previewBtn = Admin.safeGetElement("import-preview-btn");
        const validateBtn = Admin.safeGetElement("import-validate-btn");
        const executeBtn = Admin.safeGetElement("import-execute-btn");

        if (previewBtn) {
            previewBtn.disabled = show;
        }
        if (validateBtn) {
            validateBtn.disabled = show;
        }
        if (executeBtn) {
            executeBtn.disabled = show;
        }
    }

    /**
    * Load recent import operations
    */
    Admin.loadRecentImports = async function () {
        try {
            const response = await fetch(
                (window.ROOT_PATH || "") + "/admin/import/status",
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (response.ok) {
                const imports = await response.json();
                console.log("Loaded recent imports:", imports.length);
            }
        } catch (error) {
            console.error("Failed to load recent imports:", error);
        }
    }

    /**
    * Refresh current tab data after successful import
    */
    Admin.refreshCurrentTabData = function () {
        // Find the currently active tab and refresh its data
        const activeTab = document.querySelector(".tab-link.border-indigo-500");
        if (activeTab) {
            const href = activeTab.getAttribute("href");
            if (href === "#catalog") {
                // Refresh servers
                if (typeof window.loadCatalog === "function") {
                    window.loadCatalog();
                }
            } else if (href === "#tools") {
                // Refresh tools (for tool-ops-panel when toolops_enabled=true)
                if (typeof window.loadTools === "function") {
                    window.loadTools();
                }
            } else if (href === "#gateways") {
                // Refresh gateways
                if (typeof window.loadGateways === "function") {
                    window.loadGateways();
                }
            }
            // Add other tab refresh logic as needed
        }
    }

    /**
    * Show notification (simple implementation)
    */
    Admin.showNotification = function (message, type = "info") {
        console.log(`${type.toUpperCase()}: ${message}`);

        // Create a simple toast notification
        const toast = document.createElement("div");
        toast.className = `fixed top-4 right-4 z-50 px-4 py-3 rounded-md text-sm font-medium max-w-sm ${
            type === "success"
                ? "bg-green-100 text-green-800 border border-green-400"
                : type === "error"
                ? "bg-red-100 text-red-800 border border-red-400"
                : "bg-blue-100 text-blue-800 border border-blue-400"
        }`;
        toast.textContent = message;

        document.body.appendChild(toast);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 5000);
    }

    /**
    * Show a modal dialog with copyable content.
    *
    * @param {string} title - The modal title.
    * @param {string} message - The message to display (can be multi-line).
    * @param {string} type - The type of modal: 'success', 'error', or 'info'.
    */
    Admin.showCopyableModal = function (title, message, type = "info") {
        // Remove any existing modal
        const existingModal = Admin.safeGetElement("copyable-modal-overlay");
        if (existingModal) {
            existingModal.remove();
        }

        // Color schemes based on type
        const colors = {
            success: {
                bg: "bg-green-50 dark:bg-green-900/20",
                border: "border-green-500",
                title: "text-green-800 dark:text-green-200",
                icon: `<svg class="h-6 w-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>`,
            },
            error: {
                bg: "bg-red-50 dark:bg-red-900/20",
                border: "border-red-500",
                title: "text-red-800 dark:text-red-200",
                icon: `<svg class="h-6 w-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>`,
            },
            info: {
                bg: "bg-blue-50 dark:bg-blue-900/20",
                border: "border-blue-500",
                title: "text-blue-800 dark:text-blue-200",
                icon: `<svg class="h-6 w-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>`,
            },
        };

        const colorScheme = colors[type] || colors.info;

        // Create modal overlay
        const overlay = document.createElement("div");
        overlay.id = "copyable-modal-overlay";
        overlay.className =
            "fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50";
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                overlay.remove();
            }
        };

        // Create modal content
        const modal = document.createElement("div");
        modal.className = `${colorScheme.bg} border-l-4 ${colorScheme.border} rounded-lg shadow-xl max-w-lg w-full mx-4 overflow-hidden`;

        modal.innerHTML = `
            <div class="p-4">
                <div class="flex items-start">
                    <div class="flex-shrink-0">
                        ${colorScheme.icon}
                    </div>
                    <div class="ml-3 flex-1">
                        <h3 class="text-lg font-medium ${colorScheme.title}">${escapeHtml(title)}</h3>
                        <div class="mt-2">
                            <pre id="copyable-modal-content" class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-white dark:bg-gray-800 p-3 rounded border border-gray-200 dark:border-gray-600 max-h-64 overflow-auto select-all cursor-text">${escapeHtml(message)}</pre>
                        </div>
                        <div class="mt-4 flex justify-end space-x-3">
                            <button id="copyable-modal-copy" class="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                                <svg class="h-4 w-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                </svg>
                                Copy
                            </button>
                            <button id="copyable-modal-close" class="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Add event listeners
        Admin.safeGetElement("copyable-modal-close").onclick = () =>
            overlay.remove();

        Admin.safeGetElement("copyable-modal-copy").onclick = async () => {
            const content = Admin.safeGetElement("copyable-modal-content");
            try {
                await navigator.clipboard.writeText(content.textContent);
                const copyBtn = Admin.safeGetElement("copyable-modal-copy");
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = `<svg class="h-4 w-4 mr-1.5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg> Copied!`;
                setTimeout(() => {
                    copyBtn.innerHTML = originalText;
                }, 2000);
            } catch (err) {
                console.error("Failed to copy:", err);
                // Fallback: select the text
                const range = document.createRange();
                range.selectNodeContents(content);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
            }
        };

        // Close on Escape key
        const handleEscape = (e) => {
            if (e.key === "Escape") {
                overlay.remove();
                document.removeEventListener("keydown", handleEscape);
            }
        };
        document.addEventListener("keydown", handleEscape);
    }

    /**
    * Utility function to get cookie value
    */
    Admin.getCookie = function (name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) {
            return parts.pop().split(";").shift();
        }
        return "";
    }

    // ===================================================================
    // A2A AGENT TEST MODAL FUNCTIONALITY
    // ===================================================================

    Admin.a2aTestFormHandler = null;
    Admin.a2aTestCloseHandler = null;

    /**
    * Open A2A test modal with agent details
    * @param {string} agentId - ID of the agent to test
    * @param {string} agentName - Name of the agent for display
    * @param {string} endpointUrl - Endpoint URL of the agent
    */
    Admin.testA2AAgent = async function (agentId, agentName, endpointUrl) {
        try {
            console.log("Opening A2A test modal for:", agentName);

            // Clean up any existing event listeners
            Admin.cleanupA2ATestModal();

            // Open the modal
            Admin.openModal("a2a-test-modal");

            // Set modal title and description
            const titleElement = Admin.safeGetElement("a2a-test-modal-title");
            const descElement = Admin.safeGetElement("a2a-test-modal-description");
            const agentIdInput = Admin.safeGetElement("a2a-test-agent-id");
            const queryInput = Admin.safeGetElement("a2a-test-query");
            const resultDiv = Admin.safeGetElement("a2a-test-result");

            if (titleElement) {
                titleElement.textContent = `Test A2A Agent: ${agentName}`;
            }
            if (descElement) {
                descElement.textContent = `Endpoint: ${endpointUrl}`;
            }
            if (agentIdInput) {
                agentIdInput.value = agentId;
            }
            if (queryInput) {
                // Reset to default value
                queryInput.value = "Hello from MCP Gateway Admin UI test!";
            }
            if (resultDiv) {
                resultDiv.classList.add("hidden");
            }

            // Set up form submission handler
            const form = Admin.safeGetElement("a2a-test-form");
            if (form) {
                Admin.a2aTestFormHandler = async (e) => {
                    await Admin.handleA2ATestSubmit(e);
                };
                form.addEventListener("submit", Admin.a2aTestFormHandler);
            }

            // Set up close button handler
            const closeButton = Admin.safeGetElement("a2a-test-close");
            if (closeButton) {
                Admin.a2aTestCloseHandler = () => {
                    Admin.handleA2ATestClose();
                };
                closeButton.addEventListener("click", Admin.a2aTestCloseHandler);
            }
        } catch (error) {
            console.error("Error setting up A2A test modal:", error);
            Admin.showErrorMessage("Failed to open A2A test modal");
        }
    }

    /**
    * Handle A2A test form submission
    * @param {Event} e - Form submit event
    */
    Admin.handleA2ATestSubmit = async function (e) {
        e.preventDefault();

        const loading = Admin.safeGetElement("a2a-test-loading");
        const responseDiv = Admin.safeGetElement("a2a-test-response-json");
        const resultDiv = Admin.safeGetElement("a2a-test-result");
        const testButton = Admin.safeGetElement("a2a-test-submit");

        try {
            // Show loading
            if (loading) {
                loading.classList.remove("hidden");
            }
            if (resultDiv) {
                resultDiv.classList.add("hidden");
            }
            if (testButton) {
                testButton.disabled = true;
                testButton.textContent = "Testing...";
            }

            const agentId = Admin.safeGetElement("a2a-test-agent-id")?.value;
            const query =
                Admin.safeGetElement("a2a-test-query")?.value ||
                "Hello from MCP Gateway Admin UI test!";

            if (!agentId) {
                throw new Error("Agent ID is missing");
            }

            // Get auth token
            const token = await Admin.getAuthToken();
            const headers = { "Content-Type": "application/json" };
            if (token) {
                headers.Authorization = `Bearer ${token}`;
            } else {
                // Fallback to basic auth if JWT not available
                console.warn("JWT token not found, attempting basic auth fallback");
                headers.Authorization = "Basic " + btoa("admin:changeme");
            }

            // Send test request with user query
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH}/admin/a2a/${agentId}/test`,
                {
                    method: "POST",
                    headers,
                    body: JSON.stringify({ query }),
                },
                window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
            );

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            // Display result
            const isSuccess = result.success && !result.error;
            const icon = isSuccess ? "✅" : "❌";
            const title = isSuccess ? "Test Successful" : "Test Failed";

            let bodyHtml = "";
            if (result.result) {
                bodyHtml = `<details open>
                    <summary class='cursor-pointer font-medium'>Response</summary>
                    <pre class="text-sm px-4 max-h-96 dark:bg-gray-800 dark:text-gray-100 overflow-auto whitespace-pre-wrap">${escapeHtml(JSON.stringify(result.result, null, 2))}</pre>
                </details>`;
            }

            responseDiv.innerHTML = `
                <div class="p-3 rounded ${isSuccess ? "bg-green-50 dark:bg-green-900/20" : "bg-red-50 dark:bg-red-900/20"}">
                    <h4 class="font-bold ${isSuccess ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}">${icon} ${title}</h4>
                    ${result.error ? `<p class="text-red-600 dark:text-red-400 mt-2">Error: ${escapeHtml(result.error)}</p>` : ""}
                    ${bodyHtml}
                </div>
            `;
        } catch (error) {
            console.error("A2A test error:", error);
            if (responseDiv) {
                responseDiv.innerHTML = `<div class="text-red-600 dark:text-red-400 p-4 bg-red-50 dark:bg-red-900/20 rounded">❌ Error: ${escapeHtml(error.message)}</div>`;
            }
        } finally {
            if (loading) {
                loading.classList.add("hidden");
            }
            if (resultDiv) {
                resultDiv.classList.remove("hidden");
            }
            if (testButton) {
                testButton.disabled = false;
                testButton.textContent = "Test Agent";
            }
        }
    }

    /**
    * Handle A2A test modal close
    */
    Admin.handleA2ATestClose = function () {
        try {
            // Reset form
            const form = Admin.safeGetElement("a2a-test-form");
            if (form) {
                form.reset();
            }

            // Clear response
            const responseDiv = Admin.safeGetElement("a2a-test-response-json");
            const resultDiv = Admin.safeGetElement("a2a-test-result");
            if (responseDiv) {
                responseDiv.innerHTML = "";
            }
            if (resultDiv) {
                resultDiv.classList.add("hidden");
            }

            // Close modal
            Admin.closeModal("a2a-test-modal");
        } catch (error) {
            console.error("Error closing A2A test modal:", error);
        }
    }

    /**
    * Clean up A2A test modal event listeners
    */
    Admin.cleanupA2ATestModal = function () {
        try {
            const form = Admin.safeGetElement("a2a-test-form");
            const closeButton = Admin.safeGetElement("a2a-test-close");

            if (form && a2aTestFormHandler) {
                form.removeEventListener("submit", a2aTestFormHandler);
                a2aTestFormHandler = null;
            }

            if (closeButton && a2aTestCloseHandler) {
                closeButton.removeEventListener("click", a2aTestCloseHandler);
                a2aTestCloseHandler = null;
            }

            console.log("✓ Cleaned up A2A test modal listeners");
        } catch (error) {
            console.error("Error cleaning up A2A test modal:", error);
        }
    }

    /**
    * Token Management Functions
    */

    /**
    * Load tokens list from API
    */
    Admin.loadTokensList = async function () {
        const tokensList = Admin.safeGetElement("tokens-list");
        if (!tokensList) {
            return;
        }

        try {
            tokensList.innerHTML =
                '<p class="text-gray-500 dark:text-gray-400">Loading tokens...</p>';

            const response = await Admin.fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
                headers: {
                    Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    "Content-Type": "application/json",
                },
            });

            if (!response.ok) {
                throw new Error(`Failed to load tokens: (${response.status})`);
            }

            const data = await response.json();
            Admin.displayTokensList(data.tokens);
        } catch (error) {
            console.error("Error loading tokens:", error);
            tokensList.innerHTML =
                '<div class="text-red-500">Error loading tokens: ' +
                Admin.escapeHtml(error.message) +
                "</div>";
        }
    }

    /**
    * Display tokens list in the UI
    */
    Admin.displayTokensList = function (tokens) {
        const tokensList = Admin.safeGetElement("tokens-list");
        if (!tokensList) {
            return;
        }

        if (!tokens || tokens.length === 0) {
            tokensList.innerHTML =
                '<p class="text-gray-500 dark:text-gray-400">No tokens found. Create your first token above.</p>';
            return;
        }

        let tokensHTML = "";
        tokens.forEach((token) => {
            const expiresText = token.expires_at
                ? new Date(token.expires_at).toLocaleDateString()
                : "Never";
            const createdText = token.created_at
                ? new Date(token.created_at).toLocaleDateString()
                : "Never";
            const lastUsedText = token.last_used
                ? new Date(token.last_used).toLocaleDateString()
                : "Never";
            const statusBadge = token.is_active
                ? '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100">Active</span>'
                : '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100">Inactive</span>';

            // Build scope badges
            const teamName = token.team_id ? Admin.getTeamNameById(token.team_id) : null;
            const teamBadge = teamName
                ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-800 dark:text-purple-100">Team: ${escapeHtml(teamName)}</span>`
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">Public-only</span>';

            const ipBadge =
                token.ip_restrictions && token.ip_restrictions.length > 0
                    ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-100">${token.ip_restrictions.length} IP${token.ip_restrictions.length > 1 ? "s" : ""}</span>`
                    : "";

            const serverBadge = token.server_id
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-800 dark:text-blue-100">Server-scoped</span>'
                : "";

            // Safely encode token data for data attribute (URL encoding preserves all characters)
            const tokenDataEncoded = encodeURIComponent(JSON.stringify(token));

            tokensHTML += `
                <div class="border border-gray-200 dark:border-gray-600 rounded-lg p-4 mb-4">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <div class="flex items-center flex-wrap gap-2">
                                <h4 class="text-lg font-medium text-gray-900 dark:text-white">${escapeHtml(token.name)}</h4>
                                ${statusBadge}
                                ${teamBadge}
                                ${serverBadge}
                                ${ipBadge}
                            </div>
                            ${token.description ? `<p class="text-sm text-gray-600 dark:text-gray-400 mt-1">${escapeHtml(token.description)}</p>` : ""}
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3 text-sm text-gray-500 dark:text-gray-400">
                                <div>
                                    <span class="font-medium">Created:</span> ${createdText}
                                </div>
                                <div>
                                    <span class="font-medium">Expires:</span> ${expiresText}
                                </div>
                                <div>
                                    <span class="font-medium">Last Used:</span> ${lastUsedText}
                                </div>
                            </div>
                            ${token.server_id ? `<div class="mt-2 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Scoped to Server:</span> ${escapeHtml(token.server_id)}</div>` : ""}
                            ${token.resource_scopes && token.resource_scopes.length > 0 ? `<div class="mt-1 text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Permissions:</span> ${token.resource_scopes.map((p) => Admin.escapeHtml(p)).join(", ")}</div>` : ""}
                        </div>
                        <div class="flex flex-wrap gap-2 ml-4">
                            <button
                                data-action="token-details"
                                data-token="${tokenDataEncoded}"
                                class="px-3 py-1 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 border border-gray-300 dark:border-gray-600 hover:border-gray-500 dark:hover:border-gray-400 rounded-md"
                            >
                                Details
                            </button>
                            <button
                                data-action="token-usage"
                                data-token-id="${escapeHtml(token.id)}"
                                class="px-3 py-1 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-600 hover:border-blue-500 dark:hover:border-blue-400 rounded-md"
                            >
                                Usage Stats
                            </button>
                            <button
                                data-action="token-revoke"
                                data-token-id="${escapeHtml(token.id)}"
                                data-token-name="${escapeHtml(token.name)}"
                                class="px-3 py-1 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 border border-red-300 dark:border-red-600 hover:border-red-500 dark:hover:border-red-400 rounded-md"
                            >
                                Revoke
                            </button>
                        </div>
                    </div>
                </div>
            `;
        });

        tokensList.innerHTML = tokensHTML;

        // Attach event handlers via delegation (avoids inline JS and XSS risks)
        Admin.setupTokenListEventHandlers(tokensList);
    }

    /**
    * Set up event handlers for token list buttons using event delegation.
    * This avoids inline onclick handlers and associated XSS risks.
    * Uses a one-time guard to prevent duplicate handlers on repeated renders.
    * @param {HTMLElement} container - The tokens list container element
    */
    Admin.setupTokenListEventHandlers = function (container) {
        // Guard against duplicate handlers on repeated renders
        if (container.dataset.handlersAttached === "true") {
            return;
        }
        container.dataset.handlersAttached = "true";

        container.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-action]");
            if (!button) {
                return;
            }

            const action = button.dataset.action;

            if (action === "token-details") {
                const tokenData = button.dataset.token;
                if (tokenData) {
                    try {
                        const token = JSON.parse(decodeURIComponent(tokenData));
                        Admin.showTokenDetailsModal(token);
                    } catch (e) {
                        console.error("Failed to parse token data:", e);
                    }
                }
            } else if (action === "token-usage") {
                const tokenId = button.dataset.tokenId;
                if (tokenId) {
                    Admin.viewTokenUsage(tokenId);
                }
            } else if (action === "token-revoke") {
                const tokenId = button.dataset.tokenId;
                const tokenName = button.dataset.tokenName;
                if (tokenId) {
                    Admin.revokeToken(tokenId, tokenName || "");
                }
            }
        });
    }

    /**
    * Get the currently selected team ID from the team selector
    */
    Admin.getCurrentTeamId = function () {
        // First, try to get from Alpine.js component (most reliable)
        const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
        if (
            teamSelector &&
            teamSelector._x_dataStack &&
            teamSelector._x_dataStack[0]
        ) {
            const alpineData = teamSelector._x_dataStack[0];
            const selectedTeam = alpineData.selectedTeam;

            // Return null if empty string or falsy (means "All Teams")
            if (!selectedTeam || selectedTeam === "" || selectedTeam === "all") {
                return null;
            }

            return selectedTeam;
        }

        // Fallback: check URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const teamId = urlParams.get("team_id");

        if (!teamId || teamId === "" || teamId === "all") {
            return null;
        }

        return teamId;
    }

    /**
    * Get the currently selected team name from Alpine.js team selector
    * @returns {string|null} Team name or null if not found
    */
    Admin.getCurrentTeamName = function () {
        const currentTeamId = Admin.getCurrentTeamId();

        if (!currentTeamId) {
            return null;
        }

        // Method 1: Try from window.USERTEAMSDATA (most reliable)
        if (window.USERTEAMSDATA && Array.isArray(window.USERTEAMSDATA)) {
            const teamObj = window.USERTEAMSDATA.find(
                (t) => t.id === currentTeamId,
            );
            if (teamObj) {
                // Return the personal team name format if it's a personal team
                return teamObj.ispersonal ? `${teamObj.name}` : teamObj.name;
            }
        }

        // Method 2: Try from Alpine.js component
        const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
        if (
            teamSelector &&
            teamSelector._x_dataStack &&
            teamSelector._x_dataStack[0]
        ) {
            const alpineData = teamSelector._x_dataStack[0];

            // Get the selected team name directly from Alpine
            if (
                alpineData.selectedTeamName &&
                alpineData.selectedTeamName !== "All Teams"
            ) {
                return alpineData.selectedTeamName;
            }

            // Try to find in teams array
            if (alpineData.teams && Array.isArray(alpineData.teams)) {
                const selectedTeamObj = alpineData.teams.find(
                    (t) => t.id === currentTeamId,
                );
                if (selectedTeamObj) {
                    return selectedTeamObj.ispersonal
                        ? `${selectedTeamObj.name}`
                        : selectedTeamObj.name;
                }
            }
        }

        // Fallback: return the team ID if name not found
        return currentTeamId;
    }

    /**
    * Update the team scoping warning/info visibility based on team selection
    */
    Admin.updateTeamScopingWarning = function () {
        const warningDiv = Admin.safeGetElement("team-scoping-warning");
        const infoDiv = Admin.safeGetElement("team-scoping-info");
        const teamNameSpan = Admin.safeGetElement("selected-team-name");

        if (!warningDiv || !infoDiv) {
            return;
        }

        const currentTeamId = Admin.getCurrentTeamId();

        if (!currentTeamId) {
            // Show warning when "All Teams" is selected
            warningDiv.classList.remove("hidden");
            infoDiv.classList.add("hidden");
        } else {
            // Hide warning and show info when a specific team is selected
            warningDiv.classList.add("hidden");
            infoDiv.classList.remove("hidden");

            // Get team name to display
            const teamName = Admin.getCurrentTeamName() || currentTeamId;
            if (teamNameSpan) {
                teamNameSpan.textContent = teamName;
            }
        }
    }

    /**
    * Monitor team selection changes using Alpine.js watcher
    */
    Admin.initializeTeamScopingMonitor = function () {
        // Use Alpine.js $watch to monitor team selection changes
        document.addEventListener("alpine:init", () => {
            const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
            if (teamSelector && window.Alpine) {
                // The Alpine component will notify us of changes
                const checkInterval = setInterval(() => {
                    Admin.updateTeamScopingWarning();
                }, 500); // Check every 500ms

                // Store interval ID for cleanup if needed
                Admin._teamMonitorInterval = checkInterval;
            }
        });

        // Also update when tokens tab is shown
        document.addEventListener("DOMContentLoaded", () => {
            const tokensTab = document.querySelector('a[href="#tokens"]');
            if (tokensTab) {
                tokensTab.addEventListener("click", () => {
                    setTimeout(updateTeamScopingWarning, 100);
                });
            }
        });
    }

    /**
    * Set up create token form handling
    */
    Admin.setupCreateTokenForm = function () {
        const form = Admin.safeGetElement("create-token-form");
        if (!form) {
            return;
        }

        // Update team scoping warning/info display
        Admin.updateTeamScopingWarning();

        form.addEventListener("submit", async (e) => {
            e.preventDefault();

            // User can create public-only tokens in that context
            await Admin.createToken(form);
        });
    }

    /**
    * Validate an IP address or CIDR notation string.
    * @param {string} value - The IP/CIDR string to validate
    * @returns {boolean} True if valid IPv4/IPv6 address or CIDR notation
    */
    Admin.isValidIpOrCidr = function (value) {
        if (!value || typeof value !== "string") {
            return false;
        }

        const trimmed = value.trim();

        // IPv4 with optional CIDR (e.g., 192.168.1.0/24 or 192.168.1.1)
        const ipv4Segment = "(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)";
        const ipv4Pattern = new RegExp(
            `^(?:${ipv4Segment}\\.){3}${ipv4Segment}(?:\\/(?:[0-9]|[1-2][0-9]|3[0-2]))?$`,
        );

        // IPv6 with optional CIDR (supports compressed forms and IPv4-embedded)
        const ipv6Segment = "[0-9A-Fa-f]{1,4}";
        const ipv4Embedded = `(?:${ipv4Segment}\\.){3}${ipv4Segment}`;
        const ipv6Pattern = new RegExp(
            "^(?:" +
                `(?:${ipv6Segment}:){7}${ipv6Segment}|` +
                `(?:${ipv6Segment}:){1,7}:|` +
                `(?:${ipv6Segment}:){1,6}:${ipv6Segment}|` +
                `(?:${ipv6Segment}:){1,5}(?::${ipv6Segment}){1,2}|` +
                `(?:${ipv6Segment}:){1,4}(?::${ipv6Segment}){1,3}|` +
                `(?:${ipv6Segment}:){1,3}(?::${ipv6Segment}){1,4}|` +
                `(?:${ipv6Segment}:){1,2}(?::${ipv6Segment}){1,5}|` +
                `${ipv6Segment}:(?::${ipv6Segment}){1,6}|` +
                `:(?::${ipv6Segment}){1,7}|` +
                "::|" +
                `(?:${ipv6Segment}:){1,4}:${ipv4Embedded}|` +
                `::(?:ffff(?::0{1,4}){0,1}:)?${ipv4Embedded}` +
                ")(?:\\/(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-8]))?$",
        );

        return ipv4Pattern.test(trimmed) || ipv6Pattern.test(trimmed);
    }

    /**
    * Validate a permission scope string.
    * Permissions should follow format: resource.action (e.g., tools.read, resources.write)
    * Also allows wildcard (*) for full access.
    * @param {string} value - The permission string to validate
    * @returns {boolean} True if valid permission format
    */
    Admin.isValidPermission = function (value) {
        if (!value || typeof value !== "string") {
            return false;
        }

        const trimmed = value.trim();

        // Allow wildcard
        if (trimmed === "*") {
            return true;
        }

        // Permission format: resource.action (alphanumeric with underscores, dot-separated)
        // Examples: tools.read, resources.write, prompts.list, tools.execute
        const permissionPattern = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/i;

        return permissionPattern.test(trimmed);
    }

    /**
    * Create a new API token
    */
    // Create a new API token
    Admin.createToken = async function (form) {
        const formData = new FormData(form);
        const submitButton = form.querySelector('button[type="submit"]');
        const originalText = submitButton.textContent;

        try {
            submitButton.textContent = "Creating...";
            submitButton.disabled = true;

            // Get current team ID (null means "All Teams" = public-only token)
            const currentTeamId = Admin.getCurrentTeamId();

            // Build request payload
            const payload = {
                name: formData.get("name"),
                description: formData.get("description") || null,
                expires_in_days: formData.get("expires_in_days")
                    ? parseInt(formData.get("expires_in_days"))
                    : null,
                tags: [],
                team_id: currentTeamId || null, // null = public-only token
            };

            // Add scoping if provided
            const scope = {};

            if (formData.get("server_id")) {
                scope.server_id = formData.get("server_id");
            }

            // Parse and validate IP restrictions
            if (formData.get("ip_restrictions")) {
                const ipRestrictions = formData.get("ip_restrictions").trim();
                if (ipRestrictions) {
                    const ipList = ipRestrictions
                        .split(",")
                        .map((ip) => ip.trim())
                        .filter((ip) => ip.length > 0);

                    // Validate each IP/CIDR
                    const invalidIps = ipList.filter((ip) => !isValidIpOrCidr(ip));
                    if (invalidIps.length > 0) {
                        throw new Error(
                            `Invalid IP address or CIDR format: ${invalidIps.join(", ")}. ` +
                                "Use formats like 192.168.1.0/24 or 10.0.0.1",
                        );
                    }
                    scope.ip_restrictions = ipList;
                } else {
                    scope.ip_restrictions = [];
                }
            } else {
                scope.ip_restrictions = [];
            }

            // Parse and validate permissions
            if (formData.get("permissions")) {
                const permList = formData
                    .get("permissions")
                    .split(",")
                    .map((p) => p.trim())
                    .filter((p) => p.length > 0);

                // Validate each permission
                const invalidPerms = permList.filter((p) => !isValidPermission(p));
                if (invalidPerms.length > 0) {
                    throw new Error(
                        `Invalid permission format: ${invalidPerms.join(", ")}. ` +
                            "Use formats like tools.read, resources.write, or * for full access",
                    );
                }
                scope.permissions = permList;
            } else {
                scope.permissions = [];
            }

            scope.time_restrictions = {};
            scope.usage_limits = {};
            payload.scope = scope;

            const response = await Admin.fetchWithTimeout(`${window.ROOT_PATH}/tokens`, {
                method: "POST",
                headers: {
                    Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    `Failed to create token (${response.status})`,
                );
                throw new Error(errorMsg);
            }

            const result = await response.json();
            Admin.showTokenCreatedModal(result);
            form.reset();
            await Admin.loadTokensList();

            // Show appropriate success message
            const tokenType = currentTeamId ? "team-scoped" : "public-only";
            Admin.showNotification(`${tokenType} token created successfully!`, "success");
        } catch (error) {
            console.error("Error creating token:", error);
            Admin.showNotification(`Error creating token: ${error.message}`, "error");
        } finally {
            submitButton.textContent = originalText;
            submitButton.disabled = false;
        }
    }

    /**
    * Show modal with new token (one-time display)
    */
    Admin.showTokenCreatedModal = function (tokenData) {
        const modal = document.createElement("div");
        modal.className =
            "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
        modal.innerHTML = `
            <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-lg shadow-lg rounded-md bg-white dark:bg-gray-800">
                <div class="mt-3">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Created Successfully</h3>
                        <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                            </svg>
                        </button>
                    </div>

                    <div class="bg-yellow-50 dark:bg-yellow-900 border border-yellow-200 dark:border-yellow-700 rounded-md p-4 mb-4">
                        <div class="flex">
                            <div class="flex-shrink-0">
                                <svg class="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                                </svg>
                            </div>
                            <div class="ml-3">
                                <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                                    Important: Save your token now!
                                </h3>
                                <div class="mt-2 text-sm text-yellow-700 dark:text-yellow-300">
                                    This is the only time you will be able to see this token. Make sure to save it in a secure location.
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                            Your API Token:
                        </label>
                        <div class="flex">
                            <input
                                type="text"
                                value="${tokenData.access_token}"
                                readonly
                                class="flex-1 p-2 border border-gray-300 dark:border-gray-600 rounded-l-md bg-gray-50 dark:bg-gray-700 text-sm font-mono"
                                id="new-token-value"
                            />
                            <button
                                onclick="Admin.copyToClipboard('new-token-value')"
                                class="px-3 py-2 bg-indigo-600 text-white text-sm rounded-r-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            >
                                Copy
                            </button>
                        </div>
                    </div>

                    <div class="text-sm text-gray-600 dark:text-gray-400 mb-4">
                        <strong>Token Name:</strong> ${escapeHtml(tokenData.token.name || "Unnamed Token")}<br/>
                        <strong>Expires:</strong> ${tokenData.token.expires_at ? new Date(tokenData.token.expires_at).toLocaleDateString() : "Never"}
                    </div>

                    <div class="flex justify-end">
                        <button
                            onclick="this.closest('.fixed').remove()"
                            class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                            I've Saved It
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Focus the token input for easy selection
        const tokenInput = modal.querySelector("#new-token-value");
        tokenInput.focus();
        tokenInput.select();
    }

    /**
    * Copy text to clipboard
    */
    Admin.copyToClipboard = function (elementId) {
        const element = Admin.safeGetElement(elementId);
        if (element) {
            element.select();
            document.execCommand("copy");
            Admin.showNotification("Token copied to clipboard", "success");
        }
    }

    /**
    * Revoke a token
    */
    Admin.revokeToken = async function (tokenId, tokenName) {
        if (
            !confirm(
                `Are you sure you want to revoke the token "${tokenName}"? This action cannot be undone.`,
            )
        ) {
            return;
        }

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH}/tokens/${tokenId}`,
                {
                    method: "DELETE",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        reason: "Revoked by user via admin interface",
                    }),
                },
            );

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    `Failed to revoke token: ${response.status}`,
                );
                throw new Error(errorMsg);
            }

            Admin.showNotification("Token revoked successfully", "success");
            await Admin.loadTokensList();
        } catch (error) {
            console.error("Error revoking token:", error);
            Admin.showNotification(`Error revoking token: ${error.message}`, "error");
        }
    }

    /**
    * View token usage statistics
    */
    Admin.viewTokenUsage = async function (tokenId) {
        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH}/tokens/${tokenId}/usage`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                },
            );

            if (!response.ok) {
                throw new Error(`Failed to load usage stats: ${response.status}`);
            }

            const stats = await response.json();
            Admin.showUsageStatsModal(stats);
        } catch (error) {
            console.error("Error loading usage stats:", error);
            Admin.showNotification(
                `Error loading usage stats: ${error.message}`,
                "error",
            );
        }
    }

    /**
    * Show usage statistics modal
    */
    Admin.showUsageStatsModal = function (stats) {
        const modal = document.createElement("div");
        modal.className =
            "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
        modal.innerHTML = `
            <div class="relative top-20 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Usage Statistics (Last ${stats.period_days} Days)</h3>
                    <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    <div class="bg-blue-50 dark:bg-blue-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-blue-600 dark:text-blue-300">${stats.total_requests}</div>
                        <div class="text-sm text-blue-600 dark:text-blue-400">Total Requests</div>
                    </div>
                    <div class="bg-green-50 dark:bg-green-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-green-600 dark:text-green-300">${stats.successful_requests}</div>
                        <div class="text-sm text-green-600 dark:text-green-400">Successful</div>
                    </div>
                    <div class="bg-red-50 dark:bg-red-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-red-600 dark:text-red-300">${stats.blocked_requests}</div>
                        <div class="text-sm text-red-600 dark:text-red-400">Blocked</div>
                    </div>
                    <div class="bg-purple-50 dark:bg-purple-900 p-4 rounded-lg">
                        <div class="text-2xl font-bold text-purple-600 dark:text-purple-300">${Math.round(stats.success_rate * 100)}%</div>
                        <div class="text-sm text-purple-600 dark:text-purple-400">Success Rate</div>
                    </div>
                </div>

                <div class="mb-4">
                    <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Average Response Time</h4>
                    <div class="text-lg text-gray-700 dark:text-gray-300">${stats.average_response_time_ms}ms</div>
                </div>

                ${
                    stats.top_endpoints && stats.top_endpoints.length > 0
                        ? `
                    <div class="mb-4">
                        <h4 class="text-md font-medium text-gray-900 dark:text-white mb-2">Top Endpoints</h4>
                        <div class="space-y-2">
                            ${stats.top_endpoints
                                .map(
                                    ([endpoint, count]) => `
                                <div class="flex justify-between items-center p-2 bg-gray-50 dark:bg-gray-700 rounded">
                                    <span class="font-mono text-sm">${escapeHtml(endpoint)}</span>
                                    <span class="text-sm font-medium">${count} requests</span>
                                </div>
                            `,
                                )
                                .join("")}
                        </div>
                    </div>
                `
                        : ""
                }

                <div class="flex justify-end">
                    <button
                        onclick="this.closest('.fixed').remove()"
                        class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500"
                    >
                        Close
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
    }

    /**
    * Get team name by team ID from cached team data
    * @param {string} teamId - The team ID to look up
    * @returns {string} Team name or truncated ID if not found
    */
    Admin.getTeamNameById = function (teamId) {
        if (!teamId) {
            return null;
        }

        // Try from window.USERTEAMSDATA (most reliable source)
        if (window.USERTEAMSDATA && Array.isArray(window.USERTEAMSDATA)) {
            const teamObj = window.USERTEAMSDATA.find((t) => t.id === teamId);
            if (teamObj) {
                return teamObj.name;
            }
        }

        // Try from Alpine.js component
        const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
        if (
            teamSelector &&
            teamSelector._x_dataStack &&
            teamSelector._x_dataStack[0]
        ) {
            const alpineData = teamSelector._x_dataStack[0];
            if (alpineData.teams && Array.isArray(alpineData.teams)) {
                const teamObj = alpineData.teams.find((t) => t.id === teamId);
                if (teamObj) {
                    return teamObj.name;
                }
            }
        }

        // Fallback: return truncated ID
        return teamId.substring(0, 8) + "...";
    }

    /**
    * Show token details modal with full token information
    * @param {Object} token - The token object with all fields
    */
    Admin.showTokenDetailsModal = function (token) {
        const formatDate = (dateStr) => {
            if (!dateStr) {
                return "Never";
            }
            return new Date(dateStr).toLocaleString();
        };

        const formatList = (list) => {
            if (!list || list.length === 0) {
                return "None";
            }
            return list
                .map((item) => `<li class="ml-4">• ${escapeHtml(item)}</li>`)
                .join("");
        };

        const formatJson = (obj) => {
            if (!obj || Object.keys(obj).length === 0) {
                return "None";
            }
            return `<pre class="bg-gray-100 dark:bg-gray-700 p-2 rounded text-xs overflow-x-auto">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`;
        };

        const teamName = token.team_id ? Admin.getTeamNameById(token.team_id) : null;
        const statusClass = token.is_active
            ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100"
            : "bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100";
        const statusText = token.is_active ? "Active" : "Inactive";

        const modal = document.createElement("div");
        modal.className =
            "fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50";
        modal.innerHTML = `
            <div class="relative top-10 mx-auto p-5 border w-11/12 max-w-2xl shadow-lg rounded-md bg-white dark:bg-gray-800 mb-10">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">Token Details</h3>
                    <button data-action="close-modal" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Basic Information -->
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Basic Information</h4>
                    <div class="grid grid-cols-1 gap-2 text-sm">
                        <div class="flex items-center">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">ID:</span>
                            <code class="bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded text-xs flex-1 overflow-hidden text-ellipsis">${escapeHtml(token.id)}</code>
                            <button data-action="copy-id" data-copy-value="${escapeHtml(token.id)}"
                                    class="ml-2 px-2 py-0.5 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 border border-blue-300 dark:border-blue-600 rounded">
                                Copy
                            </button>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Name:</span>
                            <span class="text-gray-900 dark:text-white">${escapeHtml(token.name)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Description:</span>
                            <span class="text-gray-600 dark:text-gray-400">${token.description ? Admin.escapeHtml(token.description) : "None"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Created by:</span>
                            <span class="text-gray-900 dark:text-white">${escapeHtml(token.user_email || "Unknown")}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Team:</span>
                            <span class="text-gray-900 dark:text-white">${teamName ? `${escapeHtml(teamName)} <code class="text-xs text-gray-500">(${escapeHtml(token.team_id.substring(0, 8))}...)</code>` : "None (Public-only)"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Created:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.created_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Expires:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.expires_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Last Used:</span>
                            <span class="text-gray-600 dark:text-gray-400">${formatDate(token.last_used)}</span>
                        </div>
                        <div class="flex items-center">
                            <span class="font-medium text-gray-700 dark:text-gray-300 w-28">Status:</span>
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                </div>

                <!-- Scope & Restrictions -->
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Scope & Restrictions</h4>
                    <div class="grid grid-cols-1 gap-3 text-sm">
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Server:</span>
                            <span class="ml-2 text-gray-600 dark:text-gray-400">${token.server_id ? Admin.escapeHtml(token.server_id) : "All servers"}</span>
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Permissions:</span>
                            ${
                                token.resource_scopes &&
                                token.resource_scopes.length > 0
                                    ? `<ul class="mt-1 text-gray-600 dark:text-gray-400">${formatList(token.resource_scopes)}</ul>`
                                    : '<span class="ml-2 text-gray-600 dark:text-gray-400">All (no restrictions)</span>'
                            }
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">IP Restrictions:</span>
                            ${
                                token.ip_restrictions &&
                                token.ip_restrictions.length > 0
                                    ? `<ul class="mt-1 text-gray-600 dark:text-gray-400">${formatList(token.ip_restrictions)}</ul>`
                                    : '<span class="ml-2 text-gray-600 dark:text-gray-400">None</span>'
                            }
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Time Restrictions:</span>
                            <div class="mt-1">${formatJson(token.time_restrictions)}</div>
                        </div>
                        <div>
                            <span class="font-medium text-gray-700 dark:text-gray-300">Usage Limits:</span>
                            <div class="mt-1">${formatJson(token.usage_limits)}</div>
                        </div>
                    </div>
                </div>

                <!-- Tags -->
                ${
                    token.tags && token.tags.length > 0
                        ? `
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-gray-900 dark:text-white mb-3 border-b border-gray-200 dark:border-gray-600 pb-2">Tags</h4>
                    <div class="flex flex-wrap gap-2">
                        ${token.tags
                            .map((tag) => {
                                const raw =
                                    typeof tag === "object" && tag !== null
                                        ? tag.id || tag.label || JSON.stringify(tag)
                                        : tag;
                                return `<span class="px-2 py-1 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-xs rounded">${escapeHtml(raw)}</span>`;
                            })
                            .join("")}
                    </div>
                </div>
                `
                        : ""
                }

                <!-- Revocation Details (if revoked) -->
                ${
                    token.is_revoked
                        ? `
                <div class="mb-6">
                    <h4 class="text-md font-semibold text-red-600 dark:text-red-400 mb-3 border-b border-red-200 dark:border-red-600 pb-2">Revocation Details</h4>
                    <div class="grid grid-cols-1 gap-2 text-sm bg-red-50 dark:bg-red-900/20 p-3 rounded">
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Revoked at:</span>
                            <span class="text-red-600 dark:text-red-400">${formatDate(token.revoked_at)}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Revoked by:</span>
                            <span class="text-red-600 dark:text-red-400">${token.revoked_by ? Admin.escapeHtml(token.revoked_by) : "Unknown"}</span>
                        </div>
                        <div class="flex">
                            <span class="font-medium text-red-700 dark:text-red-300 w-28">Reason:</span>
                            <span class="text-red-600 dark:text-red-400">${token.revocation_reason ? Admin.escapeHtml(token.revocation_reason) : "No reason provided"}</span>
                        </div>
                    </div>
                </div>
                `
                        : ""
                }

                <div class="flex justify-end">
                    <button
                        data-action="close-modal"
                        class="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500"
                    >
                        Close
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Attach event handlers (avoids inline JS and XSS risks)
        modal.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-action]");
            if (!button) {
                return;
            }

            const action = button.dataset.action;

            if (action === "close-modal") {
                modal.remove();
            } else if (action === "copy-id") {
                const value = button.dataset.copyValue;
                if (value) {
                    navigator.clipboard.writeText(value).then(() => {
                        button.textContent = "Copied!";
                        setTimeout(() => {
                            button.textContent = "Copy";
                        }, 1500);
                    });
                }
            }
        });
    }

    /**
    * Get auth token from storage or user input
    */
    Admin.getAuthToken = async function () {
        // Use the same authentication method as the rest of the admin interface
        let token = Admin.getCookie("jwt_token");

        // Try alternative cookie names if primary not found
        if (!token) {
            token = Admin.getCookie("token");
        }

        // Fallback to localStorage for compatibility
        if (!token) {
            token = localStorage.getItem("auth_token");
        }
        return token || "";
    }

    /**
    * Fetch helper that always includes auth context.
    * Ensures HTTP-only cookies are sent even when JS cannot read them.
    */
    Admin.fetchWithAuth = async function (url, options = {}) {
        const opts = { ...options };
        // Always send same-origin cookies unless caller overrides explicitly
        opts.credentials = options.credentials || "same-origin";

        // Clone headers to avoid mutating caller-provided object
        const headers = new Headers(options.headers || {});
        const token = await Admin.getAuthToken();
        if (token) {
            headers.set("Authorization", `Bearer ${token}`);
        }
        opts.headers = headers;

        return fetch(url, opts);
    }

    // ===================================================================
    // USER MANAGEMENT FUNCTIONS
    // ===================================================================

    /**
    * Show user edit modal and load edit form
    */
    Admin.showUserEditModal = function (userEmail) {
        const modal = Admin.safeGetElement("user-edit-modal");
        if (modal) {
            modal.style.display = "block";
            modal.classList.remove("hidden");
        }
    }

    /**
    * Hide user edit modal
    */
    Admin.hideUserEditModal = function () {
        const modal = Admin.safeGetElement("user-edit-modal");
        if (modal) {
            modal.style.display = "none";
            modal.classList.add("hidden");
        }
    }

    /**
    * Close modal when clicking outside of it
    */
    document.addEventListener("DOMContentLoaded", function () {
        const userModal = Admin.safeGetElement("user-edit-modal");
        if (userModal) {
            userModal.addEventListener("click", function (event) {
                if (event.target === userModal) {
                    Admin.hideUserEditModal();
                }
            });
        }

        const teamModal = Admin.safeGetElement("team-edit-modal");
        if (teamModal) {
            teamModal.addEventListener("click", function (event) {
                if (event.target === teamModal) {
                    Admin.hideTeamEditModal();
                }
            });
        }

        // Handle HTMX events to show/hide modal
        document.body.addEventListener("htmx:afterRequest", function (event) {
            if (
                event.detail.pathInfo.requestPath.includes("/admin/users/") &&
                event.detail.pathInfo.requestPath.includes("/edit")
            ) {
                Admin.showUserEditModal();
            }
        });
    });

    // Team edit modal functions
    Admin.showTeamEditModal = async function (teamId) {
        // Get the root path by extracting it from the current pathname
        let rootPath = window.location.pathname;
        const adminIndex = rootPath.lastIndexOf("/admin");
        if (adminIndex !== -1) {
            rootPath = rootPath.substring(0, adminIndex);
        } else {
            rootPath = "";
        }

        // Construct the full URL - ensure it starts with /
        const url = (rootPath || "") + "/admin/teams/" + teamId + "/edit";

        // Load the team edit form via HTMX
        fetch(url, {
            method: "GET",
            headers: {
                Authorization: "Bearer " + (await Admin.getAuthToken()),
            },
        })
            .then((response) => response.text())
            .then((html) => {
                Admin.safeGetElement("team-edit-modal-content").innerHTML = html;
                document
                    .getElementById("team-edit-modal")
                    .classList.remove("hidden");
            })
            .catch((error) => {
                console.error("Error loading team edit form:", error);
            });
    }

    Admin.hideTeamEditModal = function () {
        Admin.safeGetElement("team-edit-modal").classList.add("hidden");
    }

    // Team member management functions
    Admin.showAddMemberForm = function (teamId) {
        const form = Admin.safeGetElement("add-member-form-" + teamId);
        if (form) {
            form.classList.remove("hidden");
        }
    }

    Admin.hideAddMemberForm = function (teamId) {
        const form = Admin.safeGetElement("add-member-form-" + teamId);
        if (form) {
            form.classList.add("hidden");
            // Reset form
            const formElement = form.querySelector("form");
            if (formElement) {
                formElement.reset();
            }
        }
    }

    // Reset team creation form after successful HTMX actions
    Admin.resetTeamCreateForm = function () {
        const form = document.querySelector('form[hx-post*="/admin/teams"]');
        if (form) {
            form.reset();
        }
        const errorEl = Admin.safeGetElement("create-team-error");
        if (errorEl) {
            errorEl.innerHTML = "";
        }
    }

    // Normalize team ID from element IDs like "add-members-form-<id>"
    Admin.extractTeamId = function (prefix, elementId) {
        if (!elementId || !elementId.startsWith(prefix)) {
            return null;
        }
        return elementId.slice(prefix.length);
    }

    Admin.updateAddMembersCount = function (teamId) {
        const form = Admin.safeGetElement(`add-members-form-${teamId}`);
        const countEl = Admin.safeGetElement(`selected-count-${teamId}`);
        if (!form || !countEl) {
            return;
        }
        const checked = form.querySelectorAll(
            'input[name="associatedUsers"]:checked',
        );
        countEl.textContent =
            checked.length === 0
                ? "No users selected"
                : `${checked.length} user${checked.length !== 1 ? "s" : ""} selected`;
    }

    Admin.dedupeSelectorItems = function (container) {
        if (!container) {
            return;
        }
        const seen = new Set();
        const items = Array.from(container.querySelectorAll(".user-item"));
        items.forEach((item) => {
            const email = item.getAttribute("data-user-email") || "";
            if (!email) {
                return;
            }
            if (seen.has(email)) {
                item.remove();
                return;
            }
            seen.add(email);
        });
    }

    // Perform server-side user search and build HTML from JSON (like tools search)
    Admin.performUserSearch = async function (teamId, query, container, teamMemberData) {
        console.log(`[Team ${teamId}] Performing user search: "${query}"`);

        // Step 1: Capture current selections before replacing HTML
        const selections = {};
        const roleSelections = {};
        try {
            const userItems = container.querySelectorAll(".user-item");
            userItems.forEach((item) => {
                const email = item.dataset.userEmail || "";
                const checkbox = item.querySelector(
                    'input[name="associatedUsers"]',
                );
                const roleSelect = item.querySelector(".role-select");
                if (checkbox && email) {
                    selections[email] = checkbox.checked;
                }
                if (roleSelect && email) {
                    roleSelections[email] = roleSelect.value;
                }
            });
            console.log(
                `[Team ${teamId}] Captured ${Object.keys(selections).length} selections and ${Object.keys(roleSelections).length} role selections`,
            );
        } catch (e) {
            console.error(`[Team ${teamId}] Error capturing selections:`, e);
        }

        // Step 2: Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching users...</p>
            </div>
        `;

        // Step 3: If query is empty, reload default list from /admin/users/partial
        if (query === "") {
            try {
                const usersUrl = `${window.ROOT_PATH}/admin/users/partial?page=1&per_page=50&render=selector&team_id=${encodeURIComponent(teamId)}`;
                console.log(
                    `[Team ${teamId}] Loading default users with URL: ${usersUrl}`,
                );

                const response = await Admin.fetchWithAuth(usersUrl);
                if (response.ok) {
                    const html = await response.text();
                    container.innerHTML = html;

                    // Restore selections
                    Admin.restoreUserSelections(container, selections, roleSelections);
                } else {
                    console.error(
                        `[Team ${teamId}] Failed to load users: ${response.status}`,
                    );
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load users</div>';
                }
            } catch (error) {
                console.error(`[Team ${teamId}] Error loading users:`, error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading users</div>';
            }
            return;
        }

        // Step 4: Call /admin/users/search API
        try {
            const searchUrl = `${window.ROOT_PATH}/admin/users/search?q=${encodeURIComponent(query)}&limit=50`;
            console.log(`[Team ${teamId}] Searching users with URL: ${searchUrl}`);

            const response = await Admin.fetchWithAuth(searchUrl);
            if (!response.ok) {
                console.error(
                    `[Team ${teamId}] Search failed: ${response.status} ${response.statusText}`,
                );
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.users && data.users.length > 0) {
                // Step 5: Build HTML manually from JSON
                let searchResultsHtml = "";
                data.users.forEach((user) => {
                    const memberData = teamMemberData[user.email] || {};
                    const isMember = Object.keys(memberData).length > 0;
                    const memberRole = memberData.role || "member";
                    const joinedAt = memberData.joined_at;
                    const isCurrentUser = memberData.is_current_user || false;
                    const isLastOwner = memberData.is_last_owner || false;
                    const isChecked =
                        selections[user.email] !== undefined
                            ? selections[user.email]
                            : isMember;
                    const selectedRole = roleSelections[user.email] || memberRole;

                    const borderClass = isMember
                        ? "border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/20"
                        : "border-transparent";

                    searchResultsHtml += `
                        <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border ${borderClass}" data-user-email="${escapeHtml(user.email)}">
                            <!-- Avatar Circle -->
                            <div class="flex-shrink-0">
                                <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${escapeHtml(user.email[0].toUpperCase())}</span>
                                </div>
                            </div>

                            <!-- Checkbox -->
                            <input
                                type="checkbox"
                                name="associatedUsers"
                                value="${escapeHtml(user.email)}"
                                data-user-name="${escapeHtml(user.full_name || user.email)}"
                                class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0"
                                data-auto-check="true"
                                ${isChecked ? "checked" : ""}
                            />

                            <!-- User Info with Badges -->
                            <div class="flex-grow min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="select-none font-medium text-gray-900 dark:text-white truncate">${escapeHtml(user.full_name || user.email)}</span>
                                    ${isCurrentUser ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 rounded-full dark:bg-blue-900 dark:text-blue-200">You</span>' : ""}
                                    ${isLastOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 rounded-full dark:bg-yellow-900 dark:text-yellow-200">Last Owner</span>' : ""}
                                    ${isMember && memberRole === "owner" && !isLastOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Owner</span>' : ""}
                                </div>
                                <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${escapeHtml(user.email)}</div>
                                ${isMember && joinedAt ? `<div class="text-xs text-gray-400 dark:text-gray-500">Joined: ${formatDate(joinedAt)}</div>` : ""}
                            </div>

                            <!-- Role Selector -->
                            <select
                                name="role_${encodeURIComponent(user.email)}"
                                class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0"
                            >
                                <option value="member" ${selectedRole === "member" ? "selected" : ""}>Member</option>
                                <option value="owner" ${selectedRole === "owner" ? "selected" : ""}>Owner</option>
                            </select>
                        </div>
                    `;
                });

                // Step 6: Replace container innerHTML
                container.innerHTML = searchResultsHtml;

                // Step 7: No need to restore selections - they're already built into the HTML
                console.log(
                    `[Team ${teamId}] Rendered ${data.users.length} users from search`,
                );
            } else {
                container.innerHTML =
                    '<div class="text-center py-4 text-gray-500">No users found</div>';
            }
        } catch (error) {
            console.error(`[Team ${teamId}] Error searching users:`, error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching users</div>';
        }
    }

    // Restore user selections after loading default list
    Admin.restoreUserSelections = function (container, selections, roleSelections) {
        try {
            const checkboxes = container.querySelectorAll(
                'input[name="associatedUsers"]',
            );
            checkboxes.forEach((cb) => {
                if (selections[cb.value] !== undefined) {
                    cb.checked = selections[cb.value];
                }
            });

            const roleSelects = container.querySelectorAll(".role-select");
            roleSelects.forEach((select) => {
                const email = select.name.replace("role_", "");
                const decodedEmail = decodeURIComponent(email);
                if (roleSelections[decodedEmail]) {
                    select.value = roleSelections[decodedEmail];
                }
            });

            console.log(`Restored ${Object.keys(selections).length} selections`);
        } catch (e) {
            console.error("Error restoring selections:", e);
        }
    }

    // Helper to format date (similar to Python strftime "%b %d, %Y")
    Admin.formatDate = function (dateString) {
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
            });
        } catch (e) {
            return dateString;
        }
    }

    Admin.initializeAddMembersForm = function (form) {
        if (!form || form.dataset.initialized === "true") {
            return;
        }
        form.dataset.initialized = "true";

        // Support both old add-members-form pattern and new team-members-form pattern
        const teamId =
            form.dataset.teamId ||
            Admin.extractTeamId("add-members-form-", form.id) ||
            Admin.extractTeamId("team-members-form-", form.id) ||
            "";

        console.log(
            `[initializeAddMembersForm] Form ID: ${form.id}, Team ID: ${teamId}`,
        );

        if (!teamId) {
            console.warn(
                `[initializeAddMembersForm] No team ID found for form:`,
                form,
            );
            return;
        }

        const searchInput = Admin.safeGetElement(`user-search-${teamId}`);
        const searchResults = Admin.safeGetElement(
            `user-search-results-${teamId}`,
        );
        const searchLoading = Admin.safeGetElement(
            `user-search-loading-${teamId}`,
        );

        // For unified view, find the list container for client-side filtering
        const userListContainer = Admin.safeGetElement(
            `team-members-list-${teamId}`,
        );

        console.log(
            `[Team ${teamId}] Form initialization - searchInput: ${!!searchInput}, userListContainer: ${!!userListContainer}, searchResults: ${!!searchResults}`,
        );

        const memberEmails = [];
        if (searchResults?.dataset.memberEmails) {
            try {
                const parsed = JSON.parse(searchResults.dataset.memberEmails);
                if (Array.isArray(parsed)) {
                    memberEmails.push(...parsed);
                }
            } catch (error) {
                console.warn("Failed to parse member emails", error);
            }
        }
        const memberEmailSet = new Set(memberEmails);

        form.addEventListener("change", function (event) {
            if (event.target?.name === "associatedUsers") {
                Admin.updateAddMembersCount(teamId);
                // Role dropdown state is not managed client-side - all logic is server-side
            }
        });

        Admin.updateAddMembersCount(teamId);

        // If we have searchInput and userListContainer, use server-side search like tools (unified view)
        if (searchInput && userListContainer) {
            console.log(
                `[Team ${teamId}] Initializing server-side search for unified view`,
            );

            // Get team member data from the initial page load (embedded in the form)
            const teamMemberDataScript = Admin.safeGetElement(
                `team-member-data-${teamId}`,
            );
            let teamMemberData = {};
            if (teamMemberDataScript) {
                try {
                    teamMemberData = JSON.parse(
                        teamMemberDataScript.textContent || "{}",
                    );
                    console.log(
                        `[Team ${teamId}] Loaded team member data for ${Object.keys(teamMemberData).length} members`,
                    );
                } catch (e) {
                    console.error(
                        `[Team ${teamId}] Failed to parse team member data:`,
                        e,
                    );
                }
            }

            let searchTimeout;
            searchInput.addEventListener("input", function () {
                clearTimeout(searchTimeout);
                const query = this.value.trim();

                searchTimeout = setTimeout(async () => {
                    await Admin.performUserSearch(
                        teamId,
                        query,
                        userListContainer,
                        teamMemberData,
                    );
                }, 300);
            });

            return;
        }

        if (!searchInput || !searchResults) {
            return;
        }

        let searchTimeout;
        searchInput.addEventListener("input", function () {
            clearTimeout(searchTimeout);
            const query = this.value.trim();

            if (query.length < 2) {
                searchResults.innerHTML = "";
                if (searchLoading) {
                    searchLoading.classList.add("hidden");
                }
                return;
            }

            searchTimeout = setTimeout(async () => {
                if (searchLoading) {
                    searchLoading.classList.remove("hidden");
                }
                try {
                    const searchUrl = searchInput.dataset.searchUrl || "";
                    const limit = searchInput.dataset.searchLimit || "10";
                    if (!searchUrl) {
                        throw new Error("Search URL missing");
                    }
                    const response = await Admin.fetchWithAuth(
                        `${searchUrl}?q=${encodeURIComponent(query)}&limit=${limit}`,
                    );
                    if (!response.ok) {
                        throw new Error(`Search failed: ${response.status}`);
                    }
                    const data = await response.json();

                    searchResults.innerHTML = "";
                    if (data.users && data.users.length > 0) {
                        const container = document.createElement("div");
                        container.className =
                            "bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md p-2 mt-1";

                        data.users.forEach((user) => {
                            if (memberEmailSet.has(user.email)) {
                                return;
                            }
                            const item = document.createElement("div");
                            item.className =
                                "p-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded cursor-pointer text-sm";
                            item.textContent = `${user.full_name || ""} (${user.email})`;
                            item.addEventListener("click", () => {
                                const container = Admin.safeGetElement(
                                    `user-selector-container-${teamId}`,
                                );
                                if (!container) {
                                    return;
                                }
                                const checkbox = container.querySelector(
                                    `input[value="${user.email}"]`,
                                );

                                if (checkbox) {
                                    checkbox.checked = true;
                                    checkbox.dispatchEvent(
                                        new Event("change", { bubbles: true }),
                                    );
                                } else {
                                    const userItem = document.createElement("div");
                                    userItem.className =
                                        "flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-2 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item";
                                    userItem.setAttribute(
                                        "data-user-email",
                                        user.email,
                                    );

                                    const newCheckbox =
                                        document.createElement("input");
                                    newCheckbox.type = "checkbox";
                                    newCheckbox.name = "associatedUsers";
                                    newCheckbox.value = user.email;
                                    newCheckbox.setAttribute(
                                        "data-user-name",
                                        user.full_name || "",
                                    );
                                    newCheckbox.className =
                                        "user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0";
                                    newCheckbox.setAttribute(
                                        "data-auto-check",
                                        "true",
                                    );
                                    newCheckbox.checked = true;

                                    const label = document.createElement("span");
                                    label.className = "select-none flex-grow";
                                    label.textContent = `${user.full_name || ""} (${user.email})`;

                                    const roleSelect =
                                        document.createElement("select");
                                    roleSelect.name = `role_${encodeURIComponent(
                                        user.email,
                                    )}`;
                                    roleSelect.className =
                                        "role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0";

                                    const memberOption =
                                        document.createElement("option");
                                    memberOption.value = "member";
                                    memberOption.textContent = "Member";
                                    memberOption.selected = true;

                                    const ownerOption =
                                        document.createElement("option");
                                    ownerOption.value = "owner";
                                    ownerOption.textContent = "Owner";

                                    roleSelect.appendChild(memberOption);
                                    roleSelect.appendChild(ownerOption);

                                    userItem.appendChild(newCheckbox);
                                    userItem.appendChild(label);
                                    userItem.appendChild(roleSelect);

                                    const firstChild = container.firstChild;
                                    if (firstChild) {
                                        container.insertBefore(
                                            userItem,
                                            firstChild,
                                        );
                                    } else {
                                        container.appendChild(userItem);
                                    }

                                    newCheckbox.dispatchEvent(
                                        new Event("change", { bubbles: true }),
                                    );
                                }

                                searchInput.value = "";
                                searchResults.innerHTML = "";
                            });
                            container.appendChild(item);
                        });

                        if (container.childElementCount > 0) {
                            searchResults.appendChild(container);
                        } else {
                            const empty = document.createElement("div");
                            empty.className =
                                "text-sm text-gray-500 dark:text-gray-400 mt-1";
                            empty.textContent = "No users found";
                            searchResults.appendChild(empty);
                        }
                    } else {
                        const empty = document.createElement("div");
                        empty.className =
                            "text-sm text-gray-500 dark:text-gray-400 mt-1";
                        empty.textContent = "No users found";
                        searchResults.appendChild(empty);
                    }
                } catch (error) {
                    console.error("Search error:", error);
                    searchResults.innerHTML = "";
                    const errorEl = document.createElement("div");
                    errorEl.className = "text-sm text-red-500 mt-1";
                    errorEl.textContent = "Search failed";
                    searchResults.appendChild(errorEl);
                } finally {
                    if (searchLoading) {
                        searchLoading.classList.add("hidden");
                    }
                }
            }, 300);
        });
    }

    Admin.initializeAddMembersForms = function (root = document) {
        // Support both old add-members-form pattern and new unified team-members-form pattern
        const addMembersForms =
            root?.querySelectorAll?.('[id^="add-members-form-"]') || [];
        const teamMembersForms =
            root?.querySelectorAll?.('[id^="team-members-form-"]') || [];
        const allForms = [...addMembersForms, ...teamMembersForms];
        allForms.forEach((form) => Admin.initializeAddMembersForm(form));
    }

    Admin.handleAdminTeamAction = function (event) {
        const detail = event.detail || {};
        const delayMs = Number(detail.delayMs) || 0;
        setTimeout(() => {
            if (detail.resetTeamCreateForm) {
                Admin.resetTeamCreateForm();
            }
            if (
                detail.closeTeamEditModal &&
                typeof hideTeamEditModal === "function"
            ) {
                Admin.hideTeamEditModal();
            }
            if (detail.closeRoleModal) {
                const roleModal = Admin.safeGetElement("role-assignment-modal");
                if (roleModal) {
                    roleModal.classList.add("hidden");
                }
            }
            if (detail.closeAllModals) {
                const modals = document.querySelectorAll('[id$="-modal"]');
                modals.forEach((modal) => modal.classList.add("hidden"));
            }
            if (detail.refreshTeamsList) {
                const teamsList = Admin.safeGetElement("teams-list");
                if (teamsList && window.htmx) {
                    window.htmx.trigger(teamsList, "load");
                }
            }
            if (detail.refreshUnifiedTeamsList && window.htmx) {
                const unifiedList = Admin.safeGetElement("unified-teams-list");
                if (unifiedList) {
                    // Preserve current pagination/filter state on refresh
                    const params = new URLSearchParams();
                    params.set("page", "1"); // Reset to first page on action
                    if (typeof getTeamsPerPage === "function") {
                        params.set("per_page", Admin.getTeamsPerPage().toString());
                    }
                    // Preserve search query from input field
                    const searchInput = Admin.safeGetElement("team-search");
                    if (searchInput && searchInput.value.trim()) {
                        params.set("q", searchInput.value.trim());
                    }
                    // Preserve relationship filter
                    if (
                        typeof currentTeamRelationshipFilter !== "undefined" &&
                        currentTeamRelationshipFilter &&
                        currentTeamRelationshipFilter !== "all"
                    ) {
                        params.set("relationship", currentTeamRelationshipFilter);
                    }
                    const url = `${window.ROOT_PATH || ""}/admin/teams/partial?${params.toString()}`;
                    window.htmx.ajax("GET", url, {
                        target: "#unified-teams-list",
                        swap: "innerHTML",
                    });
                }
            }
            if (detail.refreshTeamMembers && detail.teamId) {
                if (typeof window.loadTeamMembersView === "function") {
                    window.loadTeamMembersView(detail.teamId);
                } else if (window.htmx) {
                    const modalContent = Admin.safeGetElement(
                        "team-edit-modal-content",
                    );
                    if (modalContent) {
                        window.htmx.ajax(
                            "GET",
                            `${window.ROOT_PATH || ""}/admin/teams/${detail.teamId}/members`,
                            {
                                target: "#team-edit-modal-content",
                                swap: "innerHTML",
                            },
                        );
                    }
                }
            }
            if (detail.refreshJoinRequests && detail.teamId && window.htmx) {
                const joinRequests = Admin.safeGetElement(
                    "team-join-requests-modal-content",
                );
                if (joinRequests) {
                    window.htmx.ajax(
                        "GET",
                        `${window.ROOT_PATH || ""}/admin/teams/${detail.teamId}/join-requests`,
                        {
                            target: "#team-join-requests-modal-content",
                            swap: "innerHTML",
                        },
                    );
                }
            }
        }, delayMs);
    }

    Admin.handleAdminUserAction = function (event) {
        const detail = event.detail || {};
        const delayMs = Number(detail.delayMs) || 0;
        setTimeout(() => {
            if (
                detail.closeUserEditModal &&
                typeof hideUserEditModal === "function"
            ) {
                Admin.hideUserEditModal();
            }
            if (detail.refreshUsersList) {
                const usersList = Admin.safeGetElement("users-list-container");
                if (usersList && window.htmx) {
                    window.htmx.trigger(usersList, "refreshUsers");
                }
            }
        }, delayMs);
    }

    Admin.registerAdminActionListeners = function () {
        if (!document.body) {
            return;
        }
        if (document.body.dataset.adminActionListeners === "1") {
            return;
        }
        document.body.dataset.adminActionListeners = "1";

        document.body.addEventListener("adminTeamAction", Admin.handleAdminTeamAction);
        document.body.addEventListener("adminUserAction", Admin.handleAdminUserAction);
        document.body.addEventListener("userCreated", function () {
            Admin.handleAdminUserAction({ detail: { refreshUsersList: true } });
        });

        document.body.addEventListener("htmx:afterSwap", function (event) {
            Admin.initializeAddMembersForms(event.target);
            Admin.initializePasswordValidation(event.target);
            const target = event.target;
            if (
                target &&
                target.id &&
                target.id.startsWith("user-selector-container-")
            ) {
                const teamId = Admin.extractTeamId("user-selector-container-", target.id);
                if (teamId) {
                    Admin.dedupeSelectorItems(target);
                    Admin.updateAddMembersCount(teamId);
                }
            }
        });

        document.body.addEventListener("htmx:load", function (event) {
            Admin.initializeAddMembersForms(event.target);
            Admin.initializePasswordValidation(event.target);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", Admin.registerAdminActionListeners);
    } else {
        Admin.registerAdminActionListeners();
    }

    // Logs refresh function
    Admin.refreshLogs = function () {
        const logsSection = Admin.safeGetElement("logs");
        if (logsSection && typeof window.htmx !== "undefined") {
            // Trigger HTMX refresh on the logs section
            window.htmx.trigger(logsSection, "refresh");
        }
    }

    // User edit modal functions (already defined above)
    // Functions are already exposed to global scope

    // Team permissions functions are implemented in the admin.html template
    // Remove placeholder functions to avoid overriding template functionality

    Admin.initializePermissionsPanel = function () {
        // Load team data if available
        if (window.USER_TEAMS && window.USER_TEAMS.length > 0) {
            const membersList = Admin.safeGetElement("team-members-list");
            const rolesList = Admin.safeGetElement("role-assignments-list");

            if (membersList) {
                membersList.innerHTML =
                    '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to view and manage team members.</div>';
            }

            if (rolesList) {
                rolesList.innerHTML =
                    '<div class="text-sm text-gray-500 dark:text-gray-400">Use the Teams Management tab to assign roles to team members.</div>';
            }
        }
    }

    // ===================================================================
    // TEAM DISCOVERY AND SELF-SERVICE FUNCTIONS
    // ===================================================================

    /**
    * Load and display public teams that the user can join
    */
    Admin.loadPublicTeams = async function () {
        const container = Admin.safeGetElement("public-teams-list");
        if (!container) {
            console.error("Public teams list container not found");
            return;
        }

        // Show loading state
        container.innerHTML =
            '<div class="animate-pulse text-gray-500 dark:text-gray-400">Loading public teams...</div>';

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH || ""}/teams/discover`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                },
            );
            if (!response.ok) {
                throw new Error(`Failed to load teams: ${response.status}`);
            }

            const teams = await response.json();
            Admin.displayPublicTeams(teams);
        } catch (error) {
            console.error("Error loading public teams:", error);
            container.innerHTML = `
                <div class="bg-red-50 dark:bg-red-900 border border-red-200 dark:border-red-700 rounded-md p-4">
                    <div class="flex">
                        <div class="flex-shrink-0">
                            <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
                            </svg>
                        </div>
                        <div class="ml-3">
                            <h3 class="text-sm font-medium text-red-800 dark:text-red-200">
                                Failed to load public teams
                            </h3>
                            <div class="mt-2 text-sm text-red-700 dark:text-red-300">
                                ${escapeHtml(error.message)}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    /**
    * Display public teams in the UI
    * @param {Array} teams - Array of team objects
    */
    Admin.displayPublicTeams = function (teams) {
        const container = Admin.safeGetElement("public-teams-list");
        if (!container) {
            return;
        }

        if (!teams || teams.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.83-1M17 20H7m10 0v-2c0-1.09-.29-2.11-.83-3M7 20v2m0-2v-2a3 3 0 011.87-2.77m0 0A3 3 0 017 12m0 0a3 3 0 013-3m-3 3h6.4M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <h3 class="mt-2 text-sm font-medium text-gray-900 dark:text-gray-100">No public teams found</h3>
                    <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">There are no public teams available to join at the moment.</p>
                </div>
            `;
            return;
        }

        // Create teams grid
        const teamsHtml = teams
            .map(
                (team) => `
            <div class="bg-white dark:bg-gray-700 shadow rounded-lg p-6 hover:shadow-lg transition-shadow">
                <div class="flex items-center justify-between">
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white">
                        ${escapeHtml(team.name)}
                    </h3>
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Public
                    </span>
                </div>

                ${
                    team.description
                        ? `
                    <p class="mt-2 text-sm text-gray-600 dark:text-gray-300">
                        ${escapeHtml(team.description)}
                    </p>
                `
                        : ""
                }

                <div class="mt-4 flex items-center justify-between">
                    <div class="flex items-center text-sm text-gray-500 dark:text-gray-400">
                        <svg class="flex-shrink-0 mr-1.5 h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/>
                        </svg>
                        ${team.member_count} members
                    </div>
                    <button
                        onclick="Admin.requestToJoinTeam('${escapeHtml(team.id)}')"
                        class="px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                    >
                        Request to Join
                    </button>
                </div>
            </div>
        `,
            )
            .join("");

        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                ${teamsHtml}
            </div>
        `;
    }

    /**
    * Request to join a public team
    * @param {string} teamId - ID of the team to join
    */
    Admin.requestToJoinTeam = async function (teamId) {
        if (!teamId) {
            console.error("Team ID is required");
            return;
        }

        // Show confirmation dialog
        const message = prompt("Optional: Enter a message to the team owners:");

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH || ""}/teams/${teamId}/join`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        message: message || null,
                    }),
                },
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(
                    errorData?.detail ||
                        `Failed to request join: ${response.status}`,
                );
            }

            const result = await response.json();

            // Show success message
            Admin.showSuccessMessage(
                `Join request sent to ${result.team_name}! Team owners will review your request.`,
            );

            // Refresh the public teams list
            setTimeout(loadPublicTeams, 1000);
        } catch (error) {
            console.error("Error requesting to join team:", error);
            Admin.showErrorMessage(`Failed to send join request: ${error.message}`);
        }
    }

    /**
    * Leave a team
    * @param {string} teamId - ID of the team to leave
    * @param {string} teamName - Name of the team (for confirmation)
    */
    Admin.leaveTeam = async function (teamId, teamName) {
        if (!teamId) {
            console.error("Team ID is required");
            return;
        }

        // Show confirmation dialog
        const confirmed = confirm(
            `Are you sure you want to leave the team "${teamName}"? This action cannot be undone.`,
        );
        if (!confirmed) {
            return;
        }

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH || ""}/teams/${teamId}/leave`,
                {
                    method: "DELETE",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                },
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(
                    errorData?.detail || `Failed to leave team: ${response.status}`,
                );
            }

            await response.json();

            // Show success message
            Admin.showSuccessMessage(`Successfully left ${teamName}`);

            // Refresh teams list
            const teamsList = Admin.safeGetElement("teams-list");
            if (teamsList && window.htmx) {
                window.htmx.trigger(teamsList, "load");
            }

            // Refresh team selector if available
            if (typeof updateTeamContext === "function") {
                // Force reload teams data
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            }
        } catch (error) {
            console.error("Error leaving team:", error);
            Admin.showErrorMessage(`Failed to leave team: ${error.message}`);
        }
    }

    /**
    * Approve a join request
    * @param {string} teamId - ID of the team
    * @param {string} requestId - ID of the join request
    */
    Admin.approveJoinRequest = async function (teamId, requestId) {
        if (!teamId || !requestId) {
            console.error("Team ID and request ID are required");
            return;
        }

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}/approve`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                },
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(
                    errorData?.detail ||
                        `Failed to approve join request: ${response.status}`,
                );
            }

            const result = await response.json();

            // Show success message
            Admin.showSuccessMessage(
                `Join request approved! ${result.user_email} is now a member.`,
            );

            // Refresh teams list
            const teamsList = Admin.safeGetElement("teams-list");
            if (teamsList && window.htmx) {
                window.htmx.trigger(teamsList, "load");
            }
        } catch (error) {
            console.error("Error approving join request:", error);
            Admin.showErrorMessage(`Failed to approve join request: ${error.message}`);
        }
    }

    /**
    * Reject a join request
    * @param {string} teamId - ID of the team
    * @param {string} requestId - ID of the join request
    */
    Admin.rejectJoinRequest = async function (teamId, requestId) {
        if (!teamId || !requestId) {
            console.error("Team ID and request ID are required");
            return;
        }

        const confirmed = confirm(
            "Are you sure you want to reject this join request?",
        );
        if (!confirmed) {
            return;
        }

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH || ""}/teams/${teamId}/join-requests/${requestId}`,
                {
                    method: "DELETE",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                        "Content-Type": "application/json",
                    },
                },
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(
                    errorData?.detail ||
                        `Failed to reject join request: ${response.status}`,
                );
            }

            // Show success message
            Admin.showSuccessMessage("Join request rejected.");

            // Refresh teams list
            const teamsList = Admin.safeGetElement("teams-list");
            if (teamsList && window.htmx) {
                window.htmx.trigger(teamsList, "load");
            }
        } catch (error) {
            console.error("Error rejecting join request:", error);
            Admin.showErrorMessage(`Failed to reject join request: ${error.message}`);
        }
    }

    /**
    * Validate password match in user edit form
    */
    Admin.getPasswordPolicy = function () {
        const policyEl = Admin.safeGetElement("password-policy-data");
        if (!policyEl) {
            return null;
        }
        return {
            minLength: parseInt(policyEl.dataset.minLength || "0", 10),
            requireUppercase: policyEl.dataset.requireUppercase === "true",
            requireLowercase: policyEl.dataset.requireLowercase === "true",
            requireNumbers: policyEl.dataset.requireNumbers === "true",
            requireSpecial: policyEl.dataset.requireSpecial === "true",
        };
    }

    Admin.updateRequirementIcon = function (elementId, isValid) {
        const req = Admin.safeGetElement(elementId);
        if (!req) {
            return;
        }
        const icon = req.querySelector("span");
        if (!icon) {
            return;
        }
        if (isValid) {
            icon.className =
                "inline-flex items-center justify-center w-4 h-4 bg-green-500 text-white rounded-full text-xs mr-2";
            icon.textContent = "✓";
        } else {
            icon.className =
                "inline-flex items-center justify-center w-4 h-4 bg-gray-400 text-white rounded-full text-xs mr-2";
            icon.textContent = "✗";
        }
    }

    Admin.validatePasswordRequirements = function () {
        const policy = Admin.getPasswordPolicy();
        const passwordField = Admin.safeGetElement("password-field");
        if (!policy || !passwordField) {
            return;
        }

        const password = passwordField.value || "";
        const lengthCheck = password.length >= policy.minLength;
        Admin.updateRequirementIcon("req-length", lengthCheck);

        const uppercaseCheck = !policy.requireUppercase || /[A-Z]/.test(password);
        Admin.updateRequirementIcon("req-uppercase", uppercaseCheck);

        const lowercaseCheck = !policy.requireLowercase || /[a-z]/.test(password);
        Admin.updateRequirementIcon("req-lowercase", lowercaseCheck);

        const numbersCheck = !policy.requireNumbers || /[0-9]/.test(password);
        Admin.updateRequirementIcon("req-numbers", numbersCheck);

        const specialChars = "!@#$%^&*()_+-=[]{};:'\"\\|,.<>`~/?";
        const specialCheck =
            !policy.requireSpecial ||
            [...password].some((char) => specialChars.includes(char));
        Admin.updateRequirementIcon("req-special", specialCheck);

        const submitButton = document.querySelector(
            '#user-edit-modal-content button[type="submit"]',
        );
        const allRequirementsMet =
            lengthCheck &&
            uppercaseCheck &&
            lowercaseCheck &&
            numbersCheck &&
            specialCheck;
        const passwordEmpty = password.length === 0;

        if (submitButton) {
            if (passwordEmpty || allRequirementsMet) {
                submitButton.disabled = false;
                submitButton.className =
                    "px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500";
            } else {
                submitButton.disabled = true;
                submitButton.className =
                    "px-4 py-2 text-sm font-medium text-white bg-gray-400 border border-transparent rounded-md cursor-not-allowed";
            }
        }
    }

    Admin.initializePasswordValidation = function (root = document) {
        if (
            root?.querySelector?.("#password-field") ||
            Admin.safeGetElement("password-field")
        ) {
            Admin.validatePasswordRequirements();
            Admin.validatePasswordMatch();
        }
    }

    Admin.validatePasswordMatch = function () {
        const passwordField = Admin.safeGetElement("password-field");
        const confirmPasswordField = Admin.safeGetElement(
            "confirm-password-field",
        );
        const messageElement = Admin.safeGetElement("password-match-message");
        const submitButton = document.querySelector(
            '#user-edit-modal-content button[type="submit"]',
        );

        if (!passwordField || !confirmPasswordField || !messageElement) {
            return;
        }

        const password = passwordField.value;
        const confirmPassword = confirmPasswordField.value;

        // Only show validation if both fields have content or if confirm field has content
        if (
            (password.length > 0 || confirmPassword.length > 0) &&
            password !== confirmPassword
        ) {
            messageElement.classList.remove("hidden");
            confirmPasswordField.classList.add("border-red-500");
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.classList.add("opacity-50", "cursor-not-allowed");
            }
        } else {
            messageElement.classList.add("hidden");
            confirmPasswordField.classList.remove("border-red-500");
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.classList.remove("opacity-50", "cursor-not-allowed");
            }
        }
    }

    // ===================================================================
    // SELECTIVE IMPORT FUNCTIONS
    // ===================================================================

    /**
    * Display import preview with selective import options
    */
    Admin.displayImportPreview = function (preview) {
        console.log("📋 Displaying import preview:", preview);

        // Find or create preview container
        let previewContainer = Admin.safeGetElement("import-preview-container");
        if (!previewContainer) {
            previewContainer = document.createElement("div");
            previewContainer.id = "import-preview-container";
            previewContainer.className = "mt-6 border-t pt-6";

            // Insert after import options in the import section
            const importSection =
                document.querySelector("#import-drop-zone").parentElement
                    .parentElement;
            importSection.appendChild(previewContainer);
        }

        previewContainer.innerHTML = `
            <h4 class="text-lg font-medium text-gray-900 dark:text-white mb-4">
                📋 Selective Import - Choose What to Import
            </h4>

            <!-- Summary -->
            <div class="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-lg p-4 mb-6">
                <div class="flex items-center">
                    <div class="ml-3">
                        <h3 class="text-sm font-medium text-blue-800 dark:text-blue-200">
                            Found ${preview.summary.total_items} items in import file
                        </h3>
                        <div class="mt-1 text-sm text-blue-600 dark:text-blue-300">
                            ${Object.entries(preview.summary.by_type)
                                .map(([type, count]) => `${type}: ${count}`)
                                .join(", ")}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Selection Controls -->
            <div class="flex justify-between items-center mb-4">
                <div class="space-x-4">
                    <button onclick="Admin.selectAllItems()"
                            class="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline">
                        Select All
                    </button>
                    <button onclick="Admin.selectNoneItems()"
                            class="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-300 underline">
                        Select None
                    </button>
                    <button onclick="Admin.selectOnlyCustom()"
                            class="text-sm text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 underline">
                        Custom Items Only
                    </button>
                </div>

                <div class="text-sm text-gray-500 dark:text-gray-400">
                    <span id="selection-count">0 items selected</span>
                </div>
            </div>

            <!-- Gateway Bundles -->
            ${
                Object.keys(preview.bundles || {}).length > 0
                    ? `
                <div class="mb-6">
                    <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3">
                        🌐 Gateway Bundles (Gateway + Auto-discovered Items)
                    </h5>
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        ${Object.entries(preview.bundles)
                            .map(
                                ([gatewayName, bundle]) => `
                            <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-gray-750">
                                <label class="flex items-start cursor-pointer">
                                    <input type="checkbox"
                                        class="gateway-checkbox mt-1 mr-3"
                                        data-gateway="${gatewayName}"
                                        onchange="Admin.updateSelectionCount()">
                                    <div class="flex-1">
                                        <div class="font-medium text-gray-900 dark:text-white">
                                            ${bundle.gateway.name}
                                        </div>
                                        <div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
                                            ${bundle.gateway.description || "No description"}
                                        </div>
                                        <div class="text-xs text-blue-600 dark:text-blue-400">
                                            Bundle includes: ${bundle.total_items} items
                                            (${Object.entries(bundle.items)
                                                .filter(
                                                    ([type, items]) =>
                                                        items.length > 0,
                                                )
                                                .map(
                                                    ([type, items]) =>
                                                        `${items.length} ${type}`,
                                                )
                                                .join(", ")})
                                        </div>
                                    </div>
                                </label>
                            </div>
                        `,
                            )
                            .join("")}
                    </div>
                </div>
            `
                    : ""
            }

            <!-- Custom Items by Type -->
            ${Object.entries(preview.items || {})
                .map(([entityType, items]) => {
                    const customItems = items.filter((item) => item.is_custom);
                    return customItems.length > 0
                        ? `
                    <div class="mb-6">
                        <h5 class="text-md font-medium text-gray-900 dark:text-white mb-3 capitalize">
                            🛠️ Custom ${entityType}
                        </h5>
                        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            ${customItems
                                .map(
                                    (item) => `
                                <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-3 hover:bg-gray-50 dark:hover:bg-gray-750 ${item.conflicts_with ? "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-900" : ""}">
                                    <label class="flex items-start cursor-pointer">
                                        <input type="checkbox"
                                            class="item-checkbox mt-1 mr-3"
                                            data-type="${entityType}"
                                            data-id="${item.id}"
                                            onchange="Admin.updateSelectionCount()">
                                        <div class="flex-1">
                                            <div class="text-sm font-medium text-gray-900 dark:text-white">
                                                ${item.name}
                                                ${
                                                    item.conflicts_with
                                                        ? '<span class="text-orange-600 text-xs ml-1">⚠️ Conflict</span>'
                                                        : ""
                                                }
                                            </div>
                                            <div class="text-xs text-gray-500 dark:text-gray-400">
                                                ${item.description || `Custom ${entityType} item`}
                                            </div>
                                        </div>
                                    </label>
                                </div>
                            `,
                                )
                                .join("")}
                        </div>
                    </div>
                `
                        : "";
                })
                .join("")}

            <!-- Conflicts Warning -->
            ${
                Object.keys(preview.conflicts || {}).length > 0
                    ? `
                <div class="mb-6">
                    <div class="bg-orange-50 dark:bg-orange-900 border border-orange-200 dark:border-orange-800 rounded-lg p-4">
                        <div class="flex items-start">
                            <div class="flex-shrink-0">
                                <svg class="h-5 w-5 text-orange-400" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                                </svg>
                            </div>
                            <div class="ml-3">
                                <h3 class="text-sm font-medium text-orange-800 dark:text-orange-200">
                                    Naming conflicts detected
                                </h3>
                                <div class="mt-1 text-sm text-orange-600 dark:text-orange-300">
                                    Some items have the same names as existing items. Use conflict strategy to resolve.
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `
                    : ""
            }

            <!-- Action Buttons -->
            <div class="flex justify-between pt-6 border-t border-gray-200 dark:border-gray-700">
                <button onclick="Admin.resetImportSelection()"
                        class="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                    🔄 Reset Selection
                </button>

                <div class="space-x-3">
                    <button onclick="Admin.handleSelectiveImport(true)"
                            class="px-4 py-2 text-sm font-medium text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-800 rounded-md hover:bg-blue-100 dark:hover:bg-blue-800">
                        🧪 Preview Selected
                    </button>
                    <button onclick="Admin.handleSelectiveImport(false)"
                            class="px-4 py-2 text-sm font-medium text-white bg-green-600 border border-transparent rounded-md hover:bg-green-700">
                        ✅ Import Selected Items
                    </button>
                </div>
            </div>
        `;

        // Store preview data and show preview section
        Admin.currentImportPreview = preview;
        Admin.updateSelectionCount();
    }

    /**
    * Handle selective import based on user selections
    */
    Admin.handleSelectiveImport = async function (dryRun = false) {
        console.log(`🎯 Starting selective import (dry_run=${dryRun})`);

        if (!window.currentImportData) {
            Admin.showNotification("❌ Please select an import file first", "error");
            return;
        }

        try {
            Admin.showImportProgress(true);

            // Collect user selections
            const selectedEntities = Admin.collectUserSelections();

            if (Object.keys(selectedEntities).length === 0) {
                Admin.showNotification(
                    "❌ Please select at least one item to import",
                    "warning",
                );
                Admin.showImportProgress(false);
                return;
            }

            const conflictStrategy =
                Admin.safeGetElement("import-conflict-strategy")?.value ||
                "update";
            const rekeySecret =
                Admin.safeGetElement("import-rekey-secret")?.value || null;

            const requestData = {
                import_data: window.currentImportData,
                conflict_strategy: conflictStrategy,
                dry_run: dryRun,
                rekey_secret: rekeySecret,
                selectedEntities,
            };

            console.log("🎯 Selected entities for import:", selectedEntities);

            const response = await fetch(
                (window.ROOT_PATH || "") + "/admin/import/configuration",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                    body: JSON.stringify(requestData),
                },
            );

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || `Import failed: ${response.statusText}`,
                );
            }

            const result = await response.json();
            Admin.displayImportResults(result, dryRun);

            if (!dryRun) {
                Admin.refreshCurrentTabData();
                Admin.showNotification(
                    "✅ Selective import completed successfully",
                    "success",
                );
            } else {
                Admin.showNotification("✅ Import preview completed", "success");
            }
        } catch (error) {
            console.error("Selective import error:", error);
            Admin.showNotification(`❌ Import failed: ${error.message}`, "error");
        } finally {
            Admin.showImportProgress(false);
        }
    }

    /**
    * Collect user selections for selective import
    */
    Admin.collectUserSelections = function () {
        const selections = {};

        // Collect gateway selections
        document
            .querySelectorAll(".gateway-checkbox:checked")
            .forEach((checkbox) => {
                const gatewayName = checkbox.dataset.gateway;
                if (!selections.gateways) {
                    selections.gateways = [];
                }
                selections.gateways.push(gatewayName);
            });

        // Collect individual item selections
        document.querySelectorAll(".item-checkbox:checked").forEach((checkbox) => {
            const entityType = checkbox.dataset.type;
            const itemId = checkbox.dataset.id;
            if (!selections[entityType]) {
                selections[entityType] = [];
            }
            selections[entityType].push(itemId);
        });

        return selections;
    }

    /**
    * Update selection count display
    */
    Admin.updateSelectionCount = function () {
        const gatewayCount = document.querySelectorAll(
            ".gateway-checkbox:checked",
        ).length;
        const itemCount = document.querySelectorAll(
            ".item-checkbox:checked",
        ).length;
        const totalCount = gatewayCount + itemCount;

        const countElement = Admin.safeGetElement("selection-count");
        if (countElement) {
            countElement.textContent = `${totalCount} items selected (${gatewayCount} gateways, ${itemCount} individual items)`;
        }
    }

    /**
    * Select all items
    */
    Admin.selectAllItems = function () {
        document
            .querySelectorAll(".gateway-checkbox, .item-checkbox")
            .forEach((checkbox) => {
                checkbox.checked = true;
            });
        Admin.updateSelectionCount();
    }

    /**
    * Select no items
    */
    Admin.selectNoneItems = function () {
        document
            .querySelectorAll(".gateway-checkbox, .item-checkbox")
            .forEach((checkbox) => {
                checkbox.checked = false;
            });
        Admin.updateSelectionCount();
    }

    /**
    * Select only custom items (not gateway items)
    */
    Admin.selectOnlyCustom = function () {
        document.querySelectorAll(".gateway-checkbox").forEach((checkbox) => {
            checkbox.checked = false;
        });
        document.querySelectorAll(".item-checkbox").forEach((checkbox) => {
            checkbox.checked = true;
        });
        Admin.updateSelectionCount();
    }

    /**
    * Reset import selection
    */
    Admin.resetImportSelection = function () {
        const previewContainer = Admin.safeGetElement(
            "import-preview-container",
        );
        if (previewContainer) {
            previewContainer.remove();
        }
        Admin.currentImportPreview = null;
    }

    /* ---------------------------------------------------------------------------
    Robust reloadAllResourceSections
    - Replaces each section's full innerHTML with a server-rendered partial
    - Restores saved initial markup on failure
    - Re-runs initializers (Alpine, CodeMirror, select/pills, event handlers)
    --------------------------------------------------------------------------- */

    Admin.registerReloadAllResourceSections = function () {
        // list of sections we manage
        const SECTION_NAMES = [
            "tools",
            "resources",
            "prompts",
            "servers",
            "gateways",
            "catalog",
        ];

        // Save initial markup on first full load so we can restore exactly if needed
        document.addEventListener("DOMContentLoaded", () => {
            Admin.__initialSectionMarkup = window.__initialSectionMarkup || {};
            SECTION_NAMES.forEach((s) => {
                const el = Admin.safeGetElement(`${s}-section`);
                if (el && !(s in window.__initialSectionMarkup)) {
                    // store the exact innerHTML produced by the server initially
                    Admin.__initialSectionMarkup[s] = el.innerHTML;
                }
            });
        });

        // Helper: try to re-run common initializers after a section's DOM is replaced
    Admin.reinitializeSection = function (sectionEl, sectionName) {
            try {
                if (!sectionEl) {
                    return;
                }

                // 1) Re-init Alpine for the new subtree (if Alpine is present)
                try {
                    if (window.Alpine) {
                        // For Alpine 3 use initTree if available
                        if (typeof window.Alpine.initTree === "function") {
                            window.Alpine.initTree(sectionEl);
                        } else if (
                            typeof window.Alpine.discoverAndRegisterComponents ===
                            "function"
                        ) {
                            // fallback: attempt a component discovery if available
                            window.Alpine.discoverAndRegisterComponents(sectionEl);
                        }
                    }
                } catch (err) {
                    console.warn(
                        "Alpine re-init failed for section",
                        sectionName,
                        err,
                    );
                }

                // 2) Re-initialize tool/resource/pill helpers that expect DOM structure
                try {
                    // these functions exist elsewhere in admin.js; call them if present
                    if (typeof Admin.initResourceSelect === "function") {
                        // Many panels use specific ids — attempt to call generic initializers if they exist
                        Admin.initResourceSelect(
                            "associatedResources",
                            "selectedResourcePills",
                            "selectedResourceWarning",
                            10,
                            null,
                            null,
                        );
                    }
                    if (typeof Admin.initToolSelect === "function") {
                        Admin.initToolSelect(
                            "associatedTools",
                            "selectedToolsPills",
                            "selectedToolsWarning",
                            10,
                            null,
                            null,
                        );
                    }
                    // restore generic tool/resource selection areas if present
                    if (typeof Admin.initResourceSelect === "function") {
                        // try specific common containers if present (Admin.safeGetElement suppresses warnings)
                        const containers = [
                            "edit-server-resources",
                            "edit-server-tools",
                        ];
                        containers.forEach((cid) => {
                            const c = Admin.safeGetElement(cid);
                            if (c && typeof Admin.initResourceSelect === "function") {
                                // caller may have different arg signature — best-effort call is OK
                                // we don't want to throw here if arguments mismatch
                                try {
                                    /* no args: assume function will find DOM by ids */ Admin.initResourceSelect();
                                } catch (e) {
                                    /* ignore */
                                }
                            }
                        });
                    }
                } catch (err) {
                    console.warn("Select/pill reinit error", err);
                }

                // 3) Re-run integration & schema handlers which attach behaviour to new inputs
                try {
                    if (typeof setupIntegrationTypeHandlers === "function") {
                        Admin.setupIntegrationTypeHandlers();
                    }
                    if (typeof setupSchemaModeHandlers === "function") {
                        Admin.setupSchemaModeHandlers();
                    }
                } catch (err) {
                    console.warn("Integration/schema handler reinit failed", err);
                }

                // 4) Reinitialize CodeMirror editors within the replaced DOM (if CodeMirror used)
                try {
                    if (window.CodeMirror) {
                        // For any <textarea class="codemirror"> re-create or refresh editors
                        const textareas = sectionEl.querySelectorAll("textarea");
                        textareas.forEach((ta) => {
                            // If the page previously attached a CodeMirror instance on same textarea,
                            // the existing instance may have been stored on the element. If refresh available, refresh it.
                            if (
                                ta.CodeMirror &&
                                typeof ta.CodeMirror.refresh === "function"
                            ) {
                                ta.CodeMirror.refresh();
                            } else {
                                // Create a new CodeMirror instance only when an explicit init function is present on page
                                if (
                                    typeof window.createCodeMirrorForTextarea ===
                                    "function"
                                ) {
                                    try {
                                        window.createCodeMirrorForTextarea(ta);
                                    } catch (e) {
                                        // ignore - not all textareas need CodeMirror
                                    }
                                }
                            }
                        });
                    }
                } catch (err) {
                    console.warn("CodeMirror reinit failed", err);
                }

                // 5) Re-attach generic event wiring that is expected by the UI (checkboxes, buttons)
                try {
                    // checkbox-driven pill updates
                    const checkboxChangeEvent = new Event("change", {
                        bubbles: true,
                    });
                    sectionEl
                        .querySelectorAll('input[type="checkbox"]')
                        .forEach((cb) => {
                            // If there were checkbox-specific change functions on page, they will now re-run
                            cb.dispatchEvent(checkboxChangeEvent);
                        });

                    // Reconnect any HTMX triggers that expect a load event
                    if (window.htmx && typeof window.htmx.trigger === "function") {
                        // find elements with data-htmx or that previously had an HTMX load
                        const htmxTargets = sectionEl.querySelectorAll(
                            "[hx-get], [hx-post], [data-hx-load]",
                        );
                        htmxTargets.forEach((el) => {
                            try {
                                window.htmx.trigger(el, "load");
                            } catch (e) {
                                /* ignore */
                            }
                        });
                    }
                } catch (err) {
                    console.warn("Event wiring re-attach failed", err);
                }

                // 6) Accessibility / visual: force a small layout reflow, useful in some browsers
                try {
                    // eslint-disable-next-line no-unused-expressions
                    sectionEl.offsetHeight; // read to force reflow
                } catch (e) {
                    /* ignore */
                }
            } catch (err) {
                console.error("Error reinitializing section", sectionName, err);
            }
        }

    Admin.updateSectionHeaders = function (teamId) {
            const sections = [
                "tools",
                "resources",
                "prompts",
                "servers",
                "gateways",
            ];

            sections.forEach((section) => {
                const header = document.querySelector(
                    "#" + section + "-section h2",
                );
                if (header) {
                    // Remove existing team badge
                    const existingBadge = header.querySelector(".team-badge");
                    if (existingBadge) {
                        existingBadge.remove();
                    }

                    // Add team badge if team is selected
                    if (teamId && teamId !== "") {
                        const teamName = Admin.getTeamNameById(teamId);
                        if (teamName) {
                            const badge = document.createElement("span");
                            badge.className =
                                "team-badge inline-flex items-center px-2 py-1 ml-2 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full";
                            badge.textContent = teamName;
                            header.appendChild(badge);
                        }
                    }
                }
            });
        }

    Admin.getTeamNameById = function (teamId) {
            // Get team name from Alpine.js data or fallback
            const teamSelector = document.querySelector('[x-data*="selectedTeam"]');
            if (
                teamSelector &&
                teamSelector._x_dataStack &&
                teamSelector._x_dataStack[0].teams
            ) {
                const team = teamSelector._x_dataStack[0].teams.find(
                    (t) => t.id === teamId,
                );
                return team ? team.name : null;
            }
            return null;
        }

        // The exported function: reloadAllResourceSections
    Admin.reloadAllResourceSections = async function (teamId) {
            const sections = [
                "tools",
                "resources",
                "prompts",
                "servers",
                "gateways",
            ];

            // ensure there is a ROOT_PATH set
            if (!window.ROOT_PATH) {
                console.warn(
                    "ROOT_PATH not defined; aborting reloadAllResourceSections",
                );
                return;
            }

            // Iterate sections sequentially to avoid overloading the server and to ensure consistent order.
            for (const section of sections) {
                const sectionEl = Admin.safeGetElement(`${section}-section`);
                if (!sectionEl) {
                    console.warn(`Section element not found: ${section}-section`);
                    continue;
                }

                // Build server partial URL (server should return the *full HTML fragment* for the section)
                // Server endpoint pattern: /admin/sections/{section}?partial=true
                let url = `${window.ROOT_PATH}/admin/sections/${section}?partial=true`;
                if (teamId && teamId !== "") {
                    url += `&team_id=${encodeURIComponent(teamId)}`;
                }

                try {
                    const resp = await Admin.fetchWithTimeout(
                        url,
                        { credentials: "same-origin" },
                        window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000,
                    );
                    if (!resp.ok) {
                        throw new Error(`HTTP ${resp.status}`);
                    }
                    const html = await resp.text();

                    // Replace entire section's innerHTML with server-provided HTML to keep DOM identical.
                    // Use safeSetInnerHTML with isTrusted = true because this is server-rendered trusted content.
                    Admin.safeSetInnerHTML(sectionEl, html, true);

                    // After replacement, re-run local initializers so the new DOM behaves like initial load
                    Admin.reinitializeSection(sectionEl, section);
                } catch (err) {
                    console.error(
                        `Failed to load section ${section} from server:`,
                        err,
                    );

                    // Restore the original markup exactly as it was on initial load (fallback)
                    if (
                        window.__initialSectionMarkup &&
                        window.__initialSectionMarkup[section]
                    ) {
                        sectionEl.innerHTML =
                            window.__initialSectionMarkup[section];
                        // Re-run initializers on restored markup as well
                        Admin.reinitializeSection(sectionEl, section);
                        console.log(
                            `Restored initial markup for section ${section}`,
                        );
                    } else {
                        // No fallback available: leave existing DOM intact and show error to console
                        console.warn(
                            `No saved initial markup for section ${section}; leaving DOM untouched`,
                        );
                    }
                }
            }

            // Update headers (team badges) after reload
            try {
                if (typeof updateSectionHeaders === "function") {
                    Admin.updateSectionHeaders(teamId);
                }
            } catch (err) {
                console.warn("updateSectionHeaders failed after reload", err);
            }

            console.log("✓ reloadAllResourceSections completed");
        }
    }
    Admin.registerReloadAllResourceSections();

    // Plugin management functions
    Admin.initializePluginFunctions = function () {
        // Populate hook, tag, and author filters on page load
        Admin.populatePluginFilters = function () {
            const cards = document.querySelectorAll(".plugin-card");
            const hookSet = new Set();
            const tagSet = new Set();
            const authorSet = new Set();

            cards.forEach((card) => {
                const hooks = card.dataset.hooks
                    ? card.dataset.hooks.split(",")
                    : [];
                const tags = card.dataset.tags ? card.dataset.tags.split(",") : [];
                const author = card.dataset.author;

                hooks.forEach((hook) => {
                    if (hook.trim()) {
                        hookSet.add(hook.trim());
                    }
                });
                tags.forEach((tag) => {
                    if (tag.trim()) {
                        tagSet.add(tag.trim());
                    }
                });
                if (author && author.trim()) {
                    authorSet.add(author.trim());
                }
            });

            const hookFilter = Admin.safeGetElement("plugin-hook-filter");
            const tagFilter = Admin.safeGetElement("plugin-tag-filter");
            const authorFilter = Admin.safeGetElement("plugin-author-filter");

            if (hookFilter) {
                hookSet.forEach((hook) => {
                    const option = document.createElement("option");
                    option.value = hook;
                    option.textContent = hook
                        .replace(/_/g, " ")
                        .replace(/\b\w/g, (l) => l.toUpperCase());
                    hookFilter.appendChild(option);
                });
            }

            if (tagFilter) {
                tagSet.forEach((tag) => {
                    const option = document.createElement("option");
                    option.value = tag;
                    option.textContent = tag;
                    tagFilter.appendChild(option);
                });
            }

            if (authorFilter) {
                // Convert authorSet to array and sort for consistent ordering
                const sortedAuthors = Array.from(authorSet).sort();
                sortedAuthors.forEach((author) => {
                    const option = document.createElement("option");
                    // Value is lowercase (matches data-author), text is capitalized for display
                    option.value = author.toLowerCase();
                    option.textContent =
                        author.charAt(0).toUpperCase() + author.slice(1);
                    authorFilter.appendChild(option);
                });
            }
        };

        // Filter plugins based on search and filters
        Admin.filterPlugins = function () {
            const searchInput = Admin.safeGetElement("plugin-search");
            const modeFilter = Admin.safeGetElement("plugin-mode-filter");
            const statusFilter = Admin.safeGetElement("plugin-status-filter");
            const hookFilter = Admin.safeGetElement("plugin-hook-filter");
            const tagFilter = Admin.safeGetElement("plugin-tag-filter");
            const authorFilter = Admin.safeGetElement("plugin-author-filter");

            const searchQuery = searchInput ? searchInput.value.toLowerCase() : "";
            const selectedMode = modeFilter ? modeFilter.value : "";
            const selectedStatus = statusFilter ? statusFilter.value : "";
            const selectedHook = hookFilter ? hookFilter.value : "";
            const selectedTag = tagFilter ? tagFilter.value : "";
            const selectedAuthor = authorFilter ? authorFilter.value : "";

            // Update visual highlighting for all filter types
            Admin.updateBadgeHighlighting("hook", selectedHook);
            Admin.updateBadgeHighlighting("tag", selectedTag);
            Admin.updateBadgeHighlighting("author", selectedAuthor);

            const cards = document.querySelectorAll(".plugin-card");

            cards.forEach((card) => {
                const name = card.dataset.name
                    ? card.dataset.name.toLowerCase()
                    : "";
                const description = card.dataset.description
                    ? card.dataset.description.toLowerCase()
                    : "";
                const author = card.dataset.author
                    ? card.dataset.author.toLowerCase()
                    : "";
                const mode = card.dataset.mode;
                const status = card.dataset.status;
                const hooks = card.dataset.hooks
                    ? card.dataset.hooks.split(",")
                    : [];
                const tags = card.dataset.tags ? card.dataset.tags.split(",") : [];

                let visible = true;

                // Search filter
                if (
                    searchQuery &&
                    !name.includes(searchQuery) &&
                    !description.includes(searchQuery) &&
                    !author.includes(searchQuery)
                ) {
                    visible = false;
                }

                // Mode filter
                if (selectedMode && mode !== selectedMode) {
                    visible = false;
                }

                // Status filter
                if (selectedStatus && status !== selectedStatus) {
                    visible = false;
                }

                // Hook filter
                if (selectedHook && !hooks.includes(selectedHook)) {
                    visible = false;
                }

                // Tag filter
                if (selectedTag && !tags.includes(selectedTag)) {
                    visible = false;
                }

                // Author filter
                if (
                    selectedAuthor &&
                    author.trim() !== selectedAuthor.toLowerCase().trim()
                ) {
                    visible = false;
                }

                if (visible) {
                    card.style.display = "block";
                } else {
                    card.style.display = "none";
                }
            });
        };

        // Filter by hook when clicking on hook point
        Admin.filterByHook = function (hook) {
            const hookFilter = Admin.safeGetElement("plugin-hook-filter");
            if (hookFilter) {
                hookFilter.value = hook;
                window.filterPlugins();
                hookFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

                // Update visual highlighting
                Admin.updateBadgeHighlighting("hook", hook);
            }
        };

        // Filter by tag when clicking on tag
        Admin.filterByTag = function (tag) {
            const tagFilter = Admin.safeGetElement("plugin-tag-filter");
            if (tagFilter) {
                tagFilter.value = tag;
                window.filterPlugins();
                tagFilter.scrollIntoView({ behavior: "smooth", block: "nearest" });

                // Update visual highlighting
                Admin.updateBadgeHighlighting("tag", tag);
            }
        };

        // Filter by author when clicking on author
        Admin.filterByAuthor = function (author) {
            const authorFilter = Admin.safeGetElement("plugin-author-filter");
            if (authorFilter) {
                // Convert to lowercase to match data-author attribute
                authorFilter.value = author.toLowerCase();
                window.filterPlugins();
                authorFilter.scrollIntoView({
                    behavior: "smooth",
                    block: "nearest",
                });

                // Update visual highlighting
                Admin.updateBadgeHighlighting("author", author);
            }
        };

        // Helper function to update badge highlighting
    Admin.updateBadgeHighlighting = function (type, value) {
            // Define selectors for each type
            const selectors = {
                hook: "[onclick^='filterByHook']",
                tag: "[onclick^='filterByTag']",
                author: "[onclick^='filterByAuthor']",
            };

            const selector = selectors[type];
            if (!selector) {
                return;
            }

            // Get all badges of this type
            const badges = document.querySelectorAll(selector);

            badges.forEach((badge) => {
                // Check if this is the "All" badge (empty value)
                const isAllBadge = badge.getAttribute("onclick").includes("('')");

                // Check if this badge matches the selected value
                const badgeValue = badge
                    .getAttribute("onclick")
                    .match(/'([^']*)'/)?.[1];
                const isSelected =
                    value === ""
                        ? isAllBadge
                        : badgeValue?.toLowerCase() === value?.toLowerCase();

                if (isSelected) {
                    // Apply active/selected styling
                    badge.classList.remove(
                        "bg-gray-100",
                        "text-gray-800",
                        "hover:bg-gray-200",
                    );
                    badge.classList.remove(
                        "dark:bg-gray-700",
                        "dark:text-gray-200",
                        "dark:hover:bg-gray-600",
                    );
                    badge.classList.add(
                        "bg-indigo-100",
                        "text-indigo-800",
                        "border",
                        "border-indigo-300",
                    );
                    badge.classList.add(
                        "dark:bg-indigo-900",
                        "dark:text-indigo-200",
                        "dark:border-indigo-700",
                    );
                } else if (!isAllBadge) {
                    // Reset to default styling for non-All badges
                    badge.classList.remove(
                        "bg-indigo-100",
                        "text-indigo-800",
                        "border",
                        "border-indigo-300",
                    );
                    badge.classList.remove(
                        "dark:bg-indigo-900",
                        "dark:text-indigo-200",
                        "dark:border-indigo-700",
                    );
                    badge.classList.add(
                        "bg-gray-100",
                        "text-gray-800",
                        "hover:bg-gray-200",
                    );
                    badge.classList.add(
                        "dark:bg-gray-700",
                        "dark:text-gray-200",
                        "dark:hover:bg-gray-600",
                    );
                }
            });
        }

        // Show plugin details modal
        Admin.showPluginDetails = async function (pluginName) {
            const modal = Admin.safeGetElement("plugin-details-modal");
            const modalName = Admin.safeGetElement("modal-plugin-name");
            const modalContent = Admin.safeGetElement("modal-plugin-content");

            if (!modal || !modalName || !modalContent) {
                console.error("Plugin details modal elements not found");
                return;
            }

            // Show loading state
            modalName.textContent = pluginName;
            modalContent.innerHTML =
                '<div class="text-center py-4">Loading...</div>';
            modal.classList.remove("hidden");

            try {
                const rootPath = window.ROOT_PATH || "";
                // Fetch plugin details
                const response = await fetch(
                    `${rootPath}/admin/plugins/${encodeURIComponent(pluginName)}`,
                    {
                        credentials: "same-origin",
                        headers: {
                            Accept: "application/json",
                        },
                    },
                );

                if (!response.ok) {
                    throw new Error(
                        `Failed to load plugin details: ${response.statusText}`,
                    );
                }

                const plugin = await response.json();

                // Render plugin details
                modalContent.innerHTML = `
                    <div class="space-y-4">
                        <div>
                            <h4 class="font-medium text-gray-700 dark:text-gray-300">Description</h4>
                            <p class="mt-1">${plugin.description || "No description available"}</p>
                        </div>

                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <h4 class="font-medium text-gray-700 dark:text-gray-300">Author</h4>
                                <p class="mt-1">${plugin.author || "Unknown"}</p>
                            </div>
                            <div>
                                <h4 class="font-medium text-gray-700 dark:text-gray-300">Version</h4>
                                <p class="mt-1">${plugin.version || "0.0.0"}</p>
                            </div>
                        </div>

                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <h4 class="font-medium text-gray-700 dark:text-gray-300">Mode</h4>
                                <p class="mt-1">
                                    <span class="px-2 py-1 text-xs rounded-full ${
                                        plugin.mode === "enforce"
                                            ? "bg-red-100 text-red-800"
                                            : plugin.mode === "permissive"
                                            ? "bg-yellow-100 text-yellow-800"
                                            : "bg-gray-100 text-gray-800"
                                    }">
                                        ${plugin.mode}
                                    </span>
                                </p>
                            </div>
                            <div>
                                <h4 class="font-medium text-gray-700 dark:text-gray-300">Priority</h4>
                                <p class="mt-1">${plugin.priority}</p>
                            </div>
                        </div>

                        <div>
                            <h4 class="font-medium text-gray-700 dark:text-gray-300">Hooks</h4>
                            <div class="mt-1 flex flex-wrap gap-1">
                                ${(plugin.hooks || [])
                                    .map(
                                        (hook) =>
                                            `<span class="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">${hook}</span>`,
                                    )
                                    .join("")}
                            </div>
                        </div>

                        <div>
                            <h4 class="font-medium text-gray-700 dark:text-gray-300">Tags</h4>
                            <div class="mt-1 flex flex-wrap gap-1">
                                ${(plugin.tags || [])
                                    .map(
                                        (tag) =>
                                            `<span class="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded">${tag}</span>`,
                                    )
                                    .join("")}
                            </div>
                        </div>

                        ${
                            plugin.config && Object.keys(plugin.config).length > 0
                                ? `
                            <div>
                                <h4 class="font-medium text-gray-700 dark:text-gray-300">Configuration</h4>
                                <pre class="mt-1 p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs overflow-x-auto">${JSON.stringify(plugin.config, null, 2)}</pre>
                            </div>
                        `
                                : ""
                        }
                    </div>
                `;
            } catch (error) {
                console.error("Error loading plugin details:", error);
                modalContent.innerHTML = `
                    <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                        <strong class="font-bold">Error:</strong>
                        <span class="block sm:inline">${error.message}</span>
                    </div>
                `;
            }
        };

        // Close plugin details modal
        Admin.closePluginDetails = function () {
            const modal = Admin.safeGetElement("plugin-details-modal");
            if (modal) {
                modal.classList.add("hidden");
            }
        };
    }

    // Initialize plugin functions if plugins panel exists
    if (Admin.isAdminUser() && Admin.safeGetElement("plugins-panel")) {
        Admin.initializePluginFunctions();
        // Populate filter dropdowns on initial load
        if (window.populatePluginFilters) {
            window.populatePluginFilters();
        }
    }

    // ===================================================================
    // MCP REGISTRY MODAL FUNCTIONS
    // ===================================================================

    // Define modal functions in global scope for MCP Registry
    Admin.showApiKeyModal = function (serverId, serverName, serverUrl) {
        const modal = Admin.safeGetElement("api-key-modal");
        if (modal) {
            Admin.safeGetElement("modal-server-id").value = serverId;
            Admin.safeGetElement("modal-server-name").textContent = serverName;
            Admin.safeGetElement("modal-custom-name").placeholder = serverName;
            modal.classList.remove("hidden");
        }
    };

    Admin.closeApiKeyModal = function () {
        const modal = Admin.safeGetElement("api-key-modal");
        if (modal) {
            modal.classList.add("hidden");
        }
        const form = Admin.safeGetElement("api-key-form");
        if (form) {
            form.reset();
        }
    };

    Admin.submitApiKeyForm = function (event) {
        event.preventDefault();
        const serverId = Admin.safeGetElement("modal-server-id").value;
        const customName = Admin.safeGetElement("modal-custom-name").value;
        const apiKey = Admin.safeGetElement("modal-api-key").value;

        // Prepare request data
        const requestData = {};
        if (customName) {
            requestData.name = customName;
        }
        if (apiKey) {
            requestData.api_key = apiKey;
        }

        const rootPath = window.ROOT_PATH || "";

        // Send registration request
        fetch(`${rootPath}/admin/mcp-registry/${serverId}/register`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: "Bearer " + (Admin.getCookie("jwt_token") || ""),
            },
            body: JSON.stringify(requestData),
        })
            .then((response) => response.json())
            .then((data) => {
                if (data.success) {
                    window.closeApiKeyModal();
                    // Reload the catalog
                    if (window.htmx && window.htmx.ajax) {
                        window.htmx.ajax(
                            "GET",
                            `${rootPath}/admin/mcp-registry/partial`,
                            {
                                target: "#mcp-registry-content",
                                swap: "innerHTML",
                            },
                        );
                    }
                } else {
                    alert("Registration failed: " + (data.error || data.message));
                }
            })
            .catch((error) => {
                alert("Error registering server: " + error);
            });
    };

    // gRPC Services Functions

    /**
    * Toggle visibility of TLS certificate/key fields based on TLS checkbox
    */
    Admin.toggleGrpcTlsFields = function () {
        const tlsEnabled =
            Admin.safeGetElement("grpc-tls-enabled")?.checked || false;
        const certField = Admin.safeGetElement("grpc-tls-cert-field");
        const keyField = Admin.safeGetElement("grpc-tls-key-field");

        if (tlsEnabled) {
            certField?.classList.remove("hidden");
            keyField?.classList.remove("hidden");
        } else {
            certField?.classList.add("hidden");
            keyField?.classList.add("hidden");
        }
    };

    /**
    * View gRPC service methods in a modal or alert
    * @param {string} serviceId - The gRPC service ID
    */
    Admin.viewGrpcMethods = function (serviceId) {
        const rootPath = window.ROOT_PATH || "";

        fetch(`${rootPath}/grpc/${serviceId}/methods`, {
            method: "GET",
            headers: {
                "Content-Type": "application/json",
                Authorization: "Bearer " + (Admin.getCookie("jwt_token") || ""),
            },
        })
            .then((response) => response.json())
            .then((data) => {
                if (data.methods && data.methods.length > 0) {
                    let methodsList = "gRPC Methods:\n\n";
                    data.methods.forEach((method) => {
                        methodsList += `${method.full_name}\n`;
                        methodsList += `  Input: ${method.input_type || "N/A"}\n`;
                        methodsList += `  Output: ${method.output_type || "N/A"}\n`;
                        if (method.client_streaming || method.server_streaming) {
                            methodsList += `  Streaming: ${method.client_streaming ? "Client" : ""} ${method.server_streaming ? "Server" : ""}\n`;
                        }
                        methodsList += "\n";
                    });
                    alert(methodsList);
                } else {
                    alert(
                        "No methods discovered for this service. Try re-reflecting the service.",
                    );
                }
            })
            .catch((error) => {
                alert("Error fetching methods: " + error);
            });
    };

    // Helper function to get cookie if not already defined
    if (typeof window.getCookie === "undefined") {
        Admin.getCookie = function (name) {
            const value = "; " + document.cookie;
            const parts = value.split("; " + name + "=");
            if (parts.length === 2) {
                return parts.pop().split(";").shift();
            }
            return "";
        };
    }

    // ==================== LLM CHAT FUNCTIONALITY ====================

    // State management for LLM chat
    const llmChatState = {
        selectedServerId: null,
        selectedServerName: null,
        isConnected: false,
        userId: null,
        messageHistory: [],
        connectedTools: [],
        toolCount: 0,
        serverToken: "",
        autoScroll: true,
    };

    /**
    * Initialize LLM Chat when tab is shown
    */
    Admin.initializeLLMChat = function () {
        console.log("Initializing LLM Chat...");

        // Generate or retrieve user ID
        llmChatState.userId = Admin.generateUserId();

        // Restore previously selected server (if any) from sessionStorage
        try {
            const persistedServerId = sessionStorage.getItem(
                "llm_chat_selected_server_id",
            );
            const persistedServerName = sessionStorage.getItem(
                "llm_chat_selected_server_name",
            );
            if (persistedServerId) {
                llmChatState.selectedServerId = persistedServerId;
                if (persistedServerName) {
                    llmChatState.selectedServerName = persistedServerName;
                }
            }
        } catch (e) {
            // sessionStorage may be unavailable in some environments
            console.warn("Could not restore persisted LLM server selection:", e);
        }

        // Load servers if not already loaded
        const serversList = Admin.safeGetElement("llm-chat-servers-list");
        if (serversList && serversList.children.length <= 1) {
            Admin.loadVirtualServersForChat();
        }

        // Load available LLM models from LLM Settings
        Admin.loadLLMModels();

        // Initialize chat input resize behavior
        Admin.initializeChatInputResize();

        // Initialize scroll handling
        Admin.initializeChatScroll();
    }

    /**
    * Initialize scroll listener for auto-scroll management
    */
    Admin.initializeChatScroll = function () {
        const container = Admin.safeGetElement("chat-messages-container");
        if (container) {
            container.addEventListener("scroll", () => {
                // Check if user is near bottom (within 50px)
                const isAtBottom =
                    container.scrollHeight -
                        container.scrollTop -
                        container.clientHeight <
                    50;
                llmChatState.autoScroll = isAtBottom;
            });
        }
    }

    /**
    * Generate a unique user ID for the session
    */
    Admin.getAuthenticatedUserId = function () {
        const currentUser = window.CURRENT_USER;
        if (!currentUser) {
            return "";
        }
        if (typeof currentUser === "string") {
            return currentUser;
        }
        if (typeof currentUser === "object") {
            return (
                currentUser.id ||
                currentUser.user_id ||
                currentUser.sub ||
                currentUser.email ||
                ""
            );
        }
        return "";
    }

    Admin.generateUserId = function () {
        const authenticatedUserId = Admin.getAuthenticatedUserId();
        if (authenticatedUserId) {
            sessionStorage.setItem("llm_chat_user_id", authenticatedUserId);
            return authenticatedUserId;
        }
        // Check if user ID exists in session storage
        let userId = sessionStorage.getItem("llm_chat_user_id");
        if (!userId) {
            // Generate a unique ID
            userId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            sessionStorage.setItem("llm_chat_user_id", userId);
        }
        return userId;
    }

    /**
    * Load virtual servers for chat
    */
    Admin.loadVirtualServersForChat = async function () {
        const serversList = Admin.safeGetElement("llm-chat-servers-list");
        if (!serversList) {
            return;
        }

        serversList.innerHTML =
            '<div class="flex items-center justify-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div></div>';

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH}/admin/servers`,
                {
                    method: "GET",
                    credentials: "same-origin",
                },
            );

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            let data = await response.json();
            // Handle new paginated response format
            if ("data" in data) {
                data = data.data;
            }
            const servers = Array.isArray(data) ? data : data.servers || [];

            if (servers.length === 0) {
                serversList.innerHTML =
                    '<div class="text-center text-gray-500 dark:text-gray-400 text-sm py-4">No virtual servers available</div>';
                return;
            }

            // Render server list with "Requires Token" pill and tooltip
            serversList.innerHTML = servers
                .map((server) => {
                    const toolCount = (server.associatedTools || []).length;
                    const isActive =
                        server.isActive !== undefined
                            ? server.isActive
                            : server.enabled;
                    const visibility = server.visibility || "public";
                    const requiresToken =
                        visibility === "team" || visibility === "private";

                    // Generate appropriate tooltip message
                    const tooltipMessage = requiresToken
                        ? server.visibility === "team"
                            ? "This is a team-level server. An access token will be required to connect."
                            : "This is a private server. An access token will be required to connect."
                        : "";

                    return `
                    <div class="server-item relative p-3 border rounded-lg cursor-pointer transition-colors
                        ${llmChatState.selectedServerId === server.id ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900" : "border-gray-200 dark:border-gray-600 hover:border-indigo-300 dark:hover:border-indigo-600"}
                        ${!isActive ? "opacity-50" : ""}"
                        onclick="Admin.selectServerForChat('${server.id}', '${escapeHtml(server.name)}', ${isActive}, ${requiresToken}, '${visibility}')"
                        style="position: relative;">

                        ${
                            requiresToken
                                ? `
                            <div class="tooltip"
                            style="position: absolute; left: 50%; transform: Admin.translateX(-50%); bottom: 120%; margin-bottom: 8px;
                                    background-color: #6B7280; color: white; font-size: 10px; border-radius: 4px;
                                    padding: 4px 20px; /* More horizontal width */
                                    opacity: 0; visibility: hidden; transition: opacity 0.2s ease-in;
                                    z-index: 1000;"> <!-- Added higher z-index to ensure it's above other elements -->
                            ${tooltipMessage}
                            <div style="position: absolute; left: 50%; bottom: -5px; transform: Admin.translateX(-50%);
                                        width: 0; height: 0; border-left: 5px solid transparent;
                                        border-right: 5px solid transparent; border-top: 5px solid #6B7280;"></div>
                            </div>`
                                : ""
                        }

                        <div class="flex justify-between items-start">
                            <div class="flex-1 min-w-0">
                                <h4 class="text-sm font-medium text-gray-900 dark:text-white truncate">${escapeHtml(server.name)}</h4>
                                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">${toolCount} tool${toolCount !== 1 ? "s" : ""}</p>
                            </div>
                            <div class="flex flex-col items-end gap-1">
                                ${!isActive ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">Inactive</span>' : ""}
                                ${requiresToken ? '<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-100 text-yellow-800">Requires Token</span>' : ""}
                            </div>
                        </div>
                        ${server.description ? `<p class="text-xs text-gray-600 dark:text-gray-400 mt-2 line-clamp-2">${escapeHtml(server.description)}</p>` : ""}
                    </div>
                `;
                })
                .join("");

            // Add hover event to show tooltip immediately on hover
            const serverItems = document.querySelectorAll(".server-item");
            serverItems.forEach((item) => {
                const tooltip = item.querySelector(".tooltip");
                item.addEventListener("mouseenter", () => {
                    if (tooltip) {
                        tooltip.style.opacity = "1"; // Make tooltip visible
                        tooltip.style.visibility = "visible"; // Show tooltip immediately
                    }
                });
                item.addEventListener("mouseleave", () => {
                    if (tooltip) {
                        tooltip.style.opacity = "0"; // Hide tooltip
                        tooltip.style.visibility = "hidden"; // Keep tooltip hidden when not hovering
                    }
                });
            });
        } catch (error) {
            console.error("Error loading servers for chat:", error);
            serversList.innerHTML =
                '<div class="text-center text-red-600 dark:text-red-400 text-sm py-4">Failed to load servers: ' +
                Admin.escapeHtml(error.message) +
                "</div>";
        }
    }

    /**
    * Select a server for chat
    */
    // eslint-disable-next-line no-unused-vars
    Admin.selectServerForChat = async function (
        serverId,
        serverName,
        isActive,
        requiresToken,
        serverVisibility,
    ) {
        if (!isActive) {
            Admin.showErrorMessage(
                "This server is inactive. Please select an active server.",
            );
            return;
        }

        // If server requires token (team or private), prompt for it
        if (requiresToken) {
            // Create context-aware message based on visibility level
            const visibilityMessage =
                serverVisibility === "team"
                    ? "This is a team-level server that requires authentication for access."
                    : "This is a private server that requires authentication for access.";

            const token = prompt(
                `Authentication Required\n\n${visibilityMessage}\n\nPlease enter the access token for "${serverName}":`,
            );

            if (token === null) {
                // User cancelled
                return;
            }

            // Store the token temporarily for this server
            llmChatState.serverToken = token || "";
        } else {
            // Public server - no token needed
            llmChatState.serverToken = "";
        }

        // Update state
        llmChatState.selectedServerId = serverId;
        llmChatState.selectedServerName = serverName;

        // Persist selection so it survives tab reloads within the session
        try {
            sessionStorage.setItem("llm_chat_selected_server_id", serverId);
            sessionStorage.setItem("llm_chat_selected_server_name", serverName);
        } catch (e) {
            // sessionStorage may be unavailable (e.g. privacy mode); ignore silently
            console.warn("Could not persist selected LLM server:", e);
        }

        // Update toolbar dropdown button text
        const selectedServerName = Admin.safeGetElement("selected-server-name");
        if (selectedServerName) {
            selectedServerName.textContent = serverName;
        }

        // Update UI to show selected server in dropdown list
        const serverItems = document.querySelectorAll(".server-item");
        serverItems.forEach((item) => {
            if (item.onclick.toString().includes(serverId)) {
                item.classList.add(
                    "border-indigo-500",
                    "bg-indigo-50",
                    "dark:bg-indigo-900",
                );
                item.classList.remove("border-gray-200", "dark:border-gray-600");
            } else {
                item.classList.remove(
                    "border-indigo-500",
                    "bg-indigo-50",
                    "dark:bg-indigo-900",
                );
                item.classList.add("border-gray-200", "dark:border-gray-600");
            }
        });

        // Close the dropdown
        const dropdownBtn = Admin.safeGetElement("llm-server-dropdown-btn");
        if (dropdownBtn) {
            // Trigger click outside to close dropdown
            const event = new Event("click");
            document.body.dispatchEvent(event);
        }

        // Enable connect button if provider is selected
        Admin.updateConnectButtonState();

        console.log(
            `Selected server: ${serverName} (${serverId}), Visibility: ${serverVisibility}, Token: ${requiresToken ? "Required" : "Not required"}`,
        );
    }

    /**
    * Load available LLM models from the gateway's LLM Settings
    */
    Admin.loadLLMModels = async function () {
        const modelSelect = Admin.safeGetElement("llm-model-select");
        if (!modelSelect) {
            return;
        }

        try {
            const response = await Admin.fetchWithTimeout(
                `${window.ROOT_PATH}/llmchat/gateway/models`,
            );
            if (!response.ok) {
                throw new Error("Failed to load models");
            }
            const data = await response.json();

            // Clear existing options except the placeholder
            modelSelect.innerHTML =
                '<option value="">Select Model (configure in Settings → LLM Settings)</option>';

            // Add enabled models from enabled providers
            if (data.models && data.models.length > 0) {
                data.models.forEach((model) => {
                    const option = document.createElement("option");
                    option.value = model.model_id;
                    option.textContent = `${model.model_id} (${model.provider_name || model.provider_type})`;
                    modelSelect.appendChild(option);
                });
            }

            if (modelSelect.options.length === 1) {
                // Only placeholder exists - no models configured
                modelSelect.innerHTML =
                    '<option value="">No models configured - go to Settings → LLM Settings</option>';
            }
        } catch (error) {
            console.error("Error loading LLM models:", error);
            modelSelect.innerHTML =
                '<option value="">Error loading models</option>';
        }

        Admin.updateConnectButtonState();
    }

    /**
    * Handle LLM model selection change
    */
    // eslint-disable-next-line no-unused-vars
    Admin.handleLLMModelChange = function () {
        const modelSelect = Admin.safeGetElement("llm-model-select");
        const modelBadge = Admin.safeGetElement("llm-model-badge");
        const modelNameSpan = Admin.safeGetElement("llmchat-model-name");

        if (modelSelect && modelBadge && modelNameSpan) {
            const selectedOption = modelSelect.options[modelSelect.selectedIndex];
            const modelValue = modelSelect.value;

            if (modelValue) {
                // Show badge with selected model name
                const modelName = selectedOption.text;
                modelNameSpan.textContent = modelName;
                modelBadge.classList.remove("hidden");
            } else {
                // Hide badge when no model selected
                modelBadge.classList.add("hidden");
            }
        }

        Admin.updateConnectButtonState();
    }

    /**
    * Update connect button state
    */
    Admin.updateConnectButtonState = function () {
        const connectBtn = Admin.safeGetElement("llm-connect-btn");
        const modelSelect = Admin.safeGetElement("llm-model-select");
        const selectedModel = modelSelect ? modelSelect.value : "";
        const hasServer = llmChatState.selectedServerId !== null;

        if (connectBtn) {
            connectBtn.disabled = !hasServer || !selectedModel;
        }
    }

    /**
    * Connect to LLM chat
    */
    // eslint-disable-next-line no-unused-vars
    Admin.connectLLMChat = async function () {
        if (!llmChatState.selectedServerId) {
            Admin.showErrorMessage("Please select a virtual server first");
            return;
        }

        const modelSelect = Admin.safeGetElement("llm-model-select");
        const selectedModel = modelSelect ? modelSelect.value : "";
        if (!selectedModel) {
            Admin.showErrorMessage("Please select an LLM model");
            return;
        }

        // Clear previous chat history before connecting
        Admin.clearChatMessages();
        llmChatState.messageHistory = [];

        // Show loading state
        const connectBtn = Admin.safeGetElement("llm-connect-btn");
        const originalText = connectBtn.textContent;
        connectBtn.textContent = "Connecting...";
        connectBtn.disabled = true;

        // Clear any previous error messages
        const statusDiv = Admin.safeGetElement("llm-config-status");
        if (statusDiv) {
            statusDiv.classList.add("hidden");
        }

        try {
            // Build LLM config - now uses model ID from LLM Settings
            const llmConfig = Admin.buildLLMConfig(selectedModel);

            // Build server URL
            const serverUrl = `${location.protocol}//${location.hostname}${![80, 443].includes(location.port) ? `:${location.port}` : ""}/servers/${llmChatState.selectedServerId}/mcp`;
            console.log("Selected server URL:", serverUrl);

            // Use the stored server token (empty string for public servers)
            const jwtToken = llmChatState.serverToken || "";

            const payload = {
                user_id: llmChatState.userId,
                server: {
                    url: serverUrl,
                    transport: "streamable_http",
                    auth_token: jwtToken,
                },
                llm: llmConfig,
                streaming: true,
            };

            console.log("Connecting with payload:", {
                ...payload,
                server: { ...payload.server, auth_token: "REDACTED" },
            });

            // Make connection request with timeout handling
            let response;
            try {
                response = await Admin.fetchWithTimeout(
                    `${window.ROOT_PATH}/llmchat/connect`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${jwtToken}`,
                        },
                        body: JSON.stringify(payload),
                        credentials: "same-origin",
                    },
                    30000,
                );
            } catch (fetchError) {
                // Handle network/timeout errors
                if (
                    fetchError.name === "AbortError" ||
                    fetchError.message.includes("timeout")
                ) {
                    throw new Error(
                        "Connection timed out. Please check if the server is responsive and try again.",
                    );
                }
                throw new Error(`Network error: ${fetchError.message}`);
            }

            // Handle HTTP errors - extract backend error message
            if (!response.ok) {
                let errorMessage = `Connection failed (HTTP ${response.status})`;

                try {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        // Use the backend error message directly
                        errorMessage = errorData.detail;
                    }
                } catch (parseError) {
                    console.warn("Could not parse error response:", parseError);
                    // Keep generic error message
                }

                throw new Error(errorMessage);
            }

            // Parse successful response
            let result;
            try {
                result = await response.json();
            } catch (parseError) {
                throw new Error(
                    "Failed to parse server response. Please try again.",
                );
            }

            console.log("Connection successful:", result);

            // Update state
            llmChatState.isConnected = true;
            llmChatState.connectedTools = result.tools || [];
            llmChatState.toolCount = result.tool_count || 0;

            // Update UI
            Admin.showConnectionSuccess();

            // Clear welcome message and show chat input
            const welcomeMsg = Admin.safeGetElement("chat-welcome-message");
            if (welcomeMsg) {
                welcomeMsg.remove();
            }

            const chatInput = Admin.safeGetElement("chat-input-container");
            if (chatInput) {
                chatInput.classList.remove("hidden");
                Admin.safeGetElement("chat-input").disabled = false;
                Admin.safeGetElement("chat-send-btn").disabled = false;
                Admin.safeGetElement("chat-input").focus();
            }

            // Hide connect button, show disconnect button
            const disconnectBtn = Admin.safeGetElement("llm-disconnect-btn");
            if (connectBtn) {
                connectBtn.classList.add("hidden");
            }
            if (disconnectBtn) {
                disconnectBtn.classList.remove("hidden");
            }

            // Auto-collapse configuration
            // Disable configuration toggle instead of hiding it
            const configToggle = Admin.safeGetElement("llm-config-toggle");
            if (configToggle) {
                configToggle.disabled = true;
                configToggle.classList.add("opacity-50", "cursor-not-allowed");
                configToggle.title = "Please disconnect to change configuration";

                // Ensure dropdown is closed if it was open (handled by Alpine, but good to be safe)
                // We DON'T set 'hidden' class manually as it breaks Alpine's state
                // But we can trigger a click if we knew it was open, or just let Alpine handle click.away
            }

            // Disable server dropdown as well
            const serverDropdownBtn = Admin.safeGetElement(
                "llm-server-dropdown-btn",
            );
            if (serverDropdownBtn) {
                serverDropdownBtn.disabled = true;
                serverDropdownBtn.classList.add("opacity-50", "cursor-not-allowed");
                serverDropdownBtn.title = "Please disconnect to change server";
            }

            // Show success message
            Admin.showNotification(
                `Connected to ${llmChatState.selectedServerName}`,
                "success",
            );
        } catch (error) {
            console.error("Connection error:", error);
            // Display the backend error message to the user
            Admin.showConnectionError(error.message);
        } finally {
            connectBtn.textContent = originalText;
            connectBtn.disabled = false;
        }
    }

    /**
    * Build LLM config object from form inputs
    * Models are configured via Admin UI -> Settings -> LLM Settings
    */
    Admin.buildLLMConfig = function (modelId) {
        const config = {
            model: modelId,
        };

        // Get optional temperature
        const temperatureEl = Admin.safeGetElement("llm-temperature");
        if (temperatureEl && temperatureEl.value.trim()) {
            config.temperature = parseFloat(temperatureEl.value.trim());
        }

        // Get optional max tokens
        const maxTokensEl = Admin.safeGetElement("llm-max-tokens");
        if (maxTokensEl && maxTokensEl.value.trim()) {
            config.max_tokens = parseInt(maxTokensEl.value.trim(), 10);
        }

        return config;
    }

    /**
    * Legacy function - kept for compatibility but no longer used
    * @deprecated Use Admin.buildLLMConfig(modelId) instead
    */
    // eslint-disable-next-line no-unused-vars
    Admin.buildLLMConfigLegacy = function (provider) {
        const config = {
            provider,
            config: {},
        };

        if (provider === "azure_openai") {
            const apiKeyEl = Admin.safeGetElement("azure-api-key");
            const endpointEl = Admin.safeGetElement("azure-endpoint");
            const deploymentEl = Admin.safeGetElement("azure-deployment");
            const apiVersionEl = Admin.safeGetElement("azure-api-version");
            const temperatureEl = Admin.safeGetElement("azure-temperature");

            const apiKey = apiKeyEl?.value?.trim() || "";
            const endpoint = endpointEl?.value?.trim() || "";
            const deployment = deploymentEl?.value?.trim() || "";
            const apiVersion = apiVersionEl?.value?.trim() || "";
            const temperature = temperatureEl?.value?.trim() || "";

            // Only include non-empty values
            if (apiKey) {
                config.config.api_key = apiKey;
            }
            if (endpoint) {
                config.config.azure_endpoint = endpoint;
            }
            if (deployment) {
                config.config.azure_deployment = deployment;
            }
            if (apiVersion) {
                config.config.api_version = apiVersion;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
        } else if (provider === "openai") {
            const apiKeyEl = Admin.safeGetElement("openai-api-key");
            const modelEl = Admin.safeGetElement("openai-model");
            const baseUrlEl = Admin.safeGetElement("openai-base-url");
            const temperatureEl = Admin.safeGetElement("openai-temperature");

            const apiKey = apiKeyEl?.value?.trim() || "";
            const model = modelEl?.value?.trim() || "";
            const baseUrl = baseUrlEl.value.trim();
            const temperature = temperatureEl.value.trim();

            // Only include non-empty values
            if (apiKey) {
                config.config.api_key = apiKey;
            }
            if (model) {
                config.config.model = model;
            }
            if (baseUrl) {
                config.config.base_url = baseUrl;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
        } else if (provider === "anthropic") {
            const apiKey = document
                .getElementById("anthropic-api-key")
                .value.trim();
            const model = Admin.safeGetElement("anthropic-model").value.trim();
            const temperature = document
                .getElementById("anthropic-temperature")
                .value.trim();
            const maxTokens = document
                .getElementById("anthropic-max-tokens")
                .value.trim();

            // Only include non-empty values
            if (apiKey) {
                config.config.api_key = apiKey;
            }
            if (model) {
                config.config.model = model;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
            if (maxTokens) {
                config.config.max_tokens = parseInt(maxTokens, 10);
            }
        } else if (provider === "aws_bedrock") {
            const modelId = document
                .getElementById("aws-bedrock-model-id")
                .value.trim();
            const region = document
                .getElementById("aws-bedrock-region")
                .value.trim();
            const accessKeyId = document
                .getElementById("aws-access-key-id")
                .value.trim();
            const secretAccessKey = document
                .getElementById("aws-secret-access-key")
                .value.trim();
            const temperature = document
                .getElementById("aws-bedrock-temperature")
                .value.trim();
            const maxTokens = document
                .getElementById("aws-bedrock-max-tokens")
                .value.trim();

            // Only include non-empty values
            if (modelId) {
                config.config.model_id = modelId;
            }
            if (region) {
                config.config.region_name = region;
            }
            if (accessKeyId) {
                config.config.aws_access_key_id = accessKeyId;
            }
            if (secretAccessKey) {
                config.config.aws_secret_access_key = secretAccessKey;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
            if (maxTokens) {
                config.config.max_tokens = parseInt(maxTokens, 10);
            }
        } else if (provider === "watsonx") {
            const apiKey = Admin.safeGetElement("watsonx-api-key").value.trim();
            const url = Admin.safeGetElement("watsonx-url").value.trim();
            const projectId = document
                .getElementById("watsonx-project-id")
                .value.trim();
            const modelId = document
                .getElementById("watsonx-model-id")
                .value.trim();
            const temperature = document
                .getElementById("watsonx-temperature")
                .value.trim();
            const maxNewTokens = document
                .getElementById("watsonx-max-new-tokens")
                .value.trim();
            const decodingMethod = document
                .getElementById("watsonx-decoding-method")
                .value.trim();

            // Only include non-empty values
            if (apiKey) {
                config.config.apikey = apiKey;
            }
            if (url) {
                config.config.url = url;
            }
            if (projectId) {
                config.config.projectid = projectId;
            }
            if (modelId) {
                config.config.modelid = modelId;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
            if (maxNewTokens) {
                config.config.maxnewtokens = parseInt(maxNewTokens, 10);
            }
            if (decodingMethod) {
                config.config.decodingmethod = decodingMethod;
            }
        } else if (provider === "ollama") {
            const model = Admin.safeGetElement("ollama-model").value.trim();
            const baseUrl = Admin.safeGetElement("ollama-base-url").value.trim();
            const temperature = document
                .getElementById("ollama-temperature")
                .value.trim();

            // Only include non-empty values
            if (model) {
                config.config.model = model;
            }
            if (baseUrl) {
                config.config.base_url = baseUrl;
            }
            if (temperature) {
                config.config.temperature = parseFloat(temperature);
            }
        }

        return config;
    }

    /**
    * Copy environment variables to clipboard for the specified provider
    */
    // eslint-disable-next-line no-unused-vars
    Admin.copyEnvVariables = async function (provider) {
        const envVariables = {
            azure: `AZURE_OPENAI_API_KEY=<api_key>
    AZURE_OPENAI_ENDPOINT=https://test-url.openai.azure.com
    AZURE_OPENAI_API_VERSION=2024-02-15-preview
    AZURE_OPENAI_DEPLOYMENT=gpt4o
    AZURE_OPENAI_MODEL=gpt4o`,

            openai: `OPENAI_API_KEY=<api_key>
    OPENAI_MODEL=gpt-4o-mini
    OPENAI_BASE_URL=https://api.openai.com/v1`,

            anthropic: `ANTHROPIC_API_KEY=<api_key>
    ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
    ANTHROPIC_MAX_TOKENS=4096`,

            aws_bedrock: `AWS_BEDROCK_MODEL_ID=anthropic.claude-v2
    AWS_BEDROCK_REGION=us-east-1
    AWS_ACCESS_KEY_ID=<optional>
    AWS_SECRET_ACCESS_KEY=<optional>`,

            watsonx: `WATSONX_APIKEY=apikey
    WATSONX_URL=https://us-south.ml.cloud.ibm.com
    WATSONX_PROJECT_ID=project-id
    WATSONX_MODEL_ID=ibm/granite-13b-chat-v2
    WATSONX_TEMPERATURE=0.7`,

            ollama: `OLLAMA_MODEL=llama3
    OLLAMA_BASE_URL=http://localhost:11434`,
        };

        const variables = envVariables[provider];

        if (!variables) {
            console.error("Unknown provider:", provider);
            Admin.showErrorMessage("Unknown provider");
            return;
        }

        try {
            // Try modern clipboard API first
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(variables);
                Admin.showCopySuccessNotification(provider);
            } else {
                // Fallback for older browsers
                const textArea = document.createElement("textarea");
                textArea.value = variables;
                textArea.style.position = "fixed";
                textArea.style.left = "-999999px";
                textArea.style.top = "-999999px";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();

                try {
                    const successful = document.execCommand("copy");
                    if (successful) {
                        Admin.showCopySuccessNotification(provider);
                    } else {
                        throw new Error("Copy command failed");
                    }
                } catch (err) {
                    console.error("Fallback copy failed:", err);
                    Admin.showErrorMessage("Failed to copy to clipboard");
                } finally {
                    document.body.removeChild(textArea);
                }
            }
        } catch (err) {
            console.error("Failed to copy environment variables:", err);
            Admin.showErrorMessage("Failed to copy to clipboard. Please copy manually.");
        }
    }

    /**
    * Show success notification when environment variables are copied
    */
    Admin.showCopySuccessNotification = function (provider) {
        const providerNames = {
            azure: "Azure OpenAI",
            ollama: "Ollama",
            openai: "OpenAI",
        };

        const displayName = providerNames[provider] || provider;

        // Create notification element
        const notification = document.createElement("div");
        notification.className = "fixed top-4 right-4 z-50 animate-fade-in";
        notification.innerHTML = `
            <div class="bg-green-500 text-white px-4 py-3 rounded-lg shadow-lg flex items-center space-x-2">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
                <span class="font-medium">${displayName} variables copied!</span>
            </div>
        `;

        document.body.appendChild(notification);

        // Remove notification after 3 seconds
        setTimeout(() => {
            notification.style.opacity = "0";
            notification.style.transition = "opacity 0.3s ease-out";
            setTimeout(() => {
                if (notification.parentNode) {
                    document.body.removeChild(notification);
                }
            }, 300);
        }, 3000);
    }

    /**
    * Show connection success
    */
    Admin.showConnectionSuccess = function () {
        // Update connection status badge
        const statusBadge = Admin.safeGetElement("llm-connection-status");
        if (statusBadge) {
            statusBadge.classList.remove("hidden");
        }

        // Show active tools badge using data from connection response
        const toolsBadge = Admin.safeGetElement("llm-active-tools-badge");
        const toolCountSpan = Admin.safeGetElement("llm-tool-count");
        const toolListDiv = Admin.safeGetElement("llm-tool-list");

        if (toolsBadge && toolCountSpan && toolListDiv) {
            const tools = llmChatState.connectedTools || [];
            const count = tools.length;

            toolCountSpan.textContent = `${count} tool${count !== 1 ? "s" : ""}`;

            // Clear and populate tool list with individual pills
            toolListDiv.innerHTML = "";

            if (count > 0) {
                tools.forEach((toolName, index) => {
                    const pill = document.createElement("span");
                    pill.className =
                        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/40 dark:to-indigo-900/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-700 shadow-sm hover:shadow-md transition-all hover:scale-105";

                    // Tool icon
                    const icon = document.createElementNS(
                        "http://www.w3.org/2000/svg",
                        "svg",
                    );
                    icon.setAttribute("class", "w-3.5 h-3.5");
                    icon.setAttribute("fill", "none");
                    icon.setAttribute("stroke", "currentColor");
                    icon.setAttribute("viewBox", "0 0 24 24");
                    icon.innerHTML =
                        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>';

                    const text = document.createElement("span");
                    text.textContent = toolName;

                    pill.appendChild(icon);
                    pill.appendChild(text);
                    toolListDiv.appendChild(pill);
                });
            } else {
                const emptyMsg = document.createElement("div");
                emptyMsg.className = "text-center py-4";
                emptyMsg.innerHTML = `
        <svg class="w-8 h-8 mx-auto text-gray-400 dark:text-gray-600 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
        </svg>
        <p class="text-xs text-gray-500 dark:text-gray-400">No tools available for this server</p>
        `;
                toolListDiv.appendChild(emptyMsg);
            }

            toolsBadge.classList.remove("hidden");
        }

        // Hide connect button, show disconnect button
        const connectBtn = Admin.safeGetElement("llm-connect-btn");
        const disconnectBtn = Admin.safeGetElement("llm-disconnect-btn");
        if (connectBtn) {
            connectBtn.classList.add("hidden");
        }
        if (disconnectBtn) {
            disconnectBtn.classList.remove("hidden");
        }

        // Show success message
        Admin.showNotification(
            `Connected to ${llmChatState.selectedServerName}`,
            "success",
        );
    }

    /**
    * Show connection error
    */
    /**
    * Display connection error with proper formatting
    */
    Admin.showConnectionError = function (message) {
        const statusDiv = Admin.safeGetElement("llm-config-status");
        if (statusDiv) {
            statusDiv.className =
                "text-sm text-red-600 dark:text-red-400 p-3 bg-red-50 dark:bg-red-900/20 rounded border border-red-200 dark:border-red-700";
            statusDiv.innerHTML = `
                <div class="flex items-start gap-2">
                    <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                    </svg>
                    <div class="flex-1">
                        <strong class="font-semibold">Connection Failed</strong>
                        <p class="mt-1">${escapeHtml(message)}</p>
                    </div>
                </div>
            `;
            statusDiv.classList.remove("hidden");
        }
    }

    /**
    * Disconnect from LLM chat
    */
    // eslint-disable-next-line no-unused-vars
    Admin.disconnectLLMChat = async function () {
        if (!llmChatState.isConnected) {
            console.warn("No active connection to disconnect");
            return;
        }

        const disconnectBtn = Admin.safeGetElement("llm-disconnect-btn");
        const originalText = disconnectBtn.textContent;
        disconnectBtn.textContent = "Disconnecting...";
        disconnectBtn.disabled = true;

        try {
            const jwtToken = Admin.getCookie("jwt_token");

            // Attempt graceful disconnection
            let response;
            let backendError = null;

            try {
                response = await Admin.fetchWithTimeout(
                    `${window.ROOT_PATH}/llmchat/disconnect`,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${jwtToken}`,
                        },
                        body: JSON.stringify({
                            user_id: llmChatState.userId,
                        }),
                        credentials: "same-origin",
                    },
                    10000,
                ); // Shorter timeout for disconnect
            } catch (fetchError) {
                console.warn(
                    "Disconnect request failed, cleaning up locally:",
                    fetchError,
                );
                backendError = fetchError.message;
                // Continue with local cleanup even if server request fails
            }

            // Parse response if available
            let disconnectStatus = "unknown";
            if (response) {
                if (response.ok) {
                    try {
                        const result = await response.json();
                        disconnectStatus = result.status || "disconnected";

                        if (result.warning) {
                            console.warn("Disconnect warning:", result.warning);
                        }
                    } catch (parseError) {
                        console.warn("Could not parse disconnect response");
                    }
                } else {
                    // Extract backend error message
                    try {
                        const errorData = await response.json();
                        if (errorData.detail) {
                            backendError = errorData.detail;
                        }
                    } catch (parseError) {
                        backendError = `HTTP ${response.status}`;
                    }
                    console.warn(
                        `Disconnect returned error: ${backendError}, cleaning up locally`,
                    );
                }
            }

            // Always update local state regardless of server response
            llmChatState.isConnected = false;
            llmChatState.messageHistory = [];
            llmChatState.connectedTools = [];
            llmChatState.toolCount = 0;
            llmChatState.serverToken = "";

            // Update UI
            const statusBadge = Admin.safeGetElement("llm-connection-status");
            if (statusBadge) {
                statusBadge.classList.add("hidden");
            }

            const toolsBadge = Admin.safeGetElement("llm-active-tools-badge");
            if (toolsBadge) {
                toolsBadge.classList.add("hidden");
            }

            const modelBadge = Admin.safeGetElement("llm-model-badge");
            if (modelBadge) {
                modelBadge.classList.add("hidden");
            }

            const connectBtn = Admin.safeGetElement("llm-connect-btn");
            if (connectBtn) {
                connectBtn.classList.remove("hidden");
            }
            if (disconnectBtn) {
                disconnectBtn.classList.add("hidden");
            }

            // Hide chat input
            const chatInput = Admin.safeGetElement("chat-input-container");
            if (chatInput) {
                chatInput.classList.add("hidden");
                Admin.safeGetElement("chat-input").disabled = true;
                Admin.safeGetElement("chat-send-btn").disabled = true;
            }

            // Re-enable configuration toggle
            const configToggle = Admin.safeGetElement("llm-config-toggle");
            if (configToggle) {
                configToggle.disabled = false;
                configToggle.classList.remove("opacity-50", "cursor-not-allowed");
                configToggle.removeAttribute("title");
            }

            // Re-enable server dropdown
            const serverDropdownBtn = Admin.safeGetElement(
                "llm-server-dropdown-btn",
            );
            if (serverDropdownBtn) {
                serverDropdownBtn.disabled = false;
                serverDropdownBtn.classList.remove(
                    "opacity-50",
                    "cursor-not-allowed",
                );
                serverDropdownBtn.removeAttribute("title");
            }

            // Clear messages
            Admin.clearChatMessages();

            // Show appropriate notification
            if (backendError) {
                Admin.showNotification(
                    `Disconnected (server error: ${backendError})`,
                    "warning",
                );
            } else if (disconnectStatus === "no_active_session") {
                Admin.showNotification("Already disconnected", "info");
            } else if (disconnectStatus === "disconnected_with_errors") {
                Admin.showNotification("Disconnected (with cleanup warnings)", "warning");
            } else {
                Admin.showNotification("Disconnected successfully", "info");
            }
        } catch (error) {
            console.error("Unexpected disconnection error:", error);

            // Force cleanup even on error
            llmChatState.isConnected = false;
            llmChatState.messageHistory = [];
            llmChatState.connectedTools = [];
            llmChatState.toolCount = 0;

            // Display backend error if available
            Admin.showErrorMessage(
                `Disconnection error: ${error.message}. Local session cleared.`,
            );
        } finally {
            disconnectBtn.textContent = originalText;
            disconnectBtn.disabled = false;
        }
    }

    /**
    * Send chat message
    */
    Admin.sendChatMessage = async function (event) {
        event.preventDefault();

        const input = Admin.safeGetElement("chat-input");
        const message = input.value.trim();

        if (!message) {
            return;
        }

        if (!llmChatState.isConnected) {
            Admin.showErrorMessage("Please connect to a server first");
            return;
        }

        // Add user message to chat
        Admin.appendChatMessage("user", message);

        // Clear input
        input.value = "";
        input.style.height = "auto";

        // Disable input while processing
        input.disabled = true;
        Admin.safeGetElement("chat-send-btn").disabled = true;

        let assistantMsgId = null;
        let reader = null;

        try {
            const jwtToken = Admin.getCookie("jwt_token");

            // Create assistant message placeholder for streaming
            assistantMsgId = Admin.appendChatMessage("assistant", "", true);

            // Make request with timeout handling
            let response;
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minute timeout

                response = await fetch(`${window.ROOT_PATH}/llmchat/chat`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${jwtToken}`,
                    },
                    body: JSON.stringify({
                        user_id: llmChatState.userId,
                        message,
                        streaming: true,
                    }),
                    credentials: "same-origin",
                    signal: controller.signal,
                });

                clearTimeout(timeoutId);
            } catch (fetchError) {
                if (fetchError.name === "AbortError") {
                    throw new Error(
                        "Request timed out. The response took too long.",
                    );
                }
                throw new Error(`Network error: ${fetchError.message}`);
            }

            // Handle HTTP errors - extract backend error message
            if (!response.ok) {
                let errorMessage = `Chat request failed (HTTP ${response.status})`;

                try {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        // Use backend error message directly
                        errorMessage = errorData.detail;
                    }
                } catch (parseError) {
                    console.warn("Could not parse error response");
                }

                throw new Error(errorMessage);
            }

            // Validate response has body stream
            if (!response.body) {
                throw new Error("No response stream received from server");
            }

            // Handle streaming SSE response
            reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let accumulatedText = "";
            let hasReceivedData = false;

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) {
                        break;
                    }

                    hasReceivedData = true;
                    buffer += decoder.decode(value, { stream: true });

                    // Process complete SSE events (separated by blank line)
                    let boundary;
                    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
                        const rawEvent = buffer.slice(0, boundary).trim();
                        buffer = buffer.slice(boundary + 2);

                        if (!rawEvent) {
                            continue;
                        }

                        let eventType = "message";
                        const dataLines = [];

                        for (const line of rawEvent.split("\n")) {
                            if (line.startsWith("event:")) {
                                eventType = line.slice(6).trim();
                            } else if (line.startsWith("data:")) {
                                dataLines.push(line.slice(5).trim());
                            }
                        }

                        let payload = {};
                        const dataStr = dataLines.join("");

                        try {
                            payload = dataStr ? JSON.parse(dataStr) : {};
                        } catch (parseError) {
                            console.warn(
                                "Failed to parse SSE data:",
                                dataStr,
                                parseError,
                            );
                            continue;
                        }

                        // Handle different event types
                        try {
                            switch (eventType) {
                                case "token": {
                                    const text = payload.content;
                                    if (text) {
                                        accumulatedText += text;
                                        // Process and render with think tags
                                        Admin.updateChatMessageWithThinkTags(
                                            assistantMsgId,
                                            accumulatedText,
                                        );
                                    }
                                    break;
                                }
                                case "tool_start":
                                case "tool_end":
                                case "tool_error":
                                    Admin.addToolEventToCard(
                                        assistantMsgId,
                                        eventType,
                                        payload,
                                    );
                                    break;

                                case "final":
                                    if (payload.tool_used) {
                                        Admin.setToolUsedSummary(
                                            assistantMsgId,
                                            true,
                                            payload.tools,
                                        );
                                    }
                                    setTimeout(scrollChatToBottom, 50);
                                    break;

                                case "error": {
                                    // Handle server-sent error events from backend
                                    const errorMsg =
                                        payload.error ||
                                        "An error occurred during processing";
                                    const isRecoverable =
                                        payload.recoverable !== false;

                                    // Display error in the assistant message
                                    Admin.updateChatMessage(
                                        assistantMsgId,
                                        `❌ Error: ${errorMsg}`,
                                    );

                                    if (!isRecoverable) {
                                        // For non-recoverable errors, suggest reconnection
                                        Admin.appendChatMessage(
                                            "system",
                                            "⚠️ Connection lost. Please reconnect to continue.",
                                        );
                                        llmChatState.isConnected = false;

                                        // Update UI to show disconnected state
                                        const connectBtn =
                                            Admin.safeGetElement(
                                                "llm-connect-btn",
                                            );
                                        const disconnectBtn =
                                            Admin.safeGetElement(
                                                "llm-disconnect-btn",
                                            );
                                        if (connectBtn) {
                                            connectBtn.classList.remove("hidden");
                                        }
                                        if (disconnectBtn) {
                                            disconnectBtn.classList.add("hidden");
                                        }
                                    }
                                    break;
                                }
                                default:
                                    console.warn("Unknown event type:", eventType);
                                    break;
                            }
                        } catch (eventError) {
                            console.error(
                                `Error handling event ${eventType}:`,
                                eventError,
                            );
                            // Continue processing other events
                        }
                    }

                    setTimeout(scrollChatToBottom, 100);
                }
            } catch (streamError) {
                console.error("Stream reading error:", streamError);
                throw new Error(`Stream error: ${streamError.message}`);
            }

            // Validate we received some data
            if (!hasReceivedData) {
                throw new Error("No data received from server");
            }

            // Mark streaming as complete
            Admin.markMessageComplete(assistantMsgId);
        } catch (error) {
            console.error("Chat error:", error);

            // Display backend error message to user
            const errorMsg = error.message || "An unexpected error occurred";
            Admin.appendChatMessage("system", `❌ ${errorMsg}`);

            // If we have a partial assistant message, mark it as complete
            if (assistantMsgId) {
                Admin.markMessageComplete(assistantMsgId);
            }
        } finally {
            // Clean up reader if it exists
            if (reader) {
                try {
                    await reader.cancel();
                } catch (cancelError) {
                    console.warn("Error canceling reader:", cancelError);
                }
            }

            // Re-enable input
            input.disabled = false;
            Admin.safeGetElement("chat-send-btn").disabled = false;
            input.focus();
        }
    }

    /**
    * Parse content with <think> tags and separate thinking from final answer
    * Returns: { thinkingSteps: [{content: string}], finalAnswer: string, rawContent: string }
    */
    Admin.parseThinkTags = function (content) {
        const thinkingSteps = [];
        let finalAnswer = "";
        const rawContent = content;

        // Extract all <think>...</think> blocks
        const thinkRegex = /<think>([\s\S]*?)<\/think>/g;
        let match;
        // let lastIndex = 0;

        while ((match = thinkRegex.exec(content)) !== null) {
            const thinkContent = match[1].trim();
            if (thinkContent) {
                thinkingSteps.push({ content: thinkContent });
            }
            // lastIndex = match.index + match[0].length;
        }

        // Remove all <think> tags to get final answer
        finalAnswer = content.replace(/<think>[\s\S]*?<\/think>/g, "").trim();

        return { thinkingSteps, finalAnswer, rawContent };
    }

    /**
    * Update chat message with think tags support
    * Renders thinking steps in collapsible UI and final answer separately
    */
    Admin.updateChatMessageWithThinkTags = function (messageId, content) {
        const messageDiv = Admin.safeGetElement(messageId);
        if (!messageDiv) {
            return;
        }

        const contentEl = messageDiv.querySelector(".message-content");
        if (!contentEl) {
            return;
        }

        // Store raw content for final processing
        contentEl.setAttribute("data-raw-content", content);

        // Parse content for think tags
        const { thinkingSteps, finalAnswer } = Admin.parseThinkTags(content);

        // Clear existing content
        contentEl.innerHTML = "";

        // Render thinking steps if present
        if (thinkingSteps.length > 0) {
            const thinkingContainer = Admin.createThinkingUI(thinkingSteps);
            contentEl.appendChild(thinkingContainer);
        }

        // Render final answer
        if (finalAnswer) {
            const answerDiv = document.createElement("div");
            answerDiv.className = "final-answer-content markdown-body";
            answerDiv.innerHTML = Admin.renderMarkdown(finalAnswer);
            contentEl.appendChild(answerDiv);
        }

        // Throttle scroll during streaming
        if (!scrollThrottle) {
            Admin.scrollChatToBottom();
            scrollThrottle = setTimeout(() => {
                scrollThrottle = null;
            }, 100);
        }
    }

    /**
    * Create the thinking UI component with collapsible steps
    */
    Admin.createThinkingUI = function (thinkingSteps) {
        const container = document.createElement("div");
        container.className = "thinking-container";

        // Create header with icon and label
        const header = document.createElement("div");
        header.className = "thinking-header";
        header.innerHTML = `
            <div class="thinking-header-content">
                <svg class="thinking-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                </svg>
                <span class="thinking-label">Thinking</span>
                <span class="thinking-count">${thinkingSteps.length} step${thinkingSteps.length !== 1 ? "s" : ""}</span>
            </div>
            <button class="thinking-toggle" aria-label="Toggle thinking steps">
                <svg class="thinking-chevron" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                </svg>
            </button>
        `;

        // Create collapsible content
        const content = document.createElement("div");
        content.className = "thinking-content collapsed";

        // Add each thinking step
        thinkingSteps.forEach((step, index) => {
            const stepDiv = document.createElement("div");
            stepDiv.className = "thinking-step";
            stepDiv.innerHTML = `
                <div class="thinking-step-number">
                    <span>${index + 1}</span>
                </div>
                <div class="thinking-step-text">${escapeHtml(step.content)}</div>
            `;
            content.appendChild(stepDiv);
        });

        // Toggle functionality
        const toggleBtn = header.querySelector(".thinking-toggle");
        const chevron = header.querySelector(".thinking-chevron");

        toggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const isCollapsed = content.classList.contains("collapsed");

            if (isCollapsed) {
                content.classList.remove("collapsed");
                chevron.style.transform = "rotate(180deg)";
            } else {
                content.classList.add("collapsed");
                chevron.style.transform = "rotate(0deg)";
            }

            // Scroll after animation
            setTimeout(scrollChatToBottom, 200);
        });

        container.appendChild(header);
        container.appendChild(content);

        return container;
    }

    /**
    * Helper to escape HTML for safe rendering
    */
    Admin.escapeHtmlChat = function (text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    /**
    * Append chat message to UI
    */
    // Append chat message to UI
    // Append chat message to UI
    // Append chat message to UI
    // Admin.appendChatMessage = function (role, content, isStreaming = false) {
    //     const container = Admin.safeGetElement('chat-messages-container');
    //     const messageId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

    //     const messageDiv = document.createElement('div');
    //     messageDiv.id = messageId;
    //     messageDiv.className = `chat-message ${role}-message`;

    //     if (role === 'user') {
    //         messageDiv.innerHTML = `
    //             <div class="flex justify-end" style="margin: 0;">
    //                 <div class="max-w-80 rounded-lg bg-indigo-600 text-white" style="padding: 6px 12px;">
    //                     <div class="text-sm whitespace-pre-wrap" style="margin: 0; padding: 0; line-height: 1.3;">${escapeHtml(content)}</div>
    //                 </div>
    //             </div>
    //         `;
    //     } else if (role === 'assistant') {
    //         messageDiv.innerHTML = `
    //             <div class="flex justify-start" style="margin: 0;">
    //                 <div class="max-w-80 rounded-lg bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100" style="padding: 6px 12px;">
    //                     <div class="text-sm whitespace-pre-wrap message-content" style="margin: 0; padding: 0; line-height: 1.3; display: inline-block;">${escapeHtml(content)}</div>
    //                     ${isStreaming ? '<span class="streaming-indicator inline-block ml-2"></span>' : ''}
    //                 </div>
    //             </div>
    //         `;
    //     } else if (role === 'system') {
    //         messageDiv.innerHTML = `
    //             <div class="flex justify-center">
    //                 <div class="rounded-lg bg-yellow-50 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 text-xs" style="padding: 4px 10px; margin: 0;">
    //                     ${escapeHtml(content)}
    //                 </div>
    //             </div>
    //         `;
    //     }

    //     container.appendChild(messageDiv);
    //     Admin.scrollChatToBottom();
    //     return messageId;
    // }

    Admin.appendChatMessage = function (role, content, isStreaming = false) {
        const container = Admin.safeGetElement("chat-messages-container");
        const messageId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        const messageDiv = document.createElement("div");
        messageDiv.id = messageId;
        messageDiv.className = `chat-message ${role}-message`;
        messageDiv.style.marginBottom = "6px"; // compact spacing between messages

        if (role === "user") {
            messageDiv.innerHTML = `
                <div class="flex justify-end px-2">
                    <div class="bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-2xl px-4 py-2 max-w-xs shadow-sm text-sm whitespace-pre-wrap flex items-end gap-1">
                        <div class="message-content">${escapeHtmlChat(content)}</div>
                    </div>
                </div>
            `;
        } else if (role === "assistant") {
            messageDiv.innerHTML = `
                <div class="flex justify-start px-2">
                    <div class="bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 rounded-2xl px-4 py-3 shadow-sm text-sm flex flex-col gap-1 w-fit">
                        <div class="message-content markdown-body"></div>
                        ${isStreaming ? '<span class="streaming-indicator"></span>' : ""}
                    </div>
                </div>
            `;
            const contentEl = messageDiv.querySelector(".message-content");
            if (contentEl) {
                contentEl.innerHTML = Admin.renderMarkdown(content);
            }
        } else if (role === "system") {
            messageDiv.innerHTML = `
                <div class="flex justify-center px-2">
                    <div class="bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-100 text-xs px-3 py-1 rounded-md shadow-sm">
                        ${escapeHtmlChat(content)}
                    </div>
                </div>
            `;
        }

        container.appendChild(messageDiv);
        // Use force scroll for new messages
        Admin.scrollChatToBottom(true);
        return messageId;
    }

    /**
    * Render and sanitize markdown content
    */
    Admin.renderMarkdown = function (text) {
        if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
            return text;
        }

        // Configure marked for nested markdown support
        const rawHtml = marked.parse(text, {
            breaks: true, // Support GFM line breaks
            gfm: true, // GitHub Flavored Markdown
            pedantic: false, // Allow nested markdown
            sanitize: false, // We'll sanitize with DOMPurify
            smartLists: true, // Better list handling
            smartypants: false, // No typographic replacements
        });

        return DOMPurify.sanitize(rawHtml);
    }

    /**
    * Update chat message content (for streaming)
    */
    let scrollThrottle = null;
    let renderThrottle = null;
    Admin.updateChatMessage = function (messageId, content) {
        const messageDiv = Admin.safeGetElement(messageId);
        if (messageDiv) {
            const contentEl = messageDiv.querySelector(".message-content");
            if (contentEl) {
                // Store raw content for final processing
                contentEl.setAttribute("data-raw-content", content);

                // Ensure markdown-body class is present
                if (!contentEl.classList.contains("markdown-body")) {
                    contentEl.classList.add("markdown-body");
                }

                // During streaming, we use textContent for speed and to avoid broken HTML tags
                // but we can render markdown periodically for a better UI
                if (!renderThrottle) {
                    contentEl.innerHTML = Admin.renderMarkdown(content);
                    renderThrottle = setTimeout(() => {
                        renderThrottle = null;
                    }, 150);
                }

                // Throttle scroll during streaming
                if (!scrollThrottle) {
                    Admin.scrollChatToBottom();
                    scrollThrottle = setTimeout(() => {
                        scrollThrottle = null;
                    }, 100);
                }
            }
        }
    }

    /**
    * Mark message as complete (remove streaming indicator)
    */
    Admin.markMessageComplete = function (messageId) {
        const messageDiv = Admin.safeGetElement(messageId);
        if (messageDiv) {
            const indicator = messageDiv.querySelector(".streaming-indicator");
            if (indicator) {
                indicator.remove();
            }

            // Ensure final render with think tags
            const contentEl = messageDiv.querySelector(".message-content");
            if (contentEl && contentEl.textContent) {
                // Re-parse one final time to ensure complete rendering
                const fullContent =
                    contentEl.getAttribute("data-raw-content") ||
                    contentEl.textContent;
                if (fullContent.includes("<think>")) {
                    const { thinkingSteps, finalAnswer } =
                        Admin.parseThinkTags(fullContent);
                    contentEl.innerHTML = "";

                    if (thinkingSteps.length > 0) {
                        const thinkingContainer = Admin.createThinkingUI(thinkingSteps);
                        contentEl.appendChild(thinkingContainer);
                    }

                    if (finalAnswer) {
                        const answerDiv = document.createElement("div");
                        answerDiv.className = "final-answer-content markdown-body";
                        answerDiv.innerHTML = Admin.renderMarkdown(finalAnswer);
                        contentEl.appendChild(answerDiv);
                    }
                } else {
                    // If no think tags, just render markdown
                    contentEl.classList.add("markdown-body");
                    contentEl.innerHTML = Admin.renderMarkdown(fullContent);
                }
            }
        }
    }

    /**
    * Get or create a tool-events card positioned above the assistant message.
    * The card is a sibling of the message div, not nested inside.
    */
    Admin.getOrCreateToolCard = function (messageId) {
        const messageDiv = Admin.safeGetElement(messageId);
        if (!messageDiv) {
            return null;
        }

        // Check if card already exists as a sibling
        let card = messageDiv.previousElementSibling;
        if (card && card.classList.contains("tool-events-card")) {
            return card;
        }

        // Create a new card
        card = document.createElement("div");
        card.className =
            "tool-events-card mb-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700";

        const header = document.createElement("div");
        header.className = "flex items-center justify-between mb-2";

        const title = document.createElement("div");
        title.className =
            "font-semibold text-sm text-blue-800 dark:text-blue-200 flex items-center gap-2";
        title.innerHTML = `
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
        </svg>
        <span>Tool Invocations</span>
    `;

        const toggleBtn = document.createElement("button");
        toggleBtn.className =
            "text-xs text-blue-600 dark:text-blue-300 hover:underline";
        toggleBtn.textContent = "Hide";
        toggleBtn.onclick = () => {
            const body = card.querySelector(".tool-events-body");
            if (body.classList.contains("hidden")) {
                body.classList.remove("hidden");
                toggleBtn.textContent = "Hide";
            } else {
                body.classList.add("hidden");
                toggleBtn.textContent = "Show";
            }
        };

        header.appendChild(title);
        header.appendChild(toggleBtn);
        card.appendChild(header);

        const body = document.createElement("div");
        body.className = "tool-events-body space-y-2";
        card.appendChild(body);

        // Insert card before the message div
        messageDiv.parentElement.insertBefore(card, messageDiv);

        return card;
    }

    /**
    * Add a tool event row to the tool card.
    */
    Admin.addToolEventToCard = function (messageId, eventType, payload) {
        const card = Admin.getOrCreateToolCard(messageId);
        if (!card) {
            return;
        }

        const body = card.querySelector(".tool-events-body");

        const row = document.createElement("div");
        row.className =
            "text-xs p-2 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700";

        let icon = "";
        let text = "";
        let colorClass = "";

        if (eventType === "tool_start") {
            icon =
                '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
            colorClass = "text-green-700 dark:text-green-400";
            text = `<strong>Started:</strong> ${escapeHtmlChat(payload.tool || payload.id || "unknown")}`;
            if (payload.input) {
                text += `<br><span class="text-gray-600 dark:text-gray-400">Input: ${escapeHtmlChat(JSON.stringify(payload.input))}</span>`;
            }
        } else if (eventType === "tool_end") {
            icon =
                '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
            colorClass = "text-blue-700 dark:text-blue-400";
            text = `<strong>Completed:</strong> ${escapeHtmlChat(payload.tool || payload.id || "unknown")}`;
            if (payload.output) {
                const out =
                    typeof payload.output === "string"
                        ? payload.output
                        : JSON.stringify(payload.output);
                text += `<br><span class="text-gray-600 dark:text-gray-400">Output: ${escapeHtmlChat(out)}</span>`;
            }
        } else if (eventType === "tool_error") {
            icon =
                '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
            colorClass = "text-red-700 dark:text-red-400";
            text = `<strong>Error:</strong> ${escapeHtmlChat(payload.error || payload.tool || payload.id || "unknown")}`;
        }

        row.innerHTML = `<div class="flex items-start gap-2 ${colorClass}">${icon}<div>${text}</div></div>`;
        body.appendChild(row);
    }

    /**
    * Update or create a "tools used" summary badge on the tool card when final event arrives.
    */
    Admin.setToolUsedSummary = function (messageId, used, toolsList) {
        const card = Admin.getOrCreateToolCard(messageId);
        if (!card) {
            return;
        }

        let badge = card.querySelector(".tool-summary-badge");
        if (!badge) {
            badge = document.createElement("div");
            badge.className =
                "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium";
            card.appendChild(badge);
        }

        if (used && toolsList && toolsList.length > 0) {
            badge.className =
                "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium text-green-700 dark:text-green-400";
            badge.textContent = `✓ Tools used: ${toolsList.join(", ")}`;
        } else {
            badge.className =
                "tool-summary-badge mt-2 pt-2 border-t border-blue-200 dark:border-blue-700 text-xs font-medium text-gray-600 dark:text-gray-400";
            badge.textContent = "No tools invoked";
        }
    }

    /**
    * Clear all chat messages
    */
    Admin.clearChatMessages = function () {
        const container = Admin.safeGetElement("chat-messages-container");
        if (container) {
            container.innerHTML = `
        <div id="chat-welcome-message" class="flex items-center justify-center h-full">
            <div class="text-center text-gray-500 dark:text-gray-400">
            <svg class="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
            </svg>
            <p class="mt-4 text-lg font-medium">Select a server and connect to start chatting</p>
            <p class="mt-2 text-sm">Choose a virtual server from the left and configure your LLM settings</p>
            </div>
        </div>
        `;
        }
    }

    /**
    * Scroll chat to bottom
    */
    Admin.scrollChatToBottom = function (force = false) {
        const container = Admin.safeGetElement("chat-messages-container");
        if (container) {
            if (force || llmChatState.autoScroll) {
                requestAnimationFrame(() => {
                    // Use instant scroll during streaming for better UX
                    container.scrollTop = container.scrollHeight;
                });
            }
        }
    }

    /**
    * Handle Enter key in chat input (send on Enter, new line on Shift+Enter)
    */
    // eslint-disable-next-line no-unused-vars
    Admin.handleChatInputKeydown = function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            Admin.sendChatMessage(event);
        }
    }

    Admin.initializeChatInputResize = function () {
        const chatInput = Admin.safeGetElement("chat-input");
        if (chatInput) {
            chatInput.addEventListener("input", function () {
                this.style.height = "auto";
                this.style.height = Math.min(this.scrollHeight, 120) + "px";
            });

            // Reset height when message is sent
            const form = Admin.safeGetElement("chat-input-form");
            if (form) {
                form.addEventListener("submit", () => {
                    setTimeout(() => {
                        chatInput.style.height = "auto";
                    }, 0);
                });
            }
        }
    }
    /**
    * Perform server-side search for tools and update the tool list
    */
    Admin.serverSideToolSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("associatedTools");
        const noResultsMessage = Admin.safeGetElement("noToolsMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchQueryTools", true);

        if (!container) {
            console.error("associatedTools container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Tool Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // --- DOM instrumentation for debugging replacement during searches ---
        // Assign a stable debug id to the container (persists through innerHTML swaps
        // but will change if the element is replaced). Observe the parent node for
        // childList mutations and log if the container is removed or replaced.
        let _domInstrObserver = null;
        let _domInstrId = null;
        try {
            if (!container.dataset.debugNodeId) {
                container.dataset.debugNodeId = `dbg-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
            }
            _domInstrId = container.dataset.debugNodeId;
            console.info(
                `[DOM-INSTRUMENT] serverSideToolSearch start for #associatedTools debugId=${_domInstrId} searchTerm='${searchTerm}'`,
            );

            const parentNode = container.parentNode;
            if (parentNode) {
                _domInstrObserver = new MutationObserver((mutationsList) => {
                    for (const mut of mutationsList) {
                        if (mut.type === "childList") {
                            const current =
                                Admin.safeGetElement("associatedTools");
                            if (!current) {
                                console.warn(
                                    `[DOM-INSTRUMENT] associatedTools element REMOVED during search (original debugId=${_domInstrId})`,
                                    mut,
                                );
                            } else {
                                const curId = current.dataset.debugNodeId || null;
                                if (curId !== _domInstrId) {
                                    console.warn(
                                        `[DOM-INSTRUMENT] associatedTools element REPLACED during search. original=${_domInstrId} current=${curId}`,
                                        mut,
                                    );
                                }
                            }
                        }
                    }
                });
                try {
                    _domInstrObserver.observe(parentNode, { childList: true });
                } catch (e) {
                    console.error(
                        "[DOM-INSTRUMENT] Failed to observe parent node for associatedTools:",
                        e,
                    );
                }
            }
        } catch (e) {
            console.error("[DOM-INSTRUMENT] setup error:", e);
        }

        // Persist current selections to window fallback AND data attribute before we replace/clear the container
        let persistedToolIds = [];
        try {
            // First get from data attribute if it exists
            const dataAttr = container.getAttribute("data-selected-tools");
            if (dataAttr) {
                try {
                    const parsed = JSON.parse(dataAttr);
                    if (Array.isArray(parsed)) {
                        persistedToolIds = parsed.slice();
                    }
                } catch (e) {
                    console.error("Error parsing data-selected-tools:", e);
                }
            }

            // Then merge with currently checked items (important for search results)
            const currentChecked = Array.from(
                container.querySelectorAll('input[type="checkbox"]:checked'),
            ).map((cb) => cb.value);
            const merged = new Set([...persistedToolIds, ...currentChecked]);
            persistedToolIds = Array.from(merged);

            // Update both the window fallback and the container attribute
            Admin._selectedAssociatedTools = persistedToolIds.slice();
            if (persistedToolIds.length > 0) {
                container.setAttribute(
                    "data-selected-tools",
                    JSON.stringify(persistedToolIds),
                );
            }

            console.log(
                `[Tool Search] Persisted ${persistedToolIds.length} tool selections before search:`,
                persistedToolIds,
            );
        } catch (e) {
            console.error("Error capturing current selections before search:", e);
        }

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching tools...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default tool list with gateway filter
            try {
                const toolsUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Tool Search] Loading default tools with URL: ${toolsUrl}`,
                );

                const response = await fetch(toolsUrl);
                if (response.ok) {
                    const html = await response.text();

                    // Preserve the data-selected-tools attribute before replacing innerHTML
                    let persistedToolIds = [];
                    try {
                        const dataAttr = container.getAttribute(
                            "data-selected-tools",
                        );
                        if (dataAttr) {
                            try {
                                const parsed = JSON.parse(dataAttr);
                                if (Array.isArray(parsed)) {
                                    persistedToolIds = parsed.slice();
                                }
                            } catch (e) {
                                console.error(
                                    "Error parsing data-selected-tools before clearing search:",
                                    e,
                                );
                            }
                        }

                        // Merge with currently checked items
                        const currentChecked = Array.from(
                            container.querySelectorAll(
                                'input[type="checkbox"]:checked',
                            ),
                        ).map((cb) => cb.value);
                        const merged = new Set([
                            ...persistedToolIds,
                            ...currentChecked,
                        ]);
                        persistedToolIds = Array.from(merged);

                        // Update window fallback
                        Admin._selectedAssociatedTools = persistedToolIds.slice();
                    } catch (e) {
                        console.error(
                            "Error capturing current tool selections before clearing search:",
                            e,
                        );
                    }

                    container.innerHTML = html;

                    // Immediately restore the data-selected-tools attribute after innerHTML replacement
                    if (persistedToolIds.length > 0) {
                        container.setAttribute(
                            "data-selected-tools",
                            JSON.stringify(persistedToolIds),
                        );
                    }

                    // If the container has been re-rendered server-side and our
                    // `data-selected-tools` attribute was lost, restore from the
                    // global fallback `Admin._selectedAssociatedTools`.
                    try {
                        Admin.updateToolMapping(container);

                        // Re-initialize selector so handlers are attached
                        Admin.initToolSelect(
                            "associatedTools",
                            "selectedToolsPills",
                            "selectedToolsWarning",
                            6,
                            "selectAllToolsBtn",
                            "clearAllToolsBtn",
                        );

                        const dataAttr = container.getAttribute(
                            "data-selected-tools",
                        );
                        let selectedIds = null;
                        if (dataAttr) {
                            try {
                                selectedIds = JSON.parse(dataAttr);
                            } catch (e) {
                                console.error(
                                    "Error parsing server data-selected-tools:",
                                    e,
                                );
                            }
                        }

                        if (
                            (!selectedIds ||
                                !Array.isArray(selectedIds) ||
                                selectedIds.length === 0) &&
                            Array.isArray(Admin._selectedAssociatedTools)
                        ) {
                            selectedIds = Admin._selectedAssociatedTools.slice();
                        }

                        if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedTools"]',
                            );
                            checkboxes.forEach((cb) => {
                                if (selectedIds.includes(cb.value)) {
                                    cb.checked = true;
                                }
                            });

                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }

                        // Hide no results message
                        if (noResultsMessage) {
                            noResultsMessage.style.display = "none";
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring selections after loading default tools:",
                            e,
                        );
                    }
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load tools</div>';
                }
            } catch (error) {
                console.error("Error loading tools:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading tools</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/tools/search?${params.toString()}`;

            console.log(`[Tool Search] Searching tools with URL: ${searchUrl}`);

            const response = await fetch(searchUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.tools && data.tools.length > 0) {
                // Create HTML for search results
                let searchResultsHtml = "";
                data.tools.forEach((tool) => {
                    // Create a label element similar to the ones in tools_selector_items.html
                    // Use the same name priority as the template: displayName or customName or original_name
                    const displayName =
                        tool.display_name ||
                        tool.custom_name ||
                        tool.name ||
                        tool.id;

                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md p-1 tool-item"
                            data-tool-id="${escapeHtml(tool.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedTools"
                                value="${escapeHtml(tool.id)}"
                                data-tool-name="${escapeHtml(displayName)}"
                                class="tool-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(displayName)}</span>
                        </label>
                    `;
                });

                container.innerHTML = searchResultsHtml;
                // If server-side didn't provide `data-selected-tools` (or provided
                // an empty array), restore/merge from the in-memory fallback so
                // the attribute isn't left empty and selectors can pick it up.
                try {
                    const existingAttr = container.getAttribute(
                        "data-selected-tools",
                    );
                    let existingIds = null;
                    if (existingAttr) {
                        try {
                            existingIds = JSON.parse(existingAttr);
                        } catch (e) {
                            console.error(
                                "Error parsing existing data-selected-tools after search insert:",
                                e,
                            );
                        }
                    }

                    if (
                        (!existingIds ||
                            !Array.isArray(existingIds) ||
                            existingIds.length === 0) &&
                        Array.isArray(Admin._selectedAssociatedTools) &&
                        Admin._selectedAssociatedTools.length > 0
                    ) {
                        // Write a merged view back to the container attribute so
                        // subsequent init/observers see the selection
                        container.setAttribute(
                            "data-selected-tools",
                            JSON.stringify(Admin._selectedAssociatedTools.slice()),
                        );
                    } else if (
                        Array.isArray(existingIds) &&
                        Array.isArray(Admin._selectedAssociatedTools) &&
                        Admin._selectedAssociatedTools.length > 0
                    ) {
                        // Merge the two sets to avoid losing either
                        const merged = new Set([
                            ...(existingIds || []),
                            ...Admin._selectedAssociatedTools,
                        ]);
                        container.setAttribute(
                            "data-selected-tools",
                            JSON.stringify(Array.from(merged)),
                        );
                    }
                } catch (e) {
                    console.error(
                        "Error restoring data-selected-tools attribute after inserting search results:",
                        e,
                    );
                }

                // Update tool mapping with search results
                Admin.updateToolMapping(container);

                // Re-initialize selector behavior for the add-server container
                try {
                    Admin.initToolSelect(
                        "associatedTools",
                        "selectedToolsPills",
                        "selectedToolsWarning",
                        6,
                        "selectAllToolsBtn",
                        "clearAllToolsBtn",
                    );

                    // Restore any previously selected tool IDs stored on the container
                    try {
                        const dataAttr = container.getAttribute(
                            "data-selected-tools",
                        );
                        let selectedIds = null;
                        if (dataAttr) {
                            try {
                                selectedIds = JSON.parse(dataAttr);
                            } catch (e) {
                                console.error(
                                    "Error parsing data-selected-tools:",
                                    e,
                                );
                            }
                        }

                        // If parsed attribute is missing or an empty array, fall back
                        // to the in-memory `Admin._selectedAssociatedTools` saved earlier.
                        if (
                            (!selectedIds ||
                                !Array.isArray(selectedIds) ||
                                selectedIds.length === 0) &&
                            Array.isArray(Admin._selectedAssociatedTools)
                        ) {
                            selectedIds = Admin._selectedAssociatedTools.slice();
                        }

                        if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedTools"]',
                            );
                            checkboxes.forEach((cb) => {
                                if (selectedIds.includes(cb.value)) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring data-selected-tools after search:",
                            e,
                        );
                    }
                } catch (e) {
                    console.error(
                        "Error initializing associatedTools selector:",
                        e,
                    );
                }

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                // Show no results message
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching tools:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching tools</div>';

            // Hide no results message in case of error
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    /**
    * Update the tool mapping with tools in the given container
    */
    Admin.updateToolMapping = function (container) {
        if (!Admin.toolMapping) {
            Admin.toolMapping = {};
        }

        const checkboxes = container.querySelectorAll(
            'input[name="associatedTools"]',
        );
        checkboxes.forEach((checkbox) => {
            const toolId = checkbox.value;
            const toolName = checkbox.getAttribute("data-tool-name");
            if (toolId && toolName) {
                Admin.toolMapping[toolId] = toolName;
            }
        });
    }

    /**
    * Update the prompt mapping with prompts in the given container
    */
    Admin.updatePromptMapping = function (container) {
        if (!Admin.promptMapping) {
            Admin.promptMapping = {};
        }

        const checkboxes = container.querySelectorAll(
            'input[name="associatedPrompts"]',
        );
        checkboxes.forEach((checkbox) => {
            const promptId = checkbox.value;
            const promptName =
                checkbox.getAttribute("data-prompt-name") ||
                checkbox.nextElementSibling?.textContent?.trim() ||
                promptId;
            if (promptId && promptName) {
                Admin.promptMapping[promptId] = promptName;
            }
        });
    }

    /**
    * Update the resource mapping with resources in the given container
    */
    Admin.updateResourceMapping = function (container) {
        if (!Admin.resourceMapping) {
            Admin.resourceMapping = {};
        }

        const checkboxes = container.querySelectorAll(
            'input[name="associatedResources"]',
        );
        checkboxes.forEach((checkbox) => {
            const resourceId = checkbox.value;
            const resourceName =
                checkbox.getAttribute("data-resource-name") ||
                checkbox.nextElementSibling?.textContent?.trim() ||
                resourceId;
            if (resourceId && resourceName) {
                Admin.resourceMapping[resourceId] = resourceName;
            }
        });
    }

    /**
    * Perform server-side search for prompts and update the prompt list
    */
    Admin.serverSidePromptSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("associatedPrompts");
        const noResultsMessage = Admin.safeGetElement("noPromptsMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchPromptsQuery", true);

        if (!container) {
            console.error("associatedPrompts container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Prompt Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // Persist current selections to window fallback before we replace/clear the container
        try {
            const currentChecked = Array.from(
                container.querySelectorAll('input[type="checkbox"]:checked'),
            ).map((cb) => cb.value);
            if (
                !Array.isArray(window._selectedAssociatedPrompts) ||
                window._selectedAssociatedPrompts.length === 0
            ) {
                Admin._selectedAssociatedPrompts = currentChecked.slice();
            } else {
                const merged = new Set([
                    ...(window._selectedAssociatedPrompts || []),
                    ...currentChecked,
                ]);
                Admin._selectedAssociatedPrompts = Array.from(merged);
            }
        } catch (e) {
            console.error(
                "Error capturing current prompt selections before search:",
                e,
            );
        }

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-purple-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching prompts...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default prompt selector with gateway filter
            try {
                const promptsUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Prompt Search] Loading default prompts with URL: ${promptsUrl}`,
                );

                const response = await fetch(promptsUrl);
                if (response.ok) {
                    const html = await response.text();
                    container.innerHTML = html;

                    // Hide no results message
                    if (noResultsMessage) {
                        noResultsMessage.style.display = "none";
                    }

                    try {
                        // Update mapping and ensure persisted selections are applied
                        // Initialize prompt mapping if needed
                        // If the server did not supply `data-selected-prompts`, restore from fallback
                        const dataAttr = container.getAttribute(
                            "data-selected-prompts",
                        );
                        let selectedIds = null;
                        if (dataAttr) {
                            try {
                                selectedIds = JSON.parse(dataAttr);
                            } catch (e) {
                                console.error(
                                    "Error parsing server data-selected-prompts:",
                                    e,
                                );
                            }
                        }

                        if (
                            (!selectedIds ||
                                !Array.isArray(selectedIds) ||
                                selectedIds.length === 0) &&
                            Array.isArray(window._selectedAssociatedPrompts)
                        ) {
                            selectedIds = window._selectedAssociatedPrompts.slice();
                        }

                        Admin.initPromptSelect(
                            "associatedPrompts",
                            "selectedPromptsPills",
                            "selectedPromptsWarning",
                            6,
                            "selectAllPromptsBtn",
                            "clearAllPromptsBtn",
                        );

                        if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedPrompts"]',
                            );
                            checkboxes.forEach((cb) => {
                                if (selectedIds.includes(cb.value)) {
                                    cb.checked = true;
                                }
                            });
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring selections after loading default prompts:",
                            e,
                        );
                    }
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load prompts</div>';
                }
            } catch (error) {
                console.error("Error loading prompts:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading prompts</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/prompts/search?${params.toString()}`;

            console.log(`[Prompt Search] Searching prompts with URL: ${searchUrl}`);

            const response = await fetch(searchUrl);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.prompts && data.prompts.length > 0) {
                let searchResultsHtml = "";
                data.prompts.forEach((prompt) => {
                    const displayName =
                        prompt.displayName ||
                        prompt.display_name ||
                        prompt.originalName ||
                        prompt.original_name ||
                        prompt.name ||
                        prompt.id;
                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900 rounded-md p-1 prompt-item"
                            data-prompt-id="${escapeHtml(prompt.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedPrompts"
                                value="${escapeHtml(prompt.id)}"
                                data-prompt-name="${escapeHtml(displayName)}"
                                class="prompt-checkbox form-checkbox h-5 w-5 text-purple-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(displayName)}</span>
                        </label>
                    `;
                });

                // Before initializing, ensure any persisted selections are merged into the container
                try {
                    const existingAttr = container.getAttribute(
                        "data-selected-prompts",
                    );
                    let existingIds = null;
                    if (existingAttr) {
                        try {
                            existingIds = JSON.parse(existingAttr);
                        } catch (e) {
                            console.error(
                                "Error parsing existing data-selected-prompts after search insert:",
                                e,
                            );
                        }
                    }

                    if (
                        (!existingIds ||
                            !Array.isArray(existingIds) ||
                            existingIds.length === 0) &&
                        Array.isArray(window._selectedAssociatedPrompts) &&
                        window._selectedAssociatedPrompts.length > 0
                    ) {
                        container.setAttribute(
                            "data-selected-prompts",
                            JSON.stringify(
                                window._selectedAssociatedPrompts.slice(),
                            ),
                        );
                    } else if (
                        Array.isArray(existingIds) &&
                        Array.isArray(window._selectedAssociatedPrompts) &&
                        window._selectedAssociatedPrompts.length > 0
                    ) {
                        const merged = new Set([
                            ...(existingIds || []),
                            ...window._selectedAssociatedPrompts,
                        ]);
                        container.setAttribute(
                            "data-selected-prompts",
                            JSON.stringify(Array.from(merged)),
                        );
                    }
                } catch (e) {
                    console.error(
                        "Error restoring data-selected-prompts attribute after inserting search results:",
                        e,
                    );
                }

                container.innerHTML = searchResultsHtml;

                // Initialize prompt select mapping
                Admin.initPromptSelect(
                    "associatedPrompts",
                    "selectedPromptsPills",
                    "selectedPromptsWarning",
                    6,
                    "selectAllPromptsBtn",
                    "clearAllPromptsBtn",
                );

                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching prompts:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching prompts</div>';
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    /**
    * Perform server-side search for resources and update the resouces list
    */
    Admin.serverSideResourceSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("associatedResources");
        const noResultsMessage = Admin.safeGetElement("noResourcesMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchResourcesQuery", true);

        if (!container) {
            console.error("associatedResources container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Resource Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // Persist current selections to window fallback before we replace/clear the container
        try {
            const currentChecked = Array.from(
                container.querySelectorAll('input[type="checkbox"]:checked'),
            ).map((cb) => cb.value);
            if (
                !Array.isArray(Admin._selectedAssociatedResources) ||
                Admin._selectedAssociatedResources.length === 0
            ) {
                Admin._selectedAssociatedResources = currentChecked.slice();
            } else {
                const merged = new Set([
                    ...(Admin._selectedAssociatedResources || []),
                    ...currentChecked,
                ]);
                Admin._selectedAssociatedResources = Array.from(merged);
            }
        } catch (e) {
            console.error(
                "Error capturing current resource selections before search:",
                e,
            );
        }

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-purple-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching resources...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default resource selector with gateway filter
            try {
                const resourcesUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Resource Search] Loading default resources with URL: ${resourcesUrl}`,
                );

                const response = await fetch(resourcesUrl);
                if (response.ok) {
                    const html = await response.text();

                    // Persist current selections to window fallback before we replace/clear the container
                    try {
                        const currentChecked = Array.from(
                            container.querySelectorAll(
                                'input[type="checkbox"]:checked',
                            ),
                        ).map((cb) => cb.value);
                        if (
                            !Array.isArray(Admin._selectedAssociatedResources) ||
                            Admin._selectedAssociatedResources.length === 0
                        ) {
                            Admin._selectedAssociatedResources =
                                currentChecked.slice();
                        } else {
                            const merged = new Set([
                                ...(Admin._selectedAssociatedResources || []),
                                ...currentChecked,
                            ]);
                            Admin._selectedAssociatedResources =
                                Array.from(merged);
                        }
                    } catch (e) {
                        console.error(
                            "Error capturing current resource selections before search:",
                            e,
                        );
                    }

                    container.innerHTML = html;

                    // If the container has been re-rendered server-side and our
                    // `data-selected-resources` attribute was lost, restore from the
                    // global fallback `Admin._selectedAssociatedResources`.
                    try {
                        // Initialize resource mapping if needed
                        Admin.initResourceSelect(
                            "associatedResources",
                            "selectedResourcesPills",
                            "selectedResourcesWarning",
                            6,
                            "selectAllResourcesBtn",
                            "clearAllResourcesBtn",
                        );

                        const dataAttr = container.getAttribute(
                            "data-selected-resources",
                        );
                        let selectedIds = null;
                        if (dataAttr) {
                            try {
                                selectedIds = JSON.parse(dataAttr);
                            } catch (e) {
                                console.error(
                                    "Error parsing server data-selected-resources:",
                                    e,
                                );
                            }
                        }

                        if (
                            (!selectedIds ||
                                !Array.isArray(selectedIds) ||
                                selectedIds.length === 0) &&
                            Array.isArray(Admin._selectedAssociatedResources)
                        ) {
                            selectedIds =
                                Admin._selectedAssociatedResources.slice();
                        }

                        if (Array.isArray(selectedIds) && selectedIds.length > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedResources"]',
                            );
                            checkboxes.forEach((cb) => {
                                if (selectedIds.includes(cb.value)) {
                                    cb.checked = true;
                                }
                            });

                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring selections after loading default resources:",
                            e,
                        );
                    }
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load resources</div>';
                }
            } catch (error) {
                console.error("Error loading resources:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading resources</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/resources/search?${params.toString()}`;

            console.log(
                `[Resource Search] Searching resources with URL: ${searchUrl}`,
            );

            const response = await fetch(searchUrl);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.resources && data.resources.length > 0) {
                let searchResultsHtml = "";
                data.resources.forEach((resource) => {
                    const displayName = resource.name || resource.id;
                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900 rounded-md p-1 resource-item"
                            data-resource-id="${escapeHtml(resource.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedResources"
                                value="${escapeHtml(resource.id)}"
                                data-resource-name="${escapeHtml(displayName)}"
                                class="resource-checkbox form-checkbox h-5 w-5 text-purple-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(displayName)}</span>
                        </label>
                    `;
                });

                container.innerHTML = searchResultsHtml;

                // Before initializing, ensure any persisted selections are merged into the container
                try {
                    const existingAttr = container.getAttribute(
                        "data-selected-resources",
                    );
                    let existingIds = null;
                    if (existingAttr) {
                        try {
                            existingIds = JSON.parse(existingAttr);
                        } catch (e) {
                            console.error(
                                "Error parsing existing data-selected-resources after search insert:",
                                e,
                            );
                        }
                    }

                    if (
                        (!existingIds ||
                            !Array.isArray(existingIds) ||
                            existingIds.length === 0) &&
                        Array.isArray(Admin._selectedAssociatedResources) &&
                        Admin._selectedAssociatedResources.length > 0
                    ) {
                        container.setAttribute(
                            "data-selected-resources",
                            JSON.stringify(
                                Admin._selectedAssociatedResources.slice(),
                            ),
                        );
                    } else if (
                        Array.isArray(existingIds) &&
                        Array.isArray(Admin._selectedAssociatedResources) &&
                        Admin._selectedAssociatedResources.length > 0
                    ) {
                        const merged = new Set([
                            ...(existingIds || []),
                            ...Admin._selectedAssociatedResources,
                        ]);
                        container.setAttribute(
                            "data-selected-resources",
                            JSON.stringify(Array.from(merged)),
                        );
                    }
                } catch (e) {
                    console.error(
                        "Error restoring data-selected-resources attribute after inserting search results:",
                        e,
                    );
                }

                container.innerHTML = searchResultsHtml;

                // Initialize Resource select mapping
                Admin.initResourceSelect(
                    "associatedResources",
                    "selectedResourcesPills",
                    "selectedResourcesWarning",
                    6,
                    "selectAllResourcesBtn",
                    "clearAllResourcesBtn",
                );

                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching resources:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching resources</div>';
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    /**
    * Perform server-side search for tools in the edit-server selector and update the list
    */
    Admin.serverSideEditToolSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("edit-server-tools");
        const noResultsMessage = Admin.safeGetElement("noEditToolsMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchQueryEditTools", true);

        if (!container) {
            console.error("edit-server-tools container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Edit Tool Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // Persist current selections before we replace/clear the container
        let serverToolsData = null;
        let currentCheckedTools = [];
        try {
            // Preserve the data-server-tools attribute
            const dataAttr = container.getAttribute("data-server-tools");
            if (dataAttr) {
                serverToolsData = dataAttr;
            }

            // Also capture currently checked items (important for search results)
            currentCheckedTools = Array.from(
                container.querySelectorAll('input[type="checkbox"]:checked'),
            ).map((cb) => cb.value);

            console.log(
                `[Edit Tool Search] Persisted ${currentCheckedTools.length} checked tools before search:`,
                currentCheckedTools,
            );
        } catch (e) {
            console.error(
                "Error preserving selections before edit tool search:",
                e,
            );
        }

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching tools...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default tool selector partial with gateway filter
            try {
                const toolsUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Edit Tool Search] Loading default tools with URL: ${toolsUrl}`,
                );

                const response = await fetch(toolsUrl);
                if (response.ok) {
                    const html = await response.text();

                    container.innerHTML = html;

                    // Restore the data-server-tools attribute after innerHTML replacement
                    if (serverToolsData) {
                        container.setAttribute(
                            "data-server-tools",
                            serverToolsData,
                        );
                    }

                    // Hide no results message
                    if (noResultsMessage) {
                        noResultsMessage.style.display = "none";
                    }

                    // Update tool mapping
                    Admin.updateToolMapping(container);

                    // Restore checked state for any tools already associated with the server
                    // PLUS any tools that were checked during the search
                    try {
                        const dataAttr =
                            container.getAttribute("data-server-tools");
                        const toolsToCheck = new Set();

                        // Add server-associated tools
                        if (dataAttr) {
                            const serverTools = JSON.parse(dataAttr);
                            if (
                                Array.isArray(serverTools) &&
                                serverTools.length > 0
                            ) {
                                serverTools.forEach((t) =>
                                    toolsToCheck.add(String(t)),
                                );
                            }
                        }

                        // Add tools that were checked during search
                        if (
                            Array.isArray(currentCheckedTools) &&
                            currentCheckedTools.length > 0
                        ) {
                            currentCheckedTools.forEach((t) =>
                                toolsToCheck.add(String(t)),
                            );
                            console.log(
                                `[Edit Tool Search] Restoring ${currentCheckedTools.length} tools checked during search`,
                            );
                        }

                        if (toolsToCheck.size > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedTools"]',
                            );
                            checkboxes.forEach((cb) => {
                                const toolId = cb.value;
                                const toolName =
                                    cb.getAttribute("data-tool-name") ||
                                    (Admin.toolMapping &&
                                        Admin.toolMapping[cb.value]);
                                if (
                                    toolsToCheck.has(toolId) ||
                                    (toolName && toolsToCheck.has(String(toolName)))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring edit-server tools checked state:",
                            e,
                        );
                    }

                    // Re-initialize the selector logic for the edit container
                    Admin.initToolSelect(
                        "edit-server-tools",
                        "selectedEditToolsPills",
                        "selectedEditToolsWarning",
                        6,
                        "selectAllEditToolsBtn",
                        "clearAllEditToolsBtn",
                    );
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load tools</div>';
                }
            } catch (error) {
                console.error("Error loading tools:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading tools</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/tools/search?${params.toString()}`;

            console.log(
                `[Edit Tool Search] Searching tools with URL: ${searchUrl}`,
            );

            const response = await fetch(searchUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.tools && data.tools.length > 0) {
                // Create HTML for search results
                let searchResultsHtml = "";
                data.tools.forEach((tool) => {
                    const displayName =
                        tool.display_name ||
                        tool.custom_name ||
                        tool.name ||
                        tool.id;

                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md p-1 tool-item"
                            data-tool-id="${escapeHtml(tool.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedTools"
                                value="${escapeHtml(tool.id)}"
                                data-tool-name="${escapeHtml(displayName)}"
                                class="tool-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(displayName)}</span>
                        </label>
                    `;
                });

                container.innerHTML = searchResultsHtml;

                // Update mapping
                Admin.updateToolMapping(container);

                // Restore checked state for any tools already associated with the server
                try {
                    const dataAttr = container.getAttribute("data-server-tools");
                    if (dataAttr) {
                        const serverTools = JSON.parse(dataAttr);
                        if (Array.isArray(serverTools) && serverTools.length > 0) {
                            // Normalize serverTools to a set of strings for robust comparison
                            const serverToolSet = new Set(
                                serverTools.map((s) => String(s)),
                            );
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedTools"]',
                            );
                            checkboxes.forEach((cb) => {
                                const toolId = cb.value;
                                const toolName =
                                    cb.getAttribute("data-tool-name") ||
                                    (Admin.toolMapping &&
                                        Admin.toolMapping[cb.value]);
                                if (
                                    serverToolSet.has(toolId) ||
                                    (toolName &&
                                        serverToolSet.has(String(toolName)))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    }
                } catch (e) {
                    console.error(
                        "Error restoring edit-server tools checked state:",
                        e,
                    );
                }

                // Initialize selector behavior
                Admin.initToolSelect(
                    "edit-server-tools",
                    "selectedEditToolsPills",
                    "selectedEditToolsWarning",
                    6,
                    "selectAllEditToolsBtn",
                    "clearAllEditToolsBtn",
                );

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                // Show no results message
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching tools:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching tools</div>';

            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    /**
    * Perform server-side search for prompts in the edit-server selector and update the list
    */
    Admin.serverSideEditPromptsSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("edit-server-prompts");
        const noResultsMessage = Admin.safeGetElement("noEditPromptsMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchQueryEditPrompts", true);

        if (!container) {
            console.error("edit-server-prompts container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Edit Prompt Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // Capture currently checked prompts BEFORE clearing the container
        const currentlyCheckedPrompts = new Set();
        const existingCheckboxes = container.querySelectorAll(
            'input[name="associatedPrompts"]:checked',
        );
        existingCheckboxes.forEach((cb) => {
            currentlyCheckedPrompts.add(cb.value);
        });

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching prompts...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default prompts selector partial with gateway filter
            try {
                const promptsUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Edit Prompt Search] Loading default prompts with URL: ${promptsUrl}`,
                );

                const response = await fetch(promptsUrl);
                if (response.ok) {
                    const html = await response.text();
                    container.innerHTML = html;

                    // Hide no results message
                    if (noResultsMessage) {
                        noResultsMessage.style.display = "none";
                    }

                    // Update prompt mapping
                    Admin.updatePromptMapping(container);

                    // Restore checked state for prompts (both original server associations AND newly selected ones)
                    try {
                        // Combine original server prompts with currently checked prompts
                        const allSelectedPrompts = new Set(currentlyCheckedPrompts);

                        const dataAttr = container.getAttribute(
                            "data-server-prompts",
                        );
                        if (dataAttr) {
                            const serverPrompts = JSON.parse(dataAttr);
                            if (Array.isArray(serverPrompts)) {
                                serverPrompts.forEach((p) =>
                                    allSelectedPrompts.add(String(p)),
                                );
                            }
                        }

                        if (allSelectedPrompts.size > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedPrompts"]',
                            );
                            checkboxes.forEach((cb) => {
                                const promptId = cb.value;
                                const promptName =
                                    cb.getAttribute("data-prompt-name") ||
                                    (Admin.promptMapping &&
                                        Admin.promptMapping[cb.value]);

                                // Check by id first (string), then by name as a fallback
                                if (
                                    allSelectedPrompts.has(promptId) ||
                                    (promptName &&
                                        allSelectedPrompts.has(String(promptName)))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring edit-server prompts checked state:",
                            e,
                        );
                    }

                    // Re-initialize the selector logic for the edit container (prompt-specific)
                    Admin.initPromptSelect(
                        "edit-server-prompts",
                        "selectedEditPromptsPills",
                        "selectedEditPromptsWarning",
                        6,
                        "selectAllEditPromptsBtn",
                        "clearAllEditPromptsBtn",
                    );
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load prompts</div>';
                }
            } catch (error) {
                console.error("Error loading prompts:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading prompts</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/prompts/search?${params.toString()}`;

            console.log(
                `[Edit Prompt Search] Searching prompts with URL: ${searchUrl}`,
            );

            const response = await fetch(searchUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.prompts && data.prompts.length > 0) {
                // Create HTML for search results
                let searchResultsHtml = "";
                data.prompts.forEach((prompt) => {
                    const name =
                        prompt.displayName ||
                        prompt.display_name ||
                        prompt.originalName ||
                        prompt.original_name ||
                        prompt.name ||
                        prompt.id;

                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md p-1 prompt-item"
                            data-prompt-id="${escapeHtml(prompt.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedPrompts"
                                value="${escapeHtml(prompt.id)}"
                                data-prompt-name="${escapeHtml(name)}"
                                class="prompt-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(name)}</span>
                        </label>
                    `;
                });

                container.innerHTML = searchResultsHtml;

                // Update mapping
                Admin.updatePromptMapping(container);

                // Restore checked state for any prompts already associated with the server
                try {
                    const dataAttr = container.getAttribute("data-server-prompts");
                    if (dataAttr) {
                        const serverPrompts = JSON.parse(dataAttr);
                        if (
                            Array.isArray(serverPrompts) &&
                            serverPrompts.length > 0
                        ) {
                            // Normalize serverPrompts to a set of strings for robust comparison
                            const serverPromptSet = new Set(
                                serverPrompts.map((s) => String(s)),
                            );

                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedPrompts"]',
                            );
                            checkboxes.forEach((cb) => {
                                const promptId = cb.value;
                                const promptName =
                                    cb.getAttribute("data-prompt-name") ||
                                    (Admin.promptMapping &&
                                        Admin.promptMapping[cb.value]);

                                if (
                                    serverPromptSet.has(promptId) ||
                                    (promptName &&
                                        serverPromptSet.has(String(promptName)))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    }
                } catch (e) {
                    console.error(
                        "Error restoring edit-server prompts checked state:",
                        e,
                    );
                }

                // Initialize selector behavior
                Admin.initPromptSelect(
                    "edit-server-prompts",
                    "selectedEditPromptsPills",
                    "selectedEditPromptsWarning",
                    6,
                    "selectAllEditPromptsBtn",
                    "clearAllEditPromptsBtn",
                );

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                // Show no results message
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching prompts:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching prompts</div>';
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    /**
    * Perform server-side search for resources in the edit-server selector and update the list
    */
    Admin.serverSideEditResourcesSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("edit-server-resources");
        const noResultsMessage = Admin.safeGetElement("noEditResourcesMessage", true);
        const searchQuerySpan = Admin.safeGetElement("searchQueryEditResources", true);

        if (!container) {
            console.error("edit-server-resources container not found");
            return;
        }

        // Get selected gateway IDs to maintain filtering
        const selectedGatewayIds = getSelectedGatewayIds
            ? Admin.getSelectedGatewayIds()
            : [];
        const gatewayIdParam =
            selectedGatewayIds.length > 0 ? selectedGatewayIds.join(",") : "";

        console.log(
            `[Edit Resource Search] Searching with gateway filter: ${gatewayIdParam || "none (showing all)"}`,
        );

        // Capture currently checked resources BEFORE clearing the container
        const currentlyCheckedResources = new Set();
        const existingCheckboxes = container.querySelectorAll(
            'input[name="associatedResources"]:checked',
        );
        existingCheckboxes.forEach((cb) => {
            currentlyCheckedResources.add(cb.value);
        });

        // Show loading state
        container.innerHTML = `
            <div class="text-center py-4">
                <svg class="animate-spin h-5 w-5 text-indigo-600 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="mt-2 text-sm text-gray-500">Searching Resources...</p>
            </div>
        `;

        if (searchTerm.trim() === "") {
            // If search term is empty, reload the default resources selector partial with gateway filter
            try {
                const resourcesUrl = gatewayIdParam
                    ? `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
                    : `${window.ROOT_PATH}/admin/resources/partial?page=1&per_page=50&render=selector`;

                console.log(
                    `[Edit Resource Search] Loading default resources with URL: ${resourcesUrl}`,
                );

                const response = await fetch(resourcesUrl);
                if (response.ok) {
                    const html = await response.text();
                    container.innerHTML = html;

                    // Hide no results message
                    if (noResultsMessage) {
                        noResultsMessage.style.display = "none";
                    }

                    // Update resource mapping
                    Admin.updateResourceMapping(container);

                    // Restore checked state for resources (both original server associations AND newly selected ones)
                    try {
                        // Combine original server resources with currently checked resources
                        const allSelectedResources = new Set(
                            currentlyCheckedResources,
                        );

                        const dataAttr = container.getAttribute(
                            "data-server-resources",
                        );
                        if (dataAttr) {
                            const serverResources = JSON.parse(dataAttr);
                            if (Array.isArray(serverResources)) {
                                serverResources.forEach((r) =>
                                    allSelectedResources.add(String(r)),
                                );
                            }
                        }

                        if (allSelectedResources.size > 0) {
                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedResources"]',
                            );
                            checkboxes.forEach((cb) => {
                                const resourceId = cb.value;
                                const resourceName =
                                    cb.getAttribute("data-resource-name") ||
                                    (Admin.resourceMapping &&
                                        Admin.resourceMapping[cb.value]);
                                if (
                                    allSelectedResources.has(resourceId) ||
                                    (resourceName &&
                                        allSelectedResources.has(
                                            String(resourceName),
                                        ))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    } catch (e) {
                        console.error(
                            "Error restoring edit-server resources checked state:",
                            e,
                        );
                    }

                    // Re-initialize the selector logic for the edit container (resource-specific)
                    Admin.initResourceSelect(
                        "edit-server-resources",
                        "selectedEditResourcesPills",
                        "selectedEditResourcesWarning",
                        6,
                        "selectAllEditResourcesBtn",
                        "clearAllEditResourcesBtn",
                    );
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load resources</div>';
                }
            } catch (error) {
                console.error("Error loading resources:", error);
                container.innerHTML =
                    '<div class="text-center py-4 text-red-600">Error loading resources</div>';
            }
            return;
        }

        try {
            // Call the search API with gateway and team filters
            const selectedTeamId = Admin.getCurrentTeamId();
            const params = new URLSearchParams();
            params.set("q", searchTerm);
            params.set("limit", "100");
            if (gatewayIdParam) {
                params.set("gateway_id", gatewayIdParam);
            }
            if (selectedTeamId) {
                params.set("team_id", selectedTeamId);
            }
            const searchUrl = `${window.ROOT_PATH}/admin/resources/search?${params.toString()}`;

            console.log(
                `[Edit Resource Search] Searching resources with URL: ${searchUrl}`,
            );

            const response = await fetch(searchUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.resources && data.resources.length > 0) {
                // Create HTML for search results
                let searchResultsHtml = "";
                data.resources.forEach((resource) => {
                    const name = resource.name || resource.id;

                    searchResultsHtml += `
                        <label
                            class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md p-1 resource-item"
                            data-resource-id="${escapeHtml(resource.id)}"
                        >
                            <input
                                type="checkbox"
                                name="associatedResources"
                                value="${escapeHtml(resource.id)}"
                                data-resource-name="${escapeHtml(name)}"
                                class="resource-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600"
                            />
                            <span class="select-none">${escapeHtml(name)}</span>
                        </label>
                    `;
                });

                container.innerHTML = searchResultsHtml;

                // Update mapping
                Admin.updateResourceMapping(container);

                // Restore checked state for any resources already associated with the server
                try {
                    const dataAttr = container.getAttribute(
                        "data-server-resources",
                    );
                    if (dataAttr) {
                        const serverResources = JSON.parse(dataAttr);
                        if (
                            Array.isArray(serverResources) &&
                            serverResources.length > 0
                        ) {
                            // Normalize serverResources to a set of strings for robust comparison
                            const serverResourceSet = new Set(
                                serverResources.map((s) => String(s)),
                            );

                            const checkboxes = container.querySelectorAll(
                                'input[name="associatedResources"]',
                            );
                            checkboxes.forEach((cb) => {
                                const resourceId = cb.value;
                                const resourceName =
                                    cb.getAttribute("data-resource-name") ||
                                    (Admin.resourceMapping &&
                                        Admin.resourceMapping[cb.value]);
                                // Check by id first (string), then by name as a fallback
                                if (
                                    serverResourceSet.has(resourceId) ||
                                    (resourceName &&
                                        serverResourceSet.has(String(resourceName)))
                                ) {
                                    cb.checked = true;
                                }
                            });

                            // Trigger update so pills/counts refresh
                            const firstCb = container.querySelector(
                                'input[type="checkbox"]',
                            );
                            if (firstCb) {
                                firstCb.dispatchEvent(
                                    new Event("change", { bubbles: true }),
                                );
                            }
                        }
                    }
                } catch (e) {
                    console.error(
                        "Error restoring edit-server resources checked state:",
                        e,
                    );
                }

                // Initialize selector behavior
                Admin.initResourceSelect(
                    "edit-server-resources",
                    "selectedEditResourcesPills",
                    "selectedEditResourcesWarning",
                    6,
                    "selectAllEditResourcesBtn",
                    "clearAllEditResourcesBtn",
                );

                // Hide no results message
                if (noResultsMessage) {
                    noResultsMessage.style.display = "none";
                }
            } else {
                // Show no results message
                container.innerHTML = "";
                if (noResultsMessage) {
                    if (searchQuerySpan) {
                        searchQuerySpan.textContent = searchTerm;
                    }
                    noResultsMessage.style.display = "block";
                }
            }
        } catch (error) {
            console.error("Error searching resources:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching resources</div>';
            if (noResultsMessage) {
                noResultsMessage.style.display = "none";
            }
        }
    }

    // Add CSS for streaming indicator animation
    const style = document.createElement("style");
    style.textContent = `
    .streaming-indicator {
        animation: blink 1s infinite;
    }

    @keyframes blink {
        0%, 50% { opacity: 1; }
        51%, 100% { opacity: 0; }
    }

    #chat-input {
        max-height: 120px;
        overflow-y: auto;
    }
    `;
    document.head.appendChild(style);

    // ============================================================================
    // CA Certificate Validation Functions
    // ============================================================================

    /**
    * Validate CA certificate file on upload (supports multiple files)
    * @param {Event} event - The file input change event
    */
    Admin.validateCACertFiles = async function (event) {
        const files = Array.from(event.target.files);
        const feedbackEl = Admin.safeGetElement("ca-certificate-feedback");

        if (!files.length) {
            feedbackEl.textContent = "No files selected.";
            return;
        }

        // Check file size (max 10MB for cert files)
        const maxSize = 10 * 1024 * 1024; // 10MB
        const oversizedFiles = files.filter((f) => f.size > maxSize);
        if (oversizedFiles.length > 0) {
            if (feedbackEl) {
                feedbackEl.innerHTML = `
                    <div class="flex items-center text-red-600">
                        <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        <span>Certificate file(s) too large. Maximum size is 10MB per file.</span>
                    </div>
                `;
                feedbackEl.className = "mt-2 text-sm";
            }
            event.target.value = "";
            return;
        }

        // Check file extensions
        const validExtensions = [".pem", ".crt", ".cer", ".cert"];
        const invalidFiles = files.filter((file) => {
            const fileName = file.name.toLowerCase();
            return !validExtensions.some((ext) => fileName.endsWith(ext));
        });

        if (invalidFiles.length > 0) {
            if (feedbackEl) {
                feedbackEl.innerHTML = `
                    <div class="flex items-center text-red-600">
                        <svg class="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        <span>Invalid file type. Please upload valid certificate files (.pem, .crt, .cer, .cert)</span>
                    </div>
                `;
                feedbackEl.className = "mt-2 text-sm";
            }
            event.target.value = "";
            return;
        }

        // Read and validate all files
        const certResults = [];
        for (const file of files) {
            try {
                const content = await Admin.readFileAsync(file);
                const isValid = Admin.isValidCertificate(content);
                const certInfo = isValid ? Admin.parseCertificateInfo(content) : null;

                certResults.push({
                    file,
                    content,
                    isValid,
                    certInfo,
                });
            } catch (error) {
                certResults.push({
                    file,
                    content: null,
                    isValid: false,
                    certInfo: null,
                    error: error.message,
                });
            }
        }

        // Display per-file validation results
        Admin.displayCertValidationResults(certResults, feedbackEl);

        // If all valid, order and concatenate
        const allValid = certResults.every((r) => r.isValid);
        if (allValid) {
            const orderedCerts = Admin.orderCertificateChain(certResults);
            const concatenated = orderedCerts
                .map((r) => r.content.trim())
                .join("\n");

            // Store concatenated result in a hidden field
            let hiddenInput = Admin.safeGetElement(
                "ca_certificate_concatenated",
            );
            if (!hiddenInput) {
                hiddenInput = document.createElement("input");
                hiddenInput.type = "hidden";
                hiddenInput.id = "ca_certificate_concatenated";
                hiddenInput.name = "ca_certificate";
                event.target.form.appendChild(hiddenInput);
            }
            hiddenInput.value = concatenated;

            // Update drop zone
            Admin.updateDropZoneWithFiles(files);
        } else {
            event.target.value = "";
        }
    }

    /**
    * Helper function to read file as text asynchronously
    * @param {File} file - The file to read
    * @returns {Promise<string>} - Promise resolving to file content
    */
    Admin.readFileAsync = function (file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => Admin.resolve(e.target.result);
            reader.onerror = () => Admin.reject(new Error("Error reading file"));
            reader.readAsText(file);
        });
    }

    /**
    * Parse certificate information to determine if it's self-signed (root CA)
    * @param {string} content - PEM certificate content
    * @returns {Object} - Certificate info with isRoot flag
    */
    Admin.parseCertificateInfo = function (content) {
        // Basic heuristic: check if Subject and Issuer appear the same
        // In a real implementation, you'd parse the ASN.1 structure properly
        const subjectMatch = content.match(/Subject:([^\n]+)/i);
        const issuerMatch = content.match(/Issuer:([^\n]+)/i);

        // If we can't parse, assume it's an intermediate
        if (!subjectMatch || !issuerMatch) {
            return { isRoot: false };
        }

        const subject = subjectMatch[1].trim();
        const issuer = issuerMatch[1].trim();

        return {
            isRoot: subject === issuer,
            subject,
            issuer,
        };
    }

    /**
    * Order certificates in chain: root CA first, then intermediates, then leaf
    * @param {Array} certResults - Array of certificate result objects
    * @returns {Array} - Ordered array of certificate results
    */
    Admin.orderCertificateChain = function (certResults) {
        const roots = certResults.filter((r) => r.certInfo && r.certInfo.isRoot);
        const nonRoots = certResults.filter(
            (r) => r.certInfo && !r.certInfo.isRoot,
        );

        // Simple ordering: roots first, then rest
        // In production, you'd build a proper chain by matching issuer/subject
        return [...roots, ...nonRoots];
    }

    /**
    * Display validation results for each certificate file
    * @param {Array} certResults - Array of validation result objects
    * @param {HTMLElement} feedbackEl - Element to display feedback
    */
    Admin.displayCertValidationResults = function (certResults, feedbackEl) {
        const allValid = certResults.every((r) => r.isValid);

        let html = '<div class="space-y-2">';

        // Overall status
        if (allValid) {
            html += `
                <div class="flex items-center text-green-600 font-semibold text-lg">
                    <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <span>All certificates validated successfully!</span>
                </div>
            `;
        } else {
            html += `
                <div class="flex items-center text-red-600 font-semibold text-lg">
                    <svg class="w-8 h-8 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    <span>Some certificates failed validation</span>
                </div>
            `;
        }

        // Per-file results
        html += '<div class="mt-3 space-y-1">';
        for (const result of certResults) {
            const icon = result.isValid
                ? '<svg class="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
                : '<svg class="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';

            const statusClass = result.isValid ? "text-gray-700" : "text-red-700";
            const typeLabel =
                result.certInfo && result.certInfo.isRoot ? " (Root CA)" : "";

            html += `
                <div class="flex items-center ${statusClass}">
                    ${icon}
                    <span class="ml-2">${escapeHtml(result.file.name)}${typeLabel} - ${formatFileSize(result.file.size)}</span>
                </div>
            `;
        }
        html += "</div></div>";

        feedbackEl.innerHTML = html;
        feedbackEl.className = "mt-2 text-sm";
    }

    /**
    * Validate certificate content (PEM format)
    * @param {string} content - The certificate file content
    * @returns {boolean} - True if valid certificate
    */
    Admin.isValidCertificate = function (content) {
        // Trim whitespace
        content = content.trim();

        // Check for PEM certificate markers
        const beginCertPattern = /-----BEGIN CERTIFICATE-----/;
        const endCertPattern = /-----END CERTIFICATE-----/;

        if (!beginCertPattern.test(content) || !endCertPattern.test(content)) {
            return false;
        }

        // Check for proper structure
        const certPattern =
            /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;
        const matches = content.match(certPattern);

        if (!matches || matches.length === 0) {
            return false;
        }

        // Validate base64 content between markers
        for (const cert of matches) {
            const base64Content = cert
                .replace(/-----BEGIN CERTIFICATE-----/, "")
                .replace(/-----END CERTIFICATE-----/, "")
                .replace(/\s/g, "");

            // Check if content is valid base64
            if (!isValidBase64(base64Content)) {
                return false;
            }

            // Basic length check (certificates are typically > 100 chars of base64)
            if (base64Content.length < 100) {
                return false;
            }
        }

        return true;
    }

    /**
    * Check if string is valid base64
    * @param {string} str - The string to validate
    * @returns {boolean} - True if valid base64
    */
    Admin.isValidBase64 = function (str) {
        if (str.length === 0) {
            return false;
        }

        // Base64 regex pattern
        const base64Pattern = /^[A-Za-z0-9+/]*={0,2}$/;
        return base64Pattern.test(str);
    }

    /**
    * Update drop zone UI with selected file info
    * @param {File} file - The selected file
    */
    Admin.updateDropZoneWithFiles = function (files) {
        const dropZone = Admin.safeGetElement("ca-certificate-upload-drop-zone");
        if (!dropZone) {
            return;
        }

        const fileListHTML = Array.from(files)
            .map(
                (file) =>
                    `<div>${escapeHtml(file.name)} • ${formatFileSize(file.size)}</div>`,
            )
            .join("");

        dropZone.innerHTML = `
            <div class="space-y-2">
                <svg class="mx-auto h-12 w-12 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <div class="text-sm text-gray-700 dark:text-gray-300">
                    <span class="font-medium">Selected Certificates:</span>
                </div>
                <div class="text-xs text-gray-500 dark:text-gray-400">${fileListHTML}</div>
            </div>
        `;
    }

    /**
    * Format file size for display
    * @param {number} bytes - File size in bytes
    * @returns {string} - Formatted file size
    */
    Admin.formatFileSize = function (bytes) {
        if (bytes === 0) {
            return "0 Bytes";
        }
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
    }

    /**
    * Initialize drag and drop for CA cert upload
    * Called on DOMContentLoaded
    */
    Admin.initializeCACertUpload = function () {
        const dropZone = Admin.safeGetElement("ca-certificate-upload-drop-zone");
        const fileInput = Admin.safeGetElement("upload-ca-certificate");

        if (dropZone && fileInput) {
            // Click to upload
            dropZone.addEventListener("click", function (e) {
                fileInput.click();
            });

            // Drag and drop handlers
            dropZone.addEventListener("dragover", function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.add(
                    "border-indigo-500",
                    "bg-indigo-50",
                    "dark:bg-indigo-900/20",
                );
            });

            dropZone.addEventListener("dragleave", function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove(
                    "border-indigo-500",
                    "bg-indigo-50",
                    "dark:bg-indigo-900/20",
                );
            });

            dropZone.addEventListener("drop", function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropZone.classList.remove(
                    "border-indigo-500",
                    "bg-indigo-50",
                    "dark:bg-indigo-900/20",
                );

                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    fileInput.files = files;
                    // Trigger the validation
                    const event = new Event("change", { bubbles: true });
                    fileInput.dispatchEvent(event);
                }
            });
        }
    }

    // Function to update body label based on content type selection
    Admin.updateBodyLabel = function () {
        const bodyLabel = Admin.safeGetElement("gateway-test-body-label");
        const contentType = Admin.safeGetElement(
            "gateway-test-content-type",
        )?.value;

        if (bodyLabel) {
            bodyLabel.innerHTML =
                contentType === "application/x-www-form-urlencoded"
                    ? 'Body (JSON)<br><small class="text-gray-500">Auto-converts to form data</small>'
                    : "Body (JSON)";
        }
    }

    /**
    * ====================================================================
    * REAL-TIME GATEWAY & TOOL MONITORING (SSE)
    * Handles live status updates for Gateways and Tools
    * ====================================================================
    */

    document.addEventListener("DOMContentLoaded", function () {
        Admin.initializeRealTimeMonitoring();
    });

    Admin.initializeRealTimeMonitoring = function () {
        if (!window.EventSource) {
            return;
        }

        // Connect to the admin events endpoint
        const eventSource = new EventSource(`${window.ROOT_PATH}/admin/events`);

        // --- Gateway Events ---
        // Handlers for specific states

        // eventSource.addEventListener("gateway_deactivated", (e) => Admin.handleEntityEvent("gateway", e));
        eventSource.addEventListener("gateway_activated", (e) =>
            Admin.handleEntityEvent("gateway", e),
        );
        eventSource.addEventListener("gateway_offline", (e) =>
            Admin.handleEntityEvent("gateway", e),
        );

        // --- Tool Events ---
        // Handlers for specific states

        // eventSource.addEventListener("tool_deactivated", (e) => Admin.handleEntityEvent("tool", e));
        eventSource.addEventListener("tool_activated", (e) =>
            Admin.handleEntityEvent("tool", e),
        );
        eventSource.addEventListener("tool_offline", (e) =>
            Admin.handleEntityEvent("tool", e),
        );

        eventSource.onopen = () =>
            console.log("✅ SSE Connected for Real-time Monitoring");
        eventSource.onerror = (err) =>
            console.warn("⚠️ SSE Connection issue, retrying...", err);
    }

    /**
    * Generic handler for entity events
    */
    Admin.handleEntityEvent = function (type, event) {
        try {
            const data = JSON.parse(event.data);
            // Log the specific event type for debugging
            // console.log(`Received ${type} event [${event.type}]:`, data);
            Admin.updateEntityStatus(type, data);
        } catch (err) {
            console.error(`Error processing ${type} event:`, err);
        }
    }

    /**
    * Updates the status badge and action buttons for a row
    */

    Admin.updateEntityStatus = function (type, data) {
        let row = null;

        if (type === "gateway") {
            // Gateways usually have explicit IDs
            row = Admin.safeGetElement(`gateway-row-${data.id}`);
        } else if (type === "tool") {
            // 1. Try explicit ID (fastest)
            row = Admin.safeGetElement(`tool-row-${data.id}`);

            // 2. Fallback: Search rows by looking for the ID in Action buttons
            if (!row) {
                const panel = Admin.safeGetElement("tools-panel");
                if (panel) {
                    const rows = panel.querySelectorAll("table tbody tr");
                    for (const tr of rows) {
                        // Check data attribute if present
                        if (tr.dataset.toolId === data.id) {
                            row = tr;
                            break;
                        }

                        // Check innerHTML for the UUID in action attributes
                        const html = tr.innerHTML;
                        if (html.includes(data.id)) {
                            // Verify it's likely an ID usage (in quotes or url path)
                            if (
                                html.includes(`'${data.id}'`) ||
                                html.includes(`"${data.id}"`) ||
                                html.includes(`/${data.id}/`)
                            ) {
                                row = tr;
                                // Optimization: Set ID on row for next time
                                tr.id = `tool-row-${data.id}`;
                                break;
                            }
                        }
                    }
                }
            }
        }

        if (!row) {
            console.warn(`Could not find row for ${type} id: ${data.id}`);
            return;
        }

        // Dynamically find Status and Action columns
        const table = row.closest("table");
        let statusIndex = -1;
        let actionIndex = -1;

        if (table) {
            const headers = table.querySelectorAll("thead th");
            headers.forEach((th, index) => {
                const text = th.textContent.trim().toLowerCase();
                if (text === "status") {
                    statusIndex = index;
                }
                if (text === "actions") {
                    actionIndex = index;
                }
            });
        }

        // Fallback indices if headers aren't found
        if (statusIndex === -1) {
            statusIndex = type === "gateway" ? 4 : 5;
        }
        if (actionIndex === -1) {
            actionIndex = type === "gateway" ? 9 : 6;
        }

        const statusCell = row.children[statusIndex];
        const actionCell = row.children[actionIndex];

        // --- 1. Update Status Badge ---
        if (statusCell) {
            const isEnabled =
                data.enabled !== undefined ? data.enabled : data.isActive;
            const isReachable =
                data.reachable !== undefined ? data.reachable : true;

            statusCell.innerHTML = Admin.generateStatusBadgeHtml(
                isEnabled,
                isReachable,
                type,
            );

            // Flash effect
            statusCell.classList.add(
                "bg-blue-50",
                "dark:bg-blue-900",
                "transition-colors",
                "duration-500",
            );
            setTimeout(() => {
                statusCell.classList.remove("bg-blue-50", "dark:bg-blue-900");
            }, 1000);
        }

        // --- 2. Update Action Buttons ---
        if (actionCell) {
            const isEnabled =
                data.enabled !== undefined ? data.enabled : data.isActive;
            Admin.updateEntityActionButtons(actionCell, type, data.id, isEnabled);
        }
    }
    // ============================================================================
    // Structured Logging UI Functions
    // ============================================================================

    // Current log search state
    let currentLogPage = 0;
    const currentLogLimit = 50;
    // eslint-disable-next-line no-unused-vars
    let currentLogFilters = {};
    const PERFORMANCE_HISTORY_HOURS = 24;
    const PERFORMANCE_AGGREGATION_OPTIONS = {
        "5m": { label: "5-minute aggregation", query: "5m" },
        "24h": { label: "24-hour aggregation", query: "24h" },
    };
    let currentPerformanceAggregationKey = "5m";

    Admin.getPerformanceAggregationConfig = function (
        rangeKey = currentPerformanceAggregationKey,
    ) {
        return (
            PERFORMANCE_AGGREGATION_OPTIONS[rangeKey] ||
            PERFORMANCE_AGGREGATION_OPTIONS["5m"]
        );
    }

    Admin.getPerformanceAggregationLabel = function (
        rangeKey = currentPerformanceAggregationKey,
    ) {
        return Admin.getPerformanceAggregationConfig(rangeKey).label;
    }

    Admin.getPerformanceAggregationQuery = function (
        rangeKey = currentPerformanceAggregationKey,
    ) {
        return Admin.getPerformanceAggregationConfig(rangeKey).query;
    }

    Admin.syncPerformanceAggregationSelect = function () {
        const select = Admin.safeGetElement("performance-aggregation-select");
        if (select && select.value !== currentPerformanceAggregationKey) {
            select.value = currentPerformanceAggregationKey;
        }
    }

    Admin.setPerformanceAggregationVisibility = function (shouldShow) {
        const controls = Admin.safeGetElement(
            "performance-aggregation-controls",
        );
        if (!controls) {
            return;
        }
        if (shouldShow) {
            controls.classList.remove("hidden");
        } else {
            controls.classList.add("hidden");
        }
    }

    Admin.setLogFiltersVisibility = function (shouldShow) {
        const filters = Admin.safeGetElement("log-filters");
        if (!filters) {
            return;
        }
        if (shouldShow) {
            filters.classList.remove("hidden");
        } else {
            filters.classList.add("hidden");
        }
    }

    Admin.handlePerformanceAggregationChange = function (event) {
        const selectedKey = event?.target?.value;
        if (selectedKey && PERFORMANCE_AGGREGATION_OPTIONS[selectedKey]) {
            Admin.showPerformanceMetrics(selectedKey);
        }
    }

    /**
    * Search structured logs with filters
    */
    Admin.searchStructuredLogs = async function () {
        Admin.setPerformanceAggregationVisibility(false);
        Admin.setLogFiltersVisibility(true);
        const levelFilter = Admin.safeGetElement("log-level-filter")?.value;
        const componentFilter = Admin.safeGetElement(
            "log-component-filter",
        )?.value;
        const searchQuery = Admin.safeGetElement("log-search")?.value;

        // Restore default log table headers (in case we're coming from performance metrics view)
        Admin.restoreLogTableHeaders();

        // Build search request
        const searchRequest = {
            limit: currentLogLimit,
            offset: currentLogPage * currentLogLimit,
            sort_by: "timestamp",
            sort_order: "desc",
        };

        // Only add filters if they have actual values (not empty strings)
        if (searchQuery && searchQuery.trim() !== "") {
            const trimmedSearch = searchQuery.trim();
            // Check if search is a correlation ID (32 hex chars or UUID format) or text search
            const correlationIdPattern =
                /^([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
            if (correlationIdPattern.test(trimmedSearch)) {
                searchRequest.correlation_id = trimmedSearch;
            } else {
                searchRequest.search_text = trimmedSearch;
            }
        }
        if (levelFilter && levelFilter !== "") {
            searchRequest.level = [levelFilter];
        }
        if (componentFilter && componentFilter !== "") {
            searchRequest.component = [componentFilter];
        }

        // Store filters for pagination
        currentLogFilters = searchRequest;

        try {
            const response = await Admin.fetchWithAuth(
                `${getRootPath()}/api/logs/search`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify(searchRequest),
                },
            );

            if (!response.ok) {
                const errorText = await response.text();
                console.error("API Error Response:", errorText);
                throw new Error(
                    `Failed to search logs: ${response.statusText} - ${errorText}`,
                );
            }

            const data = await response.json();
            Admin.displayLogResults(data);
        } catch (error) {
            console.error("Error searching logs:", error);
            Admin.showToast("Failed to search logs: " + error.message, "error");
            Admin.safeGetElement("logs-tbody").innerHTML = `
                <tr><td colspan="7" class="px-4 py-4 text-center text-red-600 dark:text-red-400">
                    ❌ Error: ${escapeHtml(error.message)}
                </td></tr>
            `;
        }
    }

    /**
    * Display log search results
    */
    Admin.displayLogResults = function (data) {
        const tbody = Admin.safeGetElement("logs-tbody");
        const logCount = Admin.safeGetElement("log-count");
        const logStats = Admin.safeGetElement("log-stats");
        const prevButton = Admin.safeGetElement("prev-page");
        const nextButton = Admin.safeGetElement("next-page");

        // Ensure default headers are shown for log view
        Admin.restoreLogTableHeaders();

        if (!data.results || data.results.length === 0) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    📭 No logs found matching your criteria
                </td></tr>
            `;
            logCount.textContent = "0 logs";
            logStats.innerHTML = '<span class="text-sm">No results</span>';
            return;
        }

        // Update stats
        logCount.textContent = `${data.total.toLocaleString()} logs`;
        const start = currentLogPage * currentLogLimit + 1;
        const end = Math.min(start + data.results.length - 1, data.total);
        logStats.innerHTML = `
            <span class="text-sm">
                Showing ${start}-${end} of ${data.total.toLocaleString()} logs
            </span>
        `;

        // Update pagination buttons
        prevButton.disabled = currentLogPage === 0;
        nextButton.disabled = end >= data.total;

        // Render log entries
        tbody.innerHTML = data.results
            .map((log) => {
                const levelClass = Admin.getLogLevelClass(log.level);
                const durationDisplay = log.duration_ms
                    ? `${log.duration_ms.toFixed(2)}ms`
                    : "-";
                const correlationId = log.correlation_id || "-";
                const userDisplay = log.user_email || log.user_id || "-";

                return `
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
                    onclick="Admin.showLogDetails('${log.id}', '${escapeHtml(log.correlation_id || "")}')">
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${formatTimestamp(log.timestamp)}
                    </td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 text-xs font-semibold rounded ${levelClass}">
                            ${log.level}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(log.component || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${escapeHtml(Admin.truncateText(log.message, 80))}
                        ${log.error_details ? '<span class="text-red-600">⚠️</span>' : ""}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(userDisplay)}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${durationDisplay}
                    </td>
                    <td class="px-4 py-3 text-sm">
                        ${
                            correlationId !== "-"
                                ? `
                            <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(correlationId)}')"
                                    class="text-blue-600 dark:text-blue-400 hover:underline">
                                ${escapeHtml(Admin.truncateText(correlationId, 12))}
                            </button>
                        `
                                : "-"
                        }
                    </td>
                </tr>
            `;
            })
            .join("");
    }

    /**
    * Get CSS class for log level badge
    */
    Admin.getLogLevelClass = function (level) {
        const classes = {
            DEBUG: "bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200",
            INFO: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
            WARNING:
                "bg-yellow-200 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200",
            ERROR: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
            CRITICAL:
                "bg-purple-200 text-purple-800 dark:bg-purple-800 dark:text-purple-200",
        };
        return classes[level] || classes.INFO;
    }

    /**
    * Format timestamp for display
    */
    Admin.formatTimestamp = function (timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    }

    /**
    * Truncate text with ellipsis
    */
    Admin.truncateText = function (text, maxLength) {
        if (!text) {
            return "";
        }
        return text.length > maxLength
            ? text.substring(0, maxLength) + "..."
            : text;
    }

    /**
    * Show detailed log entry (future enhancement - modal)
    */
    Admin.showLogDetails = function (logId, correlationId) {
        if (correlationId) {
            Admin.showCorrelationTrace(correlationId);
        } else {
            console.log("Log details:", logId);
            Admin.showToast("Full log details view coming soon", "info");
        }
    }

    /**
    * Restore default log table headers
    */
    Admin.restoreLogTableHeaders = function () {
        const thead = Admin.safeGetElement("logs-thead");
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Time
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Level
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Component
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Message
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        User
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Duration
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Correlation ID
                    </th>
                </tr>
            `;
        }
    }

    /**
    * Trace all logs for a correlation ID
    */
    Admin.showCorrelationTrace = async function (correlationId) {
        Admin.setPerformanceAggregationVisibility(false);
        Admin.setLogFiltersVisibility(true);
        if (!correlationId) {
            const searchInput = Admin.safeGetElement("log-search");
            correlationId = Admin.prompt(
                "Enter Correlation ID to trace:",
                searchInput?.value || "",
            );
            if (!correlationId) {
                return;
            }
        }

        try {
            const response = await Admin.fetchWithAuth(
                `${getRootPath()}/api/logs/trace/${encodeURIComponent(correlationId)}`,
                {
                    method: "GET",
                },
            );

            if (!response.ok) {
                throw new Error(`Failed to fetch trace: ${response.statusText}`);
            }

            const trace = await response.json();
            Admin.displayCorrelationTrace(trace);
        } catch (error) {
            console.error("Error fetching correlation trace:", error);
            Admin.showToast(
                "Failed to fetch correlation trace: " + error.message,
                "error",
            );
        }
    }

    /**
    * Generates the HTML for the status badge (Active/Inactive/Offline)
    */
    Admin.generateStatusBadgeHtml = function (enabled, reachable, typeLabel) {
        const label = typeLabel
            ? typeLabel.charAt(0).toUpperCase() + typeLabel.slice(1)
            : "Item";

        if (!enabled) {
            // CASE 1: Inactive (Manually disabled) -> RED
            return `
            <div class="relative group inline-block">
                <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
                    Inactive
                    <svg class="ml-1 h-4 w-4 text-red-600 dark:text-red-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
                </span>
                <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Manually Deactivated</div>
            </div>`;
        } else if (!reachable) {
            // CASE 2: Offline (Enabled but Unreachable/Health Check Failed) -> YELLOW
            return `
            <div class="relative group inline-block">
                <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
                    Offline
                    <svg class="ml-1 h-4 w-4 text-yellow-600 dark:text-yellow-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd"/></svg>
                </span>
                <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Not Reachable (Health Check Failed)</div>
            </div>`;
        } else {
            // CASE 3: Active (Enabled and Reachable) -> GREEN
            return `
            <div class="relative group inline-block">
                <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                    Active
                    <svg class="ml-1 h-4 w-4 text-green-600 dark:text-green-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"/></svg>
                </span>
                <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">💡${label} is Active</div>
            </div>`;
        }
    }

    /**
    * Dynamically updates the action buttons (Activate/Deactivate) inside the table cell
    */
    Admin.updateEntityActionButtons = function (cell, type, id, isEnabled) {
        // We look for the form that toggles activation inside the cell
        const form = cell.querySelector('form[action*="/state"]');
        if (!form) {
            return;
        }

        // The HTML structure for the button
        // Ensure we are flipping the button state correctly based on isEnabled

        if (isEnabled) {
            // If Enabled -> Show Deactivate Button
            form.innerHTML = `
                <input type="hidden" name="activate" value="false" />
                <button type="submit" class="flex items-center justify-center px-2 py-1 text-xs font-medium rounded-md text-yellow-600 hover:text-yellow-900 hover:bg-yellow-50 dark:text-yellow-400 dark:hover:bg-yellow-900/20 transition-colors" x-tooltip="'💡Temporarily disable this item'">
                    Deactivate
                </button>
            `;
        } else {
            // If Disabled -> Show Activate Button
            form.innerHTML = `
                <input type="hidden" name="activate" value="true" />
                <button type="submit" class="flex items-center justify-center px-2 py-1 text-xs font-medium rounded-md text-blue-600 hover:text-blue-900 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/20 transition-colors" x-tooltip="'💡Re-enable this item'">
                    Activate
                </button>
            `;
        }
    }

    // CRITICAL DEBUG AND FIX FOR MCP SERVERS SEARCH
    console.log("🔧 LOADING MCP SERVERS SEARCH DEBUG FUNCTIONS...");

    // Emergency fix function for MCP Servers search
    Admin.emergencyFixMCPSearch = function () {
        console.log("🚨 EMERGENCY FIX: Attempting to fix MCP Servers search...");

        // Find the search input
        const searchInput = Admin.safeGetElement("gateways-search-input");
        if (!searchInput) {
            console.error("❌ Cannot find gateways-search-input element");
            return false;
        }

        console.log("✅ Found search input:", searchInput);

        // Remove all existing event listeners by cloning
        const newSearchInput = searchInput.cloneNode(true);
        searchInput.parentNode.replaceChild(newSearchInput, searchInput);

        // Add fresh event listener
        const finalSearchInput = Admin.safeGetElement("gateways-search-input");
        finalSearchInput.addEventListener("input", function (e) {
            console.log("🔍 EMERGENCY SEARCH EVENT:", e.target.value);
            Admin.filterGatewaysTable(e.target.value);
        });

        console.log(
            "✅ Emergency fix applied - test by typing in MCP Servers search box",
        );
        return true;
    };

    // Manual test function
    Admin.testMCPSearchManually = function (searchTerm = "github") {
        console.log("🧪 MANUAL TEST: Testing MCP search with:", searchTerm);
        Admin.filterGatewaysTable(searchTerm);
    };

    // Debug current state function
    Admin.debugMCPSearchState = function () {
        console.log("🔍 DEBUGGING MCP SEARCH STATE:");

        const searchInput = Admin.safeGetElement("gateways-search-input");
        console.log("Search input:", searchInput);
        console.log(
            "Search input value:",
            searchInput ? searchInput.value : "NOT FOUND",
        );

        const panel = Admin.safeGetElement("gateways-panel");
        console.log("Gateways panel:", panel);

        const table = panel ? panel.querySelector("table") : null;
        console.log("Table in panel:", table);

        const rows = table ? table.querySelectorAll("tbody tr") : [];
        console.log("Rows found:", rows.length);

        if (rows.length > 0) {
            console.log("First row content:", rows[0].textContent);
        }

        return {
            searchInput: !!searchInput,
            panel: !!panel,
            table: !!table,
            rowCount: rows.length,
        };
    };

    // Auto-fix on page load
    setTimeout(function () {
        console.log("🔄 AUTO-FIX: Attempting to fix MCP search after page load...");
        if (window.emergencyFixMCPSearch) {
            window.emergencyFixMCPSearch();
        }
    }, 1000);

    console.log("🔧 MCP SERVERS SEARCH DEBUG FUNCTIONS LOADED!");
    console.log("💡 Use: window.emergencyFixMCPSearch() to fix search");
    console.log("💡 Use: window.testMCPSearchManually('github') to test search");
    console.log("💡 Use: window.debugMCPSearchState() to check current state");

    /**
    * Display correlation trace results
    */
    Admin.displayCorrelationTrace = function (trace) {
        const tbody = Admin.safeGetElement("logs-tbody");
        const thead = Admin.safeGetElement("logs-thead");
        const logCount = Admin.safeGetElement("log-count");
        const logStats = Admin.safeGetElement("log-stats");

        // Calculate total events
        const totalEvents =
            (trace.logs?.length || 0) +
            (trace.security_events?.length || 0) +
            (trace.audit_trails?.length || 0);

        // Update table headers for trace view
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Time
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Event Type
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Component
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Message/Description
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        User
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Duration
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Status/Severity
                    </th>
                </tr>
            `;
        }

        // Update stats
        logCount.textContent = `${totalEvents} events`;
        logStats.innerHTML = `
            <div class="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
                <div>
                    <strong>Correlation ID:</strong><br>
                    <code class="text-xs bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">${escapeHtml(trace.correlation_id)}</code>
                </div>
                <div>
                    <strong>Logs:</strong> <span class="text-blue-600">${trace.log_count || 0}</span>
                </div>
                <div>
                    <strong>Security:</strong> <span class="text-red-600">${trace.security_events?.length || 0}</span>
                </div>
                <div>
                    <strong>Audit:</strong> <span class="text-yellow-600">${trace.audit_trails?.length || 0}</span>
                </div>
                <div>
                    <strong>Duration:</strong> ${trace.total_duration_ms ? trace.total_duration_ms.toFixed(2) + "ms" : "N/A"}
                </div>
            </div>
        `;

        if (totalEvents === 0) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    📭 No events found for this correlation ID
                </td></tr>
            `;
            return;
        }

        // Combine all events into a unified timeline
        const allEvents = [];

        // Add logs
        (trace.logs || []).forEach((log) => {
            const levelClass = Admin.getLogLevelClass(log.level);
            allEvents.push({
                timestamp: new Date(log.timestamp),
                html: `
                    <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-blue-500">
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            ${formatTimestamp(log.timestamp)}
                        </td>
                        <td class="px-4 py-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200">
                                📝 Log
                            </span>
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(log.component || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            ${escapeHtml(log.message)}
                            ${log.error_details ? `<br><small class="text-red-600">⚠️ ${escapeHtml(log.error_details.error_message || JSON.stringify(log.error_details))}</small>` : ""}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(log.user_email || log.user_id || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${log.duration_ms ? log.duration_ms.toFixed(2) + "ms" : "-"}
                        </td>
                        <td class="px-4 py-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded ${levelClass}">
                                ${log.level}
                            </span>
                        </td>
                    </tr>
                `,
            });
        });

        // Add security events
        (trace.security_events || []).forEach((event) => {
            const severityClass = Admin.getSeverityClass(event.severity);
            const threatScore = event.threat_score
                ? (event.threat_score * 100).toFixed(0)
                : 0;
            allEvents.push({
                timestamp: new Date(event.timestamp),
                html: `
                    <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-red-500 bg-red-50 dark:bg-red-900/10">
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            ${formatTimestamp(event.timestamp)}
                        </td>
                        <td class="px-4 py-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200">
                                🛡️ Security
                            </span>
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(event.event_type || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            ${escapeHtml(event.description || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(event.user_email || event.user_id || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                            -
                        </td>
                        <td class="px-4 py-3">
                            <div class="flex flex-col gap-1">
                                <span class="px-2 py-1 text-xs font-semibold rounded ${severityClass} w-fit">
                                    ${event.severity}
                                </span>
                                <div class="flex items-center gap-1">
                                    <span class="text-xs text-gray-600 dark:text-gray-400">Threat:</span>
                                    <div class="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                                        <div class="bg-red-600 h-2 rounded-full" style="width: ${threatScore}%"></div>
                                    </div>
                                    <span class="text-xs font-medium text-gray-700 dark:text-gray-300">${threatScore}%</span>
                                </div>
                            </div>
                        </td>
                    </tr>
                `,
            });
        });

        // Add audit trails
        (trace.audit_trails || []).forEach((audit) => {
            const actionBadgeColors = {
                create: "bg-green-200 text-green-800",
                update: "bg-blue-200 text-blue-800",
                delete: "bg-red-200 text-red-800",
                read: "bg-gray-200 text-gray-800",
            };
            const actionBadge =
                actionBadgeColors[audit.action?.toLowerCase()] ||
                "bg-purple-200 text-purple-800";
            const statusIcon = audit.success ? "✓" : "✗";
            const statusClass = audit.success ? "text-green-600" : "text-red-600";
            const statusBg = audit.success
                ? "bg-green-100 dark:bg-green-900"
                : "bg-red-100 dark:bg-red-900";

            allEvents.push({
                timestamp: new Date(audit.timestamp),
                html: `
                    <tr class="hover:bg-gray-50 dark:hover:bg-gray-700 border-l-4 border-yellow-500 bg-yellow-50 dark:bg-yellow-900/10">
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            ${formatTimestamp(audit.timestamp)}
                        </td>
                        <td class="px-4 py-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded ${actionBadge}">
                                📋 ${audit.action?.toUpperCase()}
                            </span>
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(audit.resource_type || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                            <strong>${audit.action}:</strong> ${audit.resource_type}
                            <code class="text-xs bg-gray-200 px-1 rounded">${escapeHtml(audit.resource_id || "-")}</code>
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            ${escapeHtml(audit.user_email || audit.user_id || "-")}
                        </td>
                        <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                            -
                        </td>
                        <td class="px-4 py-3">
                            <span class="px-2 py-1 text-xs font-semibold rounded ${statusBg} ${statusClass}">
                                ${statusIcon} ${audit.success ? "Success" : "Failed"}
                            </span>
                        </td>
                    </tr>
                `,
            });
        });

        // Sort all events chronologically
        allEvents.sort((a, b) => a.timestamp - b.timestamp);

        // Render sorted events
        tbody.innerHTML = allEvents.map((event) => event.html).join("");
    }

    /**
    * Show security events
    */
    Admin.showSecurityEvents = async function () {
        Admin.setPerformanceAggregationVisibility(false);
        Admin.setLogFiltersVisibility(false);
        try {
            const response = await Admin.fetchWithAuth(
                `${getRootPath()}/api/logs/security-events?limit=50&resolved=false`,
                {
                    method: "GET",
                },
            );

            if (!response.ok) {
                throw new Error(
                    `Failed to fetch security events: ${response.statusText}`,
                );
            }

            const events = await response.json();
            Admin.displaySecurityEvents(events);
        } catch (error) {
            console.error("Error fetching security events:", error);
            Admin.showToast("Failed to fetch security events: " + error.message, "error");
        }
    }

    /**
    * Display security events
    */
    Admin.displaySecurityEvents = function (events) {
        const tbody = Admin.safeGetElement("logs-tbody");
        const thead = Admin.safeGetElement("logs-thead");
        const logCount = Admin.safeGetElement("log-count");
        const logStats = Admin.safeGetElement("log-stats");

        // Update table headers for security events
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Time
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Severity
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Event Type
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Description
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        User/Source
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Threat Score
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Correlation ID
                    </th>
                </tr>
            `;
        }

        logCount.textContent = `${events.length} security events`;
        logStats.innerHTML = `
            <span class="text-sm text-red-600 dark:text-red-400">
                🛡️ Unresolved Security Events
            </span>
        `;

        if (events.length === 0) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="px-4 py-8 text-center text-green-600 dark:text-green-400">
                    ✅ No unresolved security events
                </td></tr>
            `;
            return;
        }

        tbody.innerHTML = events
            .map((event) => {
                const severityClass = Admin.getSeverityClass(event.severity);
                const threatScore = (event.threat_score * 100).toFixed(0);

                return `
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${formatTimestamp(event.timestamp)}
                    </td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 text-xs font-semibold rounded ${severityClass}">
                            ${event.severity}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(event.event_type)}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${escapeHtml(event.description)}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(event.user_email || event.user_id || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm">
                        <div class="flex items-center">
                            <div class="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2 mr-2">
                                <div class="bg-red-600 h-2 rounded-full" style="width: ${threatScore}%"></div>
                            </div>
                            <span class="text-xs">${threatScore}%</span>
                        </div>
                    </td>
                    <td class="px-4 py-3 text-sm">
                        ${
                            event.correlation_id
                                ? `
                            <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(event.correlation_id)}')"
                                    class="text-blue-600 dark:text-blue-400 hover:underline">
                                ${escapeHtml(Admin.truncateText(event.correlation_id, 12))}
                            </button>
                        `
                                : "-"
                        }
                    </td>
                </tr>
            `;
            })
            .join("");
    }

    /**
    * Get CSS class for severity badge
    */
    Admin.getSeverityClass = function (severity) {
        const classes = {
            LOW: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
            MEDIUM: "bg-yellow-200 text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200",
            HIGH: "bg-orange-200 text-orange-800 dark:bg-orange-800 dark:text-orange-200",
            CRITICAL: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
        };
        return classes[severity] || classes.MEDIUM;
    }

    /**
    * Show audit trail
    */
    Admin.showAuditTrail = async function () {
        Admin.setPerformanceAggregationVisibility(false);
        Admin.setLogFiltersVisibility(false);
        try {
            const response = await Admin.fetchWithAuth(
                `${getRootPath()}/api/logs/audit-trails?limit=50&requires_review=true`,
                {
                    method: "GET",
                },
            );

            if (!response.ok) {
                throw new Error(
                    `Failed to fetch audit trails: ${response.statusText}`,
                );
            }

            const trails = await response.json();
            Admin.displayAuditTrail(trails);
        } catch (error) {
            console.error("Error fetching audit trails:", error);
            Admin.showToast("Failed to fetch audit trails: " + error.message, "error");
        }
    }

    /**
    * Display audit trail entries
    */
    Admin.displayAuditTrail = function (trails) {
        const tbody = Admin.safeGetElement("logs-tbody");
        const thead = Admin.safeGetElement("logs-thead");
        const logCount = Admin.safeGetElement("log-count");
        const logStats = Admin.safeGetElement("log-stats");

        // Update table headers for audit trail
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Time
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Action
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Resource Type
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Resource
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        User
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Status
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Correlation ID
                    </th>
                </tr>
            `;
        }

        logCount.textContent = `${trails.length} audit entries`;
        logStats.innerHTML = `
            <span class="text-sm text-yellow-600 dark:text-yellow-400">
                📝 Audit Trail Entries Requiring Review
            </span>
        `;

        if (trails.length === 0) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="px-4 py-8 text-center text-green-600 dark:text-green-400">
                    ✅ No audit entries require review
                </td></tr>
            `;
            return;
        }

        tbody.innerHTML = trails
            .map((trail) => {
                const actionClass = trail.success
                    ? "text-green-600"
                    : "text-red-600";
                const actionIcon = trail.success ? "✓" : "✗";

                // Determine action badge color
                const actionBadgeColors = {
                    create: "bg-green-200 text-green-800 dark:bg-green-800 dark:text-green-200",
                    update: "bg-blue-200 text-blue-800 dark:bg-blue-800 dark:text-blue-200",
                    delete: "bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200",
                    read: "bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200",
                    activate:
                        "bg-teal-200 text-teal-800 dark:bg-teal-800 dark:text-teal-200",
                    deactivate:
                        "bg-orange-200 text-orange-800 dark:bg-orange-800 dark:text-orange-200",
                };
                const actionBadge =
                    actionBadgeColors[trail.action.toLowerCase()] ||
                    "bg-purple-200 text-purple-800 dark:bg-purple-800 dark:text-purple-200";

                // Format resource name with ID
                const resourceName =
                    trail.resource_name || trail.resource_id || "-";
                const resourceDisplay = `
                <div class="font-medium">${escapeHtml(resourceName)}</div>
                ${trail.resource_id && trail.resource_name ? `<div class="text-xs text-gray-500">UUID: ${escapeHtml(trail.resource_id)}</div>` : ""}
                ${trail.data_classification ? `<div class="text-xs text-orange-600 mt-1">🔒 ${escapeHtml(trail.data_classification)}</div>` : ""}
            `;

                return `
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${formatTimestamp(trail.timestamp)}
                    </td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 text-xs font-semibold rounded ${actionBadge}">
                            ${trail.action.toUpperCase()}
                        </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(trail.resource_type || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${resourceDisplay}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(trail.user_email || trail.user_id || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm ${actionClass}">
                        ${actionIcon} ${trail.success ? "Success" : "Failed"}
                    </td>
                    <td class="px-4 py-3 text-sm">
                        ${
                            trail.correlation_id
                                ? `
                            <button onclick="event.stopPropagation(); Admin.showCorrelationTrace('${escapeHtml(trail.correlation_id)}')"
                                    class="text-blue-600 dark:text-blue-400 hover:underline">
                                ${escapeHtml(Admin.truncateText(trail.correlation_id, 12))}
                            </button>
                        `
                                : "-"
                        }
                    </td>
                </tr>
            `;
            })
            .join("");
    }

    /**
    * Show performance metrics
    */
    Admin.showPerformanceMetrics = async function (rangeKey) {
        if (rangeKey && PERFORMANCE_AGGREGATION_OPTIONS[rangeKey]) {
            currentPerformanceAggregationKey = rangeKey;
        } else {
            const select = Admin.safeGetElement(
                "performance-aggregation-select",
            );
            if (select?.value && PERFORMANCE_AGGREGATION_OPTIONS[select.value]) {
                currentPerformanceAggregationKey = select.value;
            }
        }

        Admin.syncPerformanceAggregationSelect();
        Admin.setPerformanceAggregationVisibility(true);
        Admin.setLogFiltersVisibility(false);
        const hoursParam = encodeURIComponent(PERFORMANCE_HISTORY_HOURS.toString());
        const aggregationParam = encodeURIComponent(
            Admin.getPerformanceAggregationQuery(),
        );

        try {
            const response = await Admin.fetchWithAuth(
                `${getRootPath()}/api/logs/performance-metrics?hours=${hoursParam}&aggregation=${aggregationParam}`,
                {
                    method: "GET",
                },
            );

            if (!response.ok) {
                throw new Error(
                    `Failed to fetch performance metrics: ${response.statusText}`,
                );
            }

            const metrics = await response.json();
            Admin.displayPerformanceMetrics(metrics);
        } catch (error) {
            console.error("Error fetching performance metrics:", error);
            Admin.showToast(
                "Failed to fetch performance metrics: " + error.message,
                "error",
            );
        }
    }

    /**
    * Display performance metrics
    */
    Admin.displayPerformanceMetrics = function (metrics) {
        const tbody = Admin.safeGetElement("logs-tbody");
        const thead = Admin.safeGetElement("logs-thead");
        const logCount = Admin.safeGetElement("log-count");
        const logStats = Admin.safeGetElement("log-stats");
        const aggregationLabel = Admin.getPerformanceAggregationLabel();

        // Update table headers for performance metrics
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Time
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Component
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Operation
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Avg Duration
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Requests
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        Error Rate
                    </th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        P99 Duration
                    </th>
                </tr>
            `;
        }

        logCount.textContent = `${metrics.length} metrics`;
        logStats.innerHTML = `
            <span class="text-sm text-green-600 dark:text-green-400">
                ⚡ Performance Metrics (${aggregationLabel})
            </span>
        `;

        if (metrics.length === 0) {
            tbody.innerHTML = `
                <tr><td colspan="7" class="px-4 py-8 text-center text-gray-500 dark:text-gray-400">
                    📊 No performance metrics available for ${aggregationLabel.toLowerCase()}
                </td></tr>
            `;
            return;
        }

        tbody.innerHTML = metrics
            .map((metric) => {
                const errorRatePercent = (metric.error_rate * 100).toFixed(2);
                const errorClass =
                    metric.error_rate > 0.1 ? "text-red-600" : "text-green-600";

                return `
                <tr class="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        ${formatTimestamp(metric.window_start)}
                    </td>
                    <td class="px-4 py-3 text-sm font-semibold text-gray-900 dark:text-gray-300">
                        ${escapeHtml(metric.component || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${escapeHtml(metric.operation_type || "-")}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-900 dark:text-gray-300">
                        <div class="text-xs">
                            <div>Avg: <strong>${metric.avg_duration_ms.toFixed(2)}ms</strong></div>
                            <div class="text-gray-500">P95: ${metric.p95_duration_ms.toFixed(2)}ms</div>
                        </div>
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                        ${metric.request_count.toLocaleString()} requests
                    </td>
                    <td class="px-4 py-3 text-sm ${errorClass}">
                        ${errorRatePercent}%
                        ${metric.error_rate > 0.1 ? "⚠️" : ""}
                    </td>
                    <td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                        <div class="text-xs">
                            P99: ${metric.p99_duration_ms.toFixed(2)}ms
                        </div>
                    </td>
                </tr>
            `;
            })
            .join("");
    }

    /**
    * Navigate to previous log page
    */
    Admin.previousLogPage = function () {
        if (currentLogPage > 0) {
            currentLogPage--;
            Admin.searchStructuredLogs();
        }
    }

    /**
    * Navigate to next log page
    */
    Admin.nextLogPage = function () {
        currentLogPage++;
        Admin.searchStructuredLogs();
    }

    /**
    * Get root path for API calls
    */
    Admin.getRootPath = function () {
        return window.ROOT_PATH || "";
    }

    /**
    * Show toast notification
    */
    Admin.showToast = function (message, type = "info") {
        // Check if showMessage function exists (from existing admin.js)
        if (typeof showMessage === "function") {
            // eslint-disable-next-line no-undef
            Admin.showMessage(message, type === "error" ? "danger" : type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    // ===================================================================
    // LLM SETTINGS FUNCTIONS
    // ===================================================================

    /**
    * Switch between LLM Settings tabs (providers/models)
    */
    Admin.switchLLMSettingsTab = function (tabName) {
        // Hide all content panels
        const panels = document.querySelectorAll(".llm-settings-content");
        panels.forEach((panel) => panel.classList.add("hidden"));

        // Remove active state from all tabs
        const tabs = document.querySelectorAll(".llm-settings-tab");
        tabs.forEach((tab) => {
            tab.classList.remove(
                "border-indigo-500",
                "text-indigo-600",
                "dark:text-indigo-400",
            );
            tab.classList.add(
                "border-transparent",
                "text-gray-500",
                "hover:text-gray-700",
                "hover:border-gray-300",
                "dark:text-gray-400",
                "dark:hover:text-gray-300",
            );
        });

        // Show selected panel
        const selectedPanel = Admin.safeGetElement(
            `llm-settings-content-${tabName}`,
        );
        if (selectedPanel) {
            selectedPanel.classList.remove("hidden");
            // Trigger HTMX load if not yet loaded
            htmx.trigger(selectedPanel, "revealed");
        }

        // Activate selected tab
        const selectedTab = Admin.safeGetElement(`llm-settings-tab-${tabName}`);
        if (selectedTab) {
            selectedTab.classList.remove(
                "border-transparent",
                "text-gray-500",
                "hover:text-gray-700",
                "hover:border-gray-300",
                "dark:text-gray-400",
                "dark:hover:text-gray-300",
            );
            selectedTab.classList.add(
                "border-indigo-500",
                "text-indigo-600",
                "dark:text-indigo-400",
            );
        }
    }

    // Cache for provider defaults
    let llmProviderDefaults = null;

    /**
    * Load provider defaults from the server
    */
    Admin.loadLLMProviderDefaults = async function () {
        if (llmProviderDefaults) {
            return llmProviderDefaults;
        }
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/provider-defaults`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );
            if (response.ok) {
                llmProviderDefaults = await response.json();
            }
        } catch (error) {
            console.error("Failed to load provider defaults:", error);
        }
        return llmProviderDefaults || {};
    }

    // Track previous provider type for smart auto-fill
    let previousProviderType = null;

    /**
    * Handle provider type change - auto-fill defaults
    */
    Admin.onLLMProviderTypeChange = async function () {
        const providerType = Admin.safeGetElement("llm-provider-type").value;
        if (!providerType) {
            // Hide provider-specific config section
            const configSection = Admin.safeGetElement(
                "llm-provider-specific-config",
            );
            if (configSection) {
                configSection.classList.add("hidden");
            }
            return;
        }

        const defaults = await Admin.loadLLMProviderDefaults();
        const config = defaults[providerType];

        if (!config) {
            return;
        }

        // Only auto-fill if creating new provider (not editing)
        const providerId = Admin.safeGetElement("llm-provider-id").value;
        const isEditing = providerId !== "";

        const apiBaseField = Admin.safeGetElement("llm-provider-api-base");
        const defaultModelField = Admin.safeGetElement(
            "llm-provider-default-model",
        );

        if (!isEditing) {
            // Check if current values match previous provider's defaults
            const previousConfig = previousProviderType
                ? defaults[previousProviderType]
                : null;
            const apiBaseMatchesPrevious =
                previousConfig &&
                (apiBaseField.value === previousConfig.api_base ||
                    apiBaseField.value === "");
            const modelMatchesPrevious =
                previousConfig &&
                (defaultModelField.value === previousConfig.default_model ||
                    defaultModelField.value === "");

            // Auto-fill API base if empty or matches previous provider's default
            if (
                (apiBaseMatchesPrevious || !apiBaseField.value) &&
                config.api_base
            ) {
                apiBaseField.value = config.api_base;
            }

            // Auto-fill default model if empty or matches previous provider's default
            if (
                (modelMatchesPrevious || !defaultModelField.value) &&
                config.default_model
            ) {
                defaultModelField.value = config.default_model;
            }

            // Remember this provider type for next change
            previousProviderType = providerType;
        }

        // Update description/help text
        const descEl = Admin.safeGetElement("llm-provider-type-description");
        if (descEl && config.description) {
            descEl.textContent = config.description;
            descEl.classList.remove("hidden");
        }

        // Show/hide API key requirement indicator
        const apiKeyRequired = Admin.safeGetElement(
            "llm-provider-api-key-required",
        );
        if (apiKeyRequired) {
            if (config.requires_api_key) {
                apiKeyRequired.classList.remove("hidden");
            } else {
                apiKeyRequired.classList.add("hidden");
            }
        }

        // Load and render provider-specific configuration fields
        await Admin.renderProviderSpecificFields(providerType, isEditing);
    }

    /**
    * Render provider-specific configuration fields dynamically
    */
    Admin.renderProviderSpecificFields = async function (providerType, isEditing = false) {
        try {
            // Fetch provider configurations
            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/provider-configs`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                console.error("Failed to fetch provider configs");
                return;
            }

            const providerConfigs = await response.json();
            const providerConfig = providerConfigs[providerType];

            if (
                !providerConfig ||
                !providerConfig.config_fields ||
                providerConfig.config_fields.length === 0
            ) {
                // No provider-specific fields, hide the section
                const configSection = Admin.safeGetElement(
                    "llm-provider-specific-config",
                );
                if (configSection) {
                    configSection.classList.add("hidden");
                }
                return;
            }

            // Show the provider-specific config section
            const configSection = Admin.safeGetElement(
                "llm-provider-specific-config",
            );
            const fieldsContainer = Admin.safeGetElement(
                "llm-provider-config-fields",
            );

            if (!configSection || !fieldsContainer) {
                return;
            }

            configSection.classList.remove("hidden");
            fieldsContainer.innerHTML = ""; // Clear existing fields

            // Render each field
            for (const fieldDef of providerConfig.config_fields) {
                const fieldDiv = document.createElement("div");

                const label = document.createElement("label");
                label.setAttribute("for", `llm-config-${fieldDef.name}`);
                label.className =
                    "block text-sm font-medium text-gray-700 dark:text-gray-300";
                label.textContent = fieldDef.label;
                if (fieldDef.required) {
                    const requiredSpan = document.createElement("span");
                    requiredSpan.className = "text-red-500 ml-1";
                    requiredSpan.textContent = "*";
                    label.appendChild(requiredSpan);
                }
                fieldDiv.appendChild(label);

                let inputElement;

                if (fieldDef.field_type === "select") {
                    inputElement = document.createElement("select");
                    inputElement.className =
                        "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";

                    // Add empty option
                    const emptyOption = document.createElement("option");
                    emptyOption.value = "";
                    emptyOption.textContent = "Select...";
                    inputElement.appendChild(emptyOption);

                    // Add options
                    if (fieldDef.options) {
                        for (const opt of fieldDef.options) {
                            const option = document.createElement("option");
                            option.value = opt.value;
                            option.textContent = opt.label;
                            inputElement.appendChild(option);
                        }
                    }
                } else if (fieldDef.field_type === "textarea") {
                    inputElement = document.createElement("textarea");
                    inputElement.className =
                        "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";
                    inputElement.rows = 3;
                } else {
                    inputElement = document.createElement("input");
                    inputElement.type = fieldDef.field_type;
                    inputElement.className =
                        "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white sm:text-sm";

                    if (fieldDef.field_type === "number") {
                        if (
                            fieldDef.min_value !== null &&
                            fieldDef.min_value !== undefined
                        ) {
                            inputElement.min = fieldDef.min_value;
                        }
                        if (
                            fieldDef.max_value !== null &&
                            fieldDef.max_value !== undefined
                        ) {
                            inputElement.max = fieldDef.max_value;
                        }
                    }
                }

                inputElement.id = `llm-config-${fieldDef.name}`;
                inputElement.name = `config_${fieldDef.name}`;

                if (fieldDef.required) {
                    inputElement.required = true;
                }

                if (fieldDef.placeholder) {
                    inputElement.placeholder = fieldDef.placeholder;
                }

                if (fieldDef.default_value && !isEditing) {
                    inputElement.value = fieldDef.default_value;
                }

                fieldDiv.appendChild(inputElement);

                // Add help text if available
                if (fieldDef.help_text) {
                    const helpText = document.createElement("p");
                    helpText.className =
                        "mt-1 text-xs text-gray-500 dark:text-gray-400";
                    helpText.textContent = fieldDef.help_text;
                    fieldDiv.appendChild(helpText);
                }

                fieldsContainer.appendChild(fieldDiv);
            }
        } catch (error) {
            console.error("Error rendering provider-specific fields:", error);
        }
    }

    /**
    * Show Add Provider Modal
    */
    Admin.showAddProviderModal = async function () {
        Admin.safeGetElement("llm-provider-id").value = "";
        Admin.safeGetElement("llm-provider-form").reset();
        Admin.safeGetElement("llm-provider-modal-title").textContent =
            "Add LLM Provider";

        // Reset helper elements
        const descEl = Admin.safeGetElement("llm-provider-type-description");
        if (descEl) {
            descEl.classList.add("hidden");
        }

        // Reset provider type tracker for smart auto-fill
        previousProviderType = null;

        // Load defaults for quick access
        await Admin.loadLLMProviderDefaults();

        Admin.safeGetElement("llm-provider-modal").classList.remove("hidden");
    }

    /**
    * Close Provider Modal
    */
    Admin.closeLLMProviderModal = function () {
        Admin.safeGetElement("llm-provider-modal").classList.add("hidden");
    }

    /**
    * Fetch models from a provider's API
    */
    Admin.fetchLLMProviderModels = async function (providerId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/providers/${providerId}/fetch-models`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            const result = await response.json();

            if (result.success) {
                const modelList = result.models
                    .map((m) => `- ${m.id} (${m.owned_by || "unknown"})`)
                    .join("\n");
                Admin.showCopyableModal(
                    `Found ${result.count} Models`,
                    modelList || "No models found",
                    "success",
                );
            } else {
                Admin.showCopyableModal("Failed to Fetch Models", result.error, "error");
            }

            return result;
        } catch (error) {
            console.error("Error fetching models:", error);
            Admin.showCopyableModal(
                "Failed to Fetch Models",
                `Error: ${error.message}`,
                "error",
            );
            return { success: false, error: error.message, models: [] };
        }
    }

    /**
    * Sync models from provider API to database
    */
    Admin.syncLLMProviderModels = async function (providerId) {
        try {
            Admin.showToast("Syncing models...", "info");

            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/providers/${providerId}/sync-models`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            const result = await response.json();

            if (result.success) {
                Admin.showCopyableModal(
                    "Models Synced Successfully",
                    `${result.message}\n\nTotal available: ${result.total || 0}`,
                    "success",
                );
                // Refresh the models list
                Admin.refreshLLMModels();
            } else {
                Admin.showCopyableModal("Failed to Sync Models", result.error, "error");
            }

            return result;
        } catch (error) {
            console.error("Error syncing models:", error);
            Admin.showCopyableModal(
                "Failed to Sync Models",
                `Error: ${error.message}`,
                "error",
            );
            return { success: false, error: error.message };
        }
    }

    /**
    * Edit LLM Provider
    */
    Admin.editLLMProvider = async function (providerId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/providers/${providerId}`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );
            if (!response.ok) {
                throw new Error("Failed to fetch provider details");
            }
            const provider = await response.json();

            Admin.safeGetElement("llm-provider-id").value = provider.id;
            Admin.safeGetElement("llm-provider-name").value = provider.name;
            Admin.safeGetElement("llm-provider-type").value =
                provider.provider_type;
            Admin.safeGetElement("llm-provider-description").value =
                provider.description || "";
            Admin.safeGetElement("llm-provider-api-key").value = "";
            Admin.safeGetElement("llm-provider-api-base").value =
                provider.api_base || "";
            Admin.safeGetElement("llm-provider-default-model").value =
                provider.default_model || "";
            Admin.safeGetElement("llm-provider-temperature").value =
                provider.default_temperature || 0.7;
            Admin.safeGetElement("llm-provider-max-tokens").value =
                provider.default_max_tokens || "";
            Admin.safeGetElement("llm-provider-enabled").checked =
                provider.enabled;

            // Render provider-specific fields and populate with existing config
            await Admin.renderProviderSpecificFields(provider.provider_type, true);

            // Populate provider-specific config values
            if (provider.config) {
                for (const [key, value] of Object.entries(provider.config)) {
                    const input = Admin.safeGetElement(`llm-config-${key}`);
                    if (input) {
                        if (input.type === "checkbox") {
                            input.checked = value;
                        } else {
                            input.value = value || "";
                        }
                    }
                }
            }

            Admin.safeGetElement("llm-provider-modal-title").textContent =
                "Edit LLM Provider";
            document
                .getElementById("llm-provider-modal")
                .classList.remove("hidden");
        } catch (error) {
            console.error("Error fetching provider:", error);
            Admin.showToast("Failed to load provider details", "error");
        }
    }

    /**
    * Save LLM Provider (create or update)
    */
    Admin.saveLLMProvider = async function (event) {
        event.preventDefault();

        const providerId = Admin.safeGetElement("llm-provider-id").value;
        const isUpdate = providerId !== "";

        const formData = {
            name: Admin.safeGetElement("llm-provider-name").value,
            provider_type: Admin.safeGetElement("llm-provider-type").value,
            description:
                Admin.safeGetElement("llm-provider-description").value || null,
            api_base:
                Admin.safeGetElement("llm-provider-api-base").value || null,
            default_model:
                Admin.safeGetElement("llm-provider-default-model").value || null,
            default_temperature: parseFloat(
                Admin.safeGetElement("llm-provider-temperature").value,
            ),
            enabled: Admin.safeGetElement("llm-provider-enabled").checked,
            config: {},
        };

        const apiKey = Admin.safeGetElement("llm-provider-api-key").value;
        if (apiKey) {
            formData.api_key = apiKey;
        }

        const maxTokens = Admin.safeGetElement("llm-provider-max-tokens").value;
        if (maxTokens) {
            formData.default_max_tokens = parseInt(maxTokens, 10);
        }

        // Collect provider-specific configuration fields
        const configFieldsContainer = Admin.safeGetElement(
            "llm-provider-config-fields",
        );
        if (configFieldsContainer) {
            const configInputs = configFieldsContainer.querySelectorAll(
                "input, select, textarea",
            );
            for (const input of configInputs) {
                if (input.name && input.name.startsWith("config_")) {
                    const fieldName = input.name.replace("config_", "");
                    let value = input.value;

                    // Convert to appropriate type
                    if (input.type === "number") {
                        value = value ? parseFloat(value) : null;
                    } else if (input.type === "checkbox") {
                        value = input.checked;
                    } else if (value === "") {
                        value = null;
                    }

                    if (value !== null && value !== "") {
                        formData.config[fieldName] = value;
                    }
                }
            }
        }

        try {
            const url = isUpdate
                ? `${window.ROOT_PATH}/llm/providers/${providerId}`
                : `${window.ROOT_PATH}/llm/providers`;
            const method = isUpdate ? "PATCH" : "POST";

            const response = await fetch(url, {
                method,
                headers: {
                    Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(formData),
            });

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    "Failed to save provider",
                );
                throw new Error(errorMsg);
            }

            Admin.closeLLMProviderModal();
            Admin.showToast(
                isUpdate
                    ? "Provider updated successfully"
                    : "Provider created successfully",
                "success",
            );
            Admin.refreshLLMProviders();
        } catch (error) {
            console.error("Error saving provider:", error);
            Admin.showToast(error.message || "Failed to save provider", "error");
        }
    }

    /**
    * Delete LLM Provider
    */
    Admin.deleteLLMProvider = async function (providerId, providerName) {
        if (
            !confirm(
                `Are you sure you want to delete the provider "${providerName}"? This will also delete all associated models.`,
            )
        ) {
            return;
        }

        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/providers/${providerId}`,
                {
                    method: "DELETE",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    "Failed to delete provider",
                );
                throw new Error(errorMsg);
            }

            Admin.showToast("Provider deleted successfully", "success");
            Admin.refreshLLMProviders();
        } catch (error) {
            console.error("Error deleting provider:", error);
            Admin.showToast(error.message || "Failed to delete provider", "error");
        }
    }

    /**
    * Toggle LLM Provider enabled state
    */
    Admin.toggleLLMProvider = async function (providerId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/providers/${providerId}/state`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                throw new Error("Failed to toggle provider");
            }

            Admin.refreshLLMProviders();
        } catch (error) {
            console.error("Error toggling provider:", error);
            Admin.showToast("Failed to toggle provider", "error");
        }
    }

    /**
    * Check LLM Provider health
    */
    Admin.checkLLMProviderHealth = async function (providerId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/providers/${providerId}/health`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            const result = await response.json();

            // Show result message with details using copyable modal
            if (result.status === "healthy") {
                const message = `Status: ${result.status}\nLatency: ${result.latency_ms}ms`;
                Admin.showCopyableModal("Health Check Passed", message, "success");
            } else {
                // Show error details for unhealthy status
                let message = `Status: ${result.status}`;
                if (result.latency_ms) {
                    message += `\nLatency: ${result.latency_ms}ms`;
                }
                if (result.error) {
                    message += `\n\nError:\n${result.error}`;
                }
                Admin.showCopyableModal("Health Check Failed", message, "error");
            }

            // Refresh providers to update status
            Admin.refreshLLMProviders();
        } catch (error) {
            console.error("Error checking provider health:", error);
            Admin.showCopyableModal(
                "Health Check Request Failed",
                `Error: ${error.message}`,
                "error",
            );
        }
    }

    /**
    * Refresh LLM Providers list
    */
    Admin.refreshLLMProviders = function () {
        const container = Admin.safeGetElement("llm-providers-container");
        if (container) {
            htmx.ajax("GET", `${window.ROOT_PATH}/admin/llm/providers/html`, {
                target: "#llm-providers-container",
                swap: "innerHTML",
            });
        }
    }

    /**
    * Show Add Model Modal
    */
    Admin.showAddModelModal = async function () {
        Admin.safeGetElement("llm-model-id").value = "";
        Admin.safeGetElement("llm-model-form").reset();
        Admin.safeGetElement("llm-model-modal-title").textContent =
            "Add LLM Model";

        // Populate providers dropdown
        await Admin.populateProviderDropdown();

        Admin.safeGetElement("llm-model-modal").classList.remove("hidden");
    }

    /**
    * Populate provider dropdown in model modal
    */
    Admin.populateProviderDropdown = async function () {
        try {
            const response = await fetch(`${window.ROOT_PATH}/llm/providers`, {
                headers: {
                    Authorization: `Bearer ${await Admin.getAuthToken()}`,
                },
            });
            if (!response.ok) {
                throw new Error("Failed to fetch providers");
            }
            const data = await response.json();

            const select = Admin.safeGetElement("llm-model-provider");
            select.innerHTML = '<option value="">Select provider</option>';

            data.providers.forEach((provider) => {
                const option = document.createElement("option");
                option.value = provider.id;
                option.textContent = `${provider.name} (${provider.provider_type})`;
                select.appendChild(option);
            });
        } catch (error) {
            console.error("Error fetching providers:", error);
        }
    }

    /**
    * Close Model Modal
    */
    Admin.closeLLMModelModal = function () {
        Admin.safeGetElement("llm-model-modal").classList.add("hidden");
    }

    /**
    * Handle provider change in model modal - auto-fetch models
    */
    Admin.onModelProviderChange = async function () {
        const providerId = Admin.safeGetElement("llm-model-provider").value;
        const modelInput = Admin.safeGetElement("llm-model-model-id");
        const datalist = Admin.safeGetElement("llm-model-suggestions");
        const statusEl = Admin.safeGetElement("llm-model-fetch-status");

        // Clear existing suggestions
        datalist.innerHTML = "";

        if (!providerId) {
            modelInput.placeholder = "Select provider first...";
            statusEl.classList.add("hidden");
            return;
        }

        modelInput.placeholder = "Type or select a model...";

        // Auto-fetch models when provider is selected
        await Admin.fetchModelsForModelModal();
    }

    /**
    * Fetch available models for the model modal
    */
    Admin.fetchModelsForModelModal = async function () {
        const providerId = Admin.safeGetElement("llm-model-provider").value;
        const datalist = Admin.safeGetElement("llm-model-suggestions");
        const statusEl = Admin.safeGetElement("llm-model-fetch-status");

        if (!providerId) {
            Admin.showToast("Please select a provider first", "warning");
            return;
        }

        statusEl.textContent = "Fetching models...";
        statusEl.classList.remove("hidden");

        try {
            const response = await fetch(
                `${window.ROOT_PATH}/admin/llm/providers/${providerId}/fetch-models`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            const result = await response.json();

            if (result.success && result.models && result.models.length > 0) {
                // Populate datalist with model suggestions
                datalist.innerHTML = "";
                result.models.forEach((model) => {
                    const option = document.createElement("option");
                    option.value = model.id;
                    option.textContent = model.name || model.id;
                    datalist.appendChild(option);
                });

                statusEl.textContent = `Found ${result.models.length} models. Type to filter or enter custom.`;
                statusEl.classList.remove("hidden");
            } else {
                statusEl.textContent =
                    result.error || "No models found. Enter model ID manually.";
                statusEl.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Error fetching models:", error);
            statusEl.textContent =
                "Failed to fetch models. Enter model ID manually.";
            statusEl.classList.remove("hidden");
        }
    }

    /**
    * Edit LLM Model
    */
    Admin.editLLMModel = async function (modelId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/models/${modelId}`,
                {
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );
            if (!response.ok) {
                throw new Error("Failed to fetch model details");
            }
            const model = await response.json();

            await Admin.populateProviderDropdown();

            Admin.safeGetElement("llm-model-id").value = model.id;
            Admin.safeGetElement("llm-model-provider").value = model.provider_id;
            Admin.safeGetElement("llm-model-model-id").value = model.model_id;
            Admin.safeGetElement("llm-model-name").value = model.model_name;
            Admin.safeGetElement("llm-model-alias").value =
                model.model_alias || "";
            Admin.safeGetElement("llm-model-description").value =
                model.description || "";
            Admin.safeGetElement("llm-model-context-window").value =
                model.context_window || "";
            Admin.safeGetElement("llm-model-max-output").value =
                model.max_output_tokens || "";
            Admin.safeGetElement("llm-model-supports-chat").checked =
                model.supports_chat;
            Admin.safeGetElement("llm-model-supports-streaming").checked =
                model.supports_streaming;
            Admin.safeGetElement("llm-model-supports-functions").checked =
                model.supports_function_calling;
            Admin.safeGetElement("llm-model-supports-vision").checked =
                model.supports_vision;
            Admin.safeGetElement("llm-model-enabled").checked = model.enabled;
            Admin.safeGetElement("llm-model-deprecated").checked =
                model.deprecated;

            Admin.safeGetElement("llm-model-modal-title").textContent =
                "Edit LLM Model";
            Admin.safeGetElement("llm-model-modal").classList.remove("hidden");
        } catch (error) {
            console.error("Error fetching model:", error);
            Admin.showToast("Failed to load model details", "error");
        }
    }

    /**
    * Save LLM Model (create or update)
    */
    Admin.saveLLMModel = async function (event) {
        event.preventDefault();

        const modelId = Admin.safeGetElement("llm-model-id").value;
        const isUpdate = modelId !== "";

        const formData = {
            provider_id: Admin.safeGetElement("llm-model-provider").value,
            model_id: Admin.safeGetElement("llm-model-model-id").value,
            model_name: Admin.safeGetElement("llm-model-name").value,
            model_alias: Admin.safeGetElement("llm-model-alias").value || null,
            description:
                Admin.safeGetElement("llm-model-description").value || null,
            supports_chat: Admin.safeGetElement("llm-model-supports-chat")
                .checked,
            supports_streaming: Admin.safeGetElement(
                "llm-model-supports-streaming",
            ).checked,
            supports_function_calling: Admin.safeGetElement(
                "llm-model-supports-functions",
            ).checked,
            supports_vision: Admin.safeGetElement("llm-model-supports-vision")
                .checked,
            enabled: Admin.safeGetElement("llm-model-enabled").checked,
            deprecated: Admin.safeGetElement("llm-model-deprecated").checked,
        };

        const contextWindow = Admin.safeGetElement(
            "llm-model-context-window",
        ).value;
        if (contextWindow) {
            formData.context_window = parseInt(contextWindow, 10);
        }

        const maxOutput = Admin.safeGetElement("llm-model-max-output").value;
        if (maxOutput) {
            formData.max_output_tokens = parseInt(maxOutput, 10);
        }

        try {
            const url = isUpdate
                ? `${window.ROOT_PATH}/llm/models/${modelId}`
                : `${window.ROOT_PATH}/llm/models`;
            const method = isUpdate ? "PATCH" : "POST";

            const response = await fetch(url, {
                method,
                headers: {
                    Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(formData),
            });

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    "Failed to save model",
                );
                throw new Error(errorMsg);
            }

            Admin.closeLLMModelModal();
            Admin.showToast(
                isUpdate
                    ? "Model updated successfully"
                    : "Model created successfully",
                "success",
            );
            Admin.refreshLLMModels();
        } catch (error) {
            console.error("Error saving model:", error);
            Admin.showToast(error.message || "Failed to save model", "error");
        }
    }

    /**
    * Delete LLM Model
    */
    Admin.deleteLLMModel = async function (modelId, modelName) {
        if (!confirm(`Are you sure you want to delete the model "${modelName}"?`)) {
            return;
        }

        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/models/${modelId}`,
                {
                    method: "DELETE",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                const errorMsg = await Admin.parseErrorResponse(
                    response,
                    "Failed to delete model",
                );
                throw new Error(errorMsg);
            }

            Admin.showToast("Model deleted successfully", "success");
            Admin.refreshLLMModels();
        } catch (error) {
            console.error("Error deleting model:", error);
            Admin.showToast(error.message || "Failed to delete model", "error");
        }
    }

    /**
    * Toggle LLM Model enabled state
    */
    Admin.toggleLLMModel = async function (modelId) {
        try {
            const response = await fetch(
                `${window.ROOT_PATH}/llm/models/${modelId}/state`,
                {
                    method: "POST",
                    headers: {
                        Authorization: `Bearer ${await Admin.getAuthToken()}`,
                    },
                },
            );

            if (!response.ok) {
                throw new Error("Failed to toggle model");
            }

            Admin.refreshLLMModels();
        } catch (error) {
            console.error("Error toggling model:", error);
            Admin.showToast("Failed to toggle model", "error");
        }
    }

    /**
    * Refresh LLM Models list
    */
    Admin.refreshLLMModels = function () {
        const container = Admin.safeGetElement("llm-models-container");
        if (container) {
            htmx.ajax("GET", `${window.ROOT_PATH}/admin/llm/models/html`, {
                target: "#llm-models-container",
                swap: "innerHTML",
            });
        }
    }

    /**
    * Filter models by provider
    */
    Admin.filterModelsByProvider = function (providerId) {
        const url = providerId
            ? `${window.ROOT_PATH}/admin/llm/models/html?provider_id=${providerId}`
            : `${window.ROOT_PATH}/admin/llm/models/html`;

        htmx.ajax("GET", url, {
            target: "#llm-models-container",
            swap: "innerHTML",
        });
    }

    /**
    * Alpine.js component for LLM API Info & Test
    */
    Admin.llmApiInfoApp = function () {
        return {
            testType: "models",
            testModel: "",
            testMessage: "Hello! Please respond with a short greeting.",
            testing: false,
            testResult: null,
            testSuccess: false,
            testMetrics: null,
            assistantMessage: null,
            modelList: null,

            formatDuration(ms) {
                if (ms < 1000) {
                    return `${ms}ms`;
                }
                return `${(ms / 1000).toFixed(2)}s`;
            },

            formatBytes(bytes) {
                if (bytes === 0) {
                    return "0 B";
                }
                if (bytes < 1024) {
                    return `${bytes} B`;
                } else if (bytes < 1024 * 1024) {
                    return `${(bytes / 1024).toFixed(2)} KB`;
                } else {
                    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
                }
            },

            async runTest() {
                // Use admin test endpoint directly
                this.testing = true;
                this.testResult = null;
                this.testSuccess = false;
                this.testMetrics = null;
                this.assistantMessage = null;
                this.modelList = null;

                try {
                    const requestBody = {
                        test_type: this.testType,
                    };

                    if (this.testType === "chat") {
                        if (!this.testModel) {
                            this.testResult = JSON.stringify(
                                { error: "Please select a model" },
                                null,
                                2,
                            );
                            this.testSuccess = false;
                            this.testMetrics = {
                                httpStatus: 400,
                                httpStatusText: "Bad Request",
                            };
                            return;
                        }
                        requestBody.model_id = this.testModel;
                        requestBody.message = this.testMessage;
                        requestBody.max_tokens = 100;
                    }

                    const requestBodyStr = JSON.stringify(requestBody);
                    const startTime = performance.now();

                    const response = await fetch(
                        `${window.ROOT_PATH}/admin/llm/test`,
                        {
                            method: "POST",
                            headers: {
                                Authorization: `Bearer ${await Admin.getAuthToken()}`,
                                "Content-Type": "application/json",
                            },
                            body: requestBodyStr,
                        },
                    );

                    const endTime = performance.now();
                    const data = await response.json();

                    this.testSuccess = data.success === true;
                    this.testResult = JSON.stringify(data, null, 2);

                    // Build metrics
                    this.testMetrics = {
                        duration:
                            data.metrics?.duration ||
                            Math.round(endTime - startTime),
                        httpStatus: response.status,
                        httpStatusText: response.statusText,
                        requestSize: requestBodyStr.length,
                        responseSize: JSON.stringify(data).length,
                    };

                    if (this.testType === "chat" && data.metrics) {
                        this.testMetrics.promptTokens =
                            data.metrics.promptTokens || 0;
                        this.testMetrics.completionTokens =
                            data.metrics.completionTokens || 0;
                        this.testMetrics.totalTokens =
                            data.metrics.totalTokens || 0;
                        this.testMetrics.responseModel = data.metrics.responseModel;
                        this.assistantMessage = data.assistant_message;
                    }

                    if (this.testType === "models" && data.metrics) {
                        this.testMetrics.modelCount = data.metrics.modelCount;
                        this.modelList = data.data?.data || [];
                    }
                } catch (error) {
                    this.testResult = JSON.stringify(
                        { error: error.message },
                        null,
                        2,
                    );
                    this.testSuccess = false;
                    this.testMetrics = {
                        httpStatus: 0,
                        httpStatusText: "Network Error",
                    };
                } finally {
                    this.testing = false;
                }
            },
        };
    }

    Admin.overviewDashboard = function () {
        return {
            init() {
                this.updateSvgColors();
                const observer = new MutationObserver(() => this.updateSvgColors());
                observer.observe(document.documentElement, {
                    attributes: true,
                    attributeFilter: ["class"],
                });
            },
            updateSvgColors() {
                const isDark = document.documentElement.classList.contains("dark");
                const svg = Admin.safeGetElement("overview-architecture");
                if (!svg) {
                    return;
                }

                const marker = svg.querySelector("#arrowhead polygon");
                if (marker) {
                    marker.setAttribute(
                        "class",
                        isDark ? "fill-gray-500" : "fill-gray-400",
                    );
                }
            },
        };
    };

    // Debounce helper for search
    const searchDebounceTimers = {};
    Admin.debouncedServerSideUserSearch = function (teamId, searchTerm, delay = 300) {
        if (searchDebounceTimers[teamId]) {
            clearTimeout(searchDebounceTimers[teamId]);
        }
        searchDebounceTimers[teamId] = setTimeout(() => {
            Admin.serverSideUserSearch(teamId, searchTerm);
        }, delay);
    }

    // Team user search function - searches all users and splits into members/non-members
    Admin.serverSideUserSearch = async function (teamId, searchTerm) {
        const membersContainer = Admin.safeGetElement(
            `team-members-container-${teamId}`,
        );
        const nonMembersContainer = Admin.safeGetElement(
            `team-non-members-container-${teamId}`,
        );

        if (!membersContainer || !nonMembersContainer) {
            console.error("Team containers not found");
            return;
        }

        // Read per_page from data attributes (set server-side), fallback to 20
        const membersPerPage =
            membersContainer.dataset.perPage ||
            membersContainer.getAttribute("data-per-page") ||
            20;
        const nonMembersPerPage =
            nonMembersContainer.dataset.perPage ||
            nonMembersContainer.getAttribute("data-per-page") ||
            20;

        // If search is empty, reload both sections with full data
        if (!searchTerm || searchTerm.trim() === "") {
            try {
                // Reload members - use fetchWithAuth for bearer token support
                const membersResponse = await Admin.fetchWithAuth(
                    `${window.ROOT_PATH}/admin/teams/${teamId}/members/partial?page=1&per_page=${membersPerPage}`,
                );
                if (membersResponse.ok) {
                    membersContainer.innerHTML = await membersResponse.text();
                    // Re-initialize HTMX on new content for infinite scroll triggers
                    if (typeof htmx !== "undefined") {
                        htmx.process(membersContainer);
                    }
                }

                // Reload non-members
                const nonMembersResponse = await Admin.fetchWithAuth(
                    `${window.ROOT_PATH}/admin/teams/${teamId}/non-members/partial?page=1&per_page=${nonMembersPerPage}`,
                );
                if (nonMembersResponse.ok) {
                    nonMembersContainer.innerHTML = await nonMembersResponse.text();
                    // Re-initialize HTMX on new content for infinite scroll triggers
                    if (typeof htmx !== "undefined") {
                        htmx.process(nonMembersContainer);
                    }
                }
            } catch (error) {
                console.error("Error reloading user lists:", error);
            }
            return;
        }

        try {
            // First, collect member data AND checkbox states from DOM (before search replaces content)
            const memberDataFromDom = {};
            const checkboxStates = {}; // Track checkbox states for all visible users
            const existingMemberItems = document.querySelectorAll(
                `#team-members-container-${teamId} .user-item`,
            );
            existingMemberItems.forEach((item) => {
                const email = item.dataset.userEmail;
                if (email) {
                    const roleSelect = item.querySelector(".role-select");
                    const checkbox = item.querySelector(".user-checkbox");
                    memberDataFromDom[email] = {
                        role: roleSelect ? roleSelect.value : "member",
                    };
                    if (checkbox) {
                        checkboxStates[email] = checkbox.checked;
                    }
                }
            });

            // Also collect checkbox states from non-members section
            const existingNonMemberItems = document.querySelectorAll(
                `#team-non-members-container-${teamId} .user-item`,
            );
            existingNonMemberItems.forEach((item) => {
                const email = item.dataset.userEmail;
                if (email) {
                    const checkbox = item.querySelector(".user-checkbox");
                    const roleSelect = item.querySelector(".role-select");
                    if (checkbox) {
                        checkboxStates[email] = checkbox.checked;
                        // Also preserve role selection for users being added
                        if (checkbox.checked && roleSelect) {
                            memberDataFromDom[email] = {
                                role: roleSelect.value,
                                pendingAdd: true, // Flag that this is a pending addition
                            };
                        }
                    }
                }
            });

            // If no members found in DOM yet, fetch from server to get membership data with roles
            if (Object.keys(memberDataFromDom).length === 0) {
                try {
                    const membersResp = await Admin.fetchWithAuth(
                        `${window.ROOT_PATH}/admin/teams/${teamId}/members/partial?page=1&per_page=100`,
                    );
                    if (membersResp.ok) {
                        const tempDiv = document.createElement("div");
                        tempDiv.innerHTML = await membersResp.text();
                        tempDiv.querySelectorAll(".user-item").forEach((item) => {
                            const email = item.dataset.userEmail;
                            if (email) {
                                const roleSelect =
                                    item.querySelector(".role-select");
                                memberDataFromDom[email] = {
                                    role: roleSelect ? roleSelect.value : "member",
                                };
                            }
                        });
                    }
                } catch (e) {
                    console.error("Error fetching member data:", e);
                }
            }

            // Search all users - use fetchWithAuth for bearer token support
            const searchUrl = `${window.ROOT_PATH}/admin/users/search?q=${encodeURIComponent(searchTerm)}&limit=100`;
            const response = await Admin.fetchWithAuth(searchUrl);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.users && data.users.length > 0) {
                // Split users into members and non-members based on collected data
                const members = [];
                const nonMembers = [];

                data.users.forEach((user) => {
                    if (memberDataFromDom[user.email]) {
                        members.push({
                            ...user,
                            role: memberDataFromDom[user.email].role,
                        });
                    } else {
                        nonMembers.push(user);
                    }
                });

                // Helper to escape HTML
    Admin.escapeHtml = function (text) {
                    const div = document.createElement("div");
                    div.textContent = text;
                    return div.innerHTML;
                }

                // Render members with preserved roles, checkbox states, and loadedMembers hidden input
                let membersHtml = "";
                members.forEach((user) => {
                    const fullName = Admin.escapeHtml(user.full_name || user.email);
                    const email = Admin.escapeHtml(user.email);
                    const role = user.role || "member";
                    const isOwner = role === "owner";
                    // Preserve checkbox state if available, otherwise default to checked for existing members
                    const isChecked =
                        checkboxStates[user.email] !== undefined
                            ? checkboxStates[user.email]
                            : true;
                    membersHtml += `
                        <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/20" data-user-email="${email}">
                            <div class="flex-shrink-0">
                                <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${user.email[0].toUpperCase()}</span>
                                </div>
                            </div>
                            <input type="hidden" name="loadedMembers" value="${email}" />
                            <input type="checkbox" name="associatedUsers" value="${email}" data-user-name="${fullName}" class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0" ${isChecked ? "checked" : ""} data-auto-check="true" />
                            <div class="flex-grow min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="select-none font-medium text-gray-900 dark:text-white truncate">${fullName}</span>
                                    ${isOwner ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 rounded-full dark:bg-purple-900 dark:text-purple-200">Owner</span>' : ""}
                                </div>
                                <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${email}</div>
                            </div>
                            <select name="role_${encodeURIComponent(user.email)}" class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0">
                                <option value="member" ${!isOwner ? "selected" : ""}>Member</option>
                                <option value="owner" ${isOwner ? "selected" : ""}>Owner</option>
                            </select>
                        </div>
                    `;
                });

                // Render non-members with preserved checkbox states and roles
                let nonMembersHtml = "";
                nonMembers.forEach((user) => {
                    const fullName = Admin.escapeHtml(user.full_name || user.email);
                    const email = Admin.escapeHtml(user.email);
                    // Preserve checkbox state if available, otherwise default to unchecked for non-members
                    const isChecked =
                        checkboxStates[user.email] !== undefined
                            ? checkboxStates[user.email]
                            : false;
                    // Preserve role selection for users being added
                    const pendingData = memberDataFromDom[user.email];
                    const role =
                        pendingData && pendingData.pendingAdd
                            ? pendingData.role
                            : "member";
                    const isOwner = role === "owner";
                    nonMembersHtml += `
                        <div class="flex items-center space-x-3 text-gray-700 dark:text-gray-300 mb-2 p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900 rounded-md user-item border border-transparent" data-user-email="${email}" data-is-member="false">
                            <div class="flex-shrink-0">
                                <div class="w-8 h-8 bg-gray-300 dark:bg-gray-600 rounded-full flex items-center justify-center">
                                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${user.email[0].toUpperCase()}</span>
                                </div>
                            </div>
                            <input type="checkbox" name="associatedUsers" value="${email}" data-user-name="${fullName}" class="user-checkbox form-checkbox h-5 w-5 text-indigo-600 dark:bg-gray-800 dark:border-gray-600 flex-shrink-0" ${isChecked ? "checked" : ""} />
                            <div class="flex-grow min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="select-none font-medium text-gray-900 dark:text-white truncate">${fullName}</span>
                                </div>
                                <div class="text-sm text-gray-500 dark:text-gray-400 truncate">${email}</div>
                            </div>
                            <select name="role_${encodeURIComponent(user.email)}" class="role-select text-sm px-2 py-1 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white flex-shrink-0">
                                <option value="member" ${!isOwner ? "selected" : ""}>Member</option>
                                <option value="owner" ${isOwner ? "selected" : ""}>Owner</option>
                            </select>
                        </div>
                    `;
                });

                membersContainer.innerHTML =
                    membersHtml ||
                    '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching members</div>';
                nonMembersContainer.innerHTML =
                    nonMembersHtml ||
                    '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching users</div>';
            } else {
                // No results
                membersContainer.innerHTML =
                    '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching members</div>';
                nonMembersContainer.innerHTML =
                    '<div class="text-center py-4 text-gray-500 dark:text-gray-400">No matching users</div>';
            }
        } catch (error) {
            console.error("Error searching users:", error);
            membersContainer.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching users</div>';
            nonMembersContainer.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching users</div>';
        }
    }

    // ============================================================================ //
    //                         TEAM SEARCH AND FILTER FUNCTIONS                      //
    // ============================================================================ //

    /**
    * Debounce timer for team search
    */
    let teamSearchDebounceTimer = null;

    /**
    * Current relationship filter state
    */
    let currentTeamRelationshipFilter = "all";

    /**
    * Perform server-side search for teams and update the teams list
    * @param {string} searchTerm - The search query
    */
    Admin.serverSideTeamSearch = function (searchTerm) {
        // Debounce the search to avoid excessive API calls
        if (teamSearchDebounceTimer) {
            clearTimeout(teamSearchDebounceTimer);
        }

        teamSearchDebounceTimer = setTimeout(() => {
            Admin.performTeamSearch(searchTerm);
        }, 300);
    }

    /**
    * Default per_page for teams list
    */
    const DEFAULT_TEAMS_PER_PAGE = 10;

    /**
    * Get current per_page value from pagination controls or use default
    */
    Admin.getTeamsPerPage = function () {
        // Try to get from pagination controls select element
        const paginationControls = Admin.safeGetElement(
            "teams-pagination-controls",
        );
        if (paginationControls) {
            const select = paginationControls.querySelector("select");
            if (select && select.value) {
                return parseInt(select.value, 10) || DEFAULT_TEAMS_PER_PAGE;
            }
        }
        return DEFAULT_TEAMS_PER_PAGE;
    }

    /**
    * Actually perform the team search after debounce
    * @param {string} searchTerm - The search query
    */
    Admin.performTeamSearch = async function (searchTerm) {
        const container = Admin.safeGetElement("unified-teams-list");
        const loadingIndicator = Admin.safeGetElement("teams-loading");

        if (!container) {
            console.error("unified-teams-list container not found");
            return;
        }

        // Show loading state
        if (loadingIndicator) {
            loadingIndicator.style.display = "block";
        }

        // Build URL with search query and current relationship filter
        const params = new URLSearchParams();
        params.set("page", "1");
        params.set("per_page", Admin.getTeamsPerPage().toString());

        if (searchTerm && searchTerm.trim() !== "") {
            params.set("q", searchTerm.trim());
        }

        if (
            currentTeamRelationshipFilter &&
            currentTeamRelationshipFilter !== "all"
        ) {
            params.set("relationship", currentTeamRelationshipFilter);
        }

        const url = `${window.ROOT_PATH || ""}/admin/teams/partial?${params.toString()}`;

        console.log(`[Team Search] Searching teams with URL: ${url}`);

        try {
            // Use HTMX to load the results
            if (window.htmx) {
                // HTMX handles the indicator automatically via the indicator option
                // Don't manually hide it - HTMX will hide it when request completes
                window.htmx.ajax("GET", url, {
                    target: "#unified-teams-list",
                    swap: "innerHTML",
                    indicator: "#teams-loading",
                });
            } else {
                // Fallback to fetch if HTMX is not available
                const response = await fetch(url);
                if (response.ok) {
                    const html = await response.text();
                    container.innerHTML = html;
                } else {
                    container.innerHTML =
                        '<div class="text-center py-4 text-red-600">Failed to load teams</div>';
                }
                // Only hide indicator in fetch fallback path (HTMX handles its own)
                if (loadingIndicator) {
                    loadingIndicator.style.display = "none";
                }
            }
        } catch (error) {
            console.error("Error searching teams:", error);
            container.innerHTML =
                '<div class="text-center py-4 text-red-600">Error searching teams</div>';
            // Hide indicator on error in fallback path
            if (loadingIndicator) {
                loadingIndicator.style.display = "none";
            }
        }
    }

    /**
    * Filter teams by relationship (owner, member, public, all)
    * @param {string} filter - The relationship filter value
    */
    Admin.filterByRelationship = function (filter) {
        // Update button states
        const filterButtons = document.querySelectorAll(".filter-btn");
        filterButtons.forEach((btn) => {
            if (btn.getAttribute("data-filter") === filter) {
                btn.classList.add(
                    "active",
                    "bg-indigo-100",
                    "dark:bg-indigo-900",
                    "text-indigo-700",
                    "dark:text-indigo-300",
                    "border-indigo-300",
                    "dark:border-indigo-600",
                );
                btn.classList.remove(
                    "bg-white",
                    "dark:bg-gray-700",
                    "text-gray-700",
                    "dark:text-gray-300",
                );
            } else {
                btn.classList.remove(
                    "active",
                    "bg-indigo-100",
                    "dark:bg-indigo-900",
                    "text-indigo-700",
                    "dark:text-indigo-300",
                    "border-indigo-300",
                    "dark:border-indigo-600",
                );
                btn.classList.add(
                    "bg-white",
                    "dark:bg-gray-700",
                    "text-gray-700",
                    "dark:text-gray-300",
                );
            }
        });

        // Update current filter state
        currentTeamRelationshipFilter = filter;

        // Get current search query
        const searchInput = Admin.safeGetElement("team-search");
        const searchQuery = searchInput ? searchInput.value.trim() : "";

        // Perform search with new filter
        Admin.performTeamSearch(searchQuery);
    }

    /**
    * Legacy filterTeams function - redirects to serverSideTeamSearch
    * @param {string} searchValue - The search query
    */
    Admin.filterTeams = function (searchValue) {
        Admin.serverSideTeamSearch(searchValue);
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
    Admin.searchTeamSelector = function (searchTerm) {
        // Debounce the search
        if (teamSelectorSearchDebounceTimer) {
            clearTimeout(teamSelectorSearchDebounceTimer);
        }

        teamSelectorSearchDebounceTimer = setTimeout(() => {
            Admin.performTeamSelectorSearch(searchTerm);
        }, 300);
    }

    /**
    * Perform the team selector search
    * @param {string} searchTerm - The search query
    */
    Admin.performTeamSelectorSearch = function (searchTerm) {
        const container = Admin.safeGetElement("team-selector-items");
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
    Admin.selectTeamFromSelector = function (button) {
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
        const searchInput = Admin.safeGetElement("team-selector-search");
        if (searchInput) {
            searchInput.value = "";
        }

        // Reset the loaded flag so next open reloads the list
        const itemsContainer = Admin.safeGetElement("team-selector-items");
        if (itemsContainer) {
            delete itemsContainer.dataset.loaded;
        }

        // Call the existing updateTeamContext function (defined in admin.html)
        if (typeof window.updateTeamContext === "function") {
            window.updateTeamContext(teamId);
        }
    }



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
                `Destroying ${toDestroy.length} charts with prefix: ${prefix}`,
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

    // Cleanup all charts on page unload
    window.addEventListener("beforeunload", () => {
        Admin.chartRegistry.destroyAll();
    });

    // Add three fields to passthrough section on Advanced button click
    Admin.handleAddPassthrough = function () {
        const passthroughContainer = Admin.safeGetElement("passthrough-container");
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
            if (!Admin.safeGetElement("query-mapping-field")) {
                const queryDiv = document.createElement("div");
                queryDiv.className = "mb-4";
                queryDiv.innerHTML = `
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Query Mapping (JSON)</label>
                    <textarea id="query-mapping-field" name="query_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
                `;
                passthroughContainer.appendChild(queryDiv);
            }
            if (!Admin.safeGetElement("header-mapping-field")) {
                const headerDiv = document.createElement("div");
                headerDiv.className = "mb-4";
                headerDiv.innerHTML = `
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Header Mapping (JSON)</label>
                    <textarea id="header-mapping-field" name="header_mapping" class="mt-1 px-1.5 block w-full h-40 rounded-md border border-gray-300 dark:border-gray-600 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 bg-black text-white" placeholder="{}"></textarea>
                `;
                passthroughContainer.appendChild(headerDiv);
            }
            if (!Admin.safeGetElement("timeout-ms-field")) {
                const timeoutDiv = document.createElement("div");
                timeoutDiv.className = "mb-4";
                timeoutDiv.innerHTML = `
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">timeout_ms (number)</label>
                    <input type="number" id="timeout-ms-field" name="timeout_ms" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="30000" min="0" />
                `;
                passthroughContainer.appendChild(timeoutDiv);
            }
            if (!Admin.safeGetElement("expose-passthrough-field")) {
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
            if (!Admin.safeGetElement("allowlist-field")) {
                const allowlistDiv = document.createElement("div");
                allowlistDiv.className = "mb-4";
                allowlistDiv.innerHTML = `
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Allowlist (comma-separated hosts/schemes)</label>
                    <input type="text" id="allowlist-field" name="allowlist" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[example.com, https://api.example.com]" />
                `;
                passthroughContainer.appendChild(allowlistDiv);
            }
            if (!Admin.safeGetElement("plugin-chain-pre-field")) {
                const pluginPreDiv = document.createElement("div");
                pluginPreDiv.className = "mb-4";
                pluginPreDiv.innerHTML = `
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-400 mb-1">Plugin Chain Pre</label>
                    <input type="text" id="plugin-chain-pre-field" name="plugin_chain_pre" class="mt-1 px-1.5 block w-full rounded-md border border-gray-300 dark:border-gray-700 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300" placeholder="[]" />
                `;
                passthroughContainer.appendChild(pluginPreDiv);
            }
            if (!Admin.safeGetElement("plugin-chain-post-field")) {
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

    // Make URL field read-only for integration type MCP
    Admin.updateEditToolUrl = function () {
        const editTypeField = Admin.safeGetElement("edit-tool-type");
        const editurlField = Admin.safeGetElement("edit-tool-url");
        if (editTypeField && editurlField) {
            if (editTypeField.value === "MCP") {
                editurlField.readOnly = true;
            } else {
                editurlField.readOnly = false;
            }
        }
    }

    // Attach event listener after DOM is loaded or when modal opens
    document.addEventListener("DOMContentLoaded", function () {
        const TypeField = Admin.safeGetElement("edit-tool-type");
        if (TypeField) {
            TypeField.addEventListener("change", Admin.updateEditToolUrl);
            // Set initial state
            Admin.updateEditToolUrl();
        }

        // Initialize CA certificate upload immediately
        Admin.initializeCACertUpload();

        // Also try to initialize after a short delay (in case the panel loads later)
        setTimeout(Admin.initializeCACertUpload, 500);

        // Re-initialize when switching to gateways tab
        const gatewaysTab = document.querySelector('[onclick*="gateways"]');
        if (gatewaysTab) {
            gatewaysTab.addEventListener("click", function () {
                setTimeout(Admin.initializeCACertUpload, 100);
            });
        }

        // Initialize search functionality for all entity types (immediate, no debounce)
        initializeSearchInputsMemoized();
        Admin.initializePasswordValidation();
        Admin.initializeAddMembersForms();

        // Event delegation for team member search - server-side search for unified view
        // This handler is initialized here for early binding, but the actual search logic
        // is in Admin.performUserSearch() which is attached when the form is initialized
        const teamSearchTimeouts = {};
        const teamMemberDataCache = {};

        document.body.addEventListener("input", async function (event) {
            const target = event.target;
            if (target.id && target.id.startsWith("user-search-")) {
                const teamId = target.id.replace("user-search-", "");
                const listContainer = Admin.safeGetElement(
                    `team-members-list-${teamId}`,
                );

                if (!listContainer) return;

                const query = target.value.trim();

                // Clear previous timeout for this team
                if (teamSearchTimeouts[teamId]) {
                    clearTimeout(teamSearchTimeouts[teamId]);
                }

                // Get team member data from cache or script tag
                if (!teamMemberDataCache[teamId]) {
                    const teamMemberDataScript = Admin.safeGetElement(
                        `team-member-data-${teamId}`,
                    );
                    if (teamMemberDataScript) {
                        try {
                            teamMemberDataCache[teamId] = JSON.parse(
                                teamMemberDataScript.textContent || "{}",
                            );
                            console.log(
                                `[Team ${teamId}] Loaded team member data for ${Object.keys(teamMemberDataCache[teamId]).length} members`,
                            );
                        } catch (e) {
                            console.error(
                                `[Team ${teamId}] Failed to parse team member data:`,
                                e,
                            );
                            teamMemberDataCache[teamId] = {};
                        }
                    } else {
                        teamMemberDataCache[teamId] = {};
                    }
                }

                // Debounce server call
                teamSearchTimeouts[teamId] = setTimeout(async () => {
                    await Admin.performUserSearch(
                        teamId,
                        query,
                        listContainer,
                        teamMemberDataCache[teamId],
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
                    (panelId) =>
                        target.id === panelId || target.closest(`#${panelId}`),
                )
            ) {
                console.log(
                    `📝 HTMX swap detected in ${target.id}, resetting search state`,
                );
                resetSearchInputsState();
                initializeSearchInputsDebounced();
            }
        });

        // Initialize search when switching tabs
        document.addEventListener("click", function (event) {
            if (
                event.target.matches('[onclick*="showTab"]') ||
                event.target.closest('[onclick*="showTab"]')
            ) {
                console.log("🔄 Tab switch detected, resetting search state");
                resetSearchInputsState();
                initializeSearchInputsDebounced();
            }
        });
    });

    /**
     * Handle keydown event when Enter or Space key is pressed
     *
     * @param {KeyboardEvent} event - the keyboard event triggered
     * @param {function} callback - the function to call when Enter or Space is pressed
     */
    Admin.handleKeydown = (event, callback) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            callback(event);
        }
    }
})(window.Admin)