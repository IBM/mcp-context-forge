import { HEADER_NAME_REGEX } from './constants';
import { generateSchema } from './formFieldHandlers';
import { 
  safeParseJsonResponse,
  validateInputName, 
  validateJson, 
  validateUrl,
} from './security';
import { 
  isInactiveChecked, 
  safeGetElement, 
  showErrorMessage,
} from './utils'

// ===================================================================
// ENHANCED FORM HANDLERS with Input Validation
// ===================================================================

export const handleGatewayFormSubmit = async function (e) {
  e.preventDefault();
  
  const form = e.target;
  const formData = new FormData(form);
  const status = safeGetElement("status-gateways");
  const loading = safeGetElement("add-gateway-loading");
  
  try {
    // Validate form inputs
    const name = formData.get("name");
    const url = formData.get("url");
    
    const nameValidation = validateInputName(name, "gateway");
    const urlValidation = validateUrl(url);
    
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
    
    const isInactiveCheckedBool = isInactiveChecked("gateways");
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
        if (!HEADER_NAME_REGEX.test(headerName)) {
          showErrorMessage(
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
    const result = await safeParseJsonResponse(
      response,
      "Failed to add Gateway",
    );
    
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to add Gateway");
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
    showErrorMessage(error.message);
  } finally {
    if (loading) {
      loading.style.display = "none";
    }
  }
}

export const handleResourceFormSubmit = async function (e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const status = safeGetElement("status-resources");
  const loading = safeGetElement("add-resource-loading");
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
    
    const nameValidation = validateInputName(name, "resource");
    const uriValidation = validateInputName(uri, "resource URI");
    
    if (!nameValidation.valid) {
      showErrorMessage(nameValidation.error);
      return;
    }
    
    if (!uriValidation.valid) {
      showErrorMessage(uriValidation.error);
      return;
    }
    
    if (loading) {
      loading.style.display = "block";
    }
    if (status) {
      status.textContent = "";
      status.classList.remove("error-status");
    }
    
    const isInactiveCheckedBool = isInactiveChecked("resources");
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
    const result = await safeParseJsonResponse(
      response,
      "Failed to add Resource",
    );
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
    showErrorMessage(error.message);
  } finally {
    // location.reload();
    if (loading) {
      loading.style.display = "none";
    }
  }
}

export const handlePromptFormSubmit = async function (e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const status = safeGetElement("status-prompts");
  const loading = safeGetElement("add-prompts-loading");
  try {
    // Validate inputs
    const name = formData.get("name");
    const nameValidation = validateInputName(name, "prompt");
    
    if (!nameValidation.valid) {
      showErrorMessage(nameValidation.error);
      return;
    }
    
    if (loading) {
      loading.style.display = "block";
    }
    if (status) {
      status.textContent = "";
      status.classList.remove("error-status");
    }
    
    const isInactiveCheckedBool = isInactiveChecked("prompts");
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
    const result = await safeParseJsonResponse(
      response,
      "Failed to add Prompt",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to add Prompt");
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
    showErrorMessage(error.message);
  } finally {
    // location.reload();
    if (loading) {
      loading.style.display = "none";
    }
  }
}

export const handleEditPromptFormSubmit = async function (e) {
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
    const nameValidation = validateInputName(name, "prompt");
    if (!nameValidation.valid) {
      showErrorMessage(nameValidation.error);
      return;
    }
    
    // Save CodeMirror editors' contents if present
    if (window.promptToolHeadersEditor) {
      window.promptToolHeadersEditor.save();
    }
    if (window.promptToolSchemaEditor) {
      window.promptToolSchemaEditor.save();
    }
    
    const isInactiveCheckedBool = isInactiveChecked("prompts");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
    });
    
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit Prompt",
    );
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
    showErrorMessage(error.message);
  }
}

