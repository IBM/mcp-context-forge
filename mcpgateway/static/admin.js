document.addEventListener("DOMContentLoaded", function () {
  const hash = window.location.hash;
  if (hash) {
    showTab(hash.slice(1));
  }

  document.getElementById("tab-catalog").addEventListener("click", () => {
    showTab("catalog");
  });
  document.getElementById("tab-tools").addEventListener("click", () => {
    showTab("tools");
  });
  document.getElementById("tab-resources").addEventListener("click", () => {
    showTab("resources");
  });
  document.getElementById("tab-prompts").addEventListener("click", () => {
    showTab("prompts");
  });
  document.getElementById("tab-gateways").addEventListener("click", () => {
    showTab("gateways");
  });
  document.getElementById("tab-roots").addEventListener("click", () => {
    showTab("roots");
  });
  document.getElementById("tab-metrics").addEventListener("click", () => {
    showTab("metrics");
  });
  document.getElementById("tab-version-info").addEventListener("click", () => {
    showTab("version-info");
  });

  /* ------------------------------------------------------------------
  * Pre-load the "Version & Environment Info" partial once per page
  * ------------------------------------------------------------------ */
   /* Pre-load version-info once */
  document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("version-info-panel");
    if (!panel || panel.innerHTML.trim() !== "") return; // already loaded

    fetch(`${window.ROOT_PATH}/version?partial=true`)
      .then((response) => {
        if (!response.ok) throw new Error("Network response was not ok");
        return response.text();
      })
      .then((html) => {
        panel.innerHTML = html;

        // If the page was opened at #version-info, show that tab now
        if (window.location.hash === "#version-info") {
          showTab("version-info");
        }
      })
      .catch((error) => {
        console.error("Failed to preload version info:", error);
        panel.innerHTML =
          "<p class='text-red-600'>Failed to load version info.</p>";
      });
  });

  /* ------------------------------------------------------------------
  * HTMX debug hooks
  * ------------------------------------------------------------------ */
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id === "version-info-panel") {
      console.log("HTMX: Content swapped into version-info-panel");
    }
  });


  // HTMX event listeners for debugging
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

  // Authentication toggle
  document.getElementById("auth-type").addEventListener("change", function () {
    const basicFields = document.getElementById("auth-basic-fields");
    const bearerFields = document.getElementById("auth-bearer-fields");
    const headersFields = document.getElementById("auth-headers-fields");
    handleAuthTypeSelection(
      this.value,
      basicFields,
      bearerFields,
      headersFields,
    );
  });
  document
    .getElementById("auth-type-gw")
    .addEventListener("change", function () {
      const basicFields = document.getElementById("auth-basic-fields-gw");
      const bearerFields = document.getElementById("auth-bearer-fields-gw");
      const headersFields = document.getElementById("auth-headers-fields-gw");
      handleAuthTypeSelection(
        this.value,
        basicFields,
        bearerFields,
        headersFields,
      );
    });
  document
    .getElementById("auth-type-gw-edit")
    .addEventListener("change", function () {
      const basicFields = document.getElementById("auth-basic-fields-gw-edit");
      const bearerFields = document.getElementById(
        "auth-bearer-fields-gw-edit",
      );
      const headersFields = document.getElementById(
        "auth-headers-fields-gw-edit",
      );
      handleAuthTypeSelection(
        this.value,
        basicFields,
        bearerFields,
        headersFields,
      );
    });
  document
    .getElementById("edit-auth-type")
    .addEventListener("change", function () {
      const basicFields = document.getElementById("edit-auth-basic-fields");
      const bearerFields = document.getElementById("edit-auth-bearer-fields");
      const headersFields = document.getElementById("edit-auth-headers-fields");
      if (this.value === "basic") {
        basicFields.style.display = "block";
        bearerFields.style.display = "none";
        headersFields.style.display = "none";
      } else if (this.value === "bearer") {
        basicFields.style.display = "none";
        bearerFields.style.display = "block";
        headersFields.style.display = "none";
      } else if (this.value === "authheaders") {
        basicFields.style.display = "none";
        bearerFields.style.display = "none";
        headersFields.style.display = "block";
      } else {
        basicFields.style.display = "none";
        bearerFields.style.display = "none";
        headersFields.style.display = "none";
      }
    });

    document.getElementById("add-gateway-form")
      .addEventListener("submit", async (e) => {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);

        const status = document.getElementById("status-gateways");
        const loading = document.getElementById("add-gateway-loading");

        // Show loading and clear previous status
        loading.style.display = "block";
        status.textContent = "";
        status.classList.remove("error-status");

        try {
          const response = await fetch(`${window.ROOT_PATH}/admin/gateways`, {
            method: "POST",
            body: formData,
          });

          let result = await response.json();
            if (!result.success) {
              alert(result.message || "An error occurred");
            } else {
              window.location.href = `${window.ROOT_PATH}/admin#gateways`; // Redirect on success
            }

        } catch (error) {
          console.error("Error:", error);
          status.textContent = error.message || "An error occurred!";
          status.classList.add("error-status");
        } finally {
          loading.style.display = "none"; // Hide loading spinner
        }
      });


  document
    .getElementById("add-resource-form")
    .addEventListener("submit", (e) => {
      e.preventDefault();
      const form = e.target;
      const formData = new FormData(form);
      fetch(`${window.ROOT_PATH}/admin/resources`, {
        method: "POST",
        body: formData,
      })
        .then((response) => {
          console.log(response);
          if (!response.ok) {
            const status = document.getElementById("status-resources");
            status.textContent = "Connection failed!";
            status.classList.add("error-status");
          } else {
            location.reload();
          }
        })
        .catch((error) => {
          console.error("Error:", error);
        });
    });

  // Dynamically add parameter block on button click
  document.getElementById("add-parameter-btn").addEventListener("click", () => {
    parameterCount++;
    const parametersContainer = document.getElementById("parameters-container");
    const paramDiv = document.createElement("div");
    paramDiv.classList.add(
      "border",
      "p-4",
      "mb-4",
      "rounded-md",
      "bg-gray-50",
      "shadow-sm",
    );
    paramDiv.innerHTML = `
    <div class="flex justify-between items-center">
      <span class="font-semibold text-gray-800">Parameter ${parameterCount}</span>
      <button type="button" class="delete-param text-red-600 hover:text-red-800 focus:outline-none text-xl" title="Delete Parameter">&times;</button>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
      <div>
        <label class="block text-sm font-medium text-gray-700">Parameter Name</label>
        <input type="text" name="param_name_${parameterCount}" required class="mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700">Type</label>
        <select name="param_type_${parameterCount}" class="mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200">
          <option value="string">String</option>
          <option value="number">Number</option>
          <option value="boolean">Boolean</option>
          <option value="object">Object</option>
          <option value="array">Array</option>
        </select>
      </div>
    </div>
    <div class="mt-4">
      <label class="block text-sm font-medium text-gray-700">Description</label>
      <textarea name="param_description_${parameterCount}" class="mt-1 block w-full rounded-md border border-gray-300 shadow-sm focus:border-indigo-500 focus:ring focus:ring-indigo-200"></textarea>
    </div>
    <div class="mt-4 flex items-center">
      <input type="checkbox" name="param_required_${parameterCount}" checked class="h-4 w-4 text-indigo-600 border border-gray-300 rounded" />
      <label class="ml-2 text-sm font-medium text-gray-700">Required</label>
    </div>
    `;
    parametersContainer.appendChild(paramDiv);
    updateSchemaPreview();

    // Delete parameter functionality
    const deleteButton = paramDiv.querySelector(".delete-param");
    deleteButton.addEventListener("click", () => {
      paramDiv.remove();
      updateSchemaPreview();
      parameterCount--;
    });
  });

  // Let the form load and then refresh the code mirror editors
  var addToolForm = document.getElementById("add-tool-form");
  addToolForm.addEventListener("click", function () {
    if (getComputedStyle(addToolForm).display !== "none") {
      refreshEditors();
    }
  });

  // for tools insertion failure pop ups
  document
    .getElementById("add-tool-form")
    .addEventListener("submit", async function (event) {
      event.preventDefault();
      // If in UI mode, update schemaEditor with generated schema
      const mode = document.querySelector(
        'input[name="schema_input_mode"]:checked',
      ).value;
      if (mode === "ui") {
        window.schemaEditor.setValue(generateSchema());
      }
      // Save CodeMirror editors' contents into the underlying textareas
      if (window.headersEditor) {
        window.headersEditor.save();
      }
      if (window.schemaEditor) {
        window.schemaEditor.save();
      }

      let formData = new FormData(this);
      try {
        let response = await fetch(`${window.ROOT_PATH}/admin/tools`, {
          method: "POST",
          body: formData,
        });
        let result = await response.json();
        if (!result.success) {
          alert(result.message || "An error occurred");
        } else {
          window.location.href = `${window.ROOT_PATH}/admin#tools`; // Redirect on success
        }
      } catch (error) {
        console.error("Fetch error:", error);
        alert("Failed to submit the form. Check console for details.");
      }
    });

  // You can override this default in HTML by adding `data-default="REST"` (for example)
  const integrationTypeSelect = document.getElementById("integrationType");
  const defaultIntegration =
    integrationTypeSelect.dataset.default ||
    integrationTypeSelect.options[0].value;
  integrationTypeSelect.value = defaultIntegration;
  updateRequestTypeOptions();

  integrationTypeSelect.addEventListener("change", () => {
    updateRequestTypeOptions();
  });

  const editToolTypeSelect = document.getElementById("edit-tool-type");
  const editToolRequestTypeSelect = document.getElementById(
    "edit-tool-request-type",
  );

  const requestTypeMap = {
    MCP: ["SSE", "STREAMABLE", "STDIO"],
    REST: ["GET", "POST", "PUT", "DELETE"],
  };


  // Optionally pass in a pre-selected method
  function updateEditToolRequestTypes(selectedMethod = null) {
    const selectedType = editToolTypeSelect.value;
    const allowedMethods = requestTypeMap[selectedType] || [];

    // Clear existing options
    editToolRequestTypeSelect.innerHTML = "";

    // Populate new options
    allowedMethods.forEach((method) => {
      const option = document.createElement("option");
      option.value = method;
      option.textContent = method;
      editToolRequestTypeSelect.appendChild(option);
    });

    // Set the pre-selected method, if valid
    if (selectedMethod && allowedMethods.includes(selectedMethod)) {
      editToolRequestTypeSelect.value = selectedMethod;
    }
  }

  // Call once on page load or when popup opens
  const currentType = "REST"; // example: loaded from existing data
  const currentMethod = "PUT"; // example: loaded from existing data

  editToolTypeSelect.value = currentType;
  updateEditToolRequestTypes(currentMethod);

  // Update request type options when tool type changes
  editToolTypeSelect.addEventListener("change", () => {
    updateEditToolRequestTypes(); // no preselection on change
  });

  //Input schema UI backend for schema creation
  window.schemaEditor = window.CodeMirror.fromTextArea(
    document.getElementById("schema-editor"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );
});

