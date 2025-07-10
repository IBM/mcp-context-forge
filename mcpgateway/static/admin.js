/**
 * HTML-escape function to prevent XSS attacks
 * Escapes characters that have special meaning in HTML
 */
function escapeHtml(unsafe) {
  if (unsafe === null || unsafe === undefined) return '';
  return String(unsafe)
    .replace(/&/g,  "&amp;")
    .replace(/</g,  "&lt;")
    .replace(/>/g,  "&gt;")
    .replace(/"/g,  "&quot;")
    .replace(/'/g,  "&#039;")
    .replace(/`/g, "&#x60;");   // protects template-literal back-ticks
}

/**
 * Safely create DOM elements with text content
 * Use this instead of innerHTML for user data
 */
function createSafeElement(tagName, textContent = '', className = '') {
  const element = document.createElement(tagName);
  if (textContent) {
    element.textContent = textContent; // Safe - no HTML interpretation
  }
  if (className) {
    element.className = className;
  }
  return element;
}

/**
 * Safely set innerHTML with escaped content
 * For trusted HTML content from our own backend
 */
function safeSetInnerHTML(element, htmlContent) {
  // If the content is from our own trusted backend, we can set it directly
  // For user-generated content, use textContent instead
  element.innerHTML = htmlContent;
}

/**
 * Build a <table> element safely from an array of rows.
 * Each row = array of cell values (strings, numbers, etc.).
 */
function buildSafeTable(headers, rows) {
  const table   = document.createElement('table');
  table.className = 'min-w-full border';

  /* --- header --- */
  const thead   = table.createTHead();
  const htr     = thead.insertRow();
  headers.forEach(h => {
    const th      = document.createElement('th');
    th.className  = 'py-1 px-2 border dark:text-gray-300';
    th.textContent = h;
    htr.appendChild(th);
  });

  /* --- body --- */
  const tbody = table.appendChild(document.createElement('tbody'));
  rows.forEach(row => {
    const tr = tbody.insertRow();
    row.forEach(cellVal => {
      const td      = tr.insertCell();
      td.className  = 'py-1 px-2 border dark:text-gray-300';
      td.textContent = cellVal;        // <- never interprets HTML
    });
  });

  return table;
}

// helper for anything that lands in src, href, action
function safeUrl(u, allowData = false) {
  try {
    const url = new URL(u, document.baseURI);      // honours <base>
    const ok  = ["http:", "https:"];               // allowed schemes
    if (allowData) ok.push("data:");
    return ok.includes(url.protocol) ? url.href : "";
  } catch {
    return "";   // malformed → strip it
  }
}

// Tab handling
function showTab(tabName) {
  /* ---------- navigation styling ---------- */
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
  document.querySelectorAll(".tab-link").forEach((l) => {
    l.classList.remove(
      "border-indigo-500", "text-indigo-600",
      "dark:text-indigo-500", "dark:border-indigo-400",
    );
    l.classList.add(
      "border-transparent", "text-gray-500",
      "dark:text-gray-400",
    );
  });

  /* ---------- reveal chosen panel ---------- */
  document.getElementById(`${tabName}-panel`).classList.remove("hidden");
  const nav = document.querySelector(`[href="#${tabName}"]`);
  nav.classList.add(
    "border-indigo-500", "text-indigo-600",
    "dark:text-indigo-500", "dark:border-indigo-400",
  );
  nav.classList.remove(
    "border-transparent", "text-gray-500",
    "dark:text-gray-400",
  );

  /* ---------- lazy-loaders ---------- */
  if (tabName === "metrics") loadAggregatedMetrics();

  if (tabName === "version-info") {
      const panel = document.getElementById("version-info-panel");
      if (panel && panel.innerHTML.trim() === "") {
        fetch(`${window.ROOT_PATH}/version?partial=true`)
          .then((resp) => {
            if (!resp.ok) throw new Error("Network response was not ok");
            return resp.text();
          })
          .then((html) => {
            panel.innerHTML = html; // Direct assignment for trusted backend content
          })
          .catch((err) => {
            console.error("Failed to load version info:", err);
            panel.innerHTML =
              "<p class='text-red-600'>Failed to load version info.</p>";
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

// Function to check if the "Show Inactive" checkbox is checked
function isInactiveChecked(type) {
  const checkbox = document.getElementById(`show-inactive-${type}`);
  if (checkbox.checked) {
    return true;
  } else {
    return false;
  }
}

function handleToggleSubmit(event, type) {
  // Prevent form from submitting immediately
  event.preventDefault();

  // Get the value of 'is_inactive_checked' from the function
  const is_inactive_checked = isInactiveChecked(type);

  // Dynamically add the 'is_inactive_checked' value to the form
  const form = event.target;
  const hiddenField = document.createElement('input');
  hiddenField.type = 'hidden';
  hiddenField.name = 'is_inactive_checked';
  hiddenField.value = is_inactive_checked;

  form.appendChild(hiddenField);

  // Now submit the form
  form.submit();
}

function handleSubmitWithConfirmation(event, type) {
  event.preventDefault();

  const confirmationMessage = `Are you sure you want to permanently delete this ${type}? (Deactivation is reversible, deletion is permanent)`;
  const confirmation = confirm(confirmationMessage);
  if (!confirmation) {
    return false; // Prevent form submission
  }

  return handleToggleSubmit(event, type); // Proceed with your original function
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
        <p><strong>Username:</strong> ${escapeHtml(tool.auth.username)}</p>
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
        <p><strong>Header Key:</strong> ${escapeHtml(tool.auth.authHeaderKey)}</p>
        <p><strong>Header Value:</strong> ********</p>
      `;
    } else {
      authHTML = `<p><strong>Authentication Type:</strong> None</p>`;
    }

    // Helper function to create annotation badges - FIXED
    const renderAnnotations = (annotations) => {
      if (!annotations || Object.keys(annotations).length === 0) {
        return '<p><strong>Annotations:</strong> <span class="text-gray-500">None</span></p>';
      }

      const badges = [];

      // Show title if present - ESCAPED
      if (annotations.title) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mr-1 mb-1">${escapeHtml(annotations.title)}</span>`);
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

      // Show any other custom annotations - ESCAPED
      Object.keys(annotations).forEach(key => {
        if (!['title', 'readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'].includes(key)) {
          const value = annotations[key];
          badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 mr-1 mb-1">${escapeHtml(key)}: ${escapeHtml(value)}</span>`);
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
        <p><strong>Name:</strong> ${escapeHtml(tool.name)}</p>
        <p><strong>URL:</strong> ${escapeHtml(tool.url)}</p>
        <p><strong>Type:</strong> ${escapeHtml(tool.integrationType)}</p>
        <p><strong>Description:</strong> ${escapeHtml(tool.description || "N/A")}</p>
        <p><strong>Request Type:</strong> ${escapeHtml(tool.requestType || "N/A")}</p>
        ${authHTML}
        ${renderAnnotations(tool.annotations)}
        <div>
          <strong>Headers:</strong>
          <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(tool.headers || {}, null, 2))}</pre>
        </div>
        <div>
          <strong>Input Schema:</strong>
          <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(tool.inputSchema || {}, null, 2))}</pre>
        </div>
        <div>
          <strong>Metrics:</strong>
          <ul class="list-disc list-inside ml-4">
            <li>Total Executions: ${escapeHtml(tool.metrics?.totalExecutions ?? 0)}</li>
            <li>Successful Executions: ${escapeHtml(tool.metrics?.successfulExecutions ?? 0)}</li>
            <li>Failed Executions: ${escapeHtml(tool.metrics?.failedExecutions ?? 0)}</li>
            <li>Failure Rate: ${escapeHtml(tool.metrics?.failureRate ?? 0)}</li>
            <li>Min Response Time: ${escapeHtml(tool.metrics?.minResponseTime ?? "N/A")}</li>
            <li>Max Response Time: ${escapeHtml(tool.metrics?.maxResponseTime ?? "N/A")}</li>
            <li>Average Response Time: ${escapeHtml(tool.metrics?.avgResponseTime ?? "N/A")}</li>
            <li>Last Execution Time: ${escapeHtml(tool.metrics?.lastExecutionTime ?? "N/A")}</li>
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

    const isInActiveCheckedBool = isInactiveChecked('tools');
    let hiddenField = document.getElementById("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      document.getElementById("edit-tool-form").appendChild(hiddenField);
    }
    hiddenField.value = isInActiveCheckedBool;

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
    
    const contentDisplay = typeof content === "object"
      ? JSON.stringify(content, null, 2)
      : content;
    
    document.getElementById("resource-details").innerHTML = `
          <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
            <p><strong>URI:</strong> ${escapeHtml(resource.uri)}</p>
            <p><strong>Name:</strong> ${escapeHtml(resource.name)}</p>
            <p><strong>Type:</strong> ${escapeHtml(resource.mimeType || "N/A")}</p>
            <p><strong>Description:</strong> ${escapeHtml(resource.description || "N/A")}</p>
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
              <pre class="mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80">${escapeHtml(contentDisplay)}</pre>
            </div>
            <div>
              <strong>Metrics:</strong>
              <ul class="list-disc list-inside ml-4">
                <li>Total Executions: ${escapeHtml(resource.metrics.totalExecutions)}</li>
                <li>Successful Executions: ${escapeHtml(resource.metrics.successfulExecutions)}</li>
                <li>Failed Executions: ${escapeHtml(resource.metrics.failedExecutions)}</li>
                <li>Failure Rate: ${escapeHtml(resource.metrics.failureRate)}</li>
                <li>Min Response Time: ${escapeHtml(resource.metrics.minResponseTime)}</li>
                <li>Max Response Time: ${escapeHtml(resource.metrics.maxResponseTime)}</li>
                <li>Average Response Time: ${escapeHtml(resource.metrics.avgResponseTime)}</li>
                <li>Last Execution Time: ${escapeHtml(resource.metrics.lastExecutionTime || "N/A")}</li>
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
    const isInActiveCheckedBool = isInactiveChecked('resources');
    let hiddenField = document.getElementById("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      document.getElementById("edit-resource-form").appendChild(hiddenField);
    }
    hiddenField.value = isInActiveCheckedBool;

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
        <p><strong>Name:</strong> ${escapeHtml(prompt.name)}</p>
        <p><strong>Description:</strong> ${escapeHtml(prompt.description || "N/A")}</p>
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
          <pre class="mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100">${escapeHtml(prompt.template)}</pre>
        </div>
        <div>
          <strong>Arguments:</strong>
          <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(prompt.arguments || [], null, 2))}</pre>
        </div>
        <div>
          <strong>Metrics:</strong>
          <ul class="list-disc list-inside ml-4">
            <li>Total Executions: ${escapeHtml(prompt.metrics?.totalExecutions ?? 0)}</li>
            <li>Successful Executions: ${escapeHtml(prompt.metrics?.successfulExecutions ?? 0)}</li>
            <li>Failed Executions: ${escapeHtml(prompt.metrics?.failedExecutions ?? 0)}</li>
            <li>Failure Rate: ${escapeHtml(prompt.metrics?.failureRate ?? 0)}</li>
            <li>Min Response Time: ${escapeHtml(prompt.metrics?.minResponseTime ?? "N/A")}</li>
            <li>Max Response Time: ${escapeHtml(prompt.metrics?.maxResponseTime ?? "N/A")}</li>
            <li>Average Response Time: ${escapeHtml(prompt.metrics?.avgResponseTime ?? "N/A")}</li>
            <li>Last Execution Time: ${escapeHtml(prompt.metrics?.lastExecutionTime ?? "N/A")}</li>
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

    const isInActiveCheckedBool = isInactiveChecked('resources');
    let hiddenField = document.getElementById("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      document.getElementById("edit-prompt-form").appendChild(hiddenField);
    }
    hiddenField.value = isInActiveCheckedBool;

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
          <p><strong>Username:</strong> ${escapeHtml(gateway.authUsername)}</p>
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
          <p><strong>Header Key:</strong> ${escapeHtml(gateway.authHeaderKey)}</p>
          <p><strong>Header Value:</strong> ********</p>
        `;
    } else {
      authHTML = `<p><strong>Authentication Type:</strong> None</p>`;
    }

  document.getElementById("gateway-details").innerHTML = `
    <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
      <p><strong>Name:</strong> ${escapeHtml(gateway.name)}</p>
      <p><strong>URL:</strong> ${escapeHtml(gateway.url)}</p>
      <p><strong>Description:</strong> ${escapeHtml(gateway.description || "N/A")}</p>
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
      <p><strong>Last Seen:</strong> ${escapeHtml(gateway.lastSeen || "Never")}</p>
      ${authHTML}
      <div>
        <strong>Capabilities:</strong>
        <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(gateway.capabilities || {}, null, 2))}</pre>
      </div>
    </div>
  `;

    openModal("gateway-modal");
  } catch (error) {
    console.error("Error fetching gateway details:", error);
    alert("Failed to load gateway details");
  }
}

