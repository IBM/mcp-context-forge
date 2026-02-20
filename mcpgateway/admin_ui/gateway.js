import { loadAuthHeaders, updateAuthHeadersJSON } from "./auth.js";
import { MASKED_AUTH_VALUE } from "./constants.js";
import { closeModal, openModal } from "./modals.js";
import { initPromptSelect } from "./prompts.js";
import { initResourceSelect } from "./resources.js";
import { validateInputName, validateJson, validateUrl } from "./security.js";
import { initToolSelect } from "./tools.js";
import { decodeHtml, fetchWithTimeout, getCurrentTeamId, handleFetchError, isInactiveChecked, safeGetElement, showErrorMessage } from "./utils.js";


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
        {
          label: "Description",
          value: decodeHtml(gateway.description) || "N/A",
        },
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
      descField.value = decodeHtml(gateway.description || "");
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

// ===================================================================
// GATEWAY SELECT (Associated MCP Servers) - search/select/clear
// ===================================================================

export const initGatewaySelect = function (
  selectId = "associatedGateways",
  pillsId = "selectedGatewayPills",
  warnId = "selectedGatewayWarning",
  max = 12,
  selectBtnId = "selectAllGatewayBtn",
  clearBtnId = "clearAllGatewayBtn",
  searchInputId = "searchGateways"
) {
  const container = safeGetElement(selectId);
  const pillsBox = safeGetElement(pillsId);
  const warnBox = safeGetElement(warnId);
  const clearBtn = clearBtnId ? safeGetElement(clearBtnId) : null;
  const selectBtn = selectBtnId ? safeGetElement(selectBtnId) : null;
  const searchInput = searchInputId ? safeGetElement(searchInputId) : null;

  if (!container || !pillsBox || !warnBox) {
    console.warn(
      `Gateway select elements not found: ${selectId}, ${pillsId}, ${warnId}`
    );
    return;
  }

  const pillClasses =
    "inline-block bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full dark:bg-indigo-900 dark:text-indigo-200";

  // Search functionality
  const applySearch = function () {
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
      const noMsg = safeGetElement("noGatewayMessage");
      const searchQuerySpan = safeGetElement("searchQueryServers");

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
  };

  // Bind search input
  if (searchInput && !searchInput.dataset.searchBound) {
    searchInput.addEventListener("input", applySearch);
    searchInput.dataset.searchBound = "true";
  }

  const update = function () {
    try {
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      const checked = Array.from(checkboxes).filter((cb) => cb.checked);

      // Check if "Select All" mode is active
      const selectAllInput = container.querySelector(
        'input[name="selectAllGateways"]'
      );
      const allIdsInput = container.querySelector(
        'input[name="allGatewayIds"]'
      );

      let count = checked.length;

      // If Select All mode is active, use the count from allGatewayIds
      if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
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
  };

  // Remove old event listeners by cloning and replacing (preserving ID)
  if (clearBtn && !clearBtn.dataset.listenerAttached) {
    clearBtn.dataset.listenerAttached = "true";
    const newClearBtn = clearBtn.cloneNode(true);
    newClearBtn.dataset.listenerAttached = "true";
    clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);

    newClearBtn.addEventListener("click", () => {
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach((cb) => (cb.checked = false));

      // Clear the "select all" flag
      const selectAllInput = container.querySelector(
        'input[name="selectAllGateways"]'
      );
      if (selectAllInput) {
        selectAllInput.remove();
      }
      const allIdsInput = container.querySelector(
        'input[name="allGatewayIds"]'
      );
      if (allIdsInput) {
        allIdsInput.remove();
      }

      update();

      // Reload associated items after clearing selection
      reloadAssociatedItems();
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
        const selectedTeamId = getCurrentTeamId();
        const params = new URLSearchParams();
        if (selectedTeamId) {
          params.set("team_id", selectedTeamId);
        }
        const queryString = params.toString();
        const response = await fetch(
          `${window.ROOT_PATH}/admin/gateways/ids${queryString ? `?${queryString}` : ""}`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch gateway IDs");
        }

        const data = await response.json();
        const allGatewayIds = data.gateway_ids || [];

        // Apply search filter first to determine which items are visible
        applySearch();

        // Check only currently visible checkboxes
        const loadedCheckboxes = container.querySelectorAll(
          'input[type="checkbox"]'
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
          'input[name="selectAllGateways"]'
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
            'input[data-gateway-null="true"]'
          );
          if (nullCheckbox) {
            // Include the literal string "null" so server-side
            // `any(gid.lower() == 'null' ...)` evaluates to true.
            if (!allGatewayIds.includes("null")) {
              allGatewayIds.push("null");
            }
          }
        } catch (err) {
          console.error("Error ensuring null sentinel in gateway IDs:", err);
        }

        let allIdsInput = container.querySelector(
          'input[name="allGatewayIds"]'
        );
        if (!allIdsInput) {
          allIdsInput = document.createElement("input");
          allIdsInput.type = "hidden";
          allIdsInput.name = "allGatewayIds";
          container.appendChild(allIdsInput);
        }
        allIdsInput.value = JSON.stringify(allGatewayIds);

        update();

        newSelectBtn.textContent = `✓ All ${allGatewayIds.length} gateways selected`;
        setTimeout(() => {
          newSelectBtn.textContent = originalText;
        }, 2000);

        // Reload associated items after selecting all
        reloadAssociatedItems();
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

  update(); // Initial render

  // Attach change listeners to checkboxes (using delegation for dynamic content)
  if (!container.dataset.changeListenerAttached) {
    container.dataset.changeListenerAttached = "true";
    container.addEventListener("change", (e) => {
      if (e.target.type === "checkbox") {
        // Log gateway_id when checkbox is clicked
        // Normalize the special null-gateway checkbox to the literal string "null"
        let gatewayId = e.target.value;
        if (e.target.dataset && e.target.dataset.gatewayNull === "true") {
          gatewayId = "null";
        }
        const gatewayName =
          e.target.nextElementSibling?.textContent?.trim() || "Unknown";
        const isChecked = e.target.checked;

        console.log(
          `[MCP Server Selection] Gateway ID: ${gatewayId}, Name: ${gatewayName}, Checked: ${isChecked}`
        );

        // Check if we're in "Select All" mode
        const selectAllInput = container.querySelector(
          'input[name="selectAllGateways"]'
        );
        const allIdsInput = container.querySelector(
          'input[name="allGatewayIds"]'
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

        update();

        // Trigger reload of associated tools, resources, and prompts with selected gateway filter
        reloadAssociatedItems();
      }
    });
  }

  // Initial render
  applySearch();
  update();
};

/**
 * Get all selected gateway IDs from the gateway selection container
 * @returns {string[]} Array of selected gateway IDs
 */
export const getSelectedGatewayIds = function () {
  // Prefer the gateway selection belonging to the currently active form.
  // If the edit-server modal is open, use the edit modal's gateway container
  // (`associatedEditGateways`). Otherwise use the create form container
  // (`associatedGateways`). This allows the same filtering logic to work
  // for both Add and Edit flows.
  let container = safeGetElement("associatedGateways");
  const editContainer = safeGetElement("associatedEditGateways");

  const editModal = safeGetElement("server-edit-modal");
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
    container ? container.id : null
  );

  if (!container) {
    console.warn(
      "[Gateway Selection DEBUG] No gateway container found (associatedGateways or associatedEditGateways)"
    );
    return [];
  }

  // Check if "Select All" mode is active
  const selectAllInput = container.querySelector(
    "input[name='selectAllGateways']"
  );
  const allIdsInput = container.querySelector("input[name='allGatewayIds']");

  console.log(
    "[Gateway Selection DEBUG] Select All mode:",
    selectAllInput?.value === "true"
  );
  if (selectAllInput && selectAllInput.value === "true" && allIdsInput) {
    try {
      const allIds = JSON.parse(allIdsInput.value);
      console.log(
        `[Gateway Selection DEBUG] Returning all gateway IDs (${allIds.length} total)`
      );
      return allIds;
    } catch (error) {
      console.error(
        "[Gateway Selection DEBUG] Error parsing allGatewayIds:",
        error
      );
    }
  }

  // Otherwise, get all checked checkboxes. If the special 'null' gateway
  // checkbox is selected, include the sentinel 'null' alongside any real
  // gateway ids. This allows requests like `gateway_id=abc,null` which the
  // server interprets as (gateway_id = abc) OR (gateway_id IS NULL).
  const checkboxes = container.querySelectorAll(
    "input[type='checkbox']:checked"
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
    `[Gateway Selection DEBUG] Found ${selectedIds.length} checked gateway checkboxes`
  );
  console.log("[Gateway Selection DEBUG] Selected gateway IDs:", selectedIds);

  return selectedIds;
};

/**
 * Reload associated tools, resources, and prompts filtered by selected gateway IDs
 */
const reloadAssociatedItems = function () {
  const selectedGatewayIds = getSelectedGatewayIds();
  // Join all selected IDs (including the special 'null' sentinel if present)
  // so the server receives a combined filter like `gateway_id=abc,null`.
  let gatewayIdParam = "";
  if (selectedGatewayIds.length > 0) {
    gatewayIdParam = selectedGatewayIds.join(",");
  }

  console.log(
    `[Filter Update] Reloading associated items for gateway IDs: ${gatewayIdParam || "none (showing all)"}`
  );
  console.log(
    "[Filter Update DEBUG] Selected gateway IDs array:",
    selectedGatewayIds
  );

  // Determine whether to reload the 'create server' containers (associated*)
  // or the 'edit server' containers (edit-server-*). Prefer the edit
  // containers when the edit modal is open or the edit-gateway selector
  // exists and is visible.
  const editModal = safeGetElement("server-edit-modal");
  const isEditModalOpen =
    editModal && !editModal.classList.contains("hidden");
  const editGateways = safeGetElement("associatedEditGateways");

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
  const toolsContainer = safeGetElement(toolsContainerId);
  if (toolsContainer) {
    const toolsUrl = gatewayIdParam
      ? `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
      : `${window.ROOT_PATH}/admin/tools/partial?page=1&per_page=50&render=selector`;

    console.log(
      "[Filter Update DEBUG] Tools URL:",
      toolsUrl,
      "-> target:",
      `#${toolsContainerId}`
    );

    // Use HTMX to reload the content into the chosen container
    if (window.htmx) {
      window.htmx
        .ajax("GET", toolsUrl, {
          target: `#${toolsContainerId}`,
          swap: "innerHTML",
        })
        .then(() => {
          console.log("[Filter Update DEBUG] Tools reloaded successfully");
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

          initToolSelect(
            toolsContainerId,
            pillsId,
            warnId,
            6,
            selectBtn,
            clearBtn
          );
        })
        .catch((err) => {
          console.error("[Filter Update DEBUG] Tools reload failed:", err);
        });
    } else {
      console.error(
        "[Filter Update DEBUG] HTMX not available for tools reload"
      );
    }
  } else {
    console.warn(
      "[Filter Update DEBUG] Tools container not found ->",
      toolsContainerId
    );
  }

  // Reload resources - use fetch directly to avoid HTMX race conditions
  const resourcesContainer = safeGetElement(resourcesContainerId);
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
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.text();
      })
      .then((html) => {
        console.log(
          "[Filter Update DEBUG] Resources fetch successful, HTML length:",
          html.length
        );
        // Persist current selections to window fallback before replacing container
        // AND preserve the data-selected-resources attribute
        let persistedResourceIds = [];
        try {
          // First, try to get from the container's data attribute
          const dataAttr = resourcesContainer.getAttribute(
            "data-selected-resources"
          );
          if (dataAttr) {
            try {
              const parsed = JSON.parse(dataAttr);
              if (Array.isArray(parsed)) {
                persistedResourceIds = parsed.slice();
              }
            } catch (e) {
              console.error("Error parsing data-selected-resources:", e);
            }
          }

          // Merge with currently checked items
          const currentChecked = Array.from(
            resourcesContainer.querySelectorAll(
              'input[type="checkbox"]:checked'
            )
          ).map((cb) => cb.value);
          const merged = new Set([
            ...persistedResourceIds,
            ...currentChecked,
          ]);
          persistedResourceIds = Array.from(merged);

          // Update window fallback
          window.Admin._selectedAssociatedResources = persistedResourceIds.slice();
        } catch (e) {
          console.error(
            "Error capturing current resource selections before reload:",
            e
          );
        }

        resourcesContainer.innerHTML = html;

        // Immediately restore the data-selected-resources attribute after innerHTML replacement
        if (persistedResourceIds.length > 0) {
          resourcesContainer.setAttribute(
            "data-selected-resources",
            JSON.stringify(persistedResourceIds)
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
            const hadHxGet = resourcesContainer.hasAttribute("hx-get");
            const hadHxTrigger =
              resourcesContainer.hasAttribute("hx-trigger");
            const oldHxGet = resourcesContainer.getAttribute("hx-get");
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
              resourcesContainer.setAttribute("hx-trigger", oldHxTrigger);
            }

            console.log(
              "[Filter Update DEBUG] htmx.process called on resources container (attributes temporarily removed)"
            );
          } catch (e) {
            console.warn("[Filter Update DEBUG] htmx.process failed:", e);
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
            "data-selected-resources"
          );
          let selectedIds = [];
          if (dataAttr) {
            try {
              const parsed = JSON.parse(dataAttr);
              if (Array.isArray(parsed)) {
                selectedIds = parsed.slice();
              }
            } catch (e) {
              console.error("Error parsing data-selected-resources:", e);
            }
          }

          // Merge with window fallback if it has additional selections
          if (
            Array.isArray(window.Admin._selectedAssociatedResources) &&
            window.Admin._selectedAssociatedResources.length > 0
          ) {
            const merged = new Set([
              ...selectedIds,
              ...window.Admin._selectedAssociatedResources,
            ]);
            const mergedArray = Array.from(merged);
            if (mergedArray.length > selectedIds.length) {
              resourcesContainer.setAttribute(
                "data-selected-resources",
                JSON.stringify(mergedArray)
              );
              console.log(
                "[Filter Update DEBUG] Merged additional selections from window fallback"
              );
            }
          }
        } catch (e) {
          console.error(
            "Error restoring data-selected-resources after fetch reload:",
            e
          );
        }

        // First restore persisted selections from data-selected-resources (Add Server mode)
        try {
          const dataAttr = resourcesContainer.getAttribute(
            "data-selected-resources"
          );
          if (dataAttr && resourcesContainerId === "associatedResources") {
            const selectedIds = JSON.parse(dataAttr);
            if (Array.isArray(selectedIds) && selectedIds.length > 0) {
              const resourceCheckboxes = resourcesContainer.querySelectorAll(
                'input[type="checkbox"][name="associatedResources"]'
              );
              resourceCheckboxes.forEach((cb) => {
                if (selectedIds.includes(cb.value)) {
                  cb.checked = true;
                }
              });
              console.log(
                "[Filter Update DEBUG] Restored",
                selectedIds.length,
                "persisted resource selections"
              );
            }
          }
        } catch (e) {
          console.warn("Error restoring persisted resource selections:", e);
        }

        initResourceSelect(
          resourcesContainerId,
          resPills,
          resWarn,
          6,
          resSelectBtn,
          resClearBtn
        );

        // Re-apply server-associated resource selections so selections
        // persist across gateway-filtered reloads (Edit Server mode).
        // The resources partial replaces checkbox inputs; use the container's
        // `data-server-resources` attribute (set when opening edit modal)
        // to restore checked state.
        try {
          const dataAttr = resourcesContainer.getAttribute(
            "data-server-resources"
          );
          if (dataAttr) {
            const associated = JSON.parse(dataAttr);
            if (Array.isArray(associated) && associated.length > 0) {
              const resourceCheckboxes = resourcesContainer.querySelectorAll(
                'input[type="checkbox"][name="associatedResources"]'
              );
              resourceCheckboxes.forEach((cb) => {
                const val = cb.value;
                if (!Number.isNaN(val) && associated.includes(val)) {
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
          "[Filter Update DEBUG] Resources reloaded successfully via fetch"
        );
      })
      .catch((err) => {
        console.error("[Filter Update DEBUG] Resources reload failed:", err);
      });
  } else {
    console.warn("[Filter Update DEBUG] Resources container not found");
  }

  // Reload prompts
  const promptsContainer = safeGetElement(promptsContainerId);
  if (promptsContainer) {
    const promptsUrl = gatewayIdParam
      ? `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector&gateway_id=${encodeURIComponent(gatewayIdParam)}`
      : `${window.ROOT_PATH}/admin/prompts/partial?page=1&per_page=50&render=selector`;

    // Persist current prompt selections before HTMX replaces the container
    try {
      const currentCheckedPrompts = Array.from(
        promptsContainer.querySelectorAll('input[type="checkbox"]:checked')
      ).map((cb) => cb.value);
      if (
        !Array.isArray(window._selectedAssociatedPrompts) ||
        window._selectedAssociatedPrompts.length === 0
      ) {
        window._selectedAssociatedPrompts = currentCheckedPrompts.slice();
      } else {
        const merged = new Set([
          ...(window._selectedAssociatedPrompts || []),
          ...currentCheckedPrompts,
        ]);
        window.Admin._selectedAssociatedPrompts = Array.from(merged);
      }
    } catch (e) {
      console.error(
        "Error capturing current prompt selections before reload:",
        e
      );
    }

    if (window.htmx) {
      window.htmx
        .ajax("GET", promptsUrl, {
          target: `#${promptsContainerId}`,
          swap: "innerHTML",
        })
        .then(() => {
          try {
            const containerEl = safeGetElement(promptsContainerId);
            if (containerEl) {
              const existingAttr = containerEl.getAttribute(
                "data-selected-prompts"
              );
              let existingIds = null;
              if (existingAttr) {
                try {
                  existingIds = JSON.parse(existingAttr);
                } catch (e) {
                  console.error(
                    "Error parsing existing data-selected-prompts after reload:",
                    e
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
                  JSON.stringify(window._selectedAssociatedPrompts.slice())
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
                  JSON.stringify(Array.from(merged))
                );
              }
            }
          } catch (e) {
            console.error(
              "Error restoring data-selected-prompts after HTMX reload:",
              e
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

          initPromptSelect(
            promptsContainerId,
            pPills,
            pWarn,
            6,
            pSelectBtn,
            pClearBtn
          );
        });
    }
  }
};

// ===================================================================
// ENHANCED GATEWAY TEST FUNCTIONALITY
// ===================================================================

let gatewayTestHeadersEditor = null;
let gatewayTestBodyEditor = null;
let gatewayTestFormHandler = null;
let gatewayTestCloseHandler = null;

export const testGateway = async function (gatewayURL) {
  try {
    console.log("Opening gateway test modal for:", gatewayURL);

    // Validate URL
    const urlValidation = validateUrl(gatewayURL);
    if (!urlValidation.valid) {
      showErrorMessage(`Invalid gateway URL: ${urlValidation.error}`);
      return;
    }

    // Clean up any existing event listeners first
    cleanupGatewayTestModal();

    // Open the modal
    openModal("gateway-test-modal");

    // Initialize CodeMirror editors if they don't exist
    if (!gatewayTestHeadersEditor) {
      const headersElement = safeGetElement("gateway-test-headers");
      if (headersElement && window.CodeMirror) {
        gatewayTestHeadersEditor = window.CodeMirror.fromTextArea(
          headersElement,
          {
            mode: "application/json",
            lineNumbers: true,
            lineWrapping: true,
          }
        );
        gatewayTestHeadersEditor.setSize(null, 100);
        console.log("✓ Initialized gateway test headers editor");
      }
    }

    if (!gatewayTestBodyEditor) {
      const bodyElement = safeGetElement("gateway-test-body");
      if (bodyElement && window.CodeMirror) {
        gatewayTestBodyEditor = window.CodeMirror.fromTextArea(
          bodyElement,
          {
            mode: "application/json",
            lineNumbers: true,
            lineWrapping: true,
          }
        );
        gatewayTestBodyEditor.setSize(null, 100);
        console.log("✓ Initialized gateway test body editor");
      }
    }

    // Set form action and URL
    const form = safeGetElement("gateway-test-form");
    const urlInput = safeGetElement("gateway-test-url");

    if (form) {
      form.action = `${window.ROOT_PATH}/admin/gateways/test`;
    }
    if (urlInput) {
      urlInput.value = urlValidation.value;
    }

    // Set up form submission handler
    if (form) {
      gatewayTestFormHandler = async (e) => {
        await handleGatewayTestSubmit(e);
      };
      form.addEventListener("submit", gatewayTestFormHandler);
    }

    // Set up close button handler
    const closeButton = safeGetElement("gateway-test-close");
    if (closeButton) {
      gatewayTestCloseHandler = () => {
        handleGatewayTestClose();
      };
      closeButton.addEventListener("click", gatewayTestCloseHandler);
    }
  } catch (error) {
    console.error("Error setting up gateway test modal:", error);
    showErrorMessage("Failed to open gateway test modal");
  }
};

const handleGatewayTestSubmit = async function (e) {
  e.preventDefault();

  const loading = safeGetElement("gateway-test-loading");
  const responseDiv = safeGetElement("gateway-test-response-json");
  const resultDiv = safeGetElement("gateway-test-result");
  const testButton = safeGetElement("gateway-test-submit");

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
    const urlValidation = validateUrl(baseUrl);
    if (!urlValidation.valid) {
      throw new Error(`Invalid URL: ${urlValidation.error}`);
    }

    // Get CodeMirror content safely
    let headersRaw = "";
    let bodyRaw = "";

    if (gatewayTestHeadersEditor) {
      try {
        headersRaw = gatewayTestHeadersEditor.getValue() || "";
      } catch (error) {
        console.error("Error getting headers value:", error);
      }
    }

    if (gatewayTestBodyEditor) {
      try {
        bodyRaw = gatewayTestBodyEditor.getValue() || "";
      } catch (error) {
        console.error("Error getting body value:", error);
      }
    }

    // Validate and parse JSON safely
    const headersValidation = validateJson(headersRaw, "Headers");
    const bodyValidation = validateJson(bodyRaw, "Body");

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
    const response = await fetchWithTimeout(url, {
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
    const latency = result.latencyMs != null ? `${result.latencyMs}ms` : "NA";
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
};

const handleGatewayTestClose = function () {
  try {
    // Reset form
    const form = safeGetElement("gateway-test-form");
    if (form) {
      form.reset();
    }

    // Clear editors
    if (gatewayTestHeadersEditor) {
      try {
        gatewayTestHeadersEditor.setValue("");
      } catch (error) {
        console.error("Error clearing headers editor:", error);
      }
    }

    if (gatewayTestBodyEditor) {
      try {
        gatewayTestBodyEditor.setValue("");
      } catch (error) {
        console.error("Error clearing body editor:", error);
      }
    }

    // Clear response
    const responseDiv = safeGetElement("gateway-test-response-json");
    const resultDiv = safeGetElement("gateway-test-result");

    if (responseDiv) {
      responseDiv.innerHTML = "";
    }
    if (resultDiv) {
      resultDiv.classList.add("hidden");
    }

    // Close modal
    closeModal("gateway-test-modal");
  } catch (error) {
    console.error("Error closing gateway test modal:", error);
  }
};

const cleanupGatewayTestModal = function () {
  try {
    const form = safeGetElement("gateway-test-form");
    const closeButton = safeGetElement("gateway-test-close");

    // Remove existing event listeners
    if (form && gatewayTestFormHandler) {
      form.removeEventListener("submit", gatewayTestFormHandler);
      gatewayTestFormHandler = null;
    }

    if (closeButton && gatewayTestCloseHandler) {
      closeButton.removeEventListener("click", gatewayTestCloseHandler);
      gatewayTestCloseHandler = null;
    }

    console.log("✓ Cleaned up gateway test modal listeners");
  } catch (error) {
    console.error("Error cleaning up gateway test modal:", error);
  }
};
