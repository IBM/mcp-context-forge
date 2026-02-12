/* global Admin */
import { loadAuthHeaders, updateAuthHeadersJSON } from "./auth";
import { getCatalogUrl } from "./configExport";
import { MASKED_AUTH_VALUE } from "./constants";
import { updateEditToolRequestTypes } from "./formFieldHandlers";
import { initGatewaySelect } from "./gateway";
import { openModal } from "./modals";
import { initPromptSelect } from "./prompts";
import { initResourceSelect } from "./resources";
import { validateInputName, validateJson, validateUrl } from "./security";
import {
  safeGetElement,
  fetchWithTimeout,
  isInactiveChecked,
  handleFetchError,
  showErrorMessage,
  parseUriTemplate,
  updateEditToolUrl,
} from "./utils";

// ===================================================================
// SECURE CRUD OPERATIONS with Input Validation
// ===================================================================

/**
 * SECURE: Edit Tool function with input validation
 */
export const editTool = async function (toolId) {
  try {
    console.log(`Editing tool ID: ${toolId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/tools/${toolId}`
    );
    if (!response.ok) {
      // If the response is not OK, throw an error
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const tool = await response.json();

    const isInactiveCheckedBool = isInactiveChecked("tools");
    let hiddenField = safeGetElement("edit-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-show-inactive";
      const editForm = safeGetElement("edit-tool-form");
      if (editForm) {
        editForm.appendChild(hiddenField);
      }
    }
    hiddenField.value = isInactiveCheckedBool;

    // Set form action and populate basic fields with validation
    const editForm = safeGetElement("edit-tool-form");
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/tools/${toolId}/edit`;
    }

    // Validate and set fields
    const nameValidation = validateInputName(tool.name, "tool");
    const customNameValidation = validateInputName(tool.customName, "tool");

    const urlValidation = validateUrl(tool.url);

    const nameField = safeGetElement("edit-tool-name");
    const customNameField = safeGetElement("edit-tool-custom-name");
    const urlField = safeGetElement("edit-tool-url");
    const descField = safeGetElement("edit-tool-description");
    const typeField = safeGetElement("edit-tool-type");

    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (customNameField && customNameValidation.valid) {
      customNameField.value = customNameValidation.value;
    }

    const displayNameField = safeGetElement("edit-tool-display-name");
    if (displayNameField) {
      displayNameField.value = tool.displayName || "";
    }
    if (urlField && urlValidation.valid) {
      urlField.value = urlValidation.value;
    }
    if (descField) {
      tool.description = tool.description.slice(
        0,
        tool.description.indexOf("*")
      );
      descField.value = tool.description || "";
    }
    if (typeField) {
      typeField.value = tool.integrationType || "MCP";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-tool-tags");
    if (tagsField) {
      const rawTags = tool.tags
        ? tool.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    const teamId = new URL(window.location.href).searchParams.get("team_id");

    if (teamId) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = "team_id";
      hiddenInput.value = teamId;
      editForm.appendChild(hiddenInput);
    }

    const visibility = tool.visibility; // Ensure visibility is either 'public', 'team', or 'private'
    const publicRadio = safeGetElement("edit-tool-visibility-public");
    const teamRadio = safeGetElement("edit-tool-visibility-team");
    const privateRadio = safeGetElement("edit-tool-visibility-private");

    if (visibility) {
      // Check visibility and set the corresponding radio button
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    // Handle JSON fields safely with validation
    const headersValidation = validateJson(
      JSON.stringify(tool.headers || {}),
      "Headers"
    );
    const schemaValidation = validateJson(
      JSON.stringify(tool.inputSchema || {}),
      "Schema"
    );
    const outputSchemaValidation = validateJson(
      tool.outputSchema ? JSON.stringify(tool.outputSchema) : "",
      "Output Schema"
    );
    const annotationsValidation = validateJson(
      JSON.stringify(tool.annotations || {}),
      "Annotations"
    );

    const headersField = safeGetElement("edit-tool-headers");
    const schemaField = safeGetElement("edit-tool-schema");
    const outputSchemaField = safeGetElement("edit-tool-output-schema");
    const annotationsField = safeGetElement("edit-tool-annotations");

    if (headersField && headersValidation.valid) {
      headersField.value = JSON.stringify(headersValidation.value, null, 2);
    }
    if (schemaField && schemaValidation.valid) {
      schemaField.value = JSON.stringify(schemaValidation.value, null, 2);
    }
    if (outputSchemaField) {
      if (tool.outputSchema) {
        outputSchemaField.value = outputSchemaValidation.valid
          ? JSON.stringify(outputSchemaValidation.value, null, 2)
          : "";
      } else {
        outputSchemaField.value = "";
      }
    }
    if (annotationsField && annotationsValidation.valid) {
      annotationsField.value = JSON.stringify(
        annotationsValidation.value,
        null,
        2
      );
    }

    // Update CodeMirror editors if they exist
    if (window.editToolHeadersEditor && headersValidation.valid) {
      window.editToolHeadersEditor.setValue(
        JSON.stringify(headersValidation.value, null, 2)
      );
      window.editToolHeadersEditor.refresh();
    }
    if (window.editToolSchemaEditor && schemaValidation.valid) {
      window.editToolSchemaEditor.setValue(
        JSON.stringify(schemaValidation.value, null, 2)
      );
      window.editToolSchemaEditor.refresh();
    }
    if (window.editToolOutputSchemaEditor) {
      if (tool.outputSchema && outputSchemaValidation.valid) {
        window.editToolOutputSchemaEditor.setValue(
          JSON.stringify(outputSchemaValidation.value, null, 2)
        );
      } else {
        window.editToolOutputSchemaEditor.setValue("");
      }
      window.editToolOutputSchemaEditor.refresh();
    }

    // Prefill integration type from DB and set request types accordingly
    if (typeField) {
      typeField.value = tool.integrationType || "REST";
      // Disable integration type field for MCP tools (cannot be changed)
      if (tool.integrationType === "MCP") {
        typeField.disabled = true;
      } else {
        typeField.disabled = false;
      }
      updateEditToolRequestTypes(tool.requestType || null); // preselect from DB
      updateEditToolUrl(tool.url || null);
    }

    // Request Type field handling (disable for MCP)
    const requestTypeField = safeGetElement("edit-tool-request-type");
    if (requestTypeField) {
      if ((tool.integrationType || "REST") === "MCP") {
        requestTypeField.value = "";
        requestTypeField.disabled = true; // disabled -> not submitted
      } else {
        requestTypeField.disabled = false;
        requestTypeField.value = tool.requestType || ""; // keep DB verb or blank
      }
    }

    // Set auth type field
    const authTypeField = safeGetElement("edit-auth-type");
    if (authTypeField) {
      authTypeField.value = tool.auth?.authType || "";
    }
    const editAuthTokenField = safeGetElement("edit-auth-token");
    // Prefill integration type from DB and set request types accordingly
    if (typeField) {
      // Always set value from DB, never from previous UI state
      typeField.value = tool.integrationType;
      // Remove any previous hidden field for type
      const prevHiddenType = safeGetElement("hidden-edit-tool-type");
      if (prevHiddenType) {
        prevHiddenType.remove();
      }
      // Remove any previous hidden field for authType
      const prevHiddenAuthType = safeGetElement("hidden-edit-auth-type");
      if (prevHiddenAuthType) {
        prevHiddenAuthType.remove();
      }
      // Disable integration type field for MCP tools (cannot be changed)
      if (tool.integrationType === "MCP") {
        typeField.disabled = true;
        if (authTypeField) {
          authTypeField.disabled = true;
          // Add hidden field for authType
          const hiddenAuthTypeField = document.createElement("input");
          hiddenAuthTypeField.type = "hidden";
          hiddenAuthTypeField.name = authTypeField.name;
          hiddenAuthTypeField.value = authTypeField.value;
          hiddenAuthTypeField.id = "hidden-edit-auth-type";
          authTypeField.form.appendChild(hiddenAuthTypeField);
        }
        if (urlField) {
          urlField.readOnly = true;
        }
        if (headersField) {
          headersField.setAttribute("readonly", "readonly");
        }
        if (schemaField) {
          schemaField.setAttribute("readonly", "readonly");
        }
        if (editAuthTokenField) {
          editAuthTokenField.setAttribute("readonly", "readonly");
        }
        if (window.editToolHeadersEditor) {
          window.editToolHeadersEditor.setOption("readOnly", true);
        }
        if (window.editToolSchemaEditor) {
          window.editToolSchemaEditor.setOption("readOnly", true);
        }
        if (window.editToolOutputSchemaEditor) {
          window.editToolOutputSchemaEditor.setOption("readOnly", true);
        }
      } else {
        typeField.disabled = false;
        if (authTypeField) {
          authTypeField.disabled = false;
        }
        if (urlField) {
          urlField.readOnly = false;
        }
        if (headersField) {
          headersField.removeAttribute("readonly");
        }
        if (schemaField) {
          schemaField.removeAttribute("readonly");
        }
        if (editAuthTokenField) {
          editAuthTokenField.removeAttribute("readonly");
        }
        if (window.editToolHeadersEditor) {
          window.editToolHeadersEditor.setOption("readOnly", false);
        }
        if (window.editToolSchemaEditor) {
          window.editToolSchemaEditor.setOption("readOnly", false);
        }
        if (window.editToolOutputSchemaEditor) {
          window.editToolOutputSchemaEditor.setOption("readOnly", false);
        }
      }
      // Update request types and URL field
      updateEditToolRequestTypes(tool.requestType || null);
      updateEditToolUrl(tool.url || null);
    }

    // Auth containers
    const authBasicSection = safeGetElement("edit-auth-basic-fields");
    const authBearerSection = safeGetElement("edit-auth-bearer-fields");
    const authHeadersSection = safeGetElement("edit-auth-headers-fields");

    // Individual fields
    const authUsernameField = authBasicSection?.querySelector(
      "input[name='auth_username']"
    );
    const authPasswordField = authBasicSection?.querySelector(
      "input[name='auth_password']"
    );

    const authTokenField = authBearerSection?.querySelector(
      "input[name='auth_token']"
    );

    const authHeaderKeyField = authHeadersSection?.querySelector(
      "input[name='auth_header_key']"
    );
    const authHeaderValueField = authHeadersSection?.querySelector(
      "input[name='auth_header_value']"
    );
    const authHeadersContainer = safeGetElement(
      "auth-headers-container-gw-edit"
    );
    const authHeadersJsonInput = safeGetElement("auth-headers-json-gw-edit");
    if (authHeadersContainer) {
      authHeadersContainer.innerHTML = "";
    }
    if (authHeadersJsonInput) {
      authHeadersJsonInput.value = "";
    }

    // Hide all auth sections first
    if (authBasicSection) {
      authBasicSection.style.display = "none";
    }
    if (authBearerSection) {
      authBearerSection.style.display = "none";
    }
    if (authHeadersSection) {
      authHeadersSection.style.display = "none";
    }

    // Clear old values
    if (authUsernameField) {
      authUsernameField.value = "";
    }
    if (authPasswordField) {
      authPasswordField.value = "";
    }
    if (authTokenField) {
      authTokenField.value = "";
    }
    if (authHeaderKeyField) {
      authHeaderKeyField.value = "";
    }
    if (authHeaderValueField) {
      authHeaderValueField.value = "";
    }

    // Display appropriate auth section and populate values
    switch (tool.auth?.authType) {
      case "basic":
        if (authBasicSection) {
          authBasicSection.style.display = "block";
          if (authUsernameField) {
            authUsernameField.value = tool.auth.username || "";
          }
          if (authPasswordField) {
            authPasswordField.value = "*****"; // masked
          }
        }
        break;

      case "bearer":
        if (authBearerSection) {
          authBearerSection.style.display = "block";
          if (authTokenField) {
            authTokenField.value = "*****"; // masked
          }
        }
        break;

      case "authheaders":
        if (authHeadersSection) {
          authHeadersSection.style.display = "block";
          if (authHeaderKeyField) {
            authHeaderKeyField.value = tool.auth.authHeaderKey || "";
          }
          if (authHeaderValueField) {
            authHeaderValueField.value = "*****"; // masked
          }
        }
        break;

      case "":
      default:
        // No auth – keep everything hidden
        break;
    }

    openModal("tool-edit-modal");

    // Ensure editors are refreshed after modal display
    setTimeout(() => {
      if (window.editToolHeadersEditor) {
        window.editToolHeadersEditor.refresh();
      }
      if (window.editToolSchemaEditor) {
        window.editToolSchemaEditor.refresh();
      }
      if (window.editToolOutputSchemaEditor) {
        window.editToolOutputSchemaEditor.refresh();
      }
    }, 100);

    console.log("✓ Tool edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching tool details for editing:", error);
    const errorMessage = handleFetchError(error, "load tool for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: View A2A Agents function with safe display
 */
export const viewAgent = async function (agentId) {
  try {
    console.log(`Viewing agent ID: ${agentId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/a2a/${agentId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const agent = await response.json();

    const agentDetailsDiv = safeGetElement("agent-details");
    if (agentDetailsDiv) {
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      const fields = [
        { label: "Name", value: agent.name },
        { label: "Slug", value: agent.slug },
        { label: "Endpoint URL", value: agent.endpointUrl },
        { label: "Agent Type", value: agent.agentType },
        { label: "Protocol Version", value: agent.protocolVersion },
        { label: "Description", value: agent.description || "N/A" },
        { label: "Visibility", value: agent.visibility || "private" },
      ];

      // Tags
      const tagsP = document.createElement("p");
      const tagsStrong = document.createElement("strong");
      tagsStrong.textContent = "Tags: ";
      tagsP.appendChild(tagsStrong);
      if (agent.tags && agent.tags.length > 0) {
        agent.tags.forEach((tag) => {
          const tagSpan = document.createElement("span");
          tagSpan.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1";
          const raw =
            typeof tag === "object" && tag !== null
              ? tag.id || tag.label || JSON.stringify(tag)
              : tag;
          tagSpan.textContent = raw;
          tagsP.appendChild(tagSpan);
        });
      } else {
        tagsP.appendChild(document.createTextNode("No tags"));
      }
      container.appendChild(tagsP);

      // Render basic fields
      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Status
      const statusP = document.createElement("p");
      const statusStrong = document.createElement("strong");
      statusStrong.textContent = "Status: ";
      statusP.appendChild(statusStrong);

      const statusSpan = document.createElement("span");
      let statusText = "";
      let statusClass = "";
      let statusIcon = "";

      if (!agent.enabled) {
        statusText = "Inactive";
        statusClass = "bg-red-100 text-red-800";
        statusIcon = `
                  <svg class="ml-1 h-4 w-4 text-red-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                  </svg>`;
      } else if (agent.enabled && agent.reachable) {
        statusText = "Active";
        statusClass = "bg-green-100 text-green-800";
        statusIcon = `
                  <svg class="ml-1 h-4 w-4 text-green-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"></path>
                  </svg>`;
      } else if (agent.enabled && !agent.reachable) {
        statusText = "Offline";
        statusClass = "bg-yellow-100 text-yellow-800";
        statusIcon = `
                  <svg class="ml-1 h-4 w-4 text-yellow-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd"></path>
                  </svg>`;
      }

      statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusClass}`;
      statusSpan.innerHTML = `${statusText} ${statusIcon}`;
      statusP.appendChild(statusSpan);
      container.appendChild(statusP);

      // Capabilities + Config (JSON formatted)
      const capConfigDiv = document.createElement("div");
      capConfigDiv.className = "mt-4 p-2 bg-gray-50 dark:bg-gray-800 rounded";
      const capTitle = document.createElement("strong");
      capTitle.textContent = "Capabilities & Config:";
      capConfigDiv.appendChild(capTitle);

      const pre = document.createElement("pre");
      pre.className = "text-xs mt-1 whitespace-pre-wrap break-words";
      pre.textContent = JSON.stringify(
        { capabilities: agent.capabilities, config: agent.config },
        null,
        2
      );
      capConfigDiv.appendChild(pre);
      container.appendChild(capConfigDiv);

      // Metadata
      const metadataDiv = document.createElement("div");
      metadataDiv.className = "mt-6 border-t pt-4";

      const metadataTitle = document.createElement("strong");
      metadataTitle.textContent = "Metadata:";
      metadataDiv.appendChild(metadataTitle);

      const metadataGrid = document.createElement("div");
      metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

      const metadataFields = [
        {
          label: "Created By",
          value: agent.created_by || agent.createdBy || "Legacy Entity",
        },
        {
          label: "Created At",
          value:
            agent.created_at || agent.createdAt
              ? new Date(agent.created_at || agent.createdAt).toLocaleString()
              : "Pre-metadata",
        },
        {
          label: "Created From IP",
          value: agent.created_from_ip || agent.createdFromIp || "Unknown",
        },
        {
          label: "Created Via",
          value: agent.created_via || agent.createdVia || "Unknown",
        },
        {
          label: "Last Modified By",
          value: agent.modified_by || agent.modifiedBy || "N/A",
        },
        {
          label: "Last Modified At",
          value:
            agent.updated_at || agent.updatedAt
              ? new Date(agent.updated_at || agent.updatedAt).toLocaleString()
              : "N/A",
        },
        {
          label: "Modified From IP",
          value: agent.modified_from_ip || agent.modifiedFromIp || "N/A",
        },
        {
          label: "Modified Via",
          value: agent.modified_via || agent.modifiedVia || "N/A",
        },
        { label: "Version", value: agent.version || "1" },
        {
          label: "Import Batch",
          value: agent.importBatchId || "N/A",
        },
      ];

      metadataFields.forEach((field) => {
        const fieldDiv = document.createElement("div");

        const labelSpan = document.createElement("span");
        labelSpan.className = "font-medium text-gray-600 dark:text-gray-400";
        labelSpan.textContent = field.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "ml-2";
        valueSpan.textContent = field.value;

        fieldDiv.appendChild(labelSpan);
        fieldDiv.appendChild(valueSpan);
        metadataGrid.appendChild(fieldDiv);
      });

      metadataDiv.appendChild(metadataGrid);
      container.appendChild(metadataDiv);

      agentDetailsDiv.innerHTML = "";
      agentDetailsDiv.appendChild(container);
    }

    openModal("agent-modal");
    const modal = safeGetElement("agent-modal");
    if (modal && modal.classList.contains("hidden")) {
      console.warn("Modal was still hidden — forcing visible.");
      modal.classList.remove("hidden");
    }

    console.log("✓ Agent details loaded successfully");
  } catch (error) {
    console.error("Error fetching agent details:", error);
    const errorMessage = handleFetchError(error, "load agent details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit A2A Agent function
 */
export const editA2AAgent = async function (agentId) {
  try {
    console.log(`Editing A2A Agent ID: ${agentId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/a2a/${agentId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const agent = await response.json();

    console.log("Agent Details: " + JSON.stringify(agent, null, 2));

    // for (const [key, value] of Object.entries(agent)) {
    //       console.log(`${key}:`, value);
    //     }

    const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
    const editForm = safeGetElement("edit-a2a-agent-form");
    let hiddenField = safeGetElement("edit-a2a-agents-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactivate_checked";
      hiddenField.id = "edit-a2a-agents-show-inactive";

      if (editForm) {
        editForm.appendChild(hiddenField);
      }
    }
    hiddenField.value = isInactiveCheckedBool;

    // Set form action and populate fields with validation

    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/a2a/${agentId}/edit`;
      editForm.method = "POST"; // ensure method is POST
    }

    const nameValidation = validateInputName(agent.name, "a2a_agent");
    const urlValidation = validateUrl(agent.endpointUrl);

    const nameField = safeGetElement("a2a-agent-name-edit");
    const urlField = safeGetElement("a2a-agent-endpoint-url-edit");
    const descField = safeGetElement("a2a-agent-description-edit");
    const agentType = safeGetElement("a2a-agent-type-edit");

    agentType.value = agent.agentType;

    console.log("Agent Type: ", agent.agentType);

    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (urlField && urlValidation.valid) {
      urlField.value = urlValidation.value;
    }
    if (descField) {
      descField.value = agent.description || "";
    }

    // Set tags field
    const tagsField = safeGetElement("a2a-agent-tags-edit");
    if (tagsField) {
      const rawTags = agent.tags
        ? agent.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    const teamId = new URL(window.location.href).searchParams.get("team_id");

    if (teamId) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = "team_id";
      hiddenInput.value = teamId;
      editForm.appendChild(hiddenInput);
    }

    // ✅ Prefill visibility radios (consistent with server)
    const visibility = agent.visibility ? agent.visibility.toLowerCase() : null;

    const publicRadio = safeGetElement("a2a-visibility-public-edit");
    const teamRadio = safeGetElement("a2a-visibility-team-edit");
    const privateRadio = safeGetElement("a2a-visibility-private-edit");

    // Clear all first
    if (publicRadio) {
      publicRadio.checked = false;
    }
    if (teamRadio) {
      teamRadio.checked = false;
    }
    if (privateRadio) {
      privateRadio.checked = false;
    }

    if (visibility) {
      // Check visibility and set the corresponding radio button
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    const authTypeField = safeGetElement("auth-type-a2a-edit");

    if (authTypeField) {
      authTypeField.value = agent.authType || "";
    }

    toggleA2AAuthFields(agent.authType || "");

    // Auth containers
    const authBasicSection = safeGetElement("auth-basic-fields-a2a-edit");
    const authBearerSection = safeGetElement("auth-bearer-fields-a2a-edit");
    const authHeadersSection = safeGetElement("auth-headers-fields-a2a-edit");
    const authOAuthSection = safeGetElement("auth-oauth-fields-a2a-edit");
    const authQueryParamSection = safeGetElement(
      "auth-query_param-fields-a2a-edit"
    );

    // Individual fields
    const authUsernameField = safeGetElement(
      "auth-basic-fields-a2a-edit"
    )?.querySelector("input[name='auth_username']");
    const authPasswordField = safeGetElement(
      "auth-basic-fields-a2a-edit"
    )?.querySelector("input[name='auth_password']");

    const authTokenField = safeGetElement(
      "auth-bearer-fields-a2a-edit"
    )?.querySelector("input[name='auth_token']");

    const authHeaderKeyField = safeGetElement(
      "auth-headers-fields-a2a-edit"
    )?.querySelector("input[name='auth_header_key']");
    const authHeaderValueField = safeGetElement(
      "auth-headers-fields-a2a-edit"
    )?.querySelector("input[name='auth_header_value']");

    // OAuth fields
    const oauthGrantTypeField = safeGetElement("oauth-grant-type-a2a-edit");
    const oauthClientIdField = safeGetElement("oauth-client-id-a2a-edit");
    const oauthClientSecretField = safeGetElement(
      "oauth-client-secret-a2a-edit"
    );
    const oauthTokenUrlField = safeGetElement("oauth-token-url-a2a-edit");
    const oauthAuthUrlField = safeGetElement(
      "oauth-authorization-url-a2a-edit"
    );
    const oauthRedirectUriField = safeGetElement("oauth-redirect-uri-a2a-edit");
    const oauthScopesField = safeGetElement("oauth-scopes-a2a-edit");
    const oauthAuthCodeFields = safeGetElement(
      "oauth-auth-code-fields-a2a-edit"
    );

    // Query param fields
    const authQueryParamKeyField = safeGetElement(
      "auth-query-param-key-a2a-edit"
    );
    const authQueryParamValueField = safeGetElement(
      "auth-query-param-value-a2a-edit"
    );

    // Hide all auth sections first
    if (authBasicSection) {
      authBasicSection.style.display = "none";
    }
    if (authBearerSection) {
      authBearerSection.style.display = "none";
    }
    if (authHeadersSection) {
      authHeadersSection.style.display = "none";
    }
    if (authOAuthSection) {
      authOAuthSection.style.display = "none";
    }
    if (authQueryParamSection) {
      authQueryParamSection.style.display = "none";
    }

    switch (agent.authType) {
      case "basic":
        if (authBasicSection) {
          authBasicSection.style.display = "block";
          if (authUsernameField) {
            authUsernameField.value = agent.authUsername || "";
          }
          if (authPasswordField) {
            authPasswordField.value = "*****"; // mask password
          }
        }
        break;
      case "bearer":
        if (authBearerSection) {
          authBearerSection.style.display = "block";
          if (authTokenField) {
            authTokenField.value = agent.authValue || ""; // show full token
          }
        }
        break;
      case "authheaders":
        if (authHeadersSection) {
          authHeadersSection.style.display = "block";
          if (authHeaderKeyField) {
            authHeaderKeyField.value = agent.authHeaderKey || "";
          }
          if (authHeaderValueField) {
            authHeaderValueField.value = "*****"; // mask header value
          }
        }
        break;
      case "oauth":
        if (authOAuthSection) {
          authOAuthSection.style.display = "block";
        }
        // Populate OAuth fields if available
        if (agent.oauthConfig) {
          const config = agent.oauthConfig;
          if (oauthGrantTypeField && config.grant_type) {
            oauthGrantTypeField.value = config.grant_type;
            // Show/hide authorization code fields based on grant type
            if (oauthAuthCodeFields) {
              oauthAuthCodeFields.style.display =
                config.grant_type === "authorization_code" ? "block" : "none";
            }
          }
          if (oauthClientIdField && config.client_id) {
            oauthClientIdField.value = config.client_id;
          }
          if (oauthClientSecretField) {
            oauthClientSecretField.value = ""; // Don't populate secret for security
          }
          if (oauthTokenUrlField && config.token_url) {
            oauthTokenUrlField.value = config.token_url;
          }
          if (oauthAuthUrlField && config.authorization_url) {
            oauthAuthUrlField.value = config.authorization_url;
          }
          if (oauthRedirectUriField && config.redirect_uri) {
            oauthRedirectUriField.value = config.redirect_uri;
          }
          if (
            oauthScopesField &&
            config.scopes &&
            Array.isArray(config.scopes)
          ) {
            oauthScopesField.value = config.scopes.join(" ");
          }
        }
        break;
      case "query_param":
        if (authQueryParamSection) {
          authQueryParamSection.style.display = "block";
          if (authQueryParamKeyField) {
            authQueryParamKeyField.value = agent.authQueryParamKey || "";
          }
          if (authQueryParamValueField) {
            authQueryParamValueField.value = "*****"; // mask value
          }
        }
        break;
      case "":
      default:
        // No auth – keep everything hidden
        break;
    }

    // **Capabilities & Config (ensure valid dicts)**
    safeSetValue(
      "a2a-agent-capabilities-edit",
      JSON.stringify(agent.capabilities || {})
    );
    safeSetValue("a2a-agent-config-edit", JSON.stringify(agent.config || {}));

    // Set form action to the new POST endpoint

    // Handle passthrough headers
    const passthroughHeadersField = safeGetElement(
      "edit-a2a-agent-passthrough-headers"
    );
    if (passthroughHeadersField) {
      if (agent.passthroughHeaders && Array.isArray(agent.passthroughHeaders)) {
        passthroughHeadersField.value = agent.passthroughHeaders.join(", ");
      } else {
        passthroughHeadersField.value = "";
      }
    }

    openModal("a2a-edit-modal");
    console.log("✓ A2A Agent edit modal loaded successfully");
  } catch (err) {
    console.error("Error loading A2A agent:", err);
    const errorMessage = handleFetchError(err, "load A2A Agent for editing");
    showErrorMessage(errorMessage);
  }
};

export const safeSetValue = function (id, val) {
  const el = safeGetElement(id);
  if (el) {
    el.value = val;
  }
};

export const toggleA2AAuthFields = function (authType) {
  const sections = [
    "auth-basic-fields-a2a-edit",
    "auth-bearer-fields-a2a-edit",
    "auth-headers-fields-a2a-edit",
    "auth-oauth-fields-a2a-edit",
    "auth-query_param-fields-a2a-edit",
  ];
  sections.forEach((id) => {
    const el = safeGetElement(id);
    if (el) {
      el.style.display = "none";
    }
  });
  if (authType) {
    const el = safeGetElement(`auth-${authType}-fields-a2a-edit`);
    if (el) {
      el.style.display = "block";
    }
  }
};

// -------------------- Resource Testing ------------------ //
export const testResource = async function (resourceId) {
  try {
    console.log(`Testing the resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const data = await response.json();
    const resource = data.resource;
    //  console.log("Resource JSON:\n", JSON.stringify(resource, null, 2));
    openResourceTestModal(resource);
  } catch (error) {
    console.error("Error fetching resource details:", error);
    const errorMessage = handleFetchError(error, "load resource details");
    showErrorMessage(errorMessage);
  }
};

export const openResourceTestModal = function (resource) {
  const title = safeGetElement("resource-test-modal-title");
  const fieldsContainer = safeGetElement("resource-test-form-fields");
  const resultBox = safeGetElement("resource-test-result");

  title.textContent = `Test Resource: ${resource.name}`;

  fieldsContainer.innerHTML = "";
  resultBox.textContent = "Fill the fields and click Invoke Resource";

  // 1️⃣ Build form fields ONLY if uriTemplate exists
  if (resource.uriTemplate) {
    const fieldNames = parseUriTemplate(resource.uriTemplate);

    fieldNames.forEach((name) => {
      const div = document.createElement("div");
      div.className = "space-y-1";

      div.innerHTML = `
                <label class="text-sm font-medium text-gray-700 dark:text-gray-300">
                    ${name}
                </label>
                <input type="text"
                    id="resource-field-${name}"
                    class="mt-1 px-2 py-1 block w-full rounded-md border border-gray-300 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-300"
                />
            `;

      fieldsContainer.appendChild(div);
    });
  } else {
    // 2️⃣ If no template → show a simple message
    fieldsContainer.innerHTML = `
            <div class="text-gray-500 dark:text-gray-400 italic">
                This resource has no URI template.
                Click "Invoke Resource" to test directly.
            </div>
        `;
  }

  Admin.CurrentResourceUnderTest = resource;
  openModal("resource-test-modal");
};

export const runResourceTest = async function () {
  const resource = Admin.CurrentResourceUnderTest;
  if (!resource) {
    return;
  }

  let finalUri = "";

  if (resource.uriTemplate) {
    finalUri = resource.uriTemplate;

    const fieldNames = parseUriTemplate(resource.uriTemplate);
    fieldNames.forEach((name) => {
      const value = safeGetElement(`resource-field-${name}`).value;
      finalUri = finalUri.replace(`{${name}}`, encodeURIComponent(value));
    });
  } else {
    finalUri = resource.uri; // direct test
  }

  console.log("Final URI:", finalUri);

  const response = await fetchWithTimeout(
    `${window.ROOT_PATH}/admin/resources/test/${encodeURIComponent(finalUri)}`
  );

  const json = await response.json();

  const resultBox = safeGetElement("resource-test-result");
  resultBox.innerHTML = ""; // clear previous

  const container = document.createElement("div");
  resultBox.appendChild(container);

  // Extract the content text (fallback if missing)
  const content = json.content || {};
  let contentStr = content.text || JSON.stringify(content, null, 2);

  // Try to prettify JSON content
  try {
    const parsed = JSON.parse(contentStr);
    contentStr = JSON.stringify(parsed, null, 2);
  } catch (_) {}

  // ---- Content Section (same as prompt tester) ----
  const contentSection = document.createElement("div");
  contentSection.className = "mt-4";

  // Header
  const contentHeader = document.createElement("div");
  contentHeader.className =
    "flex items-center justify-between cursor-pointer select-none p-2 bg-gray-200 dark:bg-gray-700 rounded";
  contentSection.appendChild(contentHeader);

  // Title
  const contentTitle = document.createElement("strong");
  contentTitle.textContent = "Content";
  contentHeader.appendChild(contentTitle);

  // Right controls (arrow/copy/fullscreen/download)
  const headerRight = document.createElement("div");
  headerRight.className = "flex items-center space-x-2";
  contentHeader.appendChild(headerRight);

  // Arrow icon
  const toggleIcon = document.createElement("span");
  toggleIcon.innerHTML = "▶";
  toggleIcon.className = "transform transition-transform text-xs";
  headerRight.appendChild(toggleIcon);

  // Copy button
  const copyBtn = document.createElement("button");
  copyBtn.textContent = "Copy";
  copyBtn.className =
    "text-xs px-2 py-1 rounded bg-gray-300 dark:bg-gray-600 hover:bg-gray-400 dark:hover:bg-gray-500";
  headerRight.appendChild(copyBtn);

  // Fullscreen button
  const fullscreenBtn = document.createElement("button");
  fullscreenBtn.textContent = "Fullscreen";
  fullscreenBtn.className =
    "text-xs px-2 py-1 rounded bg-blue-300 dark:bg-blue-600 hover:bg-blue-400 dark:hover:bg-blue-500";
  headerRight.appendChild(fullscreenBtn);

  // Download button
  const downloadBtn = document.createElement("button");
  downloadBtn.textContent = "Download";
  downloadBtn.className =
    "text-xs px-2 py-1 rounded bg-green-300 dark:bg-green-600 hover:bg-green-400 dark:hover:bg-green-500";
  headerRight.appendChild(downloadBtn);

  // Collapsible body
  const contentBody = document.createElement("div");
  contentBody.className = "hidden mt-2";
  contentSection.appendChild(contentBody);

  // Pre block
  const contentPre = document.createElement("pre");
  contentPre.className =
    "bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100 text-sm whitespace-pre-wrap";
  contentPre.textContent = contentStr;
  contentBody.appendChild(contentPre);

  // Auto-collapse if too large
  const lineCount = contentStr.split("\n").length;

  if (lineCount > 30) {
    contentBody.classList.add("hidden");
    toggleIcon.style.transform = "rotate(0deg)";
    contentTitle.textContent = "Content (Large - Click to expand)";
  } else {
    contentBody.classList.remove("hidden");
    toggleIcon.style.transform = "rotate(90deg)";
  }

  // Toggle expand/collapse
  contentHeader.onclick = () => {
    contentBody.classList.toggle("hidden");
    toggleIcon.style.transform = contentBody.classList.contains("hidden")
      ? "rotate(0deg)"
      : "rotate(90deg)";
  };

  // Copy button
  copyBtn.onclick = (event) => {
    event.stopPropagation();
    navigator.clipboard.writeText(contentStr).then(() => {
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
    });
  };

  // Fullscreen mode
  fullscreenBtn.onclick = (event) => {
    event.preventDefault();
    event.stopPropagation();

    const overlay = document.createElement("div");
    overlay.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    overlay.className =
      "fixed inset-0 bg-black bg-opacity-70 z-[9999] flex items-center justify-center p-4";

    const box = document.createElement("div");
    box.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    box.className =
      "bg-white dark:bg-gray-900 rounded-lg w-full h-full p-4 overflow-auto";

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Close";
    closeBtn.className =
      "text-xs px-3 py-1 mb-2 rounded bg-red-400 hover:bg-red-500 dark:bg-red-700 dark:hover:bg-red-600";

    closeBtn.onclick = () => overlay.remove();

    const fsPre = document.createElement("pre");
    fsPre.className =
      "bg-gray-100 p-4 rounded overflow-auto h-full dark:bg-gray-800 dark:text-gray-100 text-sm whitespace-pre-wrap";
    fsPre.textContent = contentStr;

    box.appendChild(closeBtn);
    box.appendChild(fsPre);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  };

  // Download
  downloadBtn.onclick = (event) => {
    event.stopPropagation();

    let blob;
    let filename;

    // JSON?
    try {
      JSON.parse(contentStr);
      blob = new Blob([contentStr], { type: "application/json" });
      filename = "resource.json";
    } catch (_) {
      blob = new Blob([contentStr], { type: "text/plain" });
      filename = "resource.txt";
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  container.appendChild(contentSection);

  // resultBox.textContent = JSON.stringify(json, null, 2);
};

// -------------------- Resource Testing ------------------ //

/**
 * SECURE: View Resource function with safe display
 */
export const viewResource = async function (resourceId) {
  try {
    console.log(`Viewing resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const data = await response.json();
    const resource = data.resource;

    // console.log("Resource JSON:\n", JSON.stringify(resource, null, 2));
    // const content = data.content;

    const resourceDetailsDiv = safeGetElement("resource-details");
    if (resourceDetailsDiv) {
      // Create safe display elements
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      // Add each piece of information safely
      const fields = [
        { label: "URI", value: resource.uri },
        { label: "Name", value: resource.name },
        { label: "Type", value: resource.mimeType || "N/A" },
        { label: "Description", value: resource.description || "N/A" },
        {
          label: "Visibility",
          value: resource.visibility || "private",
        },
      ];

      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Tags section
      const tagsP = document.createElement("p");
      const tagsStrong = document.createElement("strong");
      tagsStrong.textContent = "Tags: ";
      tagsP.appendChild(tagsStrong);

      if (resource.tags && resource.tags.length > 0) {
        resource.tags.forEach((tag) => {
          const tagSpan = document.createElement("span");
          tagSpan.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
          const raw =
            typeof tag === "object" && tag !== null
              ? tag.id || tag.label || JSON.stringify(tag)
              : tag;
          tagSpan.textContent = raw;
          tagsP.appendChild(tagSpan);
        });
      } else {
        tagsP.appendChild(document.createTextNode("None"));
      }
      container.appendChild(tagsP);

      // Status with safe styling
      const statusP = document.createElement("p");
      const statusStrong = document.createElement("strong");
      statusStrong.textContent = "Status: ";
      statusP.appendChild(statusStrong);

      const isActive = resource.enabled === true;
      const statusSpan = document.createElement("span");
      statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
        isActive ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
      }`;
      statusSpan.textContent = isActive ? "Active" : "Inactive";

      statusP.appendChild(statusSpan);
      container.appendChild(statusP);

      // Content display - safely handle different types
      // const contentDiv = document.createElement("div");
      // const contentStrong = document.createElement("strong");
      // contentStrong.textContent = "Content:";
      // contentDiv.appendChild(contentStrong);

      // const contentPre = document.createElement("pre");
      // contentPre.className =
      //     "mt-1 bg-gray-100 p-2 rounded overflow-auto max-h-80 dark:bg-gray-800 dark:text-gray-100";

      // // Handle content display - extract actual content from object if needed
      // let contentStr = extractContent(
      //     content,
      //     resource.description || "No content available",
      // );

      // if (!contentStr.trim()) {
      //     contentStr = resource.description || "No content available";
      // }

      // contentPre.textContent = contentStr;
      // contentDiv.appendChild(contentPre);
      // container.appendChild(contentDiv);

      // Metrics display
      if (resource.metrics) {
        const metricsDiv = document.createElement("div");
        const metricsStrong = document.createElement("strong");
        metricsStrong.textContent = "Metrics:";
        metricsDiv.appendChild(metricsStrong);

        const metricsList = document.createElement("ul");
        metricsList.className = "list-disc list-inside ml-4";

        const metricsData = [
          {
            label: "Total Executions",
            value: resource.metrics.totalExecutions ?? 0,
          },
          {
            label: "Successful Executions",
            value: resource.metrics.successfulExecutions ?? 0,
          },
          {
            label: "Failed Executions",
            value: resource.metrics.failedExecutions ?? 0,
          },
          {
            label: "Failure Rate",
            value: resource.metrics.failureRate ?? 0,
          },
          {
            label: "Min Response Time",
            value: resource.metrics.minResponseTime ?? "N/A",
          },
          {
            label: "Max Response Time",
            value: resource.metrics.maxResponseTime ?? "N/A",
          },
          {
            label: "Average Response Time",
            value: resource.metrics.avgResponseTime ?? "N/A",
          },
          {
            label: "Last Execution Time",
            value: resource.metrics.lastExecutionTime ?? "N/A",
          },
        ];

        metricsData.forEach((metric) => {
          const li = document.createElement("li");
          li.textContent = `${metric.label}: ${metric.value}`;
          metricsList.appendChild(li);
        });

        metricsDiv.appendChild(metricsList);
        container.appendChild(metricsDiv);
      }

      // Add metadata section
      const metadataDiv = document.createElement("div");
      metadataDiv.className = "mt-6 border-t pt-4";

      const metadataTitle = document.createElement("strong");
      metadataTitle.textContent = "Metadata:";
      metadataDiv.appendChild(metadataTitle);

      const metadataGrid = document.createElement("div");
      metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

      const metadataFields = [
        {
          label: "Created By",
          value: resource.created_by || resource.createdBy || "Legacy Entity",
        },
        {
          label: "Created At",
          value:
            resource.created_at || resource.createdAt
              ? new Date(
                resource.created_at || resource.createdAt
              ).toLocaleString()
              : "Pre-metadata",
        },
        {
          label: "Created From IP",
          value:
            resource.created_from_ip || resource.createdFromIp || "Unknown",
        },
        {
          label: "Created Via",
          value: resource.created_via || resource.createdVia || "Unknown",
        },
        {
          label: "Last Modified By",
          value: resource.modified_by || resource.modifiedBy || "N/A",
        },
        {
          label: "Last Modified At",
          value:
            resource.updated_at || resource.updatedAt
              ? new Date(
                resource.updated_at || resource.updatedAt
              ).toLocaleString()
              : "N/A",
        },
        {
          label: "Modified From IP",
          value: resource.modified_from_ip || resource.modifiedFromIp || "N/A",
        },
        {
          label: "Modified Via",
          value: resource.modified_via || resource.modifiedVia || "N/A",
        },
        {
          label: "Version",
          value: resource.version || "1",
        },
        {
          label: "Import Batch",
          value: resource.import_batch_id || resource.importBatchId || "N/A",
        },
      ];

      metadataFields.forEach((field) => {
        const fieldDiv = document.createElement("div");

        const labelSpan = document.createElement("span");
        labelSpan.className = "font-medium text-gray-600 dark:text-gray-400";
        labelSpan.textContent = field.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "ml-2";
        valueSpan.textContent = field.value;

        fieldDiv.appendChild(labelSpan);
        fieldDiv.appendChild(valueSpan);
        metadataGrid.appendChild(fieldDiv);
      });

      metadataDiv.appendChild(metadataGrid);
      container.appendChild(metadataDiv);

      // Replace content safely
      resourceDetailsDiv.innerHTML = "";
      resourceDetailsDiv.appendChild(container);
    }

    openModal("resource-modal");
    console.log("✓ Resource details loaded successfully");
  } catch (error) {
    console.error("Error fetching resource details:", error);
    const errorMessage = handleFetchError(error, "load resource details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Resource function with validation
 */
export const editResource = async function (resourceId) {
  try {
    console.log(`Editing resource: ${resourceId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const data = await response.json();
    const resource = data.resource;
    // const content = data.content;
    // Ensure hidden inactive flag is preserved
    const isInactiveCheckedBool = isInactiveChecked("resources");
    let hiddenField = safeGetElement("edit-resource-show-inactive");
    const editForm = safeGetElement("edit-resource-form");

    if (!hiddenField && editForm) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-resource-show-inactive";
      const editForm = safeGetElement("edit-resource-form");
      editForm.appendChild(hiddenField);
    }
    hiddenField.value = isInactiveCheckedBool;

    // ✅ Prefill visibility radios (consistent with server)
    const visibility = resource.visibility
      ? resource.visibility.toLowerCase()
      : null;

    const publicRadio = safeGetElement("edit-resource-visibility-public");
    const teamRadio = safeGetElement("edit-resource-visibility-team");
    const privateRadio = safeGetElement("edit-resource-visibility-private");

    // Clear all first
    if (publicRadio) {
      publicRadio.checked = false;
    }
    if (teamRadio) {
      teamRadio.checked = false;
    }
    if (privateRadio) {
      privateRadio.checked = false;
    }

    if (visibility) {
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    // Set form action and populate fields with validation
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/resources/${encodeURIComponent(resourceId)}/edit`;
    }

    // Validate inputs
    const nameValidation = validateInputName(resource.name, "resource");
    const uriValidation = validateInputName(resource.uri, "resource URI");

    const uriField = safeGetElement("edit-resource-uri");
    const nameField = safeGetElement("edit-resource-name");
    const descField = safeGetElement("edit-resource-description");
    const mimeField = safeGetElement("edit-resource-mime-type");
    // const contentField = safeGetElement("edit-resource-content");

    if (uriField && uriValidation.valid) {
      uriField.value = uriValidation.value;
    }
    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (descField) {
      descField.value = resource.description || "";
    }
    if (mimeField) {
      mimeField.value = resource.mimeType || "";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-resource-tags");
    if (tagsField) {
      const rawTags = resource.tags
        ? resource.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    // if (contentField) {
    //     let contentStr = extractContent(
    //         content,
    //         resource.description || "No content available",
    //     );

    //     if (!contentStr.trim()) {
    //         contentStr = resource.description || "No content available";
    //     }

    //     contentField.value = contentStr;
    // }

    // // Update CodeMirror editor if it exists
    // if (window.editResourceContentEditor) {
    //     let contentStr = extractContent(
    //         content,
    //         resource.description || "No content available",
    //     );

    //     if (!contentStr.trim()) {
    //         contentStr = resource.description || "No content available";
    //     }

    //     window.editResourceContentEditor.setValue(contentStr);
    //     window.editResourceContentEditor.refresh();
    // }

    openModal("resource-edit-modal");

    // Refresh editor after modal display
    setTimeout(() => {
      if (window.editResourceContentEditor) {
        window.editResourceContentEditor.refresh();
      }
    }, 100);

    console.log("✓ Resource edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching resource for editing:", error);
    const errorMessage = handleFetchError(error, "load resource for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: View Prompt function with safe display
 */
export const viewPrompt = async function (promptName) {
  try {
    console.log(`Viewing prompt: ${promptName}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptName)}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const prompt = await response.json();
    const promptLabel =
      prompt.displayName || prompt.originalName || prompt.name || prompt.id;
    const gatewayLabel = prompt.gatewaySlug || "Local";

    const promptDetailsDiv = safeGetElement("prompt-details");
    if (promptDetailsDiv) {
      const safeHTML = `
        <div class="grid grid-cols-2 gap-6 mb-6">
        <div class="space-y-3">
            <div>
              <span id="prompt-id-label" class="font-medium text-gray-700 dark:text-gray-300">Prompt ID:</span>
              <div class="mt-1 prompt-id text-sm font-mono text-indigo-600 dark:text-indigo-400" aria-labelledby="prompt-id-label"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Display Name:</span>
            <div class="mt-1 prompt-display-name font-medium"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Technical Name:</span>
            <div class="mt-1 prompt-name text-sm font-mono"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Original Name:</span>
            <div class="mt-1 prompt-original-name text-sm font-mono"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Custom Name:</span>
            <div class="mt-1 prompt-custom-name text-sm font-mono"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Gateway Name:</span>
            <div class="mt-1 prompt-gateway text-sm"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Visibility:</span>
            <div class="mt-1 prompt-visibility text-sm"></div>
            </div>
        </div>
        <div class="space-y-3">
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Description:</span>
            <div class="mt-1 prompt-description text-sm"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Tags:</span>
            <div class="mt-1 prompt-tags text-sm"></div>
            </div>
            <div>
            <span class="font-medium text-gray-700 dark:text-gray-300">Status:</span>
            <div class="mt-1 prompt-status text-sm"></div>
            </div>
        </div>
        </div>

        <div class="space-y-4">
        <div>
            <strong class="text-gray-700 dark:text-gray-300">Template:</strong>
            <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 prompt-template overflow-x-auto"></pre>
        </div>
        <div>
            <strong class="text-gray-700 dark:text-gray-300">Arguments:</strong>
            <pre class="mt-1 bg-gray-100 p-3 rounded text-xs dark:bg-gray-800 dark:text-gray-200 prompt-arguments overflow-x-auto"></pre>
        </div>
        </div>

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
            <span class="ml-2 metadata-modified-from"></span>
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
    `;

      promptDetailsDiv.innerHTML = safeHTML;

      const setText = (selector, value) => {
        const el = promptDetailsDiv.querySelector(selector);
        if (el) {
          el.textContent = value;
        }
      };

      setText(".prompt-id", prompt.id || "N/A");
      setText(".prompt-display-name", promptLabel);
      setText(".prompt-name", prompt.name || "N/A");
      setText(".prompt-original-name", prompt.originalName || "N/A");
      setText(".prompt-custom-name", prompt.customName || "N/A");
      setText(".prompt-gateway", gatewayLabel);
      setText(".prompt-visibility", prompt.visibility || "private");
      setText(".prompt-description", prompt.description || "N/A");

      const tagsEl = promptDetailsDiv.querySelector(".prompt-tags");
      if (tagsEl) {
        tagsEl.innerHTML = "";
        if (prompt.tags && prompt.tags.length > 0) {
          prompt.tags.forEach((tag) => {
            const tagSpan = document.createElement("span");
            tagSpan.className =
              "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
            const raw =
              typeof tag === "object" && tag !== null
                ? tag.id || tag.label
                : tag;
            tagSpan.textContent = raw;
            tagsEl.appendChild(tagSpan);
          });
        } else {
          tagsEl.textContent = "None";
        }
      }

      const statusEl = promptDetailsDiv.querySelector(".prompt-status");
      if (statusEl) {
        const isActive =
          prompt.enabled !== undefined ? prompt.enabled : prompt.isActive;
        const statusSpan = document.createElement("span");
        statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
          isActive ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
        }`;
        statusSpan.textContent = isActive ? "Active" : "Inactive";
        statusEl.innerHTML = "";
        statusEl.appendChild(statusSpan);
      }

      const templateEl = promptDetailsDiv.querySelector(".prompt-template");
      if (templateEl) {
        templateEl.textContent = prompt.template || "";
      }

      const argsEl = promptDetailsDiv.querySelector(".prompt-arguments");
      if (argsEl) {
        argsEl.textContent = JSON.stringify(prompt.arguments || {}, null, 2);
      }

      if (prompt.metrics) {
        setText(".metric-total", prompt.metrics.totalExecutions ?? 0);
        setText(".metric-success", prompt.metrics.successfulExecutions ?? 0);
        setText(".metric-failed", prompt.metrics.failedExecutions ?? 0);
        setText(".metric-failure-rate", prompt.metrics.failureRate ?? 0);
        setText(".metric-min-time", prompt.metrics.minResponseTime ?? "N/A");
        setText(".metric-max-time", prompt.metrics.maxResponseTime ?? "N/A");
        setText(".metric-avg-time", prompt.metrics.avgResponseTime ?? "N/A");
        setText(".metric-last-time", prompt.metrics.lastExecutionTime ?? "N/A");
      } else {
        [
          ".metric-total",
          ".metric-success",
          ".metric-failed",
          ".metric-failure-rate",
          ".metric-min-time",
          ".metric-max-time",
          ".metric-avg-time",
          ".metric-last-time",
        ].forEach((selector) => setText(selector, "N/A"));
      }

      const createdAt = prompt.created_at || prompt.createdAt;
      const updatedAt = prompt.updated_at || prompt.updatedAt;

      setText(
        ".metadata-created-by",
        prompt.created_by || prompt.createdBy || "Legacy Entity"
      );
      setText(
        ".metadata-created-at",
        createdAt ? new Date(createdAt).toLocaleString() : "Pre-metadata"
      );
      setText(
        ".metadata-created-from",
        prompt.created_from_ip || prompt.createdFromIp || "Unknown"
      );
      setText(
        ".metadata-created-via",
        prompt.created_via || prompt.createdVia || "Unknown"
      );
      setText(
        ".metadata-modified-by",
        prompt.modified_by || prompt.modifiedBy || "N/A"
      );
      setText(
        ".metadata-modified-at",
        updatedAt ? new Date(updatedAt).toLocaleString() : "N/A"
      );
      setText(
        ".metadata-modified-from",
        prompt.modified_from_ip || prompt.modifiedFromIp || "N/A"
      );
      setText(
        ".metadata-modified-via",
        prompt.modified_via || prompt.modifiedVia || "N/A"
      );
      setText(".metadata-version", prompt.version || "1");
      setText(".metadata-import-batch", prompt.importBatchId || "N/A");

      // Content already injected via innerHTML; no extra wrapper needed.
    }

    openModal("prompt-modal");
    console.log("✓ Prompt details loaded successfully");
  } catch (error) {
    console.error("Error fetching prompt details:", error);
    const errorMessage = handleFetchError(error, "load prompt details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Prompt function with validation
 */
export const editPrompt = async function (promptId) {
  try {
    console.log(`Editing prompt: ${promptId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const prompt = await response.json();

    const isInactiveCheckedBool = isInactiveChecked("prompts");
    let hiddenField = safeGetElement("edit-prompt-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-prompt-show-inactive";
      const editForm = safeGetElement("edit-prompt-form");
      if (editForm) {
        editForm.appendChild(hiddenField);
      }
    }
    hiddenField.value = isInactiveCheckedBool;

    // ✅ Prefill visibility radios (consistent with server)
    const visibility = prompt.visibility
      ? prompt.visibility.toLowerCase()
      : null;

    const publicRadio = safeGetElement("edit-prompt-visibility-public");
    const teamRadio = safeGetElement("edit-prompt-visibility-team");
    const privateRadio = safeGetElement("edit-prompt-visibility-private");

    // Clear all first
    if (publicRadio) {
      publicRadio.checked = false;
    }
    if (teamRadio) {
      teamRadio.checked = false;
    }
    if (privateRadio) {
      privateRadio.checked = false;
    }

    if (visibility) {
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    // Set form action and populate fields with validation
    const editForm = safeGetElement("edit-prompt-form");
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/prompts/${encodeURIComponent(promptId)}/edit`;
      // Add or update hidden team_id input if present in URL
      const teamId = new URL(window.location.href).searchParams.get("team_id");
      if (teamId) {
        let teamInput = safeGetElement("edit-prompt-team-id");
        if (!teamInput) {
          teamInput = document.createElement("input");
          teamInput.type = "hidden";
          teamInput.name = "team_id";
          teamInput.id = "edit-prompt-team-id";
          editForm.appendChild(teamInput);
        }
        teamInput.value = teamId;
      }
    }

    const nameValidation = validateInputName(prompt.name, "prompt");
    const customNameValidation = validateInputName(
      prompt.customName || prompt.originalName || prompt.name,
      "prompt"
    );

    const nameField = safeGetElement("edit-prompt-name");
    const customNameField = safeGetElement("edit-prompt-custom-name");
    const displayNameField = safeGetElement("edit-prompt-display-name");
    const technicalNameField = safeGetElement("edit-prompt-technical-name");
    const descField = safeGetElement("edit-prompt-description");
    const templateField = safeGetElement("edit-prompt-template");
    const argsField = safeGetElement("edit-prompt-arguments");

    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (technicalNameField) {
      technicalNameField.value = prompt.name || "N/A";
    }
    if (customNameField && customNameValidation.valid) {
      customNameField.value = customNameValidation.value;
    }
    if (displayNameField) {
      displayNameField.value = prompt.displayName || "";
    }
    if (descField) {
      descField.value = prompt.description || "";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-prompt-tags");
    if (tagsField) {
      const rawTags = prompt.tags
        ? prompt.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    if (templateField) {
      templateField.value = prompt.template || "";
    }

    // Validate arguments JSON
    const argsValidation = validateJson(
      JSON.stringify(prompt.arguments || {}),
      "Arguments"
    );
    if (argsField && argsValidation.valid) {
      argsField.value = JSON.stringify(argsValidation.value, null, 2);
    }

    // Update CodeMirror editors if they exist
    if (window.editPromptTemplateEditor) {
      window.editPromptTemplateEditor.setValue(prompt.template || "");
      window.editPromptTemplateEditor.refresh();
    }
    if (window.editPromptArgumentsEditor && argsValidation.valid) {
      window.editPromptArgumentsEditor.setValue(
        JSON.stringify(argsValidation.value, null, 2)
      );
      window.editPromptArgumentsEditor.refresh();
    }

    openModal("prompt-edit-modal");

    // Refresh editors after modal display
    setTimeout(() => {
      if (window.editPromptTemplateEditor) {
        window.editPromptTemplateEditor.refresh();
      }
      if (window.editPromptArgumentsEditor) {
        window.editPromptArgumentsEditor.refresh();
      }
    }, 100);

    console.log("✓ Prompt edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching prompt for editing:", error);
    const errorMessage = handleFetchError(error, "load prompt for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: View Gateway function
 */
export const viewGateway = async function (gatewayId) {
  try {
    console.log(`Viewing gateway ID: ${gatewayId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/gateways/${gatewayId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const gateway = await response.json();

    const gatewayDetailsDiv = safeGetElement("gateway-details");
    if (gatewayDetailsDiv) {
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      const fields = [
        { label: "Name", value: gateway.name },
        { label: "URL", value: gateway.url },
        { label: "Description", value: gateway.description || "N/A" },
        { label: "Visibility", value: gateway.visibility || "private" },
      ];

      // Add tags field with special handling
      const tagsP = document.createElement("p");
      const tagsStrong = document.createElement("strong");
      tagsStrong.textContent = "Tags: ";
      tagsP.appendChild(tagsStrong);
      if (gateway.tags && gateway.tags.length > 0) {
        gateway.tags.forEach((tag, index) => {
          const tagSpan = document.createElement("span");
          tagSpan.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1";
          const raw =
            typeof tag === "object" && tag !== null
              ? tag.id || tag.label || JSON.stringify(tag)
              : tag;
          tagSpan.textContent = raw;
          tagsP.appendChild(tagSpan);
        });
      } else {
        tagsP.appendChild(document.createTextNode("No tags"));
      }
      container.appendChild(tagsP);

      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Status
      const statusP = document.createElement("p");
      const statusStrong = document.createElement("strong");
      statusStrong.textContent = "Status: ";
      statusP.appendChild(statusStrong);

      const statusSpan = document.createElement("span");
      let statusText = "";
      let statusClass = "";
      let statusIcon = "";
      if (!gateway.enabled) {
        statusText = "Inactive";
        statusClass = "bg-red-100 text-red-800";
        statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-red-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M6.293 6.293a1 1 0 011.414 0L10 8.586l2.293-2.293a1 1 0 111.414 1.414L11.414 10l2.293 2.293a1 1 0 11-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 11-1.414-1.414L8.586 10 6.293 7.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                    </svg>`;
      } else if (gateway.enabled && gateway.reachable) {
        statusText = "Active";
        statusClass = "bg-green-100 text-green-800";
        statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-green-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-4.586l5.293-5.293-1.414-1.414L9 11.586 7.121 9.707 5.707 11.121 9 14.414z" clip-rule="evenodd"></path>
                    </svg>`;
      } else if (gateway.enabled && !gateway.reachable) {
        statusText = "Offline";
        statusClass = "bg-yellow-100 text-yellow-800";
        statusIcon = `
                    <svg class="ml-1 h-4 w-4 text-yellow-600 self-center" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-10h2v4h-2V8zm0 6h2v2h-2v-2z" clip-rule="evenodd"></path>
                    </svg>`;
      }

      statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusClass}`;
      statusSpan.innerHTML = `${statusText} ${statusIcon}`;

      statusP.appendChild(statusSpan);
      container.appendChild(statusP);

      // Add metadata section
      const metadataDiv = document.createElement("div");
      metadataDiv.className = "mt-6 border-t pt-4";

      const metadataTitle = document.createElement("strong");
      metadataTitle.textContent = "Metadata:";
      metadataDiv.appendChild(metadataTitle);

      const metadataGrid = document.createElement("div");
      metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

      const metadataFields = [
        {
          label: "Created By",
          value: gateway.created_by || gateway.createdBy || "Legacy Entity",
        },
        {
          label: "Created At",
          value:
            gateway.created_at || gateway.createdAt
              ? new Date(
                gateway.created_at || gateway.createdAt
              ).toLocaleString()
              : "Pre-metadata",
        },
        {
          label: "Created From IP",
          value: gateway.created_from_ip || gateway.createdFromIp || "Unknown",
        },
        {
          label: "Created Via",
          value: gateway.created_via || gateway.createdVia || "Unknown",
        },
        {
          label: "Last Modified By",
          value: gateway.modified_by || gateway.modifiedBy || "N/A",
        },
        {
          label: "Last Modified At",
          value:
            gateway.updated_at || gateway.updatedAt
              ? new Date(
                gateway.updated_at || gateway.updatedAt
              ).toLocaleString()
              : "N/A",
        },
        {
          label: "Modified From IP",
          value: gateway.modified_from_ip || gateway.modifiedFromIp || "N/A",
        },
        {
          label: "Modified Via",
          value: gateway.modified_via || gateway.modifiedVia || "N/A",
        },
        { label: "Version", value: gateway.version || "1" },
        {
          label: "Import Batch",
          value: gateway.importBatchId || "N/A",
        },
      ];

      metadataFields.forEach((field) => {
        const fieldDiv = document.createElement("div");

        const labelSpan = document.createElement("span");
        labelSpan.className = "font-medium text-gray-600 dark:text-gray-400";
        labelSpan.textContent = field.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "ml-2";
        valueSpan.textContent = field.value;

        fieldDiv.appendChild(labelSpan);
        fieldDiv.appendChild(valueSpan);
        metadataGrid.appendChild(fieldDiv);
      });

      metadataDiv.appendChild(metadataGrid);
      container.appendChild(metadataDiv);

      gatewayDetailsDiv.innerHTML = "";
      gatewayDetailsDiv.appendChild(container);
    }

    openModal("gateway-modal");
    console.log("✓ Gateway details loaded successfully");
  } catch (error) {
    console.error("Error fetching gateway details:", error);
    const errorMessage = handleFetchError(error, "load gateway details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Gateway function
 */
export const editGateway = async function (gatewayId) {
  try {
    console.log(`Editing gateway ID: ${gatewayId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/gateways/${gatewayId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const gateway = await response.json();

    console.log("Gateway Details: " + JSON.stringify(gateway, null, 2));

    const isInactiveCheckedBool = isInactiveChecked("gateways");
    let hiddenField = safeGetElement("edit-gateway-show-inactive");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-gateway-show-inactive";
      const editForm = safeGetElement("edit-gateway-form");
      if (editForm) {
        editForm.appendChild(hiddenField);
      }
    }
    hiddenField.value = isInactiveCheckedBool;

    // Set form action and populate fields with validation
    const editForm = safeGetElement("edit-gateway-form");
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/gateways/${gatewayId}/edit`;
    }

    const nameValidation = validateInputName(gateway.name, "gateway");
    const urlValidation = validateUrl(gateway.url);

    const nameField = safeGetElement("edit-gateway-name");
    const urlField = safeGetElement("edit-gateway-url");
    const descField = safeGetElement("edit-gateway-description");

    const transportField = safeGetElement("edit-gateway-transport");

    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (urlField && urlValidation.valid) {
      urlField.value = urlValidation.value;
    }
    if (descField) {
      descField.value = gateway.description || "";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-gateway-tags");
    if (tagsField) {
      const rawTags = gateway.tags
        ? gateway.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    const teamId = new URL(window.location.href).searchParams.get("team_id");

    if (teamId) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = "team_id";
      hiddenInput.value = teamId;
      editForm.appendChild(hiddenInput);
    }

    const visibility = gateway.visibility; // Ensure visibility is either 'public', 'team', or 'private'
    const publicRadio = safeGetElement("edit-gateway-visibility-public");
    const teamRadio = safeGetElement("edit-gateway-visibility-team");
    const privateRadio = safeGetElement("edit-gateway-visibility-private");

    if (visibility) {
      // Check visibility and set the corresponding radio button
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    if (transportField) {
      transportField.value = gateway.transport || "SSE"; // falls back to Admin.SSE(default)
    }

    const authTypeField = safeGetElement("auth-type-gw-edit");

    if (authTypeField) {
      authTypeField.value = gateway.authType || ""; // falls back to None
    }

    // Auth containers
    const authBasicSection = safeGetElement("auth-basic-fields-gw-edit");
    const authBearerSection = safeGetElement("auth-bearer-fields-gw-edit");
    const authHeadersSection = safeGetElement("auth-headers-fields-gw-edit");
    const authOAuthSection = safeGetElement("auth-oauth-fields-gw-edit");
    const authQueryParamSection = safeGetElement(
      "auth-query_param-fields-gw-edit"
    );

    // Individual fields
    const authUsernameField = safeGetElement(
      "auth-basic-fields-gw-edit"
    )?.querySelector("input[name='auth_username']");
    const authPasswordField = safeGetElement(
      "auth-basic-fields-gw-edit"
    )?.querySelector("input[name='auth_password']");

    const authTokenField = safeGetElement(
      "auth-bearer-fields-gw-edit"
    )?.querySelector("input[name='auth_token']");

    const authHeaderKeyField = safeGetElement(
      "auth-headers-fields-gw-edit"
    )?.querySelector("input[name='auth_header_key']");
    const authHeaderValueField = safeGetElement(
      "auth-headers-fields-gw-edit"
    )?.querySelector("input[name='auth_header_value']");

    // OAuth fields
    const oauthGrantTypeField = safeGetElement("oauth-grant-type-gw-edit");
    const oauthClientIdField = safeGetElement("oauth-client-id-gw-edit");
    const oauthClientSecretField = safeGetElement(
      "oauth-client-secret-gw-edit"
    );
    const oauthTokenUrlField = safeGetElement("oauth-token-url-gw-edit");
    const oauthAuthUrlField = safeGetElement("oauth-authorization-url-gw-edit");
    const oauthRedirectUriField = safeGetElement("oauth-redirect-uri-gw-edit");
    const oauthScopesField = safeGetElement("oauth-scopes-gw-edit");
    const oauthAuthCodeFields = safeGetElement(
      "oauth-auth-code-fields-gw-edit"
    );

    // Hide all auth sections first
    if (authBasicSection) {
      authBasicSection.style.display = "none";
    }
    if (authBearerSection) {
      authBearerSection.style.display = "none";
    }
    if (authHeadersSection) {
      authHeadersSection.style.display = "none";
    }
    if (authOAuthSection) {
      authOAuthSection.style.display = "none";
    }
    if (authQueryParamSection) {
      authQueryParamSection.style.display = "none";
    }

    switch (gateway.authType) {
      case "basic":
        if (authBasicSection) {
          authBasicSection.style.display = "block";
          if (authUsernameField) {
            authUsernameField.value = gateway.authUsername || "";
          }
          if (authPasswordField) {
            if (gateway.authPasswordUnmasked) {
              authPasswordField.dataset.isMasked = "true";
              authPasswordField.dataset.realValue =
                gateway.authPasswordUnmasked;
            } else {
              delete authPasswordField.dataset.isMasked;
              delete authPasswordField.dataset.realValue;
            }
            authPasswordField.value = MASKED_AUTH_VALUE;
          }
        }
        break;
      case "bearer":
        if (authBearerSection) {
          authBearerSection.style.display = "block";
          if (authTokenField) {
            if (gateway.authTokenUnmasked) {
              authTokenField.dataset.isMasked = "true";
              authTokenField.dataset.realValue = gateway.authTokenUnmasked;
              authTokenField.value = MASKED_AUTH_VALUE;
            } else {
              delete authTokenField.dataset.isMasked;
              delete authTokenField.dataset.realValue;
              authTokenField.value = gateway.authToken || "";
            }
          }
        }
        break;
      case "authheaders":
        if (authHeadersSection) {
          authHeadersSection.style.display = "block";
          const unmaskedHeaders =
            Array.isArray(gateway.authHeadersUnmasked) &&
            gateway.authHeadersUnmasked.length > 0
              ? gateway.authHeadersUnmasked
              : gateway.authHeaders;
          if (Array.isArray(unmaskedHeaders) && unmaskedHeaders.length > 0) {
            loadAuthHeaders("auth-headers-container-gw-edit", unmaskedHeaders, {
              maskValues: true,
            });
          } else {
            updateAuthHeadersJSON("auth-headers-container-gw-edit");
          }
          if (authHeaderKeyField) {
            authHeaderKeyField.value = gateway.authHeaderKey || "";
          }
          if (authHeaderValueField) {
            if (
              Array.isArray(unmaskedHeaders) &&
              unmaskedHeaders.length === 1
            ) {
              authHeaderValueField.dataset.isMasked = "true";
              authHeaderValueField.dataset.realValue =
                unmaskedHeaders[0].value ?? "";
            }
            authHeaderValueField.value = MASKED_AUTH_VALUE;
          }
        }
        break;
      case "oauth":
        if (authOAuthSection) {
          authOAuthSection.style.display = "block";
        }
        // Populate OAuth fields if available
        if (gateway.oauthConfig) {
          const config = gateway.oauthConfig;
          if (oauthGrantTypeField && config.grant_type) {
            oauthGrantTypeField.value = config.grant_type;
            // Show/hide authorization code fields based on grant type
            if (oauthAuthCodeFields) {
              oauthAuthCodeFields.style.display =
                config.grant_type === "authorization_code" ? "block" : "none";
            }
          }
          if (oauthClientIdField && config.client_id) {
            oauthClientIdField.value = config.client_id;
          }
          if (oauthClientSecretField) {
            oauthClientSecretField.value = ""; // Don't populate secret for security
          }
          if (oauthTokenUrlField && config.token_url) {
            oauthTokenUrlField.value = config.token_url;
          }
          if (oauthAuthUrlField && config.authorization_url) {
            oauthAuthUrlField.value = config.authorization_url;
          }
          if (oauthRedirectUriField && config.redirect_uri) {
            oauthRedirectUriField.value = config.redirect_uri;
          }
          if (
            oauthScopesField &&
            config.scopes &&
            Array.isArray(config.scopes)
          ) {
            oauthScopesField.value = config.scopes.join(" ");
          }
        }
        break;
      case "query_param":
        if (authQueryParamSection) {
          authQueryParamSection.style.display = "block";
          // Get the input fields within the section
          const queryParamKeyField = authQueryParamSection.querySelector(
            "input[name='auth_query_param_key']"
          );
          const queryParamValueField = authQueryParamSection.querySelector(
            "input[name='auth_query_param_value']"
          );
          if (queryParamKeyField && gateway.authQueryParamKey) {
            queryParamKeyField.value = gateway.authQueryParamKey;
          }
          if (queryParamValueField) {
            // Always show masked value for security
            queryParamValueField.value = MASKED_AUTH_VALUE;
            if (gateway.authQueryParamValueUnmasked) {
              queryParamValueField.dataset.isMasked = "true";
              queryParamValueField.dataset.realValue =
                gateway.authQueryParamValueUnmasked;
            } else {
              delete queryParamValueField.dataset.isMasked;
              delete queryParamValueField.dataset.realValue;
            }
          }
        }
        break;
      case "":
      default:
        // No auth – keep everything hidden
        break;
    }

    // Handle passthrough headers
    const passthroughHeadersField = safeGetElement(
      "edit-gateway-passthrough-headers"
    );
    if (passthroughHeadersField) {
      if (
        gateway.passthroughHeaders &&
        Array.isArray(gateway.passthroughHeaders)
      ) {
        passthroughHeadersField.value = gateway.passthroughHeaders.join(", ");
      } else {
        passthroughHeadersField.value = "";
      }
    }

    openModal("gateway-edit-modal");
    console.log("✓ Gateway edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching gateway for editing:", error);
    const errorMessage = handleFetchError(error, "load gateway for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: View Server function
 */
export const viewServer = async function (serverId) {
  try {
    console.log(`Viewing server ID: ${serverId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/servers/${serverId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const server = await response.json();

    const serverDetailsDiv = safeGetElement("server-details");
    if (serverDetailsDiv) {
      const container = document.createElement("div");
      container.className = "space-y-4 dark:bg-gray-900 dark:text-gray-100";

      // Header section with server name and icon
      const headerDiv = document.createElement("div");
      headerDiv.className =
        "flex items-center space-x-3 pb-4 border-b border-gray-200 dark:border-gray-600";

      if (server.icon) {
        const iconImg = document.createElement("img");
        iconImg.src = server.icon;
        iconImg.alt = `${server.name} icon`;
        iconImg.className = "w-12 h-12 rounded-lg object-cover";
        iconImg.onerror = function () {
          this.style.display = "none";
        };
        headerDiv.appendChild(iconImg);
      }

      const headerTextDiv = document.createElement("div");
      const serverTitle = document.createElement("h2");
      serverTitle.className =
        "text-xl font-bold text-gray-900 dark:text-gray-100";
      serverTitle.textContent = server.name;
      headerTextDiv.appendChild(serverTitle);

      if (server.description) {
        const serverDesc = document.createElement("p");
        serverDesc.className = "text-sm text-gray-600 dark:text-gray-400 mt-1";
        serverDesc.textContent = server.description;
        headerTextDiv.appendChild(serverDesc);
      }

      headerDiv.appendChild(headerTextDiv);
      container.appendChild(headerDiv);

      // Basic information section
      const basicInfoDiv = document.createElement("div");
      basicInfoDiv.className = "space-y-2";

      const basicInfoTitle = document.createElement("strong");
      basicInfoTitle.textContent = "Basic Information:";
      basicInfoTitle.className = "block text-gray-900 dark:text-gray-100 mb-3";
      basicInfoDiv.appendChild(basicInfoTitle);

      const fields = [
        { label: "Server ID", value: server.id },
        { label: "URL", value: getCatalogUrl(server) || "N/A" },
        { label: "Type", value: "Virtual Server" },
        { label: "Visibility", value: server.visibility || "private" },
      ];

      fields.forEach((field) => {
        const p = document.createElement("p");
        p.className = "text-sm";
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        strong.className = "font-medium text-gray-700 dark:text-gray-300";
        p.appendChild(strong);
        const valueSpan = document.createElement("span");
        valueSpan.textContent = field.value;
        valueSpan.className = "text-gray-600 dark:text-gray-400";
        p.appendChild(valueSpan);
        basicInfoDiv.appendChild(p);
      });

      container.appendChild(basicInfoDiv);

      // Tags and Status section
      const tagsStatusDiv = document.createElement("div");
      tagsStatusDiv.className = "flex items-center justify-between space-y-2";

      // Tags section
      const tagsP = document.createElement("p");
      tagsP.className = "text-sm";
      const tagsStrong = document.createElement("strong");
      tagsStrong.textContent = "Tags: ";
      tagsStrong.className = "font-medium text-gray-700 dark:text-gray-300";
      tagsP.appendChild(tagsStrong);

      if (server.tags && server.tags.length > 0) {
        server.tags.forEach((tag) => {
          const tagSpan = document.createElement("span");
          tagSpan.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full mr-1 mb-1 dark:bg-blue-900 dark:text-blue-200";
          const raw =
            typeof tag === "object" && tag !== null ? tag.id || tag.label : tag;
          tagSpan.textContent = raw;
          tagsP.appendChild(tagSpan);
        });
      } else {
        const noneSpan = document.createElement("span");
        noneSpan.textContent = "None";
        noneSpan.className = "text-gray-500 dark:text-gray-400";
        tagsP.appendChild(noneSpan);
      }

      // Status section
      const statusP = document.createElement("p");
      statusP.className = "text-sm";
      const statusStrong = document.createElement("strong");
      statusStrong.textContent = "Status: ";
      statusStrong.className = "font-medium text-gray-700 dark:text-gray-300";
      statusP.appendChild(statusStrong);

      const statusSpan = document.createElement("span");
      statusSpan.className = `px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
        server.enabled
          ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
          : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300"
      }`;
      statusSpan.textContent = server.enabled ? "Active" : "Inactive";
      statusP.appendChild(statusSpan);

      tagsStatusDiv.appendChild(tagsP);
      tagsStatusDiv.appendChild(statusP);
      container.appendChild(tagsStatusDiv);

      // Associated Tools, Resources, and Prompts section
      const associatedDiv = document.createElement("div");
      associatedDiv.className = "mt-6 border-t pt-4";

      const associatedTitle = document.createElement("strong");
      associatedTitle.textContent = "Associated Items:";
      associatedDiv.appendChild(associatedTitle);

      // Tools section
      if (server.associatedTools && server.associatedTools.length > 0) {
        const toolsSection = document.createElement("div");
        toolsSection.className = "mt-3";

        const toolsLabel = document.createElement("p");
        const toolsStrong = document.createElement("strong");
        toolsStrong.textContent = "Tools: ";
        toolsLabel.appendChild(toolsStrong);

        const toolsList = document.createElement("div");
        toolsList.className = "mt-1 space-y-1";

        const maxToShow = 3;
        const toolsToShow = server.associatedTools.slice(0, maxToShow);

        toolsToShow.forEach((toolId) => {
          const toolItem = document.createElement("div");
          toolItem.className = "flex items-center space-x-2";

          const toolBadge = document.createElement("span");
          toolBadge.className =
            "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full dark:bg-green-900 dark:text-green-200";
          toolBadge.textContent =
            Admin.toolMapping && Admin.toolMapping[toolId]
              ? Admin.toolMapping[toolId]
              : toolId;

          const toolIdSpan = document.createElement("span");
          toolIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          toolIdSpan.textContent = `(${toolId})`;

          toolItem.appendChild(toolBadge);
          toolItem.appendChild(toolIdSpan);
          toolsList.appendChild(toolItem);
        });

        // If more than maxToShow, add a summary badge
        if (server.associatedTools.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-green-900 dark:text-green-200";
          moreBadge.title = "Total tools associated";
          const remaining = server.associatedTools.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          moreItem.appendChild(moreBadge);
          toolsList.appendChild(moreItem);
        }

        toolsLabel.appendChild(toolsList);
        toolsSection.appendChild(toolsLabel);
        associatedDiv.appendChild(toolsSection);
      }

      // Resources section
      if (server.associatedResources && server.associatedResources.length > 0) {
        const resourcesSection = document.createElement("div");
        resourcesSection.className = "mt-3";

        const resourcesLabel = document.createElement("p");
        const resourcesStrong = document.createElement("strong");
        resourcesStrong.textContent = "Resources: ";
        resourcesLabel.appendChild(resourcesStrong);

        const resourcesList = document.createElement("div");
        resourcesList.className = "mt-1 space-y-1";

        const maxToShow = 3;
        const resourcesToShow = server.associatedResources.slice(0, maxToShow);

        resourcesToShow.forEach((resourceId) => {
          const resourceItem = document.createElement("div");
          resourceItem.className = "flex items-center space-x-2";

          const resourceBadge = document.createElement("span");
          resourceBadge.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full dark:bg-blue-900 dark:text-blue-200";
          resourceBadge.textContent =
            Admin.resourceMapping && Admin.resourceMapping[resourceId]
              ? Admin.resourceMapping[resourceId]
              : `Resource ${resourceId}`;

          const resourceIdSpan = document.createElement("span");
          resourceIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          resourceIdSpan.textContent = `(${resourceId})`;

          resourceItem.appendChild(resourceBadge);
          resourceItem.appendChild(resourceIdSpan);
          resourcesList.appendChild(resourceItem);
        });

        // If more than maxToShow, add a summary badge
        if (server.associatedResources.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-blue-900 dark:text-blue-200";
          moreBadge.title = "Total resources associated";
          const remaining = server.associatedResources.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          moreItem.appendChild(moreBadge);
          resourcesList.appendChild(moreItem);
        }

        resourcesLabel.appendChild(resourcesList);
        resourcesSection.appendChild(resourcesLabel);
        associatedDiv.appendChild(resourcesSection);
      }

      // Prompts section
      if (server.associatedPrompts && server.associatedPrompts.length > 0) {
        const promptsSection = document.createElement("div");
        promptsSection.className = "mt-3";

        const promptsLabel = document.createElement("p");
        const promptsStrong = document.createElement("strong");
        promptsStrong.textContent = "Prompts: ";
        promptsLabel.appendChild(promptsStrong);

        const promptsList = document.createElement("div");
        promptsList.className = "mt-1 space-y-1";

        const maxToShow = 3;
        const promptsToShow = server.associatedPrompts.slice(0, maxToShow);

        promptsToShow.forEach((promptId) => {
          const promptItem = document.createElement("div");
          promptItem.className = "flex items-center space-x-2";

          const promptBadge = document.createElement("span");
          promptBadge.className =
            "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full dark:bg-purple-900 dark:text-purple-200";
          promptBadge.textContent =
            Admin.promptMapping && Admin.promptMapping[promptId]
              ? Admin.promptMapping[promptId]
              : `Prompt ${promptId}`;

          const promptIdSpan = document.createElement("span");
          promptIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          promptIdSpan.textContent = `(${promptId})`;

          promptItem.appendChild(promptBadge);
          promptItem.appendChild(promptIdSpan);
          promptsList.appendChild(promptItem);
        });

        // If more than maxToShow, add a summary badge
        if (server.associatedPrompts.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-purple-900 dark:text-purple-200";
          moreBadge.title = "Total prompts associated";
          const remaining = server.associatedPrompts.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          moreItem.appendChild(moreBadge);
          promptsList.appendChild(moreItem);
        }

        promptsLabel.appendChild(promptsList);
        promptsSection.appendChild(promptsLabel);
        associatedDiv.appendChild(promptsSection);
      }

      // A2A Agents section
      if (server.associatedA2aAgents && server.associatedA2aAgents.length > 0) {
        const agentsSection = document.createElement("div");
        agentsSection.className = "mt-3";

        const agentsLabel = document.createElement("p");
        const agentsStrong = document.createElement("strong");
        agentsStrong.textContent = "A2A Agents: ";
        agentsLabel.appendChild(agentsStrong);

        const agentsList = document.createElement("div");
        agentsList.className = "mt-1 space-y-1";

        server.associatedA2aAgents.forEach((agentId) => {
          const agentItem = document.createElement("div");
          agentItem.className = "flex items-center space-x-2";

          const agentBadge = document.createElement("span");
          agentBadge.className =
            "inline-block bg-orange-100 text-orange-800 text-xs px-2 py-1 rounded-full dark:bg-orange-900 dark:text-orange-200";
          agentBadge.textContent = `Agent ${agentId}`;

          const agentIdSpan = document.createElement("span");
          agentIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          agentIdSpan.textContent = `(${agentId})`;

          agentItem.appendChild(agentBadge);
          agentItem.appendChild(agentIdSpan);
          agentsList.appendChild(agentItem);
        });

        agentsLabel.appendChild(agentsList);
        agentsSection.appendChild(agentsLabel);
        associatedDiv.appendChild(agentsSection);
      }

      // Show message if no associated items
      if (
        (!server.associatedTools || server.associatedTools.length === 0) &&
        (!server.associatedResources ||
          server.associatedResources.length === 0) &&
        (!server.associatedPrompts || server.associatedPrompts.length === 0) &&
        (!server.associatedA2aAgents || server.associatedA2aAgents.length === 0)
      ) {
        const noItemsP = document.createElement("p");
        noItemsP.className = "mt-2 text-sm text-gray-500 dark:text-gray-400";
        noItemsP.textContent =
          "No tools, resources, prompts, or A2A agents are currently associated with this server.";
        associatedDiv.appendChild(noItemsP);
      }

      container.appendChild(associatedDiv);

      // Add metadata section
      const metadataDiv = document.createElement("div");
      metadataDiv.className = "mt-6 border-t pt-4";

      const metadataTitle = document.createElement("strong");
      metadataTitle.textContent = "Metadata:";
      metadataDiv.appendChild(metadataTitle);

      const metadataGrid = document.createElement("div");
      metadataGrid.className = "grid grid-cols-2 gap-4 mt-2 text-sm";

      const metadataFields = [
        {
          label: "Created By",
          value: server.createdBy || "Legacy Entity",
        },
        {
          label: "Created At",
          value: server.createdAt
            ? new Date(server.createdAt).toLocaleString()
            : "Pre-metadata",
        },
        {
          label: "Created From IP",
          value: server.created_from_ip || server.createdFromIp || "Unknown",
        },
        {
          label: "Created Via",
          value: server.created_via || server.createdVia || "Unknown",
        },
        {
          label: "Last Modified By",
          value: server.modified_by || server.modifiedBy || "N/A",
        },
        {
          label: "Last Modified At",
          value: server.updated_at
            ? new Date(server.updated_at).toLocaleString()
            : server.updatedAt
              ? new Date(server.updatedAt).toLocaleString()
              : "N/A",
        },
        {
          label: "Modified From IP",
          value: server.modified_from_ip || server.modifiedFromIp || "N/A",
        },
        {
          label: "Modified Via",
          value: server.modified_via || server.modifiedVia || "N/A",
        },
        { label: "Version", value: server.version || "1" },
        {
          label: "Import Batch",
          value: server.importBatchId || "N/A",
        },
      ];

      metadataFields.forEach((field) => {
        const fieldDiv = document.createElement("div");

        const labelSpan = document.createElement("span");
        labelSpan.className = "font-medium text-gray-600 dark:text-gray-400";
        labelSpan.textContent = field.label + ":";

        const valueSpan = document.createElement("span");
        valueSpan.className = "ml-2";
        valueSpan.textContent = field.value;

        fieldDiv.appendChild(labelSpan);
        fieldDiv.appendChild(valueSpan);
        metadataGrid.appendChild(fieldDiv);
      });

      metadataDiv.appendChild(metadataGrid);
      container.appendChild(metadataDiv);

      serverDetailsDiv.innerHTML = "";
      serverDetailsDiv.appendChild(container);
    }

    openModal("server-modal");
    console.log("✓ Server details loaded successfully");
  } catch (error) {
    console.error("Error fetching server details:", error);
    const errorMessage = handleFetchError(error, "load server details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Server function
 */
export const editServer = async function (serverId) {
  try {
    console.log(`Editing server ID: ${serverId}`);

    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/servers/${serverId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const server = await response.json();

    const isInactiveCheckedBool = isInactiveChecked("servers");
    let hiddenField = safeGetElement("edit-server-show-inactive");
    const editForm = safeGetElement("edit-server-form");
    if (!hiddenField) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-server-show-inactive";

      if (editForm) {
        editForm.appendChild(hiddenField);
      }
    }
    hiddenField.value = isInactiveCheckedBool;

    const visibility = server.visibility; // Ensure visibility is either 'public', 'team', or 'private'
    const publicRadio = safeGetElement("edit-visibility-public");
    const teamRadio = safeGetElement("edit-visibility-team");
    const privateRadio = safeGetElement("edit-visibility-private");

    // Prepopulate visibility radio buttons based on the server data
    if (visibility) {
      // Check visibility and set the corresponding radio button
      if (visibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (visibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (visibility === "private" && privateRadio) {
        privateRadio.checked = true;
      }
    }

    const teamId = new URL(window.location.href).searchParams.get("team_id");

    if (teamId) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = "team_id";
      hiddenInput.value = teamId;
      editForm.appendChild(hiddenInput);
    }

    // Set form action and populate fields with validation
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/servers/${serverId}/edit`;
    }

    const nameValidation = validateInputName(server.name, "server");
    const urlValidation = validateUrl(server.url);

    const nameField = safeGetElement("edit-server-name");
    const urlField = safeGetElement("edit-server-url");
    const descField = safeGetElement("edit-server-description");

    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    }
    if (urlField && urlValidation.valid) {
      urlField.value = urlValidation.value;
    }
    if (descField) {
      descField.value = server.description || "";
    }

    const idField = safeGetElement("edit-server-id");
    if (idField) {
      idField.value = server.id || "";
    }

    // Set tags field
    const tagsField = safeGetElement("edit-server-tags");
    if (tagsField) {
      const rawTags = server.tags
        ? server.tags.map((tag) =>
          typeof tag === "object" && tag !== null ? tag.label || tag.id : tag
        )
        : [];
      tagsField.value = rawTags.join(", ");
    }

    // Set icon field
    const iconField = safeGetElement("edit-server-icon");
    if (iconField) {
      iconField.value = server.icon || "";
    }

    // Set OAuth 2.0 configuration fields (RFC 9728)
    const oauthEnabledCheckbox = safeGetElement("edit-server-oauth-enabled");
    const oauthConfigSection = safeGetElement(
      "edit-server-oauth-config-section"
    );
    const oauthAuthServerField = safeGetElement(
      "edit-server-oauth-authorization-server"
    );
    const oauthScopesField = safeGetElement("edit-server-oauth-scopes");
    const oauthTokenEndpointField = safeGetElement(
      "edit-server-oauth-token-endpoint"
    );

    if (oauthEnabledCheckbox) {
      oauthEnabledCheckbox.checked = server.oauth_enabled || false;
    }

    // Show/hide OAuth config section based on oauth_enabled state
    if (oauthConfigSection) {
      if (server.oauth_enabled) {
        oauthConfigSection.classList.remove("hidden");
      } else {
        oauthConfigSection.classList.add("hidden");
      }
    }

    // Populate OAuth config fields if oauth_config exists
    if (server.oauth_config) {
      // Extract authorization server (may be in authorization_servers array or authorization_server string)
      let authServer = "";
      if (
        server.oauth_config.authorization_servers &&
        server.oauth_config.authorization_servers.length > 0
      ) {
        authServer = server.oauth_config.authorization_servers[0];
      } else if (server.oauth_config.authorization_server) {
        authServer = server.oauth_config.authorization_server;
      }
      if (oauthAuthServerField) {
        oauthAuthServerField.value = authServer;
      }

      // Extract scopes (may be scopes_supported array or scopes array)
      const scopes =
        server.oauth_config.scopes_supported ||
        server.oauth_config.scopes ||
        [];
      if (oauthScopesField) {
        oauthScopesField.value = Array.isArray(scopes)
          ? scopes.join(" ")
          : scopes;
      }

      // Extract token endpoint
      if (oauthTokenEndpointField) {
        oauthTokenEndpointField.value =
          server.oauth_config.token_endpoint || "";
      }
    } else {
      // Clear OAuth config fields when no config exists
      if (oauthAuthServerField) oauthAuthServerField.value = "";
      if (oauthScopesField) oauthScopesField.value = "";
      if (oauthTokenEndpointField) oauthTokenEndpointField.value = "";
    }

    // Store server data for modal population
    Admin.currentEditingServer = server;

    // Set associated tools data attribute on the container for reference by initToolSelect
    const editToolsContainer = safeGetElement("edit-server-tools");
    if (editToolsContainer && server.associatedTools) {
      editToolsContainer.setAttribute(
        "data-server-tools",
        JSON.stringify(server.associatedTools)
      );
    }

    // Set associated resources data attribute on the container
    const editResourcesContainer = safeGetElement("edit-server-resources");
    if (editResourcesContainer && server.associatedResources) {
      editResourcesContainer.setAttribute(
        "data-server-resources",
        JSON.stringify(server.associatedResources)
      );
    }

    // Set associated prompts data attribute on the container
    const editPromptsContainer = safeGetElement("edit-server-prompts");
    if (editPromptsContainer && server.associatedPrompts) {
      editPromptsContainer.setAttribute(
        "data-server-prompts",
        JSON.stringify(server.associatedPrompts)
      );
    }

    openModal("server-edit-modal");
    // Initialize the select handlers for gateways, resources and prompts in the edit modal
    // so that gateway changes will trigger filtering of associated items while editing.
    if (safeGetElement("associatedEditGateways")) {
      initGatewaySelect(
        "associatedEditGateways",
        "selectedEditGatewayPills",
        "selectedEditGatewayWarning",
        12,
        "selectAllEditGatewayBtn",
        "clearAllEditGatewayBtn",
        "searchEditGateways"
      );
    }

    initResourceSelect(
      "edit-server-resources",
      "selectedEditResourcesPills",
      "selectedEditResourcesWarning",
      6,
      "selectAllEditResourcesBtn",
      "clearAllEditResourcesBtn"
    );

    initPromptSelect(
      "edit-server-prompts",
      "selectedEditPromptsPills",
      "selectedEditPromptsWarning",
      6,
      "selectAllEditPromptsBtn",
      "clearAllEditPromptsBtn"
    );

    // Use multiple approaches to ensure checkboxes get set
    setEditServerAssociations(server);
    setTimeout(() => setEditServerAssociations(server), 100);
    setTimeout(() => setEditServerAssociations(server), 300);

    // Set associated items after modal is opened
    setTimeout(() => {
      // Set associated tools checkboxes (scope to edit modal container only)
      const editToolContainer = safeGetElement("edit-server-tools");
      const toolCheckboxes = editToolContainer
        ? editToolContainer.querySelectorAll('input[name="associatedTools"]')
        : document.querySelectorAll('input[name="associatedTools"]');

      toolCheckboxes.forEach((checkbox) => {
        let isChecked = false;
        if (server.associatedTools && Admin.toolMapping) {
          // Get the tool name for this checkbox UUID
          const toolName = Admin.toolMapping[checkbox.value];

          // Check if this tool name is in the associated tools array
          isChecked = toolName && server.associatedTools.includes(toolName);
        }

        checkbox.checked = isChecked;
      });

      // Set associated resources checkboxes (scope to edit modal container only)
      const editResourceContainer = safeGetElement("edit-server-resources");
      const resourceCheckboxes = editResourceContainer
        ? editResourceContainer.querySelectorAll(
          'input[name="associatedResources"]'
        )
        : document.querySelectorAll('input[name="associatedResources"]');

      resourceCheckboxes.forEach((checkbox) => {
        const checkboxValue = checkbox.value;
        const isChecked =
          server.associatedResources &&
          server.associatedResources.includes(checkboxValue);
        checkbox.checked = isChecked;
      });

      // Set associated prompts checkboxes (scope to edit modal container only)
      const editPromptContainer = safeGetElement("edit-server-prompts");
      const promptCheckboxes = editPromptContainer
        ? editPromptContainer.querySelectorAll(
          'input[name="associatedPrompts"]'
        )
        : document.querySelectorAll('input[name="associatedPrompts"]');

      promptCheckboxes.forEach((checkbox) => {
        const checkboxValue = checkbox.value;
        const isChecked =
          server.associatedPrompts &&
          server.associatedPrompts.includes(checkboxValue);
        checkbox.checked = isChecked;
      });

      // Manually trigger the selector update functions to refresh pills
      setTimeout(() => {
        // Find and trigger existing tool selector update
        const toolContainer = safeGetElement("edit-server-tools");
        if (toolContainer) {
          const firstToolCheckbox = toolContainer.querySelector(
            'input[type="checkbox"]'
          );
          if (firstToolCheckbox) {
            const changeEvent = new Event("change", {
              bubbles: true,
            });
            firstToolCheckbox.dispatchEvent(changeEvent);
          }
        }

        // Trigger resource selector update
        const resourceContainer = safeGetElement("edit-server-resources");
        if (resourceContainer) {
          const firstResourceCheckbox = resourceContainer.querySelector(
            'input[type="checkbox"]'
          );
          if (firstResourceCheckbox) {
            const changeEvent = new Event("change", {
              bubbles: true,
            });
            firstResourceCheckbox.dispatchEvent(changeEvent);
          }
        }

        // Trigger prompt selector update
        const promptContainer = safeGetElement("edit-server-prompts");
        if (promptContainer) {
          const firstPromptCheckbox = promptContainer.querySelector(
            'input[type="checkbox"]'
          );
          if (firstPromptCheckbox) {
            const changeEvent = new Event("change", {
              bubbles: true,
            });
            firstPromptCheckbox.dispatchEvent(changeEvent);
          }
        }
      }, 50);
    }, 200);

    console.log("✓ Server edit modal loaded successfully");
  } catch (error) {
    console.error("Error fetching server for editing:", error);
    const errorMessage = handleFetchError(error, "load server for editing");
    showErrorMessage(errorMessage);
  }
};

// Helper function to set edit server associations
export const setEditServerAssociations = function (server) {
  // Set associated tools checkboxes (scope to edit modal container only)
  const toolContainer = safeGetElement("edit-server-tools");
  const toolCheckboxes = toolContainer
    ? toolContainer.querySelectorAll('input[name="associatedTools"]')
    : document.querySelectorAll('input[name="associatedTools"]');

  if (toolCheckboxes.length === 0) {
    return;
  }

  toolCheckboxes.forEach((checkbox) => {
    let isChecked = false;
    if (server.associatedTools && Admin.toolMapping) {
      // Get the tool name for this checkbox UUID
      const toolName = Admin.toolMapping[checkbox.value];

      // Check if this tool name is in the associated tools array
      isChecked = toolName && server.associatedTools.includes(toolName);
    }

    checkbox.checked = isChecked;
  });

  // Set associated resources checkboxes (scope to edit modal container only)
  const resourceContainer = safeGetElement("edit-server-resources");
  const resourceCheckboxes = resourceContainer
    ? resourceContainer.querySelectorAll('input[name="associatedResources"]')
    : document.querySelectorAll('input[name="associatedResources"]');

  resourceCheckboxes.forEach((checkbox) => {
    const checkboxValue = checkbox.value;
    const isChecked =
      server.associatedResources &&
      server.associatedResources.includes(checkboxValue);
    checkbox.checked = isChecked;
  });

  // Set associated prompts checkboxes (scope to edit modal container only)
  const promptContainer = safeGetElement("edit-server-prompts");
  const promptCheckboxes = promptContainer
    ? promptContainer.querySelectorAll('input[name="associatedPrompts"]')
    : document.querySelectorAll('input[name="associatedPrompts"]');

  promptCheckboxes.forEach((checkbox) => {
    const checkboxValue = checkbox.value;
    const isChecked =
      server.associatedPrompts &&
      server.associatedPrompts.includes(checkboxValue);
    checkbox.checked = isChecked;
  });

  // Force update the pill displays by triggering change events
  setTimeout(() => {
    const allCheckboxes = [
      ...document.querySelectorAll('#edit-server-tools input[type="checkbox"]'),
      ...document.querySelectorAll(
        '#edit-server-resources input[type="checkbox"]'
      ),
      ...document.querySelectorAll(
        '#edit-server-prompts input[type="checkbox"]'
      ),
    ];

    allCheckboxes.forEach((checkbox) => {
      if (checkbox.checked) {
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }, 50);
};

// -------------------- Root Management ------------------ //

/**
 * SECURE: View Root function with safe display
 */
export const viewRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const root = await response.json();

    const rootDetailsDiv = safeGetElement("root-details");
    if (rootDetailsDiv) {
      // Create safe display elements
      const container = document.createElement("div");
      container.className = "space-y-2 dark:bg-gray-900 dark:text-gray-100";

      // Add each piece of information safely
      const fields = [
        { label: "URI", value: root.uri },
        { label: "Name", value: root.name || "N/A" },
      ];

      fields.forEach((field) => {
        const p = document.createElement("p");
        const strong = document.createElement("strong");
        strong.textContent = field.label + ": ";
        p.appendChild(strong);
        p.appendChild(document.createTextNode(field.value));
        container.appendChild(p);
      });

      // Replace content safely
      rootDetailsDiv.innerHTML = "";
      rootDetailsDiv.appendChild(container);
    }

    openModal("root-details-modal");
  } catch (error) {
    console.error("Error fetching root details:", error);
    const errorMessage = handleFetchError(error, "load root details");
    showErrorMessage(errorMessage);
  }
};

/**
 * SECURE: Edit Root function with validation
 */
export const editRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errorJson = await response.json();
        errorDetail = errorJson.detail || "";
      } catch (_) {}

      throw new Error(
        `HTTP ${response.status}: ${errorDetail || response.statusText}`
      );
    }

    const root = await response.json();

    // Ensure hidden inactive flag is preserved
    const isInactiveCheckedBool = isInactiveChecked("roots");
    let hiddenField = safeGetElement("edit-root-show-inactive");
    const editForm = safeGetElement("edit-root-form");

    if (!hiddenField && editForm) {
      hiddenField = document.createElement("input");
      hiddenField.type = "hidden";
      hiddenField.name = "is_inactive_checked";
      hiddenField.id = "edit-root-show-inactive";
      editForm.appendChild(hiddenField);
    }
    if (hiddenField) {
      hiddenField.value = isInactiveCheckedBool;
    }

    // Set form action and populate fields with validation
    if (editForm) {
      editForm.action = `${window.ROOT_PATH}/admin/roots/${encodeURIComponent(uri)}/update`;
    }

    // Validate inputs
    const nameValidation = validateInputName(root.name || "", "root name");
    const uriValidation = validateInputName(root.uri, "root URI");

    const uriField = safeGetElement("edit-root-uri");
    const nameField = safeGetElement("edit-root-name");

    // URI is read-only, just display it
    if (uriField && uriValidation.valid) {
      uriField.value = uriValidation.value;
    }

    // Name is editable
    if (nameField && nameValidation.valid) {
      nameField.value = nameValidation.value;
    } else if (nameField) {
      // If name is null/empty, set empty string
      nameField.value = "";
    }

    openModal("root-edit-modal");
  } catch (error) {
    console.error("Error fetching root for editing:", error);
    const errorMessage = handleFetchError(error, "load root for editing");
    showErrorMessage(errorMessage);
  }
};

/**
 * Handle export root details
 */
export const exportRoot = async function (uri) {
  try {
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/roots/export?uri=${encodeURIComponent(uri)}`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Trigger download
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;

    // Safely extract filename from Content-Disposition header
    const contentDisposition = response.headers.get("Content-Disposition");
    let filename = `root-export-${Date.now()}.json`;
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (filenameMatch && filenameMatch[1]) {
        filename = filenameMatch[1];
      }
    }
    a.download = filename;

    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  } catch (error) {
    console.error("Error exporting root:", error);
    showErrorMessage("Failed to export root");
  }
};
