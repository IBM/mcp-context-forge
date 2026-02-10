import {
  handleAuthTypeChange,
  handleAuthTypeSelection,
  handleEditOAuthGrantTypeChange,
  handleOAuthGrantTypeChange,
} from "./auth";
import {
  handleDragLeave,
  handleDragOver,
  handleExportAll,
  handleExportSelected,
  handleFileDrop,
  handleFileSelect,
  handleImport,
  loadRecentImports,
} from "./fileTransfer";
import {
  handleAddParameter,
  handleAddPassthrough,
  updateEditToolRequestTypes,
  updateRequestTypeOptions,
} from "./formFieldHandlers";
import {
  handleA2AFormSubmit,
  handleEditA2AAgentFormSubmit,
  handleEditGatewayFormSubmit,
  handleEditPromptFormSubmit,
  handleEditResFormSubmit,
  handleEditServerFormSubmit,
  handleEditToolFormSubmit,
  handleGatewayFormSubmit,
  handlePromptFormSubmit,
  handleResourceFormSubmit,
  handleServerFormSubmit,
  handleToolFormSubmit,
} from "./formSubmitHandlers";
import {
  serverSideEditPromptsSearch,
  serverSideEditResourcesSearch,
  serverSideEditToolSearch,
  serverSidePromptSearch,
  serverSideResourceSearch,
  serverSideToolSearch,
} from "./llmChat";
import { closeModal, openModal } from "./modals";
import { initPromptSelect } from "./prompts";
import { initResourceSelect } from "./resources";
import { safeSetInnerHTML } from "./security";
import { ADMIN_ONLY_TABS, showTab } from "./tabs";
import { initToolSelect } from "./tools";
import { fetchWithTimeout, isAdminUser, safeGetElement } from "./utils";

// ===================================================================
// SINGLE CONSOLIDATED INITIALIZATION SYSTEM
// ===================================================================

// Separate initialization functions
export const initializeCodeMirrorEditors = function () {
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
    const element = safeGetElement(config.id);
    if (element && window.CodeMirror) {
      try {
        window[config.varName] = window.CodeMirror.fromTextArea(element, {
          mode: config.mode,
          theme: "monokai",
          lineNumbers: false,
          autoCloseBrackets: true,
          matchBrackets: true,
          tabSize: 2,
          lineWrapping: true,
        });
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
};

export const initializeToolSelects = function () {
  console.log("Initializing tool selects...");

  // Add Server form
  initToolSelect(
    "associatedTools",
    "selectedToolsPills",
    "selectedToolsWarning",
    6,
    "selectAllToolsBtn",
    "clearAllToolsBtn",
  );

  initResourceSelect(
    "associatedResources",
    "selectedResourcesPills",
    "selectedResourcesWarning",
    10,
    "selectAllResourcesBtn",
    "clearAllResourcesBtn",
  );

  initPromptSelect(
    "associatedPrompts",
    "selectedPromptsPills",
    "selectedPromptsWarning",
    8,
    "selectAllPromptsBtn",
    "clearAllPromptsBtn",
  );

  // Edit Server form
  initToolSelect(
    "edit-server-tools",
    "selectedEditToolsPills",
    "selectedEditToolsWarning",
    6,
    "selectAllEditToolsBtn",
    "clearAllEditToolsBtn",
  );

  // Initialize resource selector
  initResourceSelect(
    "edit-server-resources",
    "selectedEditResourcesPills",
    "selectedEditResourcesWarning",
    10,
    "selectAllEditResourcesBtn",
    "clearAllEditResourcesBtn",
  );

  // Initialize prompt selector
  initPromptSelect(
    "edit-server-prompts",
    "selectedEditPromptsPills",
    "selectedEditPromptsWarning",
    8,
    "selectAllEditPromptsBtn",
    "clearAllEditPromptsBtn",
  );
};

export const initializeEventListeners = function () {
  console.log("🎯 Setting up event listeners...");

  setupTabNavigation();
  setupHTMXHooks();
  console.log("✅ HTMX hooks registered");
  setupAuthenticationToggles();
  setupFormHandlers();
  setupSchemaModeHandlers();
  setupIntegrationTypeHandlers();
  console.log("✅ All event listeners initialized");
};

export const setupTabNavigation = function () {
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

  const visibleTabs = isAdminUser()
    ? tabs
    : tabs.filter((tabName) => !ADMIN_ONLY_TABS.has(tabName));

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

    const tabElement = safeGetElement(`tab-${tabName}`, suppressWarning);
    if (tabElement) {
      tabElement.addEventListener("click", () => showTab(tabName));
    }
  });
};