export const handleServerFormSubmit = async function (e) {
  e.preventDefault();
  
  const form = e.target;
  const formData = new FormData(form);
  const status = safeGetElement("serverFormError");
  const loading = safeGetElement("add-server-loading"); // Add a loading spinner if needed
  
  try {
    const name = formData.get("name");
    
    // Basic validation
    const nameValidation = validateInputName(name, "server");
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
    
    const isInactiveCheckedBool = isInactiveChecked("servers");
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
    const result = await safeParseJsonResponse(
      response,
      "Failed to add Server",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to add Server.");
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
    showErrorMessage(error.message); // Optional if you use global popup/snackbar
  } finally {
    if (loading) {
      loading.style.display = "none";
    }
  }
}

// Handle Add A2A Form Submit
export const handleA2AFormSubmit = async function (e) {
  e.preventDefault();
  
  const form = e.target;
  const formData = new FormData(form);
  const status = safeGetElement("a2aFormError");
  const loading = safeGetElement("add-a2a-loading");
  
  try {
    // Basic validation
    const name = formData.get("name");
    const nameValidation = validateInputName(name, "A2A Agent");
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
    
    const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
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
        if (!HEADER_NAME_REGEX.test(headerName)) {
          showErrorMessage(
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
    
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit A2A Agentt",
    );
    
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
    showErrorMessage(error.message); // global popup/snackbar if available
  } finally {
    if (loading) {
      loading.style.display = "none";
    }
  }
}

export const handleToolFormSubmit = async function (event) {
  event.preventDefault();
  
  try {
    const form = event.target;
    const formData = new FormData(form);
    
    // Validate form inputs
    const name = formData.get("name");
    const url = formData.get("url");
    
    const nameValidation = validateInputName(name, "tool");
    const urlValidation = validateUrl(url);
    
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
        const generatedSchema = generateSchema();
        const schemaValidation = validateJson(
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
    
    const isInactiveCheckedBool = isInactiveChecked("tools");
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
    const result = await safeParseJsonResponse(
      response,
      "Failed to add Tool",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to add Tool");
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
    showErrorMessage(error.message);
  }
}

export const handleEditToolFormSubmit = async function (event) {
  event.preventDefault();
  
  const form = event.target;
  
  try {
    const formData = new FormData(form);
    
    // Basic validation (customize as needed)
    const name = formData.get("name");
    const url = formData.get("url");
    const nameValidation = validateInputName(name, "tool");
    const urlValidation = validateUrl(url);
    
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
    
    const isInactiveCheckedBool = isInactiveChecked("tools");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit Tool",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to edit Tool");
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
    showErrorMessage(error.message);
  }
}

// Handle Gateway Edit Form
export const handleEditGatewayFormSubmit = async function (e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  try {
    // Validate form inputs
    const name = formData.get("name");
    const url = formData.get("url");
    
    const nameValidation = validateInputName(name, "gateway");
    const urlValidation = validateUrl(url);
    
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
      if (headerName && !HEADER_NAME_REGEX.test(headerName)) {
        showErrorMessage(
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
    
    const isInactiveCheckedBool = isInactiveChecked("gateways");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
    });
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit Gateway",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to edit Gateway");
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
    showErrorMessage(error.message);
  }
}

// Handle A2A Agent Edit Form
export const handleEditA2AAgentFormSubmit = async function (e) {
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
    const nameValidation = validateInputName(name, "a2a_agent");
    const urlValidation = validateUrl(url);
    
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
      if (headerName && !HEADER_NAME_REGEX.test(headerName)) {
        showErrorMessage(
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
    
    const isInactiveCheckedBool = isInactiveChecked("a2a-agents");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
    });
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit A2A Agent",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to edit A2A Agent");
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
    showErrorMessage(error.message);
  }
}

export const handleEditServerFormSubmit = async function (e) {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  
  try {
    // Validate inputs
    const name = formData.get("name");
    const nameValidation = validateInputName(name, "server");
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
    
    const isInactiveCheckedBool = isInactiveChecked("servers");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
    });
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit Server",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to edit Server");
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
    showErrorMessage(error.message);
  }
}

export const handleEditResFormSubmit = async function (e) {
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
    const nameValidation = validateInputName(name, "resource");
    const uriValidation = validateInputName(uri, "resource URI");
    
    if (!nameValidation.valid) {
      showErrorMessage(nameValidation.error);
      return;
    }
    
    if (!uriValidation.valid) {
      showErrorMessage(uriValidation.error);
      return;
    }
    
    // Save CodeMirror editors' contents if present
    if (window.promptToolHeadersEditor) {
      window.promptToolHeadersEditor.save();
    }
    if (window.promptToolSchemaEditor) {
      window.promptToolSchemaEditor.save();
    }
    
    const isInactiveCheckedBool = isInactiveChecked("resources");
    formData.append("is_inactive_checked", isInactiveCheckedBool);
    // Submit via fetch
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
    });
    
    const result = await safeParseJsonResponse(
      response,
      "Failed to edit Resource",
    );
    if (!result || !result.success) {
      throw new Error(result?.message || "Failed to edit Resource");
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
    showErrorMessage(error.message);
  }
}