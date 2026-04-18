import { getAuthHeaders, loadAuthHeaders } from "./auth.js";
import { closeModal, openModal } from "./modals.js";
import { escapeHtml, validateInputName, validateUrl } from "./security.js";
import { applyVisibilityRestrictions } from "./teams.js";
import {
  decodeHtml,
  fetchWithTimeout,
  handleFetchError,
  isInactiveChecked,
  makeCopyIdButton,
  safeGetElement,
  safeSetValue,
  showErrorMessage,
} from "./utils.js";

// ===================================================================
// UAID TOGGLE FUNCTIONALITY
// ===================================================================

/**
 * Toggle UAID fields visibility based on checkbox state
 * @param {string} formSuffix - Form identifier suffix ('a2a' or 'a2a-edit')
 * @param {boolean} enabled - Whether UAID generation is enabled
 */
export const toggleUAIDFields = function (formSuffix, enabled) {
  const uaidFieldsId = `uaid-fields-${formSuffix}`;
  const uaidFields = document.getElementById(uaidFieldsId);

  if (uaidFields) {
    uaidFields.style.display = enabled ? 'block' : 'none';
  }
};

// ===================================================================
// A2A AGENT TEST MODAL FUNCTIONALITY
// ===================================================================

let a2aTestFormHandler = null;
let a2aTestCloseHandler = null;

/**
 * SECURE: View A2A Agents function with safe display
 */