// Tab handling
function showTab(tabName) {
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.add("hidden");
  });
  document.querySelectorAll(".tab-link").forEach((link) => {
    link.classList.remove("border-indigo-500", "text-indigo-600", "dark:text-indigo-500", "dark:border-indigo-400");
    link.classList.add("border-transparent", "text-gray-500", "dark:text-gray-400");
  });
  document.getElementById(`${tabName}-panel`).classList.remove("hidden");
  document
    .querySelector(`[href="#${tabName}"]`)
    .classList.add("border-indigo-500", "text-indigo-600", "dark:text-indigo-500", "dark:border-indigo-400");
  document
    .querySelector(`[href="#${tabName}"]`)
    .classList.remove("border-transparent", "text-gray-500", "dark:text-gray-400");

  if (tabName === "metrics") {
    loadAggregatedMetrics();
  }

  if (tabName === "version-info") {
    const panel = document.getElementById("version-info-panel");
    if (panel && panel.innerHTML.trim() === "") {
      const url = `${window.ROOT_PATH}/version?partial=true`;
      fetch(url)
        .then((response) => {
          if (!response.ok) {
            throw new Error("Network response was not ok");
          }
          return response.text();
        })
        .then((html) => {
          panel.innerHTML = html;
        })
        .catch((error) => {
          console.error("Failed to load version info:", error);
          panel.innerHTML = "<p class='text-red-600'>Failed to load version info.</p>";
        });
    }
  }
}

// handle auth type selection
function handleAuthTypeSelection(
  value,
  basicFields,
  bearerFields,
  headersFields,
) {
  if (value === "basic") {
    basicFields.style.display = "block";
    bearerFields.style.display = "none";
    headersFields.style.display = "none";
  } else if (value === "bearer") {
    basicFields.style.display = "none";
    bearerFields.style.display = "block";
    headersFields.style.display = "none";
  } else if (value === "authheaders") {
    basicFields.style.display = "none";
    bearerFields.style.display = "none";
    headersFields.style.display = "block";
  } else {
    basicFields.style.display = "none";
    bearerFields.style.display = "none";
    headersFields.style.display = "none";
  }
}

// Cached DOM elements
const schemaModeRadios = document.getElementsByName("schema_input_mode");
const uiBuilderDiv = document.getElementById("ui-builder");
const jsonInputContainer = document.getElementById("json-input-container");
let parameterCount = 0;

// Function to generate the JSON schema from UI builder inputs
function generateSchema() {
  let schema = {
    title: "CustomInputSchema",
    type: "object",
    properties: {},
    required: [],
  };
  for (let i = 1; i <= parameterCount; i++) {
    const nameField = document.querySelector(`[name="param_name_${i}"]`);
    const typeField = document.querySelector(`[name="param_type_${i}"]`);
    const descField = document.querySelector(`[name="param_description_${i}"]`);
    const requiredField = document.querySelector(
      `[name="param_required_${i}"]`,
    );
    if (nameField && nameField.value.trim() !== "") {
      schema.properties[nameField.value.trim()] = {
        type: typeField.value,
        description: descField.value.trim(),
      };
      if (requiredField && requiredField.checked) {
        schema.required.push(nameField.value.trim());
      }
    }
  }
  return JSON.stringify(schema, null, 2);
}

// Update CodeMirror editor with the generated schema
function updateSchemaPreview() {
  const mode = document.querySelector(
    'input[name="schema_input_mode"]:checked',
  ).value;
  if (mode === "json") {
    window.schemaEditor.setValue(generateSchema());
  }
}

/* ---------------------------------------------------------------
 * Switch between "UI-builder" and "JSON input" modes
 * ------------------------------------------------------------- */
Array.from(schemaModeRadios).forEach((radio) => {
  radio.addEventListener("change", () => {
    if (radio.value === "ui" && radio.checked) {
      uiBuilderDiv.style.display = "block";
      jsonInputContainer.style.display = "none";
    } else if (radio.value === "json" && radio.checked) {
      uiBuilderDiv.style.display = "none";
      jsonInputContainer.style.display = "block";
      updateSchemaPreview();        // keep preview in sync
    }
  });
});  // closes addEventListener callback, forEach callback, and forEach call


// On form submission, update CodeMirror with UI builder schema if needed
// document.getElementById('add-tool-form').addEventListener('submit', (e) => {
//   const mode = document.querySelector('input[name="schema_input_mode"]:checked').value;
//   if (mode === 'ui') {
//     schemaEditor.setValue(generateSchema());
//   }
// });

// Function to toggle inactive items based on checkbox state
function toggleInactiveItems(type) {
  const checkbox = document.getElementById(`show-inactive-${type}`);
  const url = new URL(window.location);
  if (checkbox.checked) {
    url.searchParams.set("include_inactive", "true");
  } else {
    url.searchParams.delete("include_inactive");
  }
  window.location = url;
}

