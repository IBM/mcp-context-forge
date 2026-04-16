import { AppState } from "./appState.js";
import { getCatalogUrl } from "./configExport.js";
import { toggleViewPublic } from "./filters.js";
import { initGatewaySelect } from "./gateways.js";
import { openModal } from "./modals.js";
import { initPromptSelect } from "./prompts.js";
import { initResourceSelect } from "./resources.js";
import { validateInputName, validateUrl } from "./security.js";
import { applyVisibilityRestrictions, isTeamScopedView } from "./teams.js";
import {
  safeGetElement,
  fetchWithTimeout,
  isInactiveChecked,
  handleFetchError,
  showErrorMessage,
  decodeHtml,
  makeCopyIdButton,
} from "./utils.js";

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
        serverDesc.textContent = decodeHtml(server.description);
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

      // Server ID field with copy button
      const serverIdP = document.createElement("p");
      const serverIdStrong = document.createElement("strong");
      serverIdStrong.textContent = "Server ID: ";
      serverIdP.appendChild(serverIdStrong);
      const serverIdSpan = document.createElement("span");
      serverIdSpan.className = "font-mono text-sm";
      serverIdSpan.textContent = server.id;
      serverIdP.appendChild(serverIdSpan);
      serverIdP.appendChild(makeCopyIdButton(server.id));
      basicInfoDiv.appendChild(serverIdP);

      const fields = [
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
            window.Admin.toolMapping && window.Admin.toolMapping[toolId]
              ? window.Admin.toolMapping[toolId]
              : toolId;

          const toolIdSpan = document.createElement("span");
          toolIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          toolIdSpan.textContent = `(${toolId})`;

          toolItem.appendChild(toolBadge);
          toolItem.appendChild(toolIdSpan);
          toolsList.appendChild(toolItem);
        });

        // If more than maxToShow, add a summary badge (clickable to expand)
        if (server.associatedTools.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-green-900 dark:text-green-200";
          moreBadge.title = "Total tools associated";
          const remaining = server.associatedTools.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          // Expand inline to show full list when clicked
          moreBadge.addEventListener("click", () => {
            toolsList.innerHTML = "";
            (server.associatedTools || []).forEach((toolId) => {
              const toolItem = document.createElement("div");
              toolItem.className = "flex items-center space-x-2";

              const toolBadge = document.createElement("span");
              toolBadge.className =
                "inline-block bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full dark:bg-green-900 dark:text-green-200";
              toolBadge.textContent =
                window.toolMapping && window.toolMapping[toolId]
                  ? window.toolMapping[toolId]
                  : toolId;

              const toolIdSpan = document.createElement("span");
              toolIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
              toolIdSpan.textContent = `(${toolId})`;

              toolItem.appendChild(toolBadge);
              toolItem.appendChild(toolIdSpan);
              toolsList.appendChild(toolItem);
            });
          });

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
            window.Admin.resourceMapping &&
            window.Admin.resourceMapping[resourceId]
              ? window.Admin.resourceMapping[resourceId]
              : `Resource ${resourceId}`;

          const resourceIdSpan = document.createElement("span");
          resourceIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          resourceIdSpan.textContent = `(${resourceId})`;

          resourceItem.appendChild(resourceBadge);
          resourceItem.appendChild(resourceIdSpan);
          resourcesList.appendChild(resourceItem);
        });

        // If more than maxToShow, add a summary badge (clickable to expand)
        if (server.associatedResources.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-blue-900 dark:text-blue-200";
          moreBadge.title = "Total resources associated";
          const remaining = server.associatedResources.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          moreBadge.addEventListener("click", () => {
            resourcesList.innerHTML = "";
            (server.associatedResources || []).forEach((resourceId) => {
              const resourceItem = document.createElement("div");
              resourceItem.className = "flex items-center space-x-2";

              const resourceBadge = document.createElement("span");
              resourceBadge.className =
                "inline-block bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full dark:bg-blue-900 dark:text-blue-200";
              resourceBadge.textContent =
                window.resourceMapping && window.resourceMapping[resourceId]
                  ? window.resourceMapping[resourceId]
                  : `Resource ${resourceId}`;

              const resourceIdSpan = document.createElement("span");
              resourceIdSpan.className =
                "text-xs text-gray-500 dark:text-gray-400";
              resourceIdSpan.textContent = `(${resourceId})`;

              resourceItem.appendChild(resourceBadge);
              resourceItem.appendChild(resourceIdSpan);
              resourcesList.appendChild(resourceItem);
            });
          });

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
            window.Admin.promptMapping && window.Admin.promptMapping[promptId]
              ? window.Admin.promptMapping[promptId]
              : `Prompt ${promptId}`;

          const promptIdSpan = document.createElement("span");
          promptIdSpan.className = "text-xs text-gray-500 dark:text-gray-400";
          promptIdSpan.textContent = `(${promptId})`;

          promptItem.appendChild(promptBadge);
          promptItem.appendChild(promptIdSpan);
          promptsList.appendChild(promptItem);
        });

        // If more than maxToShow, add a summary badge (clickable to expand)
        if (server.associatedPrompts.length > maxToShow) {
          const moreItem = document.createElement("div");
          moreItem.className = "flex items-center space-x-2";

          const moreBadge = document.createElement("span");
          moreBadge.className =
            "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full cursor-pointer dark:bg-purple-900 dark:text-purple-200";
          moreBadge.title = "Total prompts associated";
          const remaining = server.associatedPrompts.length - maxToShow;
          moreBadge.textContent = `+${remaining} more`;

          moreBadge.addEventListener("click", () => {
            promptsList.innerHTML = "";
            (server.associatedPrompts || []).forEach((promptId) => {
              const promptItem = document.createElement("div");
              promptItem.className = "flex items-center space-x-2";

              const promptBadge = document.createElement("span");
              promptBadge.className =
                "inline-block bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded-full dark:bg-purple-900 dark:text-purple-200";
              promptBadge.textContent =
                window.promptMapping && window.promptMapping[promptId]
                  ? window.promptMapping[promptId]
                  : `Prompt ${promptId}`;

              const promptIdSpan = document.createElement("span");
              promptIdSpan.className =
                "text-xs text-gray-500 dark:text-gray-400";
              promptIdSpan.textContent = `(${promptId})`;

              promptItem.appendChild(promptBadge);
              promptItem.appendChild(promptIdSpan);
              promptsList.appendChild(promptItem);
            });
          });

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

      // OAuth Configuration section
      if (server.oauthEnabled) {
        const oauthDiv = document.createElement("div");
        oauthDiv.className = "mt-6 border-t pt-4";

        const oauthTitle = document.createElement("strong");
        oauthTitle.textContent = "OAuth 2.0 Configuration:";
        oauthTitle.className = "block text-gray-900 dark:text-gray-100 mb-3";
        oauthDiv.appendChild(oauthTitle);

        // OAuth Config details
        const oauthConfig = server.oauthConfig || server.oauth_config;
        if (oauthConfig) {
          const oauthConfigDiv = document.createElement("div");
          oauthConfigDiv.className =
            "mt-3 space-y-2 bg-gray-50 dark:bg-gray-800 p-3 rounded-md";

          // Authorization Servers
          if (
            oauthConfig.authorization_servers &&
            oauthConfig.authorization_servers.length > 0
          ) {
            const authServersP = document.createElement("p");
            authServersP.className = "text-sm";
            const authServersStrong = document.createElement("strong");
            authServersStrong.textContent = "Authorization Servers: ";
            authServersStrong.className =
              "font-medium text-gray-700 dark:text-gray-300";
            authServersP.appendChild(authServersStrong);

            const serversList = document.createElement("ul");
            serversList.className = "mt-1 ml-4 list-disc list-inside";
            oauthConfig.authorization_servers.forEach((serverUrl) => {
              const li = document.createElement("li");
              li.className = "text-gray-600 dark:text-gray-400 text-sm";
              li.textContent = serverUrl;
              serversList.appendChild(li);
            });
            authServersP.appendChild(serversList);
            oauthConfigDiv.appendChild(authServersP);
          }

          // Token Endpoint
          if (oauthConfig.token_endpoint) {
            const tokenEndpointP = document.createElement("p");
            tokenEndpointP.className = "text-sm";
            const tokenEndpointStrong = document.createElement("strong");
            tokenEndpointStrong.textContent = "Token Endpoint: ";
            tokenEndpointStrong.className =
              "font-medium text-gray-700 dark:text-gray-300";
            tokenEndpointP.appendChild(tokenEndpointStrong);

            const tokenEndpointSpan = document.createElement("span");
            tokenEndpointSpan.className =
              "text-gray-600 dark:text-gray-400 break-all";
            tokenEndpointSpan.textContent = oauthConfig.token_endpoint;
            tokenEndpointP.appendChild(tokenEndpointSpan);
            oauthConfigDiv.appendChild(tokenEndpointP);
          }

          // Scopes Supported
          if (
            oauthConfig.scopes_supported &&
            oauthConfig.scopes_supported.length > 0
          ) {
            const scopesP = document.createElement("p");
            scopesP.className = "text-sm";
            const scopesStrong = document.createElement("strong");
            scopesStrong.textContent = "Supported Scopes: ";
            scopesStrong.className =
              "font-medium text-gray-700 dark:text-gray-300";
            scopesP.appendChild(scopesStrong);

            const scopesSpan = document.createElement("span");
            scopesSpan.className = "text-gray-600 dark:text-gray-400";
            scopesSpan.textContent = oauthConfig.scopes_supported.join(", ");
            scopesP.appendChild(scopesSpan);
            oauthConfigDiv.appendChild(scopesP);
          }

          oauthDiv.appendChild(oauthConfigDiv);
        } else {
          const noConfigP = document.createElement("p");
          noConfigP.className = "mt-2 text-sm text-gray-500 dark:text-gray-400";
          noConfigP.textContent =
            "OAuth is enabled but no configuration details are available.";
          oauthDiv.appendChild(noConfigP);
        }

        container.appendChild(oauthDiv);
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

    const visibility = server.visibility
      ? server.visibility.toLowerCase()
      : null;
    const publicRadio = safeGetElement("edit-server-visibility-public");
    const teamRadio = safeGetElement("edit-server-visibility-team");
    const privateRadio = safeGetElement("edit-server-visibility-private");

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

    // Prepopulate visibility radio buttons based on the server data
    if (visibility) {
      // When public visibility is disabled and we're in a team-scoped view,
      // coerce legacy-public records to team.
      const effectiveVisibility =
        window.ALLOW_PUBLIC_VISIBILITY === false &&
        visibility === "public" &&
        isTeamScopedView()
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

    const teamId = new URL(window.location.href).searchParams.get("team_id");

    if (teamId) {
      const hiddenInput = document.createElement("input");
      hiddenInput.type = "hidden";
      hiddenInput.name = "team_id";
      hiddenInput.value = teamId;
      editForm.appendChild(hiddenInput);
    }

    // Initialize View Public toggle for Edit Server modal
    if (teamId) {
      const viewPublicCheckbox = document.getElementById(
        "edit-server-view-public"
      );
      if (viewPublicCheckbox) {
        viewPublicCheckbox.checked = false; // Default unchecked
      }
      toggleViewPublic(
        "edit-server-view-public",
        [
          "associatedEditGateways",
          "edit-server-tools",
          "edit-server-resources",
          "edit-server-prompts",
        ],
        teamId
      );
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
      descField.value = decodeHtml(server.description || "");
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
      oauthEnabledCheckbox.checked = server.oauthEnabled || false;
    }

    // Show/hide OAuth config section based on oauthEnabled state
    if (oauthConfigSection) {
      if (server.oauthEnabled) {
        oauthConfigSection.classList.remove("hidden");
      } else {
        oauthConfigSection.classList.add("hidden");
      }
    }

    // Populate OAuth config fields if oauthConfig exists
    if (server.oauthConfig) {
      // Extract authorization server (may be in authorization_servers array or authorization_server string)
      let authServer = "";
      if (
        server.oauthConfig.authorization_servers &&
        server.oauthConfig.authorization_servers.length > 0
      ) {
        authServer = server.oauthConfig.authorization_servers[0];
      } else if (server.oauthConfig.authorization_server) {
        authServer = server.oauthConfig.authorization_server;
      }
      if (oauthAuthServerField) {
        oauthAuthServerField.value = authServer;
      }

      // Extract scopes (may be scopes_supported array or scopes array)
      const scopes =
        server.oauthConfig.scopes_supported || server.oauthConfig.scopes || [];
      if (oauthScopesField) {
        oauthScopesField.value = Array.isArray(scopes)
          ? scopes.join(" ")
          : scopes;
      }

      // Extract token endpoint
      if (oauthTokenEndpointField) {
        oauthTokenEndpointField.value = server.oauthConfig.token_endpoint || "";
      }
    } else {
      // Clear OAuth config fields when no config exists
      if (oauthAuthServerField) oauthAuthServerField.value = "";
      if (oauthScopesField) oauthScopesField.value = "";
      if (oauthTokenEndpointField) oauthTokenEndpointField.value = "";
    }

    // Store server data for modal population
    window.Admin.currentEditingServer = server;

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

    // Seed the persistent selection store with all associated item IDs
    resetEditSelections();
    if (server.associatedToolIds) {
      const toolSel = getEditSelections("edit-server-tools");
      server.associatedToolIds.forEach((id) => toolSel.add(String(id)));
    }
    if (server.associatedResources) {
      const resSel = getEditSelections("edit-server-resources");
      server.associatedResources.forEach((id) => resSel.add(String(id)));
    }
    if (server.associatedPrompts) {
      const promptSel = getEditSelections("edit-server-prompts");
      server.associatedPrompts.forEach((id) => promptSel.add(String(id)));
    }
    ensureEditStoreListeners();

    openModal("server-edit-modal");
    applyVisibilityRestrictions(["edit-server-visibility"]); // Disable public radio if restricted, preserve checked state
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

    // Set checkboxes based on selection store (seeded above) and trigger pill updates
    setEditServerAssociations(server);
    // Re-run after short delays to catch any HTMX-loaded content
    setTimeout(() => setEditServerAssociations(server), 100);
    setTimeout(() => setEditServerAssociations(server), 300);

    // Trigger pill updates after checkboxes are set
    setTimeout(() => {
      [
        "edit-server-tools",
        "edit-server-resources",
        "edit-server-prompts",
      ].forEach((containerId) => {
        const container = document.getElementById(containerId);
        if (container) {
          const firstCheckbox = container.querySelector(
            'input[type="checkbox"]'
          );
          if (firstCheckbox) {
            firstCheckbox.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
      });
    }, 350);

    // Auto-enable "View Public" if server has public associations not visible in team-filtered selectors
    if (teamId) {
      setTimeout(() => {
        const viewPublicCheckbox = document.getElementById(
          "edit-server-view-public"
        );
        if (!viewPublicCheckbox || viewPublicCheckbox.checked) return;

        let hasMissingItems = false;

        // Check tools
        const toolsContainer = document.getElementById("edit-server-tools");
        if (toolsContainer && server.associatedToolIds) {
          const visibleToolIds = new Set(
            Array.from(
              toolsContainer.querySelectorAll('input[name="associatedTools"]')
            ).map((cb) => String(cb.value))
          );
          for (const id of server.associatedToolIds) {
            if (!visibleToolIds.has(String(id))) {
              hasMissingItems = true;
              break;
            }
          }
        }

        // Check resources
        if (!hasMissingItems) {
          const resourcesContainer = document.getElementById(
            "edit-server-resources"
          );
          if (resourcesContainer && server.associatedResources) {
            const visibleResourceIds = new Set(
              Array.from(
                resourcesContainer.querySelectorAll(
                  'input[name="associatedResources"]'
                )
              ).map((cb) => String(cb.value))
            );
            for (const id of server.associatedResources) {
              if (!visibleResourceIds.has(String(id))) {
                hasMissingItems = true;
                break;
              }
            }
          }
        }

        // Check prompts
        if (!hasMissingItems) {
          const promptsContainer = document.getElementById(
            "edit-server-prompts"
          );
          if (promptsContainer && server.associatedPrompts) {
            const visiblePromptIds = new Set(
              Array.from(
                promptsContainer.querySelectorAll(
                  'input[name="associatedPrompts"]'
                )
              ).map((cb) => String(cb.value))
            );
            for (const id of server.associatedPrompts) {
              if (!visiblePromptIds.has(String(id))) {
                hasMissingItems = true;
                break;
              }
            }
          }
        }

        if (hasMissingItems) {
          console.log(
            "Auto-enabling View Public: server has associations not visible in team-filtered selectors"
          );
          viewPublicCheckbox.checked = true;
          viewPublicCheckbox.dispatchEvent(new Event("change"));
          // Re-run association setting after the re-fetch completes
          setTimeout(() => setEditServerAssociations(server), 500);
          setTimeout(() => setEditServerAssociations(server), 1000);
        }
      }, 500); // Wait for HTMX selectors to finish loading
    }

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

  // Get the selection store for tools (contains IDs)
  const toolSel = getEditSelections("edit-server-tools");

  toolCheckboxes.forEach((checkbox) => {
    let isChecked = false;
    const toolId = checkbox.value;

    // First check if the tool ID is in the selection store
    if (toolSel.has(toolId)) {
      isChecked = true;
    }
    // Fallback: check by tool name if available
    else if (server.associatedTools && window.Admin.toolMapping) {
      const toolName = window.Admin.toolMapping[toolId];
      isChecked = toolName && server.associatedTools.includes(toolName);
    }

    checkbox.checked = isChecked;
  });

  // Set associated resources checkboxes (scope to edit modal container only)
  const resourceContainer = safeGetElement("edit-server-resources");
  const resourceCheckboxes = resourceContainer
    ? resourceContainer.querySelectorAll('input[name="associatedResources"]')
    : document.querySelectorAll('input[name="associatedResources"]');

  // Get the selection store for resources (contains IDs)
  const resourceSel = getEditSelections("edit-server-resources");

  resourceCheckboxes.forEach((checkbox) => {
    const resourceId = String(checkbox.value);
    // Check if the resource ID is in the selection store first
    let isChecked = resourceSel.has(resourceId);
    // Fallback: check by server associations
    if (!isChecked && server.associatedResources) {
      isChecked = server.associatedResources.includes(resourceId);
    }
    checkbox.checked = isChecked;
  });

  // Set associated prompts checkboxes (scope to edit modal container only)
  const promptContainer = safeGetElement("edit-server-prompts");
  const promptCheckboxes = promptContainer
    ? promptContainer.querySelectorAll('input[name="associatedPrompts"]')
    : document.querySelectorAll('input[name="associatedPrompts"]');

  // Get the selection store for prompts (contains IDs)
  const promptSel = getEditSelections("edit-server-prompts");

  promptCheckboxes.forEach((checkbox) => {
    const promptId = String(checkbox.value);
    // Check if the prompt ID is in the selection store first
    let isChecked = promptSel.has(promptId);
    // Fallback: check by server associations
    if (!isChecked && server.associatedPrompts) {
      isChecked = server.associatedPrompts.includes(promptId);
    }
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

/**
 * Load servers (Virtual Servers / Catalog) with optional include_inactive parameter
 */
export const loadServers = async function () {
  const checkbox = safeGetElement("show-inactive-servers");
  const includeInactive = checkbox ? checkbox.checked : false;

  // Build URL with include_inactive parameter
  const url = new URL(window.location);
  if (includeInactive) {
    url.searchParams.set("include_inactive", "true");
  } else {
    url.searchParams.delete("include_inactive");
  }

  // Reload the page with the updated parameters
  // Since the catalog panel is server-side rendered, we need a full page reload
  window.location.href = url.toString();
};

// ===================================================================
// PERSISTENT SELECTION STORE for edit-server modal
// ===================================================================
// Tracks selected UUIDs across infinite scroll pages and searches.
// Keys: container IDs ("edit-server-tools", "edit-server-resources", "edit-server-prompts")
// Values: Set of selected UUIDs
export function getEditSelections(containerId) {
  if (!AppState.editServerSelections[containerId]) {
    AppState.editServerSelections[containerId] = new Set();
  }
  return AppState.editServerSelections[containerId];
}

export function resetEditSelections() {
  ["edit-server-tools", "edit-server-resources", "edit-server-prompts"].forEach(
    (k) => {
      delete AppState.editServerSelections[k];
    }
  );

  // Remove stale "Select All" hidden inputs so they don't leak into the
  // next edit session and override the persistent selection store on save.
  const hiddenFields = [
    {
      container: "edit-server-tools",
      names: ["selectAllTools", "allToolIds"],
    },
    {
      container: "edit-server-resources",
      names: ["selectAllResources", "allResourceIds"],
    },
    {
      container: "edit-server-prompts",
      names: ["selectAllPrompts", "allPromptIds"],
    },
  ];
  hiddenFields.forEach(({ container, names }) => {
    const el = document.getElementById(container);
    if (!el) return;
    names.forEach((n) => {
      const input = el.querySelector(`input[name="${n}"]`);
      if (input) input.remove();
    });
  });
}

export function ensureEditStoreListeners() {
  if (window._editStoreListenersAttached) return;
  window._editStoreListenersAttached = true;

  ["edit-server-tools", "edit-server-resources", "edit-server-prompts"].forEach(
    (containerId) => {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.addEventListener("change", function (e) {
        const target = e.target;
        if (
          target.type === "checkbox" &&
          (target.name === "associatedTools" ||
            target.name === "associatedResources" ||
            target.name === "associatedPrompts")
        ) {
          const sel = getEditSelections(containerId);
          const value = String(target.value);
          if (target.checked) {
            sel.add(value);
          } else {
            sel.delete(value);
          }
        }
      });
    }
  );
}

export function ensureAddStoreListeners() {
  if (window._addStoreListenersAttached) return;
  window._addStoreListenersAttached = true;

  ["associatedTools", "associatedResources", "associatedPrompts"].forEach(
    (containerId) => {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.addEventListener("change", function (e) {
        const target = e.target;
        if (
          target.type === "checkbox" &&
          (target.name === "associatedTools" ||
            target.name === "associatedResources" ||
            target.name === "associatedPrompts")
        ) {
          const sel = getEditSelections(containerId);
          const value = String(target.value);
          if (target.checked) {
            sel.add(value);
          } else {
            sel.delete(value);
          }
        }
      });
    }
  );

  // Clear selections when the add-server form is reset
  const form = document.getElementById("add-server-form");
  if (form) {
    form.addEventListener("reset", function () {
      ["associatedTools", "associatedResources", "associatedPrompts"].forEach(
        (k) => {
          delete AppState.editServerSelections[k];
        }
      );
    });
  }
}

// ===================================================================
// Object Mapping
// ===================================================================

/**
 * Update the tool mapping with tools in the given container
 */
export const updateToolMapping = function (container) {
  if (!window.Admin.toolMapping) {
    window.Admin.toolMapping = {};
  }

  const checkboxes = container.querySelectorAll(
    'input[name="associatedTools"]'
  );
  checkboxes.forEach((checkbox) => {
    const toolId = checkbox.value;
    const toolName = checkbox.getAttribute("data-tool-name");
    if (toolId && toolName) {
      window.Admin.toolMapping[toolId] = toolName;
    }
  });
};

/**
 * Update the prompt mapping with prompts in the given container
 */
export const updatePromptMapping = function (container) {
  if (!window.Admin.promptMapping) {
    window.Admin.promptMapping = {};
  }

  const checkboxes = container.querySelectorAll(
    'input[name="associatedPrompts"]'
  );
  checkboxes.forEach((checkbox) => {
    const promptId = checkbox.value;
    const promptName =
      checkbox.getAttribute("data-prompt-name") ||
      checkbox.nextElementSibling?.textContent?.trim() ||
      promptId;
    if (promptId && promptName) {
      window.Admin.promptMapping[promptId] = promptName;
    }
  });
};

/**
 * Update the resource mapping with resources in the given container
 */
export const updateResourceMapping = function (container) {
  if (!window.Admin.resourceMapping) {
    window.Admin.resourceMapping = {};
  }

  const checkboxes = container.querySelectorAll(
    'input[name="associatedResources"]'
  );
  checkboxes.forEach((checkbox) => {
    const resourceId = checkbox.value;
    const resourceName =
      checkbox.getAttribute("data-resource-name") ||
      checkbox.nextElementSibling?.textContent?.trim() ||
      resourceId;
    if (resourceId && resourceName) {
      window.Admin.resourceMapping[resourceId] = resourceName;
    }
  });
};