export const viewA2AAgent = async function (agentId) {
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

      // ID field with copy button
      const agentIdP = document.createElement("p");
      const agentIdStrong = document.createElement("strong");
      agentIdStrong.textContent = "Agent ID: ";
      agentIdP.appendChild(agentIdStrong);
      const agentIdSpan = document.createElement("span");
      agentIdSpan.className = "font-mono text-sm";
      agentIdSpan.textContent = agent.id;
      agentIdP.appendChild(agentIdSpan);
      agentIdP.appendChild(makeCopyIdButton(agent.id));
      container.appendChild(agentIdP);

      const fields = [
        { label: "Name", value: agent.name },
        { label: "Slug", value: agent.slug },
        { label: "Endpoint URL", value: agent.endpointUrl },
        { label: "Agent Type", value: agent.agentType },
        { label: "Protocol Version", value: agent.protocolVersion },
        {
          label: "Description",
          value: decodeHtml(agent.description) || "N/A",
        },
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

      // UAID Section (if agent has UAID)
      if (agent.uaid) {
        const uaidSection = document.createElement("div");
        uaidSection.className = "mt-4 p-3 bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800 rounded";

        const uaidTitle = document.createElement("strong");
        uaidTitle.className = "block mb-2 text-indigo-700 dark:text-indigo-300";
        uaidTitle.textContent = "🆔 Universal Agent ID (UAID):";
        uaidSection.appendChild(uaidTitle);

        const uaidFields = [
          { label: "Full UAID", value: agent.uaid, mono: true },
          { label: "Registry", value: agent.uaidRegistry || "N/A" },
          { label: "Protocol", value: agent.uaidProto || "N/A" },
          { label: "Native ID", value: agent.uaidNativeId || "N/A", mono: true },
        ];

        uaidFields.forEach((field) => {
          const p = document.createElement("p");
          p.className = "text-sm mt-1";
          const strong = document.createElement("strong");
          strong.textContent = field.label + ": ";
          p.appendChild(strong);
          const span = document.createElement("span");
          if (field.mono) span.className = "font-mono text-xs break-all";
          span.textContent = field.value;
          p.appendChild(span);
          uaidSection.appendChild(p);
        });

        container.appendChild(uaidSection);
      }

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

    const publicRadio = safeGetElement("edit-a2a-visibility-public");
    const teamRadio = safeGetElement("edit-a2a-visibility-team");
    const privateRadio = safeGetElement("edit-a2a-visibility-private");

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
      // When public visibility is disabled and we're in a team-scoped view,
      // coerce legacy-public records to team.
      const effectiveVisibility =
        window.ALLOW_PUBLIC_VISIBILITY === false &&
        visibility === "public" &&
        teamId
          ? "team"
          : visibility;
      if (effectiveVisibility === "public" && publicRadio) {
        publicRadio.checked = true;
      } else if (effectiveVisibility === "team" && teamRadio) {
        teamRadio.checked = true;
      } else if (effectiveVisibility === "private" && privateRadio) {
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
    const oauthIssuerField = safeGetElement("oauth-issuer-a2a-edit");
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
          // Load existing auth_headers if present
          if (agent.authHeaders && Array.isArray(agent.authHeaders)) {
            loadAuthHeaders(
              "auth-headers-container-a2a-edit",
              agent.authHeaders,
              { maskValues: true }
            );
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
          if (oauthIssuerField) {
            oauthIssuerField.value = config.issuer || "";
          }
          if (oauthGrantTypeField) {
            oauthGrantTypeField.value = config.grant_type || "";
            // Show/hide authorization code fields based on grant type
            if (oauthAuthCodeFields) {
              oauthAuthCodeFields.style.display =
                config.grant_type === "authorization_code" ? "block" : "none";
            }
          }
          if (oauthClientIdField) {
            oauthClientIdField.value = config.client_id || "";
          }
          if (oauthClientSecretField) {
            oauthClientSecretField.value = ""; // Don't populate secret for security
          }
          if (oauthTokenUrlField) {
            oauthTokenUrlField.value = config.token_url || "";
          }
          if (oauthAuthUrlField) {
            oauthAuthUrlField.value = config.authorization_url || "";
          }
          if (oauthRedirectUriField) {
            oauthRedirectUriField.value = config.redirect_uri || "";
          }
          if (oauthScopesField) {
            oauthScopesField.value = Array.isArray(config.scopes)
              ? config.scopes.join(" ")
              : "";
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

    // Handle UAID fields
    // - If agent has UAID: show as read-only (UAID is immutable)
    // - If agent has no UAID: allow user to generate one
    const generateUAIDCheckbox = safeGetElement("a2a-generate-uaid-edit");
    const uaidRegistryField = safeGetElement("a2a-uaid-registry-edit");
    const uaidProtocolField = safeGetElement("a2a-uaid-protocol-edit");

    const hasUAID = !!agent.uaid;

    if (generateUAIDCheckbox) {
      generateUAIDCheckbox.checked = hasUAID;

      if (hasUAID) {
        // Agent already has UAID - make checkbox disabled (UAID is immutable)
        generateUAIDCheckbox.disabled = true;
        generateUAIDCheckbox.title = "UAID is immutable and cannot be changed once generated";
      } else {
        // Agent has no UAID - allow user to check the box to generate one
        generateUAIDCheckbox.disabled = false;
        generateUAIDCheckbox.title = "Generate UAID for cross-gateway routing (can only be set once)";
      }

      toggleUAIDFields("a2a-edit", hasUAID);
    }

    if (uaidRegistryField) {
      // Clear any previous styling
      uaidRegistryField.classList.remove('bg-gray-100', 'dark:bg-gray-800', 'cursor-not-allowed');
      uaidRegistryField.readOnly = false;

      if (hasUAID) {
        // Agent has UAID - make field read-only and populate
        uaidRegistryField.value = agent.uaidRegistry || "";
        uaidRegistryField.readOnly = true;
        uaidRegistryField.classList.add('bg-gray-100', 'dark:bg-gray-800', 'cursor-not-allowed');
        uaidRegistryField.title = "UAID is immutable and cannot be changed";
      } else {
        // Agent has no UAID - allow editing
        uaidRegistryField.value = "context-forge";
        uaidRegistryField.title = "Registry identifier for UAID generation";
      }
    }

    if (uaidProtocolField) {
      // Clear any previous styling
      uaidProtocolField.classList.remove('bg-gray-100', 'dark:bg-gray-800', 'cursor-not-allowed');
      uaidProtocolField.disabled = false;

      if (hasUAID) {
        // Agent has UAID - make field disabled and populate
        uaidProtocolField.value = agent.uaidProto || "";
        uaidProtocolField.disabled = true;
        uaidProtocolField.classList.add('bg-gray-100', 'dark:bg-gray-800', 'cursor-not-allowed');
        uaidProtocolField.title = "UAID is immutable and cannot be changed";
      } else {
        // Agent has no UAID - allow selection
        uaidProtocolField.value = "a2a";
        uaidProtocolField.title = "Protocol for UAID generation";
      }
    }

    openModal("a2a-edit-modal");
    applyVisibilityRestrictions(["edit-a2a-visibility"]); // Disable public radio if restricted, preserve checked state
    console.log("✓ A2A Agent edit modal loaded successfully");
  } catch (err) {
    console.error("Error loading A2A agent:", err);
    const errorMessage = handleFetchError(err, "load A2A Agent for editing");
    showErrorMessage(errorMessage);
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

/**
 * Open A2A test modal with agent details
 * @param {string} agentId - ID of the agent to test
 * @param {string} agentName - Name of the agent for display
 * @param {string} endpointUrl - Endpoint URL of the agent
 */
export const testA2AAgent = async function (agentId, agentName, endpointUrl) {
  try {
    console.log("Opening A2A test modal for:", agentName);

    // Clean up any existing event listeners
    cleanupA2ATestModal();

    // Open the modal
    openModal("a2a-test-modal");

    // Set modal title and description
    const titleElement = safeGetElement("a2a-test-modal-title");
    const descElement = safeGetElement("a2a-test-modal-description");
    const agentIdInput = safeGetElement("a2a-test-agent-id");
    const queryInput = safeGetElement("a2a-test-query");
    const resultDiv = safeGetElement("a2a-test-result");

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
      queryInput.value = "Hello from ContextForge Admin UI test!";
    }
    if (resultDiv) {
      resultDiv.classList.add("hidden");
    }

    // Set up form submission handler
    const form = safeGetElement("a2a-test-form");
    if (form) {
      a2aTestFormHandler = async (e) => {
        await handleA2ATestSubmit(e);
      };
      form.addEventListener("submit", a2aTestFormHandler);
    }

    // Set up close button handler
    const closeButton = safeGetElement("a2a-test-close");
    if (closeButton) {
      a2aTestCloseHandler = () => {
        handleA2ATestClose();
      };
      closeButton.addEventListener("click", a2aTestCloseHandler);
    }
  } catch (error) {
    console.error("Error setting up A2A test modal:", error);
    showErrorMessage("Failed to open A2A test modal");
  }
};

/**
 * Handle A2A test form submission
 * @param {Event} e - Form submit event
 */
export const handleA2ATestSubmit = async function (e) {
  e.preventDefault();

  const loading = safeGetElement("a2a-test-loading");
  const responseDiv = safeGetElement("a2a-test-response-json");
  const resultDiv = safeGetElement("a2a-test-result");
  const testButton = safeGetElement("a2a-test-submit");

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

    const agentId = safeGetElement("a2a-test-agent-id")?.value;
    const query =
      safeGetElement("a2a-test-query")?.value ||
      "Hello from ContextForge Admin UI test!";

    if (!agentId) {
      throw new Error("Agent ID is missing");
    }

    // Reuse the standard admin auth helper:
    // - sends Bearer auth when a JS-readable token exists
    // - otherwise relies on same-origin cookie auth
    // Never synthesize default credentials client-side.
    const headers = await getAuthHeaders(true);

    // Send test request with user query
    const response = await fetchWithTimeout(
      `${window.ROOT_PATH}/admin/a2a/${agentId}/test`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({ query }),
      },
      window.MCPGATEWAY_UI_TOOL_TEST_TIMEOUT || 60000
    );

    // Parse the JSON body for all responses — the backend returns
    // structured {success, error, error_type} even for non-2xx status
    // codes, and the display logic below already handles both cases.
    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

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
};

/**
 * Handle A2A test modal close
 */
export const handleA2ATestClose = function () {
  try {
    // Reset form
    const form = safeGetElement("a2a-test-form");
    if (form) {
      form.reset();
    }

    // Clear response
    const responseDiv = safeGetElement("a2a-test-response-json");
    const resultDiv = safeGetElement("a2a-test-result");
    if (responseDiv) {
      responseDiv.innerHTML = "";
    }
    if (resultDiv) {
      resultDiv.classList.add("hidden");
    }

    // Close modal
    closeModal("a2a-test-modal");
  } catch (error) {
    console.error("Error closing A2A test modal:", error);
  }
};

/**
 * Clean up A2A test modal event listeners
 */
export const cleanupA2ATestModal = function () {
  try {
    const form = safeGetElement("a2a-test-form");
    const closeButton = safeGetElement("a2a-test-close");

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
};