// Tool CRUD operations
/**
 * Fetches detailed tool information from the backend and renders all properties,
 * including Request Type and Authentication details, in the tool detail modal.
 *
 * @param {number|string} toolId - The unique identifier of the tool.
 */
async function viewTool(toolId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/tools/${toolId}`);
    const tool = await response.json();

    let authHTML = "";

    if (tool.auth?.username && tool.auth?.password) {
      authHTML = `
        <p><strong>Authentication Type:</strong> Basic</p>
        <p><strong>Username:</strong> ${tool.auth.username}</p>
        <p><strong>Password:</strong> ********</p>
      `;
    } else if (tool.auth?.token) {
      authHTML = `
        <p><strong>Authentication Type:</strong> Token</p>
        <p><strong>Token:</strong> ********</p>
      `;
    } else if (tool.auth?.authHeaderKey && tool.auth?.authHeaderValue) {
      authHTML = `
        <p><strong>Authentication Type:</strong> Custom Headers</p>
        <p><strong>Header Key:</strong> ${tool.auth.authHeaderKey}</p>
        <p><strong>Header Value:</strong> ********</p>
      `;
    } else {
      authHTML = `<p><strong>Authentication Type:</strong> None</p>`;
    }

    // Helper function to create annotation badges
    const renderAnnotations = (annotations) => {
      if (!annotations || Object.keys(annotations).length === 0) {
        return '<p><strong>Annotations:</strong> <span class="text-gray-500">None</span></p>';
      }

      const badges = [];

      // Show title if present
      if (annotations.title) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mr-1 mb-1">${annotations.title}</span>`);
      }

      // Show behavior hints with appropriate colors
      if (annotations.readOnlyHint === true) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 mr-1 mb-1">📖 Read-Only</span>`);
      }

      if (annotations.destructiveHint === true) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 mr-1 mb-1">⚠️ Destructive</span>`);
      }

      if (annotations.idempotentHint === true) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 mr-1 mb-1">🔄 Idempotent</span>`);
      }

      if (annotations.openWorldHint === true) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 mr-1 mb-1">🌐 External Access</span>`);
      }

      // Show any other custom annotations
      Object.keys(annotations).forEach(key => {
        if (!['title', 'readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'].includes(key)) {
          const value = annotations[key];
          badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 mr-1 mb-1">${key}: ${value}</span>`);
        }
      });

      return `
        <div>
          <strong>Annotations:</strong>
          <div class="mt-1 flex flex-wrap">
            ${badges.join('')}
          </div>
        </div>
      `;
    };

    document.getElementById("tool-details").innerHTML = `
      <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
        <p><strong>Name:</strong> ${tool.name}</p>
        <p><strong>URL:</strong> ${tool.url}</p>
        <p><strong>Type:</strong> ${tool.integrationType}</p>
        <p><strong>Description:</strong> ${tool.description || "N/A"}</p>
        <p><strong>Request Type:</strong> ${tool.requestType || "N/A"}</p>
        ${authHTML}
        ${renderAnnotations(tool.annotations)}
        <div>
          <strong>Headers:</strong>
          <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${JSON.stringify(tool.headers || {}, null, 2)}</pre>
        </div>
        <div>
          <strong>Input Schema:</strong>
          <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${JSON.stringify(tool.inputSchema || {}, null, 2)}</pre>
        </div>
        <div>
          <strong>Metrics:</strong>
          <ul class="list-disc list-inside ml-4">
            <li>Total Executions: ${tool.metrics?.totalExecutions ?? 0}</li>
            <li>Successful Executions: ${tool.metrics?.successfulExecutions ?? 0}</li>
            <li>Failed Executions: ${tool.metrics?.failedExecutions ?? 0}</li>
            <li>Failure Rate: ${tool.metrics?.failureRate ?? 0}</li>
            <li>Min Response Time: ${tool.metrics?.minResponseTime ?? "N/A"}</li>
            <li>Max Response Time: ${tool.metrics?.maxResponseTime ?? "N/A"}</li>
            <li>Average Response Time: ${tool.metrics?.avgResponseTime ?? "N/A"}</li>
            <li>Last Execution Time: ${tool.metrics?.lastExecutionTime ?? "N/A"}</li>
          </ul>
        </div>
      </div>
    `;

    openModal("tool-modal");
  } catch (error) {
    console.error("Error fetching tool details:", error);
    alert("Failed to load tool details");
  }
}

function protectInputPrefix(inputElement, protectedText) {
    let lastValidValue = protectedText;

    // Set initial value
    inputElement.value = protectedText;

    // Listen for input events
    inputElement.addEventListener('input', function(e) {
        const currentValue = e.target.value;

        // Check if protected text is still intact
        if (!currentValue.startsWith(protectedText)) {
            // Restore the protected text
            e.target.value = lastValidValue;
            // Move cursor to end of protected text
            e.target.setSelectionRange(protectedText.length, protectedText.length);
        } else {
            // Save valid state
            lastValidValue = currentValue;
        }
    });

    // Prevent selection/editing of protected portion
    inputElement.addEventListener('keydown', function(e) {
        const start = e.target.selectionStart;
        const end = e.target.selectionEnd;

        // Block edits that would affect protected text
        if (start < protectedText.length) {
            // Allow navigation keys
            const allowedKeys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Tab'];
            if (!allowedKeys.includes(e.key)) {
                e.preventDefault();
                // Move cursor to end of protected text
                e.target.setSelectionRange(protectedText.length, protectedText.length);
            }
        }
    });

    // Handle paste events
    inputElement.addEventListener('paste', function(e) {
        const start = e.target.selectionStart;
        if (start < protectedText.length) {
            e.preventDefault();
        }
    });
}

/**
 * Fetches tool details from the backend and populates the edit modal form,
 * including Request Type and Authentication fields, so that they are pre-filled for editing.
 *
 * @param {number|string} toolId - The unique identifier of the tool to edit.
 */
async function editTool(toolId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/tools/${toolId}`);
    const tool = await response.json();

    // Set form action and populate basic fields.
    document.getElementById("edit-tool-form").action =
      `${window.ROOT_PATH}/admin/tools/${toolId}/edit`;
    // const toolNameInput = document.getElementById("edit-tool-name");
    // const protectedPrefix = tool.gatewaySlug + `${window.GATEWAY_TOOL_NAME_SEPARATOR}`;
    // protectInputPrefix(toolNameInput, protectedPrefix);
    // toolNameInput.value = protectedPrefix + (tool.name.startsWith(protectedPrefix) ?
    // tool.name.substring(protectedPrefix.length) : tool.name);
    document.getElementById("edit-tool-name").value = tool.name;
    document.getElementById("edit-tool-url").value = tool.url;
    document.getElementById("edit-tool-description").value =
      tool.description || "";
    document.getElementById("edit-tool-type").value =
      tool.integrationType || "MCP";

    // Populate authentication fields.
    document.getElementById("edit-auth-type").value = tool.auth?.authType || "";
    if (tool.auth?.authType === "basic") {
      document.getElementById("edit-auth-basic-fields").style.display = "block";
      document.getElementById("edit-auth-bearer-fields").style.display = "none";
      document.getElementById("edit-auth-headers-fields").style.display =
        "none";
      document.getElementById("edit-auth-username").value =
        tool.auth?.username || "";
      document.getElementById("edit-auth-password").value =
        tool.auth?.password || "";
    } else if (tool.auth?.authType === "bearer") {
      document.getElementById("edit-auth-basic-fields").style.display = "none";
      document.getElementById("edit-auth-bearer-fields").style.display =
        "block";
      document.getElementById("edit-auth-headers-fields").style.display =
        "none";
      document.getElementById("edit-auth-token").value = tool.auth.token || "";
    } else if (tool.auth?.authType === "authheaders") {
      document.getElementById("edit-auth-basic-fields").style.display = "none";
      document.getElementById("edit-auth-bearer-fields").style.display = "none";
      document.getElementById("edit-auth-headers-fields").style.display =
        "block";
      document.getElementById("edit-auth-key").value =
        tool.auth?.authHeaderKey || "";
      document.getElementById("edit-auth-value").value =
        tool.auth?.authHeaderValue || "";
    } else {
      document.getElementById("edit-auth-basic-fields").style.display = "none";
      document.getElementById("edit-auth-bearer-fields").style.display = "none";
      document.getElementById("edit-auth-headers-fields").style.display =
        "none";
    }

    const headersJson = JSON.stringify(tool.headers || {}, null, 2);
    const schemaJson = JSON.stringify(tool.inputSchema || {}, null, 2);
    const annotationsJson = JSON.stringify(tool.annotations || {}, null, 2);

    // Update the code editor textareas.
    document.getElementById("edit-tool-headers").value = headersJson;
    document.getElementById("edit-tool-schema").value = schemaJson;
    document.getElementById("edit-tool-annotations").value = annotationsJson;
    if (window.editToolHeadersEditor) {
      window.editToolHeadersEditor.setValue(headersJson);
      window.editToolHeadersEditor.refresh();
    }
    if (window.editToolSchemaEditor) {
      window.editToolSchemaEditor.setValue(schemaJson);
      window.editToolSchemaEditor.refresh();
    }

    const editToolTypeSelect = document.getElementById("edit-tool-type");
    const event = new Event("change");
    editToolTypeSelect.dispatchEvent(event);

    // Set Request Type field.
    document.getElementById("edit-tool-request-type").value =
      tool.requestType || "SSE";

    openModal("tool-edit-modal");

    // Ensure editors are refreshed after modal display.
    setTimeout(() => {
      if (window.editToolHeadersEditor) window.editToolHeadersEditor.refresh();
      if (window.editToolSchemaEditor) window.editToolSchemaEditor.refresh();
    }, 100);
  } catch (error) {
    console.error("Error fetching tool details:", error);
    alert("Failed to load tool for editing");
  }
}

async function viewResource(resourceUri) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}`,
    );
    const data = await response.json();
    const resource = data.resource;
    const content = data.content;
    document.getElementById("resource-details").innerHTML = `
          <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
            <p><strong>URI:</strong> ${resource.uri}</p>
            <p><strong>Name:</strong> ${resource.name}</p>
            <p><strong>Type:</strong> ${resource.mimeType || "N/A"}</p>
            <p><strong>Description:</strong> ${resource.description || "N/A"}</p>
            <p><strong>Status:</strong>
              <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                resource.isActive
                  ? "bg-green-100 text-green-800"
                  : "bg-red-100 text-red-800"
              }">
                ${resource.isActive ? "Active" : "Inactive"}
              </span>
            </p>
            <div>
              <strong>Content:</strong>
              <pre class="mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80">
                ${
                  typeof content === "object"
                    ? JSON.stringify(content, null, 2)
                    : content
                }
              </pre>
            </div>
            <!-- ADD THIS: Metrics section -->
            <div>
              <strong>Metrics:</strong>
              <ul class="list-disc list-inside ml-4">
                <li>Total Executions: ${resource.metrics.totalExecutions}</li>
                <li>Successful Executions: ${resource.metrics.successfulExecutions}</li>
                <li>Failed Executions: ${resource.metrics.failedExecutions}</li>
                <li>Failure Rate: ${resource.metrics.failureRate}</li>
                <li>Min Response Time: ${resource.metrics.minResponseTime}</li>
                <li>Max Response Time: ${resource.metrics.maxResponseTime}</li>
                <li>Average Response Time: ${resource.metrics.avgResponseTime}</li>
                <li>Last Execution Time: ${resource.metrics.lastExecutionTime || "N/A"}</li>
              </ul>
            </div>
          </div>
        `;
    openModal("resource-modal");
  } catch (error) {
    console.error("Error fetching resource details:", error);
    alert("Failed to load resource details");
  }
}

async function editResource(resourceUri) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}`,
    );
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    const resource = data.resource;
    // Set the form action for editing
    document.getElementById("edit-resource-form").action =
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceUri)}/edit`;
    // Populate the fields using the returned resource object
    document.getElementById("edit-resource-uri").value = resource.uri || "";
    document.getElementById("edit-resource-name").value = resource.name || "";
    document.getElementById("edit-resource-description").value =
      resource.description || "";
    document.getElementById("edit-resource-mime-type").value =
      resource.mimeType || "";
    const contentValue =
      typeof data.content === "object" && data.content.text
        ? data.content.text
        : typeof data.content === "object"
          ? JSON.stringify(data.content, null, 2)
          : data.content || "";
    document.getElementById("edit-resource-content").value = contentValue;
    if (window.editResourceContentEditor) {
      window.editResourceContentEditor.setValue(contentValue);
      window.editResourceContentEditor.refresh();
    }
    openModal("resource-edit-modal");
  } catch (error) {
    console.error("Error fetching resource details for editing:", error);
    alert("Failed to load resource for editing");
  }
}