// Global variables for gateway test editors
let gatewayTestHeadersEditor = null;
let gatewayTestBodyEditor = null;
let gatewayTestFormHandler = null;
let gatewayTestCloseHandler = null;

// Safe editor refresh with existence checks
function refreshEditors() {
  setTimeout(function () {
    if (window.headersEditor && typeof window.headersEditor.refresh === 'function') {
      try {
        window.headersEditor.refresh();
        console.log('✓ Refreshed headersEditor');
      } catch (error) {
        console.error('Failed to refresh headersEditor:', error);
      }
    }
    
    if (window.schemaEditor && typeof window.schemaEditor.refresh === 'function') {
      try {
        window.schemaEditor.refresh();
        console.log('✓ Refreshed schemaEditor');
      } catch (error) {
        console.error('Failed to refresh schemaEditor:', error);
      }
    }
  }, 100);
}

// Cleaned up testGateway function with proper event listener management
async function testGateway(gatewayURL) {
  try {
    console.log('Opening gateway test modal for:', gatewayURL);
    
    // Clean up any existing event listeners first
    cleanupGatewayTestModal();
    
    // Open the modal
    openModal("gateway-test-modal");
    
    // Initialize CodeMirror editors if they don't exist
    if (!gatewayTestHeadersEditor) {
      const headersElement = document.getElementById('headers-json');
      if (headersElement && window.CodeMirror) {
        gatewayTestHeadersEditor = window.CodeMirror.fromTextArea(headersElement, {
          mode: "application/json",
          lineNumbers: true,
        });
        gatewayTestHeadersEditor.setSize(null, 100);
        console.log('✓ Initialized gateway test headers editor');
      }
    }

    if (!gatewayTestBodyEditor) {
      const bodyElement = document.getElementById('body-json');
      if (bodyElement && window.CodeMirror) {
        gatewayTestBodyEditor = window.CodeMirror.fromTextArea(bodyElement, {
          mode: "application/json",
          lineNumbers: true
        });
        gatewayTestBodyEditor.setSize(null, 100);
        console.log('✓ Initialized gateway test body editor');
      }
    }

    // Set form action and URL
    const form = document.getElementById("gateway-test-form");
    const urlInput = document.getElementById("gateway-test-url");
    
    if (form) form.action = `${window.ROOT_PATH}/admin/gateways/test`;
    if (urlInput) urlInput.value = gatewayURL;

    // Set up form submission handler
    if (form) {
      gatewayTestFormHandler = async function(e) {
        await handleGatewayTestSubmit(e);
      };
      form.addEventListener("submit", gatewayTestFormHandler);
    }

    // Set up close button handler
    const closeButton = document.getElementById("gateway-test-close");
    if (closeButton) {
      gatewayTestCloseHandler = function() {
        handleGatewayTestClose();
      };
      closeButton.addEventListener("click", gatewayTestCloseHandler);
    }

  } catch (error) {
    console.error('Error setting up gateway test modal:', error);
    alert('Failed to open gateway test modal');
  }
}

// Handle gateway test form submission
async function handleGatewayTestSubmit(e) {
  e.preventDefault();

  const loading = document.getElementById("loading");
  const responseDiv = document.getElementById("response-json");
  const resultDiv = document.getElementById("test-result");

  try {
    // Show loading
    if (loading) loading.classList.remove("hidden");
    if (resultDiv) resultDiv.classList.add("hidden");

    const form = e.target;
    const url = form.action;

    // Get form data
    const formData = new FormData(form);
    const base_url = formData.get("gateway-test-url");
    const method = formData.get("method");
    const path = formData.get("path");
    
    // Get CodeMirror content safely
    let headersRaw = "";
    let bodyRaw = "";
    
    if (gatewayTestHeadersEditor) {
      try {
        headersRaw = gatewayTestHeadersEditor.getValue() || "";
      } catch (error) {
        console.error('Error getting headers value:', error);
      }
    }
    
    if (gatewayTestBodyEditor) {
      try {
        bodyRaw = gatewayTestBodyEditor.getValue() || "";
      } catch (error) {
        console.error('Error getting body value:', error);
      }
    }

    // Parse JSON safely
    let headersParsed, bodyParsed;
    try {
      headersParsed = headersRaw.trim() ? JSON.parse(headersRaw) : undefined;
      bodyParsed = bodyRaw.trim() ? JSON.parse(bodyRaw) : undefined;
    } catch (err) {
      if (responseDiv) {
        responseDiv.textContent = `❌ Invalid JSON: ${err.message}`;
      }
      if (resultDiv) resultDiv.classList.remove("hidden");
      return;
    }

    const payload = {
      base_url,
      method,
      path,
      headers: headersParsed,
      body: bodyParsed,
    };

    // Make the request with timeout
    const response = await fetchWithTimeout(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const result = await response.json();
    
    if (responseDiv) {
      responseDiv.textContent = JSON.stringify(result, null, 2);
    }

  } catch (error) {
    console.error('Gateway test error:', error);
    if (responseDiv) {
      responseDiv.textContent = `❌ Error: ${error.message}`;
    }
  } finally {
    if (loading) loading.classList.add("hidden");
    if (resultDiv) resultDiv.classList.remove("hidden");
  }
}

// Handle gateway test modal close
function handleGatewayTestClose() {
  try {
    // Reset form
    const form = document.getElementById("gateway-test-form");
    if (form) form.reset();

    // Clear editors
    if (gatewayTestHeadersEditor) {
      try {
        gatewayTestHeadersEditor.setValue('');
      } catch (error) {
        console.error('Error clearing headers editor:', error);
      }
    }
    
    if (gatewayTestBodyEditor) {
      try {
        gatewayTestBodyEditor.setValue('');
      } catch (error) {
        console.error('Error clearing body editor:', error);
      }
    }

    // Clear response
    const responseDiv = document.getElementById("response-json");
    const resultDiv = document.getElementById("test-result");
    
    if (responseDiv) responseDiv.textContent = '';
    if (resultDiv) resultDiv.classList.add("hidden");

    // Close modal
    closeModal("gateway-test-modal");
    
  } catch (error) {
    console.error('Error closing gateway test modal:', error);
  }
}

// Clean up gateway test modal event listeners
function cleanupGatewayTestModal() {
  try {
    const form = document.getElementById("gateway-test-form");
    const closeButton = document.getElementById("gateway-test-close");

    // Remove existing event listeners
    if (form && gatewayTestFormHandler) {
      form.removeEventListener("submit", gatewayTestFormHandler);
      gatewayTestFormHandler = null;
    }

    if (closeButton && gatewayTestCloseHandler) {
      closeButton.removeEventListener("click", gatewayTestCloseHandler);
      gatewayTestCloseHandler = null;
    }

    console.log('✓ Cleaned up gateway test modal listeners');
  } catch (error) {
    console.error('Error cleaning up gateway test modal:', error);
  }
}

// Enhanced modal functions with proper cleanup
function openModal(modalId) {
  try {
    const modal = document.getElementById(modalId);
    if (!modal) {
      console.error(`Modal ${modalId} not found`);
      return;
    }
    
    // Reset modal state
    resetModalState(modalId);
    
    modal.classList.remove("hidden");
    console.log(`✓ Opened modal: ${modalId}`);
  } catch (error) {
    console.error(`Error opening modal ${modalId}:`, error);
  }
}

function closeModal(modalId, clearId = null) {
  try {
    const modal = document.getElementById(modalId);
    if (!modal) {
      console.error(`Modal ${modalId} not found`);
      return;
    }

    // Clear specified content if provided
    if (clearId) {
      const resultEl = document.getElementById(clearId);
      if (resultEl) resultEl.innerHTML = '';
    }

    // Clean up specific modal types
    if (modalId === "gateway-test-modal") {
      cleanupGatewayTestModal();
    }

    modal.classList.add('hidden');
    console.log(`✓ Closed modal: ${modalId}`);
  } catch (error) {
    console.error(`Error closing modal ${modalId}:`, error);
  }
}

function resetModalState(modalId) {
  try {
    // Clear any dynamic content
    const modalContent = document.querySelector(`#${modalId} [data-dynamic-content]`);
    if (modalContent) {
      modalContent.innerHTML = '';
    }
    
    // Reset any forms in the modal
    const forms = document.querySelectorAll(`#${modalId} form`);
    forms.forEach(form => {
      try {
        form.reset();
      } catch (error) {
        console.error('Error resetting form:', error);
      }
    });
    
    console.log(`✓ Reset modal state: ${modalId}`);
  } catch (error) {
    console.error(`Error resetting modal state ${modalId}:`, error);
  }
}

// Enhanced fetch functions with better error handling
async function viewTool(toolId) {
  try {
    console.log(`Fetching tool details for ID: ${toolId}`);
    
    const response = await fetchWithTimeout(`${window.ROOT_PATH}/admin/tools/${toolId}`);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const tool = await response.json();

    let authHTML = "";
    if (tool.auth?.username && tool.auth?.password) {
      authHTML = `
        <p><strong>Authentication Type:</strong> Basic</p>
        <p><strong>Username:</strong> ${escapeHtml(tool.auth.username)}</p>
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
        <p><strong>Header Key:</strong> ${escapeHtml(tool.auth.authHeaderKey)}</p>
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

      // Show title if present - ESCAPED
      if (annotations.title) {
        badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 mr-1 mb-1">${escapeHtml(annotations.title)}</span>`);
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

      // Show any other custom annotations - ESCAPED
      Object.keys(annotations).forEach(key => {
        if (!['title', 'readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'].includes(key)) {
          const value = annotations[key];
          badges.push(`<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 mr-1 mb-1">${escapeHtml(key)}: ${escapeHtml(value)}</span>`);
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

    const toolDetailsDiv = document.getElementById("tool-details");
    if (toolDetailsDiv) {
      toolDetailsDiv.innerHTML = `
        <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
          <p><strong>Name:</strong> ${escapeHtml(tool.name)}</p>
          <p><strong>URL:</strong> ${escapeHtml(tool.url)}</p>
          <p><strong>Type:</strong> ${escapeHtml(tool.integrationType)}</p>
          <p><strong>Description:</strong> ${escapeHtml(tool.description || "N/A")}</p>
          <p><strong>Request Type:</strong> ${escapeHtml(tool.requestType || "N/A")}</p>
          ${authHTML}
          ${renderAnnotations(tool.annotations)}
          <div>
            <strong>Headers:</strong>
            <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(tool.headers || {}, null, 2))}</pre>
          </div>
          <div>
            <strong>Input Schema:</strong>
            <pre class="mt-1 bg-gray-100 p-2 rounded dark:bg-gray-800 dark:text-gray-100">${escapeHtml(JSON.stringify(tool.inputSchema || {}, null, 2))}</pre>
          </div>
          <div>
            <strong>Metrics:</strong>
            <ul class="list-disc list-inside ml-4">
              <li>Total Executions: ${escapeHtml(tool.metrics?.totalExecutions ?? 0)}</li>
              <li>Successful Executions: ${escapeHtml(tool.metrics?.successfulExecutions ?? 0)}</li>
              <li>Failed Executions: ${escapeHtml(tool.metrics?.failedExecutions ?? 0)}</li>
              <li>Failure Rate: ${escapeHtml(tool.metrics?.failureRate ?? 0)}</li>
              <li>Min Response Time: ${escapeHtml(tool.metrics?.minResponseTime ?? "N/A")}</li>
              <li>Max Response Time: ${escapeHtml(tool.metrics?.maxResponseTime ?? "N/A")}</li>
              <li>Average Response Time: ${escapeHtml(tool.metrics?.avgResponseTime ?? "N/A")}</li>
              <li>Last Execution Time: ${escapeHtml(tool.metrics?.lastExecutionTime ?? "N/A")}</li>
            </ul>
          </div>
        </div>
      `;
    }

    openModal("tool-modal");
    console.log('✓ Tool details loaded successfully');

  } catch (error) {
    console.error("Error fetching tool details:", error);
    
    if (error.name === 'AbortError') {
      alert('Request timed out. Please try again.');
    } else {
      alert(`Failed to load tool details: ${error.message}`);
    }
  }
}

async function editGateway(gatewayId) {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/gateways/${gatewayId}`);
    const gateway = await response.json();

    const isInActiveCheckedBool = isInactiveChecked('gateways');
    let hiddenField = document.getElementById("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      document.getElementById("edit-gateway-form").appendChild(hiddenField);
    }
    hiddenField.value = isInActiveCheckedBool;

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

/* ---------------------------------------------------------------
 * Function: viewServer  (server detail modal)
 * ------------------------------------------------------------- */
async function viewServer(serverId) {
  try {
    const resp   = await fetch(`${window.ROOT_PATH}/admin/servers/${serverId}`);
    const server = await resp.json();

    /* badge helper */
    const badge = (item, map) => {
      if (typeof item === "object") {
        return `<span class="inline-block px-2 py-1 text-xs font-medium
                       text-blue-800 bg-blue-100 rounded">
                  ${escapeHtml(item.id)}: ${escapeHtml(item.name)}
                </span>`;
      }
      const name = map[item] || item;
      return `<span class="inline-block px-2 py-1 text-xs font-medium
                     text-blue-800 bg-blue-100 rounded">
                ${escapeHtml(name)}
              </span>`;
    };

    const toolsHTML = (server.associatedTools     || []).map(i => badge(i, window.toolMapping)).join(" ") || "N/A";
    const resHTML   = (server.associatedResources || []).map(i => badge(i, window.resourceMapping)).join(" ") || "N/A";
    const prmHTML   = (server.associatedPrompts   || []).map(i => badge(i, window.promptMapping)).join(" ") || "N/A";

    const iconHTML  = server.icon
      ? `<img src="${safeUrl(server.icon, true)}" alt="${escapeHtml(server.name)} icon" class="h-8 w-8">`
      : "N/A";

    document.getElementById("server-details").innerHTML = `
      <div class="space-y-2 dark:bg-gray-900 dark:text-gray-100">
        <p><strong>Name:</strong> ${escapeHtml(server.name)}</p>
        <p><strong>Description:</strong> ${escapeHtml(server.description || "N/A")}</p>
        <p><strong>Status:</strong>
          <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full
                ${server.isActive ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}">
            ${server.isActive ? "Active" : "Inactive"}
          </span>
        </p>
        <div><strong>Icon:</strong> ${iconHTML}</div>
        <div><strong>Associated Tools:</strong> <div class="mt-1 space-x-1">${toolsHTML}</div></div>
        <div><strong>Associated Resources:</strong> <div class="mt-1 space-x-1">${resHTML}</div></div>
        <div><strong>Associated Prompts:</strong> <div class="mt-1 space-x-1">${prmHTML}</div></div>
        <div>
          <strong>Metrics:</strong>
          <ul class="list-disc list-inside ml-4">
            <li>Total Executions: ${escapeHtml(server.metrics.totalExecutions)}</li>
            <li>Successful Executions: ${escapeHtml(server.metrics.successfulExecutions)}</li>
            <li>Failed Executions: ${escapeHtml(server.metrics.failedExecutions)}</li>
            <li>Failure Rate: ${escapeHtml(server.metrics.failureRate)}</li>
            <li>Min RT: ${escapeHtml(server.metrics.minResponseTime)}</li>
            <li>Max RT: ${escapeHtml(server.metrics.maxResponseTime)}</li>
            <li>Avg RT: ${escapeHtml(server.metrics.avgResponseTime)}</li>
            <li>Last Exec Time: ${escapeHtml(server.metrics.lastExecutionTime || "N/A")}</li>
          </ul>
        </div>
      </div>`;

    openModal("server-modal");
  } catch (err) {
    console.error("Server-detail error:", err);
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

    const isInActiveCheckedBool = isInactiveChecked('servers');
    let hiddenField = document.getElementById("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      document.getElementById("edit-server-form").appendChild(hiddenField);
    }
    hiddenField.value = isInActiveCheckedBool;
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


/* ---------------------------------------------------------------
 * Function: loadAggregatedMetrics  (aggregated dashboard)
 * ------------------------------------------------------------- */
async function loadAggregatedMetrics() {
  try {
    const resp = await fetch(`${window.ROOT_PATH}/admin/metrics`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    /* ---------- helpers -------------------------------------- */
    const camel = (s) => s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    const get   = (cat, k, d = 0) => data[cat][k] ?? data[cat][camel(k)] ?? d;

    const pack = (cat) => ({
      total : get(cat, "total_executions"),
      ok    : get(cat, "successful_executions"),
      fail  : get(cat, "failed_executions"),
      rate  : get(cat, "failure_rate"),
      min   : get(cat, "min_response_time",  "N/A"),
      max   : get(cat, "max_response_time",  "N/A"),
      avg   : get(cat, "avg_response_time",  "N/A"),
      last  : get(cat, "last_execution_time","N/A"),
    });

    const tools     = pack("tools");
    const resources = pack("resources");
    const servers   = pack("servers");
    const prompts   = pack("prompts");

    /* ---------- table ---------------------------------------- */
    const row = (lbl, d) => `
      <tr>
        <td class="py-2 px-4 border font-semibold dark:text-gray-200">${lbl}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.total}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.ok}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.fail}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.rate}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.min}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.max}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.avg}</td>
        <td class="py-2 px-4 border dark:text-gray-300">${d.last}</td>
      </tr>`;

    document.getElementById("aggregated-metrics-content").innerHTML = `
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
          ${row("Tools",      tools)}
          ${row("Resources",  resources)}
          ${row("Servers",    servers)}
          ${row("Prompts",    prompts)}
        </tbody>
      </table>`;

    /* ---------- bar chart (total executions) ----------------- */
    if (window.metricsChartInstance) window.metricsChartInstance.destroy();

    const ctx = document.getElementById("metricsChart").getContext("2d");
    window.metricsChartInstance = new Chart(ctx, {
      type : "bar",
      data : {
        labels   : ["Tools", "Resources", "Servers", "Prompts"],
        datasets : [{
          label : "Total Executions",
          data  : [tools.total, resources.total, servers.total, prompts.total],
          backgroundColor : [
            "rgba(54,162,235,0.6)",
            "rgba(75,192,192,0.6)",
            "rgba(255,205,86,0.6)",
            "rgba(201,203,207,0.6)",
          ],
          borderColor     : [
            "rgb(54,162,235)",
            "rgb(75,192,192)",
            "rgb(255,205,86)",
            "rgb(201,203,207)",
          ],
          borderWidth : 1,
        }],
      },
      options : { scales : { y : { beginAtZero : true } } },
    });

    /* ---------- sub-tables (unchanged loaders) --------------- */
    loadTopTools();
    loadTopResources();
    loadTopServers();
    loadTopPrompts();
  } catch (err) {
    console.error("Aggregated metrics error:", err);
    alert("Failed to load aggregated metrics");
  }
}


async function loadTopTools() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/tools`);
    const tools    = await response.json();

    tools.sort((a, b) =>
      (b.metrics?.totalExecutions ?? 0) - (a.metrics?.totalExecutions ?? 0)
    );

    const top = tools.slice(0, 5);
    const rows = top.map(t => [
      t.id,
      t.name,                              // ← will be textContent-escaped
      t.metrics?.totalExecutions ?? 0
    ]);

    const table = buildSafeTable(['ID', 'Name', 'Executions'], rows);
    const slot  = document.getElementById('top-tools-content');
    slot.innerHTML = '';                   // clear previous
    slot.appendChild(table);

  } catch (err) {
    console.error('Error loading top tools:', err);
    document.getElementById('top-tools-content').innerHTML =
      `<p class="text-red-600">Error loading top tools.</p>`;
  }
}


async function loadTopResources() {
  try {
    const response  = await fetch(`${window.ROOT_PATH}/admin/resources`);
    const resources = await response.json();

    resources.sort((a, b) =>
      (b.metrics?.totalExecutions ?? 0) - (a.metrics?.totalExecutions ?? 0)
    );

    const top  = resources.slice(0, 5);
    const rows = top.map(r => [
      r.id,
      r.uri,
      r.name,
      r.metrics?.totalExecutions ?? 0
    ]);

    const table = buildSafeTable(['ID', 'URI', 'Name', 'Executions'], rows);
    const slot  = document.getElementById('top-resources-content');
    slot.innerHTML = '';
    slot.appendChild(table);

  } catch (err) {
    console.error('Error loading top resources:', err);
    document.getElementById('top-resources-content').innerHTML =
      `<p class="text-red-600">Error loading top resources.</p>`;
  }
}


async function loadTopServers() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/servers`);
    const servers  = await response.json();

    servers.sort((a, b) =>
      (b.metrics?.totalExecutions ?? 0) - (a.metrics?.totalExecutions ?? 0)
    );

    const top  = servers.slice(0, 5);
    const rows = top.map(s => [
      s.id,
      s.name,
      s.metrics?.totalExecutions ?? 0
    ]);

    const table = buildSafeTable(['ID', 'Name', 'Executions'], rows);
    const slot  = document.getElementById('top-servers-content');
    slot.innerHTML = '';
    slot.appendChild(table);

  } catch (err) {
    console.error('Error loading top servers:', err);
    document.getElementById('top-servers-content').innerHTML =
      `<p class="text-red-600">Error loading top servers.</p>`;
  }
}


async function loadTopPrompts() {
  try {
    const response = await fetch(`${window.ROOT_PATH}/admin/prompts`);
    const prompts  = await response.json();

    prompts.sort((a, b) =>
      (b.metrics?.totalExecutions ?? 0) - (a.metrics?.totalExecutions ?? 0)
    );

    const top  = prompts.slice(0, 5);
    const rows = top.map(p => [
      p.id,
      p.name,
      p.metrics?.totalExecutions ?? 0
    ]);

    const table = buildSafeTable(['ID', 'Name', 'Executions'], rows);
    const slot  = document.getElementById('top-prompts-content');
    slot.innerHTML = '';
    slot.appendChild(table);

  } catch (err) {
    console.error('Error loading top prompts:', err);
    document.getElementById('top-prompts-content').innerHTML =
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

// Global error handlers for debugging
window.addEventListener('error', function(e) {
  console.error('Global error:', e.error, e.filename, e.lineno);
});

window.addEventListener('unhandledrejection', function(e) {
  console.error('Unhandled promise rejection:', e.reason);
});

// SINGLE consolidated DOMContentLoaded handler
document.addEventListener("DOMContentLoaded", function () {
  console.log('DOM loaded - initializing...');
  
  try {
    // 1. Initialize CodeMirror editors first
    initializeCodeMirrorEditors();
    
    // 2. Initialize tool selects
    initializeToolSelects();
    
    // 3. Set up all event listeners
    initializeEventListeners();
    
    // 4. Handle initial tab/state
    initializeTabState();
    
    console.log('Initialization complete');
  } catch (error) {
    console.error('Initialization failed:', error);
  }
});

// Separate initialization functions
function initializeCodeMirrorEditors() {
  console.log('Initializing CodeMirror editors...');
  
  const editorConfigs = [
    { id: "headers-editor", mode: "application/json", varName: "headersEditor" },
    { id: "schema-editor", mode: "application/json", varName: "schemaEditor" },
    { id: "resource-content-editor", mode: "text/plain", varName: "resourceContentEditor" },
    { id: "prompt-template-editor", mode: "text/plain", varName: "promptTemplateEditor" },
    { id: "prompt-args-editor", mode: "application/json", varName: "promptArgsEditor" },
    { id: "edit-tool-headers", mode: "application/json", varName: "editToolHeadersEditor" },
    { id: "edit-tool-schema", mode: "application/json", varName: "editToolSchemaEditor" },
    { id: "edit-resource-content", mode: "text/plain", varName: "editResourceContentEditor" },
    { id: "edit-prompt-template", mode: "text/plain", varName: "editPromptTemplateEditor" },
    { id: "edit-prompt-arguments", mode: "application/json", varName: "editPromptArgumentsEditor" }
  ];

  editorConfigs.forEach(config => {
    const element = document.getElementById(config.id);
    if (element && window.CodeMirror) {
      try {
        window[config.varName] = window.CodeMirror.fromTextArea(element, {
          mode: config.mode,
          theme: "monokai",
          lineNumbers: true,
          autoCloseBrackets: true,
          matchBrackets: true,
          tabSize: 2,
        });
        console.log(`✓ Initialized ${config.varName}`);
      } catch (error) {
        console.error(`Failed to initialize ${config.varName}:`, error);
      }
    } else {
      console.warn(`Element ${config.id} not found or CodeMirror not available`);
    }
  });
}

function initializeToolSelects() {
  console.log('Initializing tool selects...');
  
  // Initialize both tool selects
  initToolSelect("associatedTools", "selectedToolsPills", "selectedToolsWarning", 6);
  initToolSelect("edit-server-tools", "selectedEditToolsPills", "selectedEditToolsWarning", 6);
}

function initializeEventListeners() {
  console.log('Setting up event listeners...');
  
  // Tab navigation
  setupTabNavigation();
  
  // HTMX debug hooks
  setupHTMXHooks();
  
  // Authentication toggles
  setupAuthenticationToggles();
  
  // Form handlers
  setupFormHandlers();
  
  // Schema mode handlers
  setupSchemaModeHandlers();
  
  // Integration type handlers
  setupIntegrationTypeHandlers();
}

function setupTabNavigation() {
  const tabs = ["catalog", "tools", "resources", "prompts", "gateways", "roots", "metrics", "version-info"];
  
  tabs.forEach(tabName => {
    const tabElement = document.getElementById(`tab-${tabName}`);
    if (tabElement) {
      tabElement.addEventListener("click", () => showTab(tabName));
    }
  });
}

function setupHTMXHooks() {
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

function setupAuthenticationToggles() {
  const authHandlers = [
    { id: "auth-type", basicId: "auth-basic-fields", bearerId: "auth-bearer-fields", headersId: "auth-headers-fields" },
    { id: "auth-type-gw", basicId: "auth-basic-fields-gw", bearerId: "auth-bearer-fields-gw", headersId: "auth-headers-fields-gw" },
    { id: "auth-type-gw-edit", basicId: "auth-basic-fields-gw-edit", bearerId: "auth-bearer-fields-gw-edit", headersId: "auth-headers-fields-gw-edit" },
    { id: "edit-auth-type", basicId: "edit-auth-basic-fields", bearerId: "edit-auth-bearer-fields", headersId: "edit-auth-headers-fields" }
  ];

  authHandlers.forEach(handler => {
    const element = document.getElementById(handler.id);
    if (element) {
      element.addEventListener("change", function () {
        const basicFields = document.getElementById(handler.basicId);
        const bearerFields = document.getElementById(handler.bearerId);
        const headersFields = document.getElementById(handler.headersId);
        handleAuthTypeSelection(this.value, basicFields, bearerFields, headersFields);
      });
    }
  });
}

function setupFormHandlers() {
  // Gateway form
  const gatewayForm = document.getElementById("add-gateway-form");
  if (gatewayForm) {
    gatewayForm.addEventListener("submit", handleGatewayFormSubmit);
  }

  // Resource form
  const resourceForm = document.getElementById("add-resource-form");
  if (resourceForm) {
    resourceForm.addEventListener("submit", handleResourceFormSubmit);
  }

  // Tool form
  const toolForm = document.getElementById("add-tool-form");
  if (toolForm) {
    toolForm.addEventListener("submit", handleToolFormSubmit);
    toolForm.addEventListener("click", function () {
      if (getComputedStyle(toolForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  // Parameter button
  const paramButton = document.getElementById("add-parameter-btn");
  if (paramButton) {
    paramButton.addEventListener("click", handleAddParameter);
  }

  // Edit resource form save handler
  const editResourceForm = document.getElementById("edit-resource-form");
  if (editResourceForm) {
    editResourceForm.addEventListener("submit", function () {
      if (window.editResourceContentEditor) {
        window.editResourceContentEditor.save();
      }
    });
  }
}

function setupSchemaModeHandlers() {
  const schemaModeRadios = document.getElementsByName("schema_input_mode");
  const uiBuilderDiv = document.getElementById("ui-builder");
  const jsonInputContainer = document.getElementById("json-input-container");

  Array.from(schemaModeRadios).forEach((radio) => {
    radio.addEventListener("change", () => {
      if (radio.value === "ui" && radio.checked) {
        if (uiBuilderDiv) uiBuilderDiv.style.display = "block";
        if (jsonInputContainer) jsonInputContainer.style.display = "none";
      } else if (radio.value === "json" && radio.checked) {
        if (uiBuilderDiv) uiBuilderDiv.style.display = "none";
        if (jsonInputContainer) jsonInputContainer.style.display = "block";
        updateSchemaPreview();
      }
    });
  });
}

function setupIntegrationTypeHandlers() {
  const integrationTypeSelect = document.getElementById("integrationType");
  if (integrationTypeSelect) {
    const defaultIntegration = integrationTypeSelect.dataset.default || integrationTypeSelect.options[0].value;
    integrationTypeSelect.value = defaultIntegration;
    updateRequestTypeOptions();
    integrationTypeSelect.addEventListener("change", () => updateRequestTypeOptions());
  }

  const editToolTypeSelect = document.getElementById("edit-tool-type");
  if (editToolTypeSelect) {
    editToolTypeSelect.value = "REST";
    updateEditToolRequestTypes("PUT");
    editToolTypeSelect.addEventListener("change", () => updateEditToolRequestTypes());
  }
}

function initializeTabState() {
  console.log('Initializing tab state...');
  
  // Handle initial tab
  const hash = window.location.hash;
  if (hash) {
    showTab(hash.slice(1));
  } else {
    showTab("catalog");
  }

  // Pre-load version info if that's the initial tab
  if (window.location.hash === "#version-info") {
    setTimeout(() => {
      const panel = document.getElementById("version-info-panel");
      if (panel && panel.innerHTML.trim() === "") {
        fetchWithTimeout(`${window.ROOT_PATH}/version?partial=true`)
          .then((resp) => {
            if (!resp.ok) throw new Error("Network response was not ok");
            return resp.text();
          })
          .then((html) => {
            panel.innerHTML = html;
          })
          .catch((err) => {
            console.error("Failed to preload version info:", err);
            panel.innerHTML = "<p class='text-red-600'>Failed to load version info.</p>";
          });
      }
    }, 100);
  }

  // Set checkbox states based on URL parameter
  const urlParams = new URLSearchParams(window.location.search);
  const includeInactive = urlParams.get("include_inactive") === "true";
  
  const checkboxes = ["show-inactive-tools", "show-inactive-resources", "show-inactive-prompts", "show-inactive-gateways", "show-inactive-servers"];
  checkboxes.forEach(id => {
    const checkbox = document.getElementById(id);
    if (checkbox) {
      checkbox.checked = includeInactive;
    }
  });
}

// Form handler functions
async function handleGatewayFormSubmit(e) {
  e.preventDefault();
  
  const form = e.target;
  const formData = new FormData(form);
  const status = document.getElementById("status-gateways");
  const loading = document.getElementById("add-gateway-loading");

  try {
    if (loading) loading.style.display = "block";
    if (status) {
      status.textContent = "";
      status.classList.remove("error-status");
    }

    const is_inactive_checked = isInactiveChecked('gateways');
    formData.append("is_inactive_checked", is_inactive_checked);

    const response = await fetchWithTimeout(`${window.ROOT_PATH}/admin/gateways`, {
      method: "POST",
      body: formData,
    });

    let result = await response.json();
    if (!result.success) {
      alert(result.message || "An error occurred");
    } else {
      const redirectUrl = is_inactive_checked 
        ? `${window.ROOT_PATH}/admin?include_inactive=true#gateways`
        : `${window.ROOT_PATH}/admin#gateways`;
      window.location.href = redirectUrl;
    }
  } catch (error) {
    console.error("Error:", error);
    if (status) {
      status.textContent = error.message || "An error occurred!";
      status.classList.add("error-status");
    }
  } finally {
    if (loading) loading.style.display = "none";
  }
}

function handleResourceFormSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  
  fetchWithTimeout(`${window.ROOT_PATH}/admin/resources`, {
    method: "POST",
    body: formData,
  })
    .then((response) => {
      if (!response.ok) {
        const status = document.getElementById("status-resources");
        if (status) {
          status.textContent = "Connection failed!";
          status.classList.add("error-status");
        }
      } else {
        location.reload();
      }
    })
    .catch((error) => {
      console.error("Error:", error);
    });
}

async function handleToolFormSubmit(event) {
  event.preventDefault();
  
  try {
    // If in UI mode, update schemaEditor with generated schema
    const mode = document.querySelector('input[name="schema_input_mode"]:checked');
    if (mode && mode.value === "ui") {
      if (window.schemaEditor) {
        window.schemaEditor.setValue(generateSchema());
      }
    }
    
    // Save CodeMirror editors' contents
    if (window.headersEditor) window.headersEditor.save();
    if (window.schemaEditor) window.schemaEditor.save();

    let formData = new FormData(event.target);
    const is_inactive_checked = isInactiveChecked('tools');
    formData.append("is_inactive_checked", is_inactive_checked);
    
    let response = await fetchWithTimeout(`${window.ROOT_PATH}/admin/tools`, {
      method: "POST",
      body: formData,
    });
    
    let result = await response.json();
    if (!result.success) {
      alert(result.message || "An error occurred");
    } else {
      const redirectUrl = is_inactive_checked 
        ? `${window.ROOT_PATH}/admin?include_inactive=true#tools`
        : `${window.ROOT_PATH}/admin#tools`;
      window.location.href = redirectUrl;
    }
  } catch (error) {
    console.error("Fetch error:", error);
    alert("Failed to submit the form. Check console for details.");
  }
}