const setupHTMXHooks = function () {
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
};

const setupAuthenticationToggles = function () {
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
    const element = safeGetElement(handler.id);
    if (element) {
      element.addEventListener("change", function () {
        const basicFields = safeGetElement(handler.basicId);
        const bearerFields = safeGetElement(handler.bearerId);
        const headersFields = safeGetElement(handler.headersId);
        const oauthFields = handler.oauthId
          ? safeGetElement(handler.oauthId)
          : null;
        const queryParamFields = handler.queryParamId
          ? safeGetElement(handler.queryParamId)
          : null;
        handleAuthTypeSelection(
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
};

const setupFormHandlers = function () {
  const gatewayForm = safeGetElement("add-gateway-form");
  if (gatewayForm) {
    gatewayForm.addEventListener("submit", handleGatewayFormSubmit);

    // Add OAuth authentication type change handler
    const authTypeField = safeGetElement("auth-type-gw");
    if (authTypeField) {
      authTypeField.addEventListener("change", handleAuthTypeChange);
    }

    // Add OAuth grant type change handler for Gateway
    const oauthGrantTypeField = safeGetElement("oauth-grant-type-gw");
    if (oauthGrantTypeField) {
      oauthGrantTypeField.addEventListener(
        "change",
        handleOAuthGrantTypeChange,
      );
    }
  }

  // Add A2A Form
  const a2aForm = safeGetElement("add-a2a-form");

  if (a2aForm) {
    a2aForm.addEventListener("submit", handleA2AFormSubmit);

    // Add OAuth authentication type change handler
    const authTypeField = safeGetElement("auth-type-a2a");
    if (authTypeField) {
      authTypeField.addEventListener("change", handleAuthTypeChange);
    }

    const oauthGrantTypeField = safeGetElement("oauth-grant-type-a2a");
    if (oauthGrantTypeField) {
      oauthGrantTypeField.addEventListener(
        "change",
        handleOAuthGrantTypeChange,
      );
    }
  }

  const resourceForm = safeGetElement("add-resource-form");
  if (resourceForm) {
    resourceForm.addEventListener("submit", handleResourceFormSubmit);
  }

  const promptForm = safeGetElement("add-prompt-form");
  if (promptForm) {
    promptForm.addEventListener("submit", handlePromptFormSubmit);
  }

  const editPromptForm = safeGetElement("edit-prompt-form");
  if (editPromptForm) {
    editPromptForm.addEventListener("submit", handleEditPromptFormSubmit);
    editPromptForm.addEventListener("click", () => {
      if (getComputedStyle(editPromptForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  // Add OAuth grant type change handler for Edit Gateway modal
  // Checkpoint commented
  /*
  const editOAuthGrantTypeField = safeGetElement("oauth-grant-type-gw-edit");
  if (editOAuthGrantTypeField) {
  editOAuthGrantTypeField.addEventListener(
  "change",
  handleEditOAuthGrantTypeChange,
  );
  }

  */

  // Checkpoint Started
  ["oauth-grant-type-gw-edit", "oauth-grant-type-a2a-edit"].forEach((id) => {
    const field = safeGetElement(id);
    if (field) {
      field.addEventListener("change", handleEditOAuthGrantTypeChange);
    }
  });
  // Checkpoint Ended

  const toolForm = safeGetElement("add-tool-form");
  if (toolForm) {
    toolForm.addEventListener("submit", handleToolFormSubmit);
    toolForm.addEventListener("click", () => {
      if (getComputedStyle(toolForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  const paramButton = safeGetElement("add-parameter-btn");
  if (paramButton) {
    paramButton.addEventListener("click", handleAddParameter);
  }

  const passthroughButton = safeGetElement("add-passthrough-btn");
  if (passthroughButton) {
    passthroughButton.addEventListener("click", handleAddPassthrough);
  }

  const serverForm = safeGetElement("add-server-form");
  if (serverForm) {
    serverForm.addEventListener("submit", handleServerFormSubmit);
  }

  const editServerForm = safeGetElement("edit-server-form");
  if (editServerForm) {
    editServerForm.addEventListener("submit", handleEditServerFormSubmit);
    editServerForm.addEventListener("click", () => {
      if (getComputedStyle(editServerForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  const editResourceForm = safeGetElement("edit-resource-form");
  if (editResourceForm) {
    editResourceForm.addEventListener("submit", handleEditResFormSubmit);
    editResourceForm.addEventListener("click", () => {
      if (getComputedStyle(editResourceForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  const editToolForm = safeGetElement("edit-tool-form");
  if (editToolForm) {
    editToolForm.addEventListener("submit", handleEditToolFormSubmit);
    editToolForm.addEventListener("click", () => {
      if (getComputedStyle(editToolForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  const editGatewayForm = safeGetElement("edit-gateway-form");
  if (editGatewayForm) {
    editGatewayForm.addEventListener("submit", handleEditGatewayFormSubmit);
    editGatewayForm.addEventListener("click", () => {
      if (getComputedStyle(editGatewayForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  const editA2AAgentForm = safeGetElement("edit-a2a-agent-form");
  if (editA2AAgentForm) {
    editA2AAgentForm.addEventListener("submit", handleEditA2AAgentFormSubmit);
    editA2AAgentForm.addEventListener("click", () => {
      if (getComputedStyle(editA2AAgentForm).display !== "none") {
        refreshEditors();
      }
    });
  }

  // Setup search functionality for selectors
  setupSelectorSearch();
};

/**
 * Setup search functionality for multi-select dropdowns
 */
const setupSelectorSearch = function () {
  // Tools search - server-side search
  const searchTools = safeGetElement("searchTools", true);
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
        serverSideToolSearch(searchTerm);
      }, 300);
    });
  }

  // Edit-server tools search (server-side, mirror of searchTools)
  const searchEditTools = safeGetElement("searchEditTools", true);
  if (searchEditTools) {
    let editSearchTimeout;
    searchEditTools.addEventListener("input", function () {
      const searchTerm = this.value;
      if (editSearchTimeout) {
        clearTimeout(editSearchTimeout);
      }
      editSearchTimeout = setTimeout(() => {
        serverSideEditToolSearch(searchTerm);
      }, 300);
    });

    // If HTMX swaps/paginates the edit tools container, re-run server-side search
    const editToolsContainer = safeGetElement("edit-server-tools");
    if (editToolsContainer) {
      editToolsContainer.addEventListener("htmx:afterSwap", function () {
        try {
          const current = searchEditTools.value || "";
          if (current && current.trim() !== "") {
            serverSideEditToolSearch(current);
          } else {
            // No active search — ensure the selector is initialized
            initToolSelect(
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
  const searchPrompts = safeGetElement("searchPrompts", true);
  if (searchPrompts) {
    let promptSearchTimeout;
    searchPrompts.addEventListener("input", function () {
      const searchTerm = this.value;
      if (promptSearchTimeout) {
        clearTimeout(promptSearchTimeout);
      }
      promptSearchTimeout = setTimeout(() => {
        serverSidePromptSearch(searchTerm);
      }, 300);
    });
  }

  // Edit-server prompts search (server-side, mirror of searchPrompts)
  const searchEditPrompts = safeGetElement("searchEditPrompts", true);
  if (searchEditPrompts) {
    let editSearchTimeout;
    searchEditPrompts.addEventListener("input", function () {
      const searchTerm = this.value;
      if (editSearchTimeout) {
        clearTimeout(editSearchTimeout);
      }
      editSearchTimeout = setTimeout(() => {
        serverSideEditPromptsSearch(searchTerm);
      }, 300);
    });

    // If HTMX swaps/paginates the edit prompts container, re-run server-side search
    const editPromptsContainer = safeGetElement("edit-server-prompts");
    if (editPromptsContainer) {
      editPromptsContainer.addEventListener("htmx:afterSwap", function () {
        try {
          const current = searchEditPrompts.value || "";
          if (current && current.trim() !== "") {
            serverSideEditPromptsSearch(current);
          } else {
            // No active search — ensure the selector is initialized
            initPromptSelect(
              "edit-server-prompts",
              "selectedEditPromptsPills",
              "selectedEditPromptsWarning",
              6,
              "selectAllEditPromptsBtn",
              "clearAllEditPromptsBtn",
            );
          }
        } catch (err) {
          console.error("Error handling edit-prompts afterSwap:", err);
        }
      });
    }
  }

  // Resources search (server-side)
  const searchResources = safeGetElement("searchResources", true);
  if (searchResources) {
    let resourceSearchTimeout;
    searchResources.addEventListener("input", function () {
      const searchTerm = this.value;
      if (resourceSearchTimeout) {
        clearTimeout(resourceSearchTimeout);
      }
      resourceSearchTimeout = setTimeout(() => {
        serverSideResourceSearch(searchTerm);
      }, 300);
    });
  }

  // Edit-server resources search (server-side, mirror of searchResources)
  const searchEditResources = safeGetElement("searchEditResources", true);
  if (searchEditResources) {
    let editSearchTimeout;
    searchEditResources.addEventListener("input", function () {
      const searchTerm = this.value;
      if (editSearchTimeout) {
        clearTimeout(editSearchTimeout);
      }
      editSearchTimeout = setTimeout(() => {
        serverSideEditResourcesSearch(searchTerm);
      }, 300);
    });

    // If HTMX swaps/paginates the edit resources container, re-run server-side search
    const editResourcesContainer = safeGetElement("edit-server-resources");
    if (editResourcesContainer) {
      editResourcesContainer.addEventListener("htmx:afterSwap", function () {
        try {
          const current = searchEditResources.value || "";
          if (current && current.trim() !== "") {
            serverSideEditResourcesSearch(current);
          } else {
            // No active search — ensure the selector is initialized
            initResourceSelect(
              "edit-server-resources",
              "selectedEditResourcesPills",
              "selectedEditResourcesWarning",
              6,
              "selectAllEditResourcesBtn",
              "clearAllEditResourcesBtn",
            );
          }
        } catch (err) {
          console.error("Error handling edit-resources afterSwap:", err);
        }
      });
    }
  }
};

/**
 * Initialize search inputs for all entity types
 * This function also handles re-initialization after HTMX content loads
 */
export const initializeSearchInputs = function () {
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
    const input = safeGetElement(inputId);
    if (input) {
      const newInput = input.cloneNode(true);
      input.parentNode.replaceChild(newInput, input);
    }
  });

  // Virtual Servers search
  const catalogSearchInput = safeGetElement("catalog-search-input");
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
  const gatewaysSearchInput = safeGetElement("gateways-search-input");
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
  const toolsSearchInput = safeGetElement("tools-search-input");
  if (toolsSearchInput) {
    toolsSearchInput.addEventListener("input", function () {
      Admin.filterToolsTable(this.value);
    });
    console.log("✅ Tools search initialized");
  }

  // Resources search
  const resourcesSearchInput = safeGetElement("resources-search-input");
  if (resourcesSearchInput) {
    resourcesSearchInput.addEventListener("input", function () {
      Admin.filterResourcesTable(this.value);
    });
    console.log("✅ Resources search initialized");
  }

  // Prompts search
  const promptsSearchInput = safeGetElement("prompts-search-input");
  if (promptsSearchInput) {
    promptsSearchInput.addEventListener("input", function () {
      Admin.filterPromptsTable(this.value);
    });
    console.log("✅ Prompts search initialized");
  }

  // A2A Agents search
  const agentsSearchInput = safeGetElement("a2a-agents-search-input");
  if (agentsSearchInput) {
    agentsSearchInput.addEventListener("input", function () {
      Admin.filterA2AAgentsTable(this.value);
    });
    console.log("✅ A2A Agents search initialized");
  }
};

export const initializeTabState = function () {
  console.log("Initializing tab state...");

  const hash = window.location.hash;
  if (hash) {
    showTab(hash.slice(1));
  } else {
    showTab("gateways");
  }

  // Pre-load version info if that's the initial tab
  if (isAdminUser() && window.location.hash === "#version-info") {
    setTimeout(() => {
      const panel = safeGetElement("version-info-panel");
      if (panel && panel.innerHTML.trim() === "") {
        fetchWithTimeout(`${window.ROOT_PATH}/version?partial=true`)
          .then((resp) => {
            if (!resp.ok) {
              throw new Error("Network response was not ok");
            }
            return resp.text();
          })
          .then((html) => {
            safeSetInnerHTML(panel, html, true);
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
  if (isAdminUser() && window.location.hash === "#maintenance") {
    setTimeout(() => {
      const panel = safeGetElement("maintenance-panel");
      if (panel && panel.innerHTML.trim() === "") {
        fetchWithTimeout(`${window.ROOT_PATH}/admin/maintenance/partial`)
          .then((resp) => {
            if (!resp.ok) {
              if (resp.status === 403) {
                throw new Error("Platform administrator access required");
              }
              throw new Error("Network response was not ok");
            }
            return resp.text();
          })
          .then((html) => {
            safeSetInnerHTML(panel, html, true);
          })
          .catch((err) => {
            console.error("Failed to preload maintenance panel:", err);
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
    const checkbox = safeGetElement(id);
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
};

export const setupSchemaModeHandlers = function () {
  const schemaModeRadios = document.getElementsByName("schema_input_mode");
  const uiBuilderDiv = safeGetElement("ui-builder");
  const jsonInputContainer = safeGetElement("json-input-container");

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
          updateSchemaPreview();
        }
      } catch (error) {
        console.error("Error handling schema mode change:", error);
      }
    });
  });

  console.log("✓ Schema mode handlers set up successfully");
};

export const setupIntegrationTypeHandlers = function () {
  const integrationTypeSelect = safeGetElement("integrationType");
  if (integrationTypeSelect) {
    const defaultIntegration =
      integrationTypeSelect.dataset.default ||
      integrationTypeSelect.options[0].value;
    integrationTypeSelect.value = defaultIntegration;
    updateRequestTypeOptions();
    integrationTypeSelect.addEventListener("change", () =>
      updateRequestTypeOptions(),
    );
  }

  const editToolTypeSelect = safeGetElement("edit-tool-type");
  if (editToolTypeSelect) {
    editToolTypeSelect.addEventListener(
      "change",
      () => updateEditToolRequestTypes(),
      // updateEditToolUrl(),
    );
  }
};

// ===================================================================
// BULK IMPORT TOOLS — MODAL WIRING
// ===================================================================

export const setupBulkImportModal = function () {
  const openBtn = safeGetElement("open-bulk-import", true);
  const modalId = "bulk-import-modal";
  const modal = safeGetElement(modalId, true);

  if (!openBtn || !modal) {
    // Bulk import feature not available - skip silently
    return;
  }

  // avoid double-binding if admin.js gets evaluated more than once
  if (openBtn.dataset.wired === "1") {
    return;
  }
  openBtn.dataset.wired = "1";

  const closeBtn = safeGetElement("close-bulk-import", true);
  const backdrop = safeGetElement("bulk-import-backdrop", true);
  const resultEl = safeGetElement("import-result", true);

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
    openModal(modalId);
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
    closeModal(modalId, "import-result");
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
  const form = safeGetElement("bulk-import-form", true);
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const resultEl = safeGetElement("import-result", true);
      const indicator = safeGetElement("bulk-import-indicator", true);

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
        const response = await fetchWithTimeout(
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
              closeModal("bulk-import-modal");
              window.location.reload();
            }, 2000);
          } else if (result.imported > 0) {
            // Partial success
            let detailsHtml = "";
            if (result.details && result.details.failed) {
              detailsHtml = '<ul class="mt-2 text-sm list-disc list-inside">';
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
};

// ===================================================================
// EXPORT/IMPORT FUNCTIONALITY
// ===================================================================

export const initializeExportImport = function () {
  // Prevent double initialization
  if (window.exportImportInitialized) {
    console.log("🔄 Export/import already initialized, skipping");
    return;
  }

  console.log("🔄 Initializing export/import functionality");

  // Export button handlers
  const exportAllBtn = safeGetElement("export-all-btn");
  const exportSelectedBtn = safeGetElement("export-selected-btn");

  if (exportAllBtn) {
    exportAllBtn.addEventListener("click", handleExportAll);
  }

  if (exportSelectedBtn) {
    exportSelectedBtn.addEventListener("click", handleExportSelected);
  }

  // Import functionality
  const importDropZone = safeGetElement("import-drop-zone");
  const importFileInput = safeGetElement("import-file-input");
  const importValidateBtn = safeGetElement("import-validate-btn");
  const importExecuteBtn = safeGetElement("import-execute-btn");

  if (importDropZone && importFileInput) {
    // File input handler
    importDropZone.addEventListener("click", () => importFileInput.click());
    importFileInput.addEventListener("change", handleFileSelect);

    // Drag and drop handlers
    importDropZone.addEventListener("dragover", handleDragOver);
    importDropZone.addEventListener("drop", handleFileDrop);
    importDropZone.addEventListener("dragleave", handleDragLeave);
  }

  if (importValidateBtn) {
    importValidateBtn.addEventListener("click", () => handleImport(true));
  }

  if (importExecuteBtn) {
    importExecuteBtn.addEventListener("click", () => handleImport(false));
  }

  // Load recent imports when tab is shown
  loadRecentImports();

  // Mark as initialized
  Admin.exportImportInitialized = true;
};

// ===================================================================
// ENHANCED EDITOR REFRESH with Safety Checks
// ===================================================================

const refreshEditors = function () {
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
};