async function viewPrompt(promptName) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`,
    );
    const prompt = await response.json();
    document.getElementById("prompt-details").innerHTML = `
          <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
            <p><strong>Name:</strong> ${prompt.name}</p>
            <p><strong>Description:</strong> ${prompt.description || "N/A"}</p>
            <p><strong>Status:</strong>
              <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                prompt.isActive
                  ? "bg-green-100 text-green-800"
                  : "bg-red-100 text-red-800"
              }">
                ${prompt.isActive ? "Active" : "Inactive"}
              </span>
            </p>
            <div>
              <strong>Template:</strong>
              <pre class="mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80">
                ${prompt.template}
              </pre>
            </div>
            <div>
              <strong>Arguments:</strong>
              <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${JSON.stringify(prompt.arguments || [], null, 2)}</pre>
            </div>
            <!-- ADD THIS: Metrics section -->
            <div>
              <strong>Metrics:</strong>
              <ul class="list-disc list-inside ml-4">
                <li>Total Executions: ${prompt.metrics.totalExecutions}</li>
                <li>Successful Executions: ${prompt.metrics.successfulExecutions}</li>
                <li>Failed Executions: ${prompt.metrics.failedExecutions}</li>
                <li>Failure Rate: ${prompt.metrics.failureRate}</li>
                <li>Min Response Time: ${prompt.metrics.minResponseTime}</li>
                <li>Max Response Time: ${prompt.metrics.maxResponseTime}</li>
                <li>Average Response Time: ${prompt.metrics.avgResponseTime}</li>
                <li>Last Execution Time: ${prompt.metrics.lastExecutionTime || "N/A"}</li>
              </ul>
            </div>
          </div>
        `;
    openModal("prompt-modal");
  } catch (error) {
    console.error("Error fetching prompt details:", error);
    alert("Failed to load prompt details");
  }
}

async function editPrompt(promptName) {
  try {
    const response = await fetch(
      `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`,
    );
    const prompt = await response.json();
    document.getElementById("edit-prompt-form").action =
      `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}/edit`;
    document.getElementById("edit-prompt-name").value = prompt.name;
    document.getElementById("edit-prompt-description").value =
      prompt.description || "";
    document.getElementById("edit-prompt-template").value = prompt.template;
    document.getElementById("edit-prompt-arguments").value = JSON.stringify(
      prompt.arguments || [],
      null,
      2,
    );
    if (window.editPromptTemplateEditor) {
      window.editPromptTemplateEditor.setValue(prompt.template);
    }
    if (window.editPromptArgumentsEditor) {
      window.editPromptArgumentsEditor.setValue(
        JSON.stringify(prompt.arguments || [], null, 2),
      );
    }
    openModal("prompt-edit-modal");
  } catch (error) {
    console.error("Error fetching prompt details:", error);
    alert("Failed to load prompt for editing");
  }
}

async function viewGateway(gatewayId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/gateways/${gatewayId}`);
    const gateway = await response.json();

    let authHTML = "";
    if (gateway.authUsername && gateway.authPassword) {
      authHTML = `
          <p><strong>Authentication Type:</strong> Basic</p>
          <p><strong>Username:</strong> ${gateway.authUsername}</p>
          <p><strong>Password:</strong> ********</p>
        `;
    } else if (gateway.authToken) {
      authHTML = `
          <p><strong>Authentication Type:</strong> Bearer</p>
          <p><strong>Token:</strong> ********</p>
        `;
    } else if (gateway.authHeaderKey && gateway.authHeaderValue) {
      authHTML = `
          <p><strong>Authentication Type:</strong> Custom Header</p>
          <p><strong>Header Key:</strong> ${gateway.authHeaderKey}</p>
          <p><strong>Header Value:</strong> ********</p>
        `;
    } else {
      authHTML = `<p><strong>Authentication Type:</strong> None</p>`;
    }

  document.getElementById("gateway-details").innerHTML = `
    <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
      <p><strong>Name:</strong> ${gateway.name}</p>
      <p><strong>URL:</strong> ${gateway.url}</p>
      <p><strong>Description:</strong> ${gateway.description || "N/A"}</p>
      <p><strong>Transport:</strong>
        ${gateway.transport === "STREAMABLEHTTP" ? "Streamable HTTP" :
          gateway.transport === "SSE" ? "SSE" : "N/A"}
      </p>
      <p class="flex items-center">
      <div class="relative group inline-block">
        <strong class="mr-2">Status:</strong>

          <span class="px-2 inline-flex items-center text-xs leading-5 font-semibold rounded-full
            ${gateway.enabled ? (gateway.reachable ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800") : "bg-red-100 text-red-800"}">
            ${gateway.enabled ? (gateway.reachable ? "Active" : "Offline") : "Inactive"}
            ${gateway.enabled ? (gateway.reachable ?
              `<svg class="ml-1 h-4 w-4 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd" />
              </svg>` :
              `<svg class="ml-1 h-4 w-4 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd" />
              </svg>`) :
              `<svg class="ml-1 h-4 w-4 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>`
            }
          </span>
          <div class="absolute left-full top-1/2 -translate-y-1/2 ml-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded py-1 px-2 z-10 whitespace-nowrap shadow">
            ${!gateway.enabled ? "Gateway is Manually Deactivated" : !gateway.reachable ? "Gateway is Not Reachable" : "Everything stable."}
          </div>
        </div>
      </p>
      <p><strong>Last Seen:</strong> ${gateway.lastSeen || "Never"}</p>
      ${authHTML}
      <div>
        <strong>Capabilities:</strong>
        <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${JSON.stringify(gateway.capabilities || {}, null, 2)}</pre>
      </div>
    </div>
  `;

    openModal("gateway-modal");
  } catch (error) {
    console.error("Error fetching gateway details:", error);
    alert("Failed to load gateway details");
  }
}

async function editGateway(gatewayId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/gateways/${gatewayId}`);
    const gateway = await response.json();
    document.getElementById("edit-gateway-form").action =
      `${window.ROOT_PATH}/admin/gateways/${gatewayId}/edit`;
    document.getElementById("edit-gateway-name").value = gateway.name;
    document.getElementById("edit-gateway-url").value = gateway.url;
    document.getElementById("edit-gateway-description").value =
      gateway.description || "";
    document.getElementById("edit-gateway-transport").value = gateway.transport;
    openModal("gateway-edit-modal");
  } catch (error) {
    console.error("Error fetching gateway details:", error);
    alert("Failed to load gateway for editing");
  }
}

// viewServer
async function viewServer(serverId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/servers/${serverId}`);
    const server = await response.json();

    // Helper function to render an associated item with ID and name
    const renderAssociatedItem = (item, mapping) => {
      // if the item is an object, use its properties directly
      if (typeof item === "object") {
        return `<span class="inline-block px-2 py-1 text-xs font-medium text-blue-800 bg-blue-100 rounded">
                      ${item.id}: ${item.name}
                    </span>`;
      } else {
        // Otherwise, lookup the name using the mapping (fallback to the id itself)
        const name = mapping[item] || item;
        return `<span class="inline-block px-2 py-1 text-xs font-medium text-blue-800 bg-blue-100 rounded">
                      ${name}
                    </span>`;
      }
    };

    const toolsHTML =
      Array.isArray(server.associatedTools) && server.associatedTools.length > 0
        ? server.associatedTools
            .map((item) => renderAssociatedItem(item, window.toolMapping))
            .join(" ")
        : "N/A";

    const resourcesHTML =
      Array.isArray(server.associatedResources) &&
      server.associatedResources.length > 0
        ? server.associatedResources
            .map((item) => renderAssociatedItem(item, window.resourceMapping))
            .join(" ")
        : "N/A";

    const promptsHTML =
      Array.isArray(server.associatedPrompts) &&
      server.associatedPrompts.length > 0
        ? server.associatedPrompts
            .map((item) => renderAssociatedItem(item, window.promptMapping))
            .join(" ")
        : "N/A";

    document.getElementById("server-details").innerHTML = `
          <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
            <p><strong>Name:</strong> ${server.name}</p>
            <p><strong>Description:</strong> ${server.description || "N/A"}</p>
            <p><strong>Status:</strong>
              <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                server.isActive
                  ? "bg-green-100 text-green-800"
                  : "bg-red-100 text-red-800"
              }">
                ${server.isActive ? "Active" : "Inactive"}
              </span>
            </p>
            <div>
              <strong>Icon:</strong>
              ${server.icon ? `<img src="${server.icon}" alt="${server.name} Icon" class="h-8 w-8">` : "N/A"}
            </div>
            <div>
              <strong>Associated Tools:</strong>
              <div class="mt-1 space-x-1">${toolsHTML}</div>
            </div>
            <div>
              <strong>Associated Resources:</strong>
              <div class="mt-1 space-x-1">${resourcesHTML}</div>
            </div>
            <div>
              <strong>Associated Prompts:</strong>
              <div class="mt-1 space-x-1">${promptsHTML}</div>
            </div>
            <div>
              <strong>Metrics:</strong>
              <ul class="list-disc list-inside ml-4">
                <li>Total Executions: ${server.metrics.totalExecutions}</li>
                <li>Successful Executions: ${server.metrics.successfulExecutions}</li>
                <li>Failed Executions: ${server.metrics.failedExecutions}</li>
                <li>Failure Rate: ${server.metrics.failureRate}</li>
                <li>Min Response Time: ${server.metrics.minResponseTime}</li>
                <li>Max Response Time: ${server.metrics.maxResponseTime}</li>
                <li>Average Response Time: ${server.metrics.avgResponseTime}</li>
                <li>Last Execution Time: ${server.metrics.lastExecutionTime || "N/A"}</li>
              </ul>
            </div>
          </div>
        `;
    openModal("server-modal");
  } catch (error) {
    console.error("Error fetching server details:", error);
    alert("Failed to load server details");
  }
}

async function editServer(serverId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/servers/${serverId}`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const server = await response.json();
    // Set the form action for editing
    document.getElementById("edit-server-form").action =
      `${window.ROOT_PATH}/admin/servers/${serverId}/edit`;
    // Fill in the basic fields
    document.getElementById("edit-server-name").value = server.name || "";
    document.getElementById("edit-server-description").value =
      server.description || "";
    document.getElementById("edit-server-icon").value = server.icon || "";
    // Fill in the associated tools field (already working)
    const select = document.getElementById('edit-server-tools');
    const pillsBox = document.getElementById('selectedEditToolsPills');
    const warnBox  = document.getElementById('selectedEditToolsWarning');

    // mark every matching <option> as selected
    for (const opt of select.options) {
      if (server.associatedTools.includes(opt.innerText)) {
        opt.selected = true;
      }
    }

    const chosen = Array.from(select.selectedOptions);
    const count  = chosen.length;
    const max = 6;

    const pillClasses =
    "inline-block px-2 py-1 text-xs font-medium " +
    "text-blue-800 bg-blue-100 rounded";

    // ─── 1. rebuild pills  ───────────────────────────────────
    pillsBox.innerHTML = "";                       // clear previous badges
    chosen.forEach(opt => {
      const span       = document.createElement("span");
      span.className   = pillClasses;
      span.textContent = opt.text;
      pillsBox.appendChild(span);
    });

    // ─── 2. warning when > max  ─────────────────────────────
    warnBox.textContent =
      count > max ? `Selected ${count} tools. Selecting more than ${max} tools can degrade agent performance with the server.` : "";

    // Fill in the associated resources field (new)
    const resourcesField = document.getElementById("edit-server-resources");
    if (resourcesField) {
      resourcesField.value = Array.isArray(server.associatedResources)
        ? server.associatedResources.join(", ")
        : "";
    }
    // Fill in the associated prompts field (new)
    const promptsField = document.getElementById("edit-server-prompts");
    if (promptsField) {
      promptsField.value = Array.isArray(server.associatedPrompts)
        ? server.associatedPrompts.join(", ")
        : "";
    }
    openModal("server-edit-modal");
  } catch (error) {
    console.error("Error fetching server details for editing:", error);
    alert("Failed to load server for editing");
  }
}