function handleAddParameter() {
  parameterCount++;
  const parametersContainer = document.getElementById("parameters-container");
  if (!parametersContainer) return;
  
  const paramDiv = document.createElement("div");
  paramDiv.classList.add("border", "p-4", "mb-4", "rounded-md", "bg-gray-50", "shadow-sm");
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
  if (deleteButton) {
    deleteButton.addEventListener("click", () => {
      paramDiv.remove();
      updateSchemaPreview();
      parameterCount--;
    });
  }
}

// Add updateEditToolRequestTypes function that was missing
function updateEditToolRequestTypes(selectedMethod = null) {
  const editToolTypeSelect = document.getElementById("edit-tool-type");
  const editToolRequestTypeSelect = document.getElementById("edit-tool-request-type");
  
  if (!editToolTypeSelect || !editToolRequestTypeSelect) return;
  
  const requestTypeMap = {
    MCP: ["SSE", "STREAMABLE", "STDIO"],
    REST: ["GET", "POST", "PUT", "DELETE"],
  };

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

// Add fetchWithTimeout function
function fetchWithTimeout(url, options = {}, timeout = 10000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  
  return fetch(url, {
    ...options,
    signal: controller.signal
  }).finally(() => {
    clearTimeout(timeoutId);
  });
}

window.toggleInactiveItems = toggleInactiveItems;
window.handleToggleSubmit = handleToggleSubmit;
window.handleSubmitWithConfirmation = handleSubmitWithConfirmation;
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