// Initialize CodeMirror editors
document.addEventListener("DOMContentLoaded", function () {
  window.headersEditor = window.CodeMirror.fromTextArea(
    document.getElementById("headers-editor"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );

  window.resourceContentEditor = window.CodeMirror.fromTextArea(
    document.getElementById("resource-content-editor"),
    {
      mode: "text/plain",
      theme: "monokai",
      lineNumbers: true,
      tabSize: 2,
    },
  );

  window.promptTemplateEditor = window.CodeMirror.fromTextArea(
    document.getElementById("prompt-template-editor"),
    {
      mode: "text/plain",
      theme: "monokai",
      lineNumbers: true,
      tabSize: 2,
    },
  );

  window.promptArgsEditor = window.CodeMirror.fromTextArea(
    document.getElementById("prompt-args-editor"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );

  window.editToolHeadersEditor = window.CodeMirror.fromTextArea(
    document.getElementById("edit-tool-headers"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );

  window.editToolSchemaEditor = window.CodeMirror.fromTextArea(
    document.getElementById("edit-tool-schema"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );

  window.editResourceContentEditor = window.CodeMirror.fromTextArea(
    document.getElementById("edit-resource-content"),
    {
      mode: "text/plain",
      theme: "monokai",
      lineNumbers: true,
      tabSize: 2,
    },
  );

  window.editPromptTemplateEditor = window.CodeMirror.fromTextArea(
    document.getElementById("edit-prompt-template"),
    {
      mode: "text/plain",
      theme: "monokai",
      lineNumbers: true,
      tabSize: 2,
    },
  );

  window.editPromptArgumentsEditor = window.CodeMirror.fromTextArea(
    document.getElementById("edit-prompt-arguments"),
    {
      mode: "application/json",
      theme: "monokai",
      lineNumbers: true,
      autoCloseBrackets: true,
      matchBrackets: true,
      tabSize: 2,
    },
  );

  // Add event listener to save resource content before submitting the edit resource form
  document
    .getElementById("edit-resource-form")
    .addEventListener("submit", function () {
      if (window.editResourceContentEditor) {
        window.editResourceContentEditor.save();
      }
    });

  // Set initial tab based on URL hash or default to Catalog
  const hash = window.location.hash || "#catalog";
  showTab(hash.substring(1));

  // Set checkbox states based on URL parameter
  const urlParams = new URLSearchParams(window.location.search);
  const includeInactive = urlParams.get("include_inactive") === "true";
  if (document.getElementById("show-inactive-tools"))
    document.getElementById("show-inactive-tools").checked = includeInactive;
  if (document.getElementById("show-inactive-resources"))
    document.getElementById("show-inactive-resources").checked =
      includeInactive;
  if (document.getElementById("show-inactive-prompts"))
    document.getElementById("show-inactive-prompts").checked = includeInactive;
  if (document.getElementById("show-inactive-gateways"))
    document.getElementById("show-inactive-gateways").checked = includeInactive;
  if (document.getElementById("show-inactive-servers"))
    document.getElementById("show-inactive-servers").checked = includeInactive;
});

function refreshEditors() {
  // Use a timeout to let the browser render the form as visible
  setTimeout(function () {
    window.headersEditor.refresh();
    window.schemaEditor.refresh();
  }, 100);
}

// <!-- Function to load aggregated metrics -->
async function loadAggregatedMetrics() {
  try {
    // Fetch aggregated metrics from the backend
    const response = await fetch(`${window.ROOT_PATH}/admin/metrics`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();

    // Use fallback for keys (snake_case vs camelCase)
    const toolsTotal =
      data.tools.total_executions ?? data.tools.totalExecutions ?? 0;
    const toolsSuccess =
      data.tools.successful_executions ?? data.tools.successfulExecutions ?? 0;
    const toolsFailed =
      data.tools.failed_executions ?? data.tools.failedExecutions ?? 0;
    const toolsFailureRate =
      data.tools.failure_rate ?? data.tools.failureRate ?? 0;
    const toolsMin =
      data.tools.min_response_time ?? data.tools.minResponseTime ?? "N/A";
    const toolsMax =
      data.tools.max_response_time ?? data.tools.maxResponseTime ?? "N/A";
    const toolsAvg =
      data.tools.avg_response_time ?? data.tools.avgResponseTime ?? "N/A";
    const toolsLast =
      data.tools.last_execution_time ?? data.tools.lastExecutionTime ?? "N/A";

    const resourcesTotal =
      data.resources.totalExecutions ?? data.resources.total_executions ?? 0;
    const resourcesSuccess =
      data.resources.successfulExecutions ??
      data.resources.successful_executions ??
      0;
    const resourcesFailed =
      data.resources.failedExecutions ?? data.resources.failed_executions ?? 0;
    const resourcesFailureRate =
      data.resources.failureRate ?? data.resources.failure_rate ?? 0;
    const resourcesMin =
      data.resources.minResponseTime ??
      data.resources.min_response_time ??
      "N/A";
    const resourcesMax =
      data.resources.maxResponseTime ??
      data.resources.max_response_time ??
      "N/A";
    const resourcesAvg =
      data.resources.avgResponseTime ??
      data.resources.avg_response_time ??
      "N/A";
    const resourcesLast =
      data.resources.lastExecutionTime ??
      data.resources.last_execution_time ??
      "N/A";

    const serversTotal =
      data.servers.totalExecutions ?? data.servers.total_executions ?? 0;
    const serversSuccess =
      data.servers.successfulExecutions ??
      data.servers.successful_executions ??
      0;
    const serversFailed =
      data.servers.failedExecutions ?? data.servers.failed_executions ?? 0;
    const serversFailureRate =
      data.servers.failureRate ?? data.servers.failure_rate ?? 0;
    const serversMin =
      data.servers.minResponseTime ?? data.servers.min_response_time ?? "N/A";
    const serversMax =
      data.servers.maxResponseTime ?? data.servers.max_response_time ?? "N/A";
    const serversAvg =
      data.servers.avgResponseTime ?? data.servers.avg_response_time ?? "N/A";
    const serversLast =
      data.servers.lastExecutionTime ??
      data.servers.last_execution_time ??
      "N/A";

    const promptsTotal =
      data.prompts.total_executions ?? data.prompts.totalExecutions ?? 0;
    const promptsSuccess =
      data.prompts.successful_executions ??
      data.prompts.successfulExecutions ??
      0;
    const promptsFailed =
      data.prompts.failed_executions ?? data.prompts.failedExecutions ?? 0;
    const promptsFailureRate =
      data.prompts.failure_rate ?? data.prompts.failureRate ?? 0;
    const promptsMin =
      data.prompts.min_response_time ?? data.prompts.minResponseTime ?? "N/A";
    const promptsMax =
      data.prompts.max_response_time ?? data.prompts.maxResponseTime ?? "N/A";
    const promptsAvg =
      data.prompts.avg_response_time ?? data.prompts.avgResponseTime ?? "N/A";
    const promptsLast =
      data.prompts.last_execution_time ??
      data.prompts.lastExecutionTime ??
      "N/A";

    // Build an aggregated metrics table
    const tableHTML = `
        <table class="min-w-full bg-white border dark:bg-gray-900 dark:text-gray-100">
          <thead>
            <tr>
              <th class="py-2 px-4 border dark:text-gray-200">Entity</th>
              <th class="py-2 px-4 border dark:text-gray-200">Total</th>
              <th class="py-2 px-4 border dark:text-gray-200">Successful</th>
              <th class="py-2 px-4 border dark:text-gray-200">Failed</th>
              <th class="py-2 px-4 border dark:text-gray-200">Failure Rate</th>
              <th class="py-2 px-4 border dark:text-gray-200">Min RT</th>
              <th class="py-2 px-4 border dark:text-gray-200">Max RT</th>
              <th class="py-2 px-4 border dark:text-gray-200">Avg RT</th>
              <th class="py-2 px-4 border dark:text-gray-200">Last Exec</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="py-2 px-4 border font-semibold dark:text-gray-200">Tools</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsTotal}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsSuccess}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsFailed}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsFailureRate}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsMin}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsMax}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsAvg}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${toolsLast}</td>
            </tr>
            <tr>
              <td class="py-2 px-4 border font-semibold dark:text-gray-200">Resources</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesTotal}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesSuccess}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesFailed}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesFailureRate}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesMin}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesMax}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesAvg}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${resourcesLast}</td>
            </tr>
            <tr>
              <td class="py-2 px-4 border font-semibold dark:text-gray-200">Servers</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversTotal}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversSuccess}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversFailed}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversFailureRate}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversMin}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversMax}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversAvg}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${serversLast}</td>
            </tr>
            <tr>
              <td class="py-2 px-4 border font-semibold dark:text-gray-200">Prompts</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsTotal}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsSuccess}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsFailed}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsFailureRate}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsMin}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsMax}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsAvg}</td>
              <td class="py-2 px-4 border dark:text-gray-300">${promptsLast}</td>
            </tr>
          </tbody>
        </table>
      `;
    document.getElementById("aggregated-metrics-content").innerHTML = tableHTML;

    // Update overall bar chart (Total Executions)
    if (window.metricsChartInstance) {
      window.metricsChartInstance.destroy();
    }
    // cma
    const ctx = document.getElementById("metricsChart").getContext("2d");
    window.metricsChartInstance = new window.Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Tools", "Resources", "Servers", "Prompts"],
        datasets: [
          {
            label: "Total Executions",
            data: [toolsTotal, resourcesTotal, serversTotal, promptsTotal],
            backgroundColor: [
              "rgba(54, 162, 235, 0.6)",
              "rgba(75, 192, 192, 0.6)",
              "rgba(255, 205, 86, 0.6)",
              "rgba(201, 203, 207, 0.6)",
            ],
            borderColor: [
              "rgb(54, 162, 235)",
              "rgb(75, 192, 192)",
              "rgb(255, 205, 86)",
              "rgb(201, 203, 207)",
            ],
            borderWidth: 1,
          },
        ],
      },
      options: {
        scales: {
          y: {
            beginAtZero: true,
          },
        },
      },
    });

    // Now load top items for each category
    loadTopTools();
    loadTopResources();
    loadTopServers();
    loadTopPrompts();
  } catch (error) {
    console.error("Error fetching aggregated metrics:", error);
    alert("Failed to load aggregated metrics");
  }
}

async function loadTopTools() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/tools`);
    const tools = await response.json();
    // Sort descending by executions
    tools.sort((a, b) => {
      const aCount = a.metrics?.totalExecutions ?? a.executionCount ?? 0;
      const bCount = b.metrics?.totalExecutions ?? b.executionCount ?? 0;
      return bCount - aCount;
    });
    const topTools = tools.slice(0, 5);
    let html = `<table class="min-w-full border">
        <thead>
          <tr>
            <th class="py-1 px-2 border dark:text-gray-300">ID</th>
            <th class="py-1 px-2 border dark:text-gray-300">Name</th>
            <th class="py-1 px-2 border dark:text-gray-300">Executions</th>
          </tr>
        </thead>
        <tbody>`;
    topTools.forEach((tool) => {
      const count = tool.metrics?.totalExecutions ?? tool.executionCount ?? 0;
      html += `<tr>
          <td class="py-1 px-2 border dark:text-gray-300">${tool.id}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${tool.name}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${count}</td>
        </tr>`;
    });
    html += `</tbody></table>`;
    document.getElementById("top-tools-content").innerHTML = html;
  } catch (error) {
    console.error("Error loading top tools:", error);
    document.getElementById("top-tools-content").innerHTML =
      `<p class="text-red-600">Error loading top tools.</p>`;
  }
}

async function loadTopResources() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/resources`);
    const resources = await response.json();
    resources.sort((a, b) => {
      const aCount = a.metrics?.totalExecutions ?? 0;
      const bCount = b.metrics?.totalExecutions ?? 0;
      return bCount - aCount;
    });
    const topResources = resources.slice(0, 5);
    let html = `<table class="min-w-full border">
        <thead>
          <tr>
            <th class="py-1 px-2 border dark:text-gray-300">ID</th>
            <th class="py-1 px-2 border dark:text-gray-300">URI</th>
            <th class="py-1 px-2 border dark:text-gray-300">Name</th>
            <th class="py-1 px-2 border dark:text-gray-300">Executions</th>
          </tr>
        </thead>
        <tbody>`;
    topResources.forEach((resource) => {
      const count = resource.metrics?.totalExecutions ?? 0;
      html += `<tr>
          <td class="py-1 px-2 border dark:text-gray-300">${resource.id}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${resource.uri}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${resource.name}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${count}</td>
        </tr>`;
    });
    html += `</tbody></table>`;
    document.getElementById("top-resources-content").innerHTML = html;
  } catch (error) {
    console.error("Error loading top resources:", error);
    document.getElementById("top-resources-content").innerHTML =
      `<p class="text-red-600">Error loading top resources.</p>`;
  }
}

async function loadTopServers() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/servers`);
    const servers = await response.json();
    servers.sort((a, b) => {
      const aCount = a.metrics?.totalExecutions ?? 0;
      const bCount = b.metrics?.totalExecutions ?? 0;
      return bCount - aCount;
    });
    const topServers = servers.slice(0, 5);
    let html = `<table class="min-w-full border">
        <thead>
          <tr>
            <th class="py-1 px-2 border dark:text-gray-300">ID</th>
            <th class="py-1 px-2 border dark:text-gray-300">Name</th>
            <th class="py-1 px-2 border dark:text-gray-300">Executions</th>
          </tr>
        </thead>
        <tbody>`;
    topServers.forEach((server) => {
      const count = server.metrics?.totalExecutions ?? 0;
      html += `<tr>
          <td class="py-1 px-2 border dark:text-gray-300">${server.id}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${server.name}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${count}</td>
        </tr>`;
    });
    html += `</tbody></table>`;
    document.getElementById("top-servers-content").innerHTML = html;
  } catch (error) {
    console.error("Error loading top servers:", error);
    document.getElementById("top-servers-content").innerHTML =
      `<p class="text-red-600">Error loading top servers.</p>`;
  }
}

async function loadTopPrompts() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/prompts`);
    const prompts = await response.json();
    prompts.sort((a, b) => {
      const aCount = a.metrics?.totalExecutions ?? 0;
      const bCount = b.metrics?.totalExecutions ?? 0;
      return bCount - aCount;
    });
    const topPrompts = prompts.slice(0, 5);
    let html = `<table class="min-w-full border">
        <thead>
          <tr>
            <th class="py-1 px-2 border dark:text-gray-300">ID</th>
            <th class="py-1 px-2 border dark:text-gray-300">Name</th>
            <th class="py-1 px-2 border dark:text-gray-300">Executions</th>
          </tr>
        </thead>
        <tbody>`;
    topPrompts.forEach((prompt) => {
      const count = prompt.metrics?.totalExecutions ?? 0;
      html += `<tr>
          <td class="py-1 px-2 border dark:text-gray-300">${prompt.id}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${prompt.name}</td>
          <td class="py-1 px-2 border dark:text-gray-300">${count}</td>
        </tr>`;
    });
    html += `</tbody></table>`;
    document.getElementById("top-prompts-content").innerHTML = html;
  } catch (error) {
    console.error("Error loading top prompts:", error);
    document.getElementById("top-prompts-content").innerHTML =
      `<p class="text-red-600">Error loading top prompts.</p>`;
  }
}

// Tool Test Modal
let currentTestTool = null;
let toolTestResultEditor = null;

function testTool(toolId) {
  // Fetch tool details from your backend (adjust the URL as needed)
  fetch(`${window.ROOT_PATH}/admin/tools/${toolId}`)
    .then((response) => response.json())
    .then((tool) => {
      currentTestTool = tool;
      // Use the tool's name as title and show its description (if available)
      document.getElementById("tool-test-modal-title").innerText =
        "Test Tool: " + tool.name;
      document.getElementById("tool-test-modal-description").innerText =
        tool.description || "No description available.";

      const container = document.getElementById("tool-test-form-fields");
      container.innerHTML = ""; // clear previous fields

      // Parse the input schema (assumed to be stored as a JSON string)
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
      if (schema.properties) {
        for (let key in schema.properties) {
          const prop = schema.properties[key];
          const fieldDiv = document.createElement("div");

          // Field label
          const label = document.createElement("label");
          label.innerText = key;
          label.className = "block text-sm font-medium text-gray-700";
          fieldDiv.appendChild(label);

          // If a description exists, display it as help text
          if (prop.description) {
            const description = document.createElement("small");
            description.innerText = prop.description;
            description.className = "text-gray-500 block mb-1";
            fieldDiv.appendChild(description);
          }

          // Input field (default to text input)
          const input = document.createElement("input");
          input.name = key;
          input.type = "text";
          input.required = schema.required && schema.required.includes(key);
          input.className =
            "mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:bg-gray-900 dark:text-gray-300 dark:border-gray-700 dark:focus:border-indigo-400 dark:focus:ring-indigo-400";
          fieldDiv.appendChild(input);

          container.appendChild(fieldDiv);
        }
      }
      openModal("tool-test-modal");
    })
    .catch((error) => {
      console.error("Error fetching tool details for testing:", error);
      alert("Failed to load tool details for testing.");
    });
}

async function runToolTest() {
  const form = document.getElementById("tool-test-form");
  const formData = new FormData(form);
  const params = {};
  for (const [key, value] of formData.entries()) {
    if (isNaN(value)) {
      if (value.toLowerCase() === "true" || value.toLowerCase() === "false") {
        params[key] = value.toLowerCase() === "true";
      } else {
        params[key] = value;
      }
    } else {
      params[key] = Number(value);
    }
  }

  const payload = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: currentTestTool.name,
    params: params,
  };

  // Show loading
  const loadingElement = document.getElementById("tool-test-loading");
  loadingElement.style.display = "block";
  const resultContainer = document.getElementById("tool-test-result");
  resultContainer.innerHTML = "";

  try {
    const response = await fetch(`${window.ROOT_PATH}/rpc`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      credentials: "include",
    });

    const result = await response.json();
    const resultStr = JSON.stringify(result, null, 2);

    toolTestResultEditor = window.CodeMirror(resultContainer, {
      value: resultStr,
      mode: "application/json",
      theme: "monokai",
      readOnly: true,
      lineNumbers: true,
    });
  } catch (error) {
    resultContainer.innerText = "Error: " + error;
  } finally {
    loadingElement.style.display = "none"; // Hide loading after fetch or error
  }
}


/* ---------------------------------------------------------------
 * Utility: copy a JSON string (or any text) to the system clipboard
 * ------------------------------------------------------------- */
function copyJsonToClipboard(sourceId) {
  // 1. Get the element that holds the JSON (can be a <pre>, <code>, <textarea>, etc.)
  const el = document.getElementById(sourceId);
  if (!el) {
    console.warn(`[copyJsonToClipboard] Source element "${sourceId}" not found.`);
    return;
  }

  // 2. Extract the text; fall back to textContent if value is undefined
  const text = "value" in el ? el.value : el.textContent;

  // 3. Copy to clipboard
  navigator.clipboard.writeText(text).then(
    () => {
      console.info("JSON copied to clipboard ✔️");
      // Optional: user feedback
      if (el.dataset.toast !== "off") {
        const toast = document.createElement("div");
        toast.textContent = "Copied!";
        toast.className =
          "fixed bottom-4 right-4 bg-green-600 text-white px-3 py-1 rounded shadow";
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 1500);
      }
    },
    (err) => {
      console.error("Clipboard write failed:", err);
      alert("Unable to copy to clipboard - see console for details.");
    }
  );
}

// Make it available to inline onclick handlers
window.copyJsonToClipboard = copyJsonToClipboard;


// Utility functions to open and close modals
function openModal(modalId) {
  document.getElementById(modalId).classList.remove("hidden");
}

function closeModal(modalId, clearId=null) {
  const modal = document.getElementById(modalId);

  if (clearId) {
    // Look up by id string
    const resultEl = document.getElementById(clearId);
    if (resultEl) resultEl.innerHTML = '';
  }

  modal.classList.add('hidden');
}

const integrationRequestMap = {
  MCP: ["SSE", "STREAMABLE", "STDIO"],
  REST: ["GET", "POST", "PUT", "DELETE"],
};

function updateRequestTypeOptions(preselectedValue = null) {
  const requestTypeSelect = document.getElementById("requestType");
  const integrationTypeSelect = document.getElementById("integrationType");
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
}

/**
 * Initialise a multi-select so it displays the chosen items
 * and warns when the count exceeds a limit.
 *
 * @param {string} selectId   - id of the <select multiple>
 * @param {string} infoId     - id of the div that lists selected names
 * @param {string} warnId     - id of the warning div
 * @param {number} max        - maximum allowed items before warning
 */
function initToolSelect(selectId,
                        pillsId,
                        warnId,
                        max = 6) {

  const select   = document.getElementById(selectId);
  const pillsBox = document.getElementById(pillsId);
  const warnBox  = document.getElementById(warnId);

  const pillClasses =
    "inline-block px-2 py-1 text-xs font-medium " +
    "text-blue-800 bg-blue-100 rounded";

  function update() {
    const chosen = Array.from(select.selectedOptions);
    const count  = chosen.length;

    // ─── 1. rebuild pills  ───────────────────────────────────
    pillsBox.innerHTML = "";                       // clear previous badges
    chosen.forEach(opt => {
      const span       = document.createElement("span");
      span.className   = pillClasses;
      span.textContent = opt.text;
      pillsBox.appendChild(span);
    });

    // ─── 2. warning when > max  ─────────────────────────────
    warnBox.textContent =
      count > max ? `Selected ${count} tools. Selecting more than ${max} tools can degrade agent performance with the server.` : "";
  }

  update();                       // initial render
  select.addEventListener("change", update);
}

document.addEventListener("DOMContentLoaded", () => {
  initToolSelect("associatedTools",
                 "selectedToolsPills",
                 "selectedToolsWarning",
                 6);
});

document.addEventListener("DOMContentLoaded", () => {
  initToolSelect("edit-server-tools",
                 "selectedEditToolsPills",
                 "selectedEditToolsWarning",
                 6);
});

window.toggleInactiveItems = toggleInactiveItems;
window.viewTool = viewTool;
window.editTool = editTool;
window.testTool = testTool;
window.viewResource = viewResource;
window.editResource = editResource;
window.viewPrompt = viewPrompt;
window.editPrompt = editPrompt;
window.viewGateway = viewGateway;
window.editGateway = editGateway;
window.viewServer = viewServer;
window.editServer = editServer;
window.runToolTest = runToolTest;
window.closeModal = closeModal;
