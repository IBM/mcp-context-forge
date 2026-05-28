/**
 * Contextual Help System for Admin UI
 *
 * Provides comprehensive help mechanisms:
 * - Tooltips on form fields, buttons, table columns
 * - Help icons (?) with expanded explanations
 * - Inline hints below form fields
 * - Keyboard shortcuts overlay
 * - Actionable error messages
 */

import { safeGetElement } from "./utils.js";

import { HelpDatabase as GeneratedHelpDatabase } from "./helpDatabase.generated.js";


const ManualHelpDatabase  = {
  // Server fields
  "edit-server-name": {
    tooltip: "📝 Unique identifier for this MCP server",
    expanded:
      "Server Name: A user-friendly name to identify this MCP server. Used in logs, dashboards, and UI. Must be unique within your platform.",
    hint: "Choose a descriptive name (e.g., 'Production Git', 'Dev Data API')",
    example: "my-mcp-server",
  },
  "edit-server-url": {
    tooltip: "🔗 The endpoint URL for this MCP server",
    expanded:
      "Server URL: Complete endpoint URL including protocol and port. This is where the MCP server is running and accepting connections.",
    hint: "Include protocol (http/https) and port. Example: http://localhost:9000",
    example: "http://localhost:9000",
    related: ["edit-server-name", "test-server"],
  },
  "edit-server-description": {
    tooltip: "📄 Optional description of what this server does",
    expanded:
      "Description: Brief explanation of server purpose, capabilities, or important notes. Visible in server listings and details.",
    hint: "Keep it concise (100 chars recommended)",
    example: "Git repository management server for version control",
  },
  "edit-server-tags": {
    tooltip: "🏷️ Categorize servers with comma-separated tags",
    expanded:
      "Tags: Help organize and filter servers by category. Comma-separated values, automatically normalized to lowercase with hyphens.",
    hint: "Example: production, external, git",
    example: "production,external,git",
  },
  "edit-server-visibility": {
    tooltip: "👁️ Control who can see and access this server",
    expanded:
      "Visibility: Choose between Public (everyone), Team (team members only), or Private (you only). RBAC (Role-Based Access Control) still applies.",
    hint: "Public = visible to all; Team = visible to team members; Private = you only",
  },
  "edit-server-icon": {
    tooltip: "🖼️ Optional icon URL for visual identification",
    expanded: "Icon URL: Public URL to an image (PNG, SVG recommended). Used in server listings and navigation.",
    hint: "Use HTTPS URLs. Recommended size: 64x64px",
    example: "https://example.com/icons/server.png",
  },

  // Tool fields
  "edit-tool-name": {
    tooltip: "📝 Unique identifier for this tool",
    expanded: "Tool Name: A unique, descriptive name. Used in API calls, logs, and documentation.",
    hint: "Use lowercase with hyphens, no spaces",
    example: "git-clone-repo",
  },
  "edit-tool-url": {
    tooltip: "🔗 REST endpoint URL for this tool",
    expanded:
      "Tool URL: The HTTP endpoint that implements this tool's functionality. Must be accessible and respond to configured HTTP method.",
    hint: "Example: https://api.example.com/tools/deploy",
    example: "https://api.example.com/tools/deploy",
  },

  // Gateway fields
  "gateway-name": {
    tooltip: "📝 Name of this MCP gateway instance",
    expanded:
      "Gateway Name: Identifies this federation point or proxy node. Used in logs, monitoring, and distributed architecture.",
    hint: "Example: 'us-east-gateway', 'prod-federation-node'",
  },
  "gateway-url": {
    tooltip: "🔗 Gateway endpoint URL",
    expanded: "Gateway URL: The base URL where this gateway serves requests (SSE, WebSocket, HTTP).",
    hint: "Include protocol and port. Example: http://localhost:8000",
  },

  // Resource fields
  "resource-name": {
    tooltip: "📝 Name of this reusable data asset",
    expanded: "Resource Name: Human-readable name for this asset. Use for documentation and discovery.",
    hint: "Example: 'config.yaml', 'api-keys', 'schema-v2'",
  },
  "resource-uri": {
    tooltip: "🔗 URI or URL pointing to this resource",
    expanded:
      "Resource URI: Where the resource is stored (file, HTTP URL, S3 path, or inline text). Used for retrieval and updates.",
    hint: "Format depends on resource type (HTTP URL, file path, etc)",
  },

  // Prompt fields
  "prompt-name": {
    tooltip: "📝 Reusable prompt template name",
    expanded: "Prompt Name: Identifier for this message template. Used when selecting prompts in flows.",
    hint: "Example: 'summarize-code', 'review-pr-template'",
  },
  "prompt-content": {
    tooltip: "✍️ The template content with {{parameters}}",
    expanded:
      "Prompt Content: Template text with {{variable}} placeholders. At runtime, parameters are substituted. Supports Jinja2-like syntax.",
    hint: "Use {{param}} for dynamic values. Example: 'Review this {{language}} code: {{code}}'",
  },

  // Common actions
  "action-edit": {
    tooltip: "✏️ Edit this item's settings",
    expanded:
      "Edit: Opens a form to modify item properties. Changes are saved to the database when you submit.",
  },
  "action-view": {
    tooltip: "👁️ View detailed information",
    expanded:
      "View: Opens a detailed view with full information, configuration, and metadata. Read-only.",
  },
  "action-delete": {
    tooltip: "🗑️ Permanently delete this item",
    expanded:
      "Delete: ⚠️ IRREVERSIBLE. This item and all associated data will be permanently removed from the system.",
    hint: "Confirm carefully. This action cannot be undone.",
  },
  "action-test": {
    tooltip: "🧪 Test connection or functionality",
    expanded:
      "Test: Verifies that the configured resource is accessible and responsive. Results show in a modal.",
  },
  "action-toggle": {
    tooltip: "⚠️ Temporarily disable (can be re-enabled later)",
    expanded:
      "Disable: Temporarily deactivate this item. It remains in the database but is no longer active or available. Re-enable at any time.",
  },

  // Error context
  "error-required-field": {
    hint: "This field is required. Enter a value before submitting.",
  },
  "error-invalid-url": {
    hint: "URL must start with http:// or https:// and be valid.",
  },
  "error-duplicate-name": {
    hint: "A resource with this name already exists. Choose a unique name.",
  },
};

/**
 * Help content database
 * Structure: { fieldId: { tooltip, expanded, hint, example, related } }
 */
export const HelpDatabase = {
  ...GeneratedHelpDatabase,
  ...ManualHelpDatabase,
};

/**
 * Keyboard shortcuts
 */
export const KeyboardShortcuts = [
  { key: "?", action: "Show this help overlay" },
  { key: "Esc", action: "Close any open modal or overlay" },
  { key: "Ctrl+S", action: "Submit active form (if applicable)" },
  { key: "Ctrl+K", action: "Open global search" },
  { key: "Tab", action: "Navigate between form fields" },
  { key: "Enter", action: "Submit form or activate button" },
  { key: "Space", action: "Toggle checkbox or open dropdown" },
  { key: "Ctrl+C", action: "Copy to clipboard (on copy buttons)" },
];

/**
 * Initialize contextual help system
 */
export function initializeContextualHelp() {
  setupHelpIcons();
  setupInlineHints();
  setupKeyboardShortcutsListener();
  attachHelpErrorMessages();
  console.log("✅ Contextual help system initialized");
}

/**
 * Setup "?" help icons on form fields
 */
function setupHelpIcons() {
  const labels = document.querySelectorAll("label");
  labels.forEach((label) => {
    const fieldName = label.getAttribute("for") || label.querySelector("input")?.id;
    const helpData = fieldName && HelpDatabase[fieldName];

    if (helpData && helpData.expanded) {
      const helpIcon = document.createElement("button");
      helpIcon.type = "button";
      helpIcon.className =
        "ml-1 inline-flex items-center justify-center w-5 h-5 rounded-full " +
        "bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-900 dark:text-blue-300 " +
        "text-xs font-bold cursor-pointer transition-colors";
      helpIcon.title = "Click for help";
      helpIcon.textContent = "?";
      helpIcon.dataset.helpField = fieldName;

      helpIcon.addEventListener("click", (e) => {
        e.preventDefault();
        showExpandedHelp(fieldName);
      });

      label.appendChild(helpIcon);
    }
  });
}

/**
 * Setup inline hints below form fields
 */
function setupInlineHints() {
  Object.entries(HelpDatabase).forEach(([fieldId, data]) => {
    if (!data.hint) return;

    const field = safeGetElement(fieldId);
    if (!field) return;

    // Check if hint already exists
    if (field.nextElementSibling?.classList.contains("help-inline-hint")) return;

    const hintEl = document.createElement("p");
    hintEl.className =
      "help-inline-hint mt-1 text-xs text-gray-500 dark:text-gray-400 italic";
    hintEl.textContent = data.hint;

    if (data.example) {
      hintEl.textContent += ` (e.g., ${data.example})`;
    }

    field.parentNode?.insertBefore(hintEl, field.nextSibling);
  });
}

/**
 * Show expanded help modal for a field
 */
export function showExpandedHelp(fieldId) {
  const data = HelpDatabase[fieldId];
  if (!data || !data.expanded) return;

  const modal = document.createElement("div");
  modal.className =
    "fixed inset-0 z-50 bg-black bg-opacity-50 dark:bg-opacity-70 " +
    "flex items-center justify-center p-4";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "help-modal-title");

  const content = document.createElement("div");
  content.className =
    "bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-md w-full " +
    "p-6 max-h-96 overflow-y-auto";

  // Title
  const title = document.createElement("h3");
  title.id = "help-modal-title";
  title.className = "text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3";
  title.textContent = `Help: ${fieldId}`;

  // Expanded explanation
  const explanation = document.createElement("p");
  explanation.className = "text-sm text-gray-700 dark:text-gray-300 mb-4 leading-relaxed";
  explanation.textContent = data.expanded;

  // Additional sections
  const sections = [];

  if (data.hint) {
    const hintSection = document.createElement("div");
    hintSection.className = "mb-4 p-3 bg-blue-50 dark:bg-blue-900 rounded";
    const hintLabel = document.createElement("p");
    hintLabel.className = "text-xs font-semibold text-blue-900 dark:text-blue-200 mb-1";
    hintLabel.textContent = "💡 Hint:";
    const hintText = document.createElement("p");
    hintText.className = "text-xs text-blue-800 dark:text-blue-300";
    hintText.textContent = data.hint;
    hintSection.appendChild(hintLabel);
    hintSection.appendChild(hintText);
    sections.push(hintSection);
  }

  if (data.example) {
    const exampleSection = document.createElement("div");
    exampleSection.className = "mb-4 p-3 bg-gray-50 dark:bg-gray-700 rounded font-mono";
    const exampleLabel = document.createElement("p");
    exampleLabel.className = "text-xs font-semibold text-gray-900 dark:text-gray-100 mb-1";
    exampleLabel.textContent = "Example:";
    const exampleText = document.createElement("p");
    exampleText.className = "text-xs text-gray-700 dark:text-gray-300 break-all";
    exampleText.textContent = data.example;
    exampleSection.appendChild(exampleLabel);
    exampleSection.appendChild(exampleText);
    sections.push(exampleSection);
  }

  // Close button
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className =
    "mt-4 w-full px-4 py-2 bg-indigo-600 hover:bg-indigo-700 " +
    "text-white text-sm rounded font-medium transition-colors";
  closeBtn.textContent = "Got it";

  closeBtn.addEventListener("click", () => {
    modal.remove();
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });

  document.addEventListener("keydown", function closeOnEscape(e) {
    if (e.key === "Escape") {
      modal.remove();
      document.removeEventListener("keydown", closeOnEscape);
    }
  });

  content.appendChild(title);
  content.appendChild(explanation);
  sections.forEach((s) => content.appendChild(s));
  content.appendChild(closeBtn);

  modal.appendChild(content);
  document.body.appendChild(modal);
}

/**
 * Setup keyboard shortcuts listener (? key)
 */
function setupKeyboardShortcutsListener() {
  document.addEventListener("keydown", (e) => {
    // Show shortcuts on "?" or "Shift+?" (/)
    if (e.key === "?" || (e.shiftKey && e.key === "/")) {
      e.preventDefault();
      showKeyboardShortcuts();
    }
  });
}

/**
 * Show keyboard shortcuts overlay
 */
function showKeyboardShortcuts() {
  const existing = document.getElementById("help-keyboard-shortcuts");
  if (existing) {
    existing.remove();
    return;
  }

  const modal = document.createElement("div");
  modal.id = "help-keyboard-shortcuts";
  modal.className =
    "fixed inset-0 z-50 bg-black bg-opacity-50 dark:bg-opacity-70 " +
    "flex items-center justify-center p-4";

  const content = document.createElement("div");
  content.className =
    "bg-white dark:bg-gray-800 rounded-lg shadow-lg max-w-sm w-full " +
    "p-6 max-h-96 overflow-y-auto";

  const title = document.createElement("h3");
  title.className = "text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4";
  title.textContent = "⌨️ Keyboard Shortcuts";

  const table = document.createElement("table");
  table.className = "w-full text-sm";
  table.innerHTML = KeyboardShortcuts.map(
    (sc) =>
      `<tr class="border-b border-gray-200 dark:border-gray-700">
         <td class="py-2 pr-4 font-mono font-semibold text-indigo-600 dark:text-indigo-400">${sc.key}</td>
         <td class="py-2 text-gray-700 dark:text-gray-300">${sc.action}</td>
       </tr>`
  ).join("");

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className =
    "mt-4 w-full px-4 py-2 bg-gray-200 dark:bg-gray-700 " +
    "text-gray-900 dark:text-gray-100 text-sm rounded font-medium";
  closeBtn.textContent = "Close (Esc)";

  const close = () => modal.remove();
  closeBtn.addEventListener("click", close);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });

  document.addEventListener("keydown", function closeOnEscape(e) {
    if (e.key === "Escape") {
      close();
      document.removeEventListener("keydown", closeOnEscape);
    }
  });

  content.appendChild(title);
  content.appendChild(table);
  content.appendChild(closeBtn);
  modal.appendChild(content);
  document.body.appendChild(modal);
}

/**
 * Attach help messages to form validation errors
 */
function attachHelpErrorMessages() {
  document.addEventListener("invalid", (e) => {
    const field = e.target;
    if (field.validity.valueMissing) {
      field.setAttribute("title", HelpDatabase["error-required-field"]?.hint || "This field is required");
    }
  });
}

/**
 * Get help text for a field (for programmatic use)
 */
export function getHelpText(fieldId, type = "tooltip") {
  const data = HelpDatabase[fieldId];
  return data ? data[type] || "" : "";
}

export default {
  initializeContextualHelp,
  showExpandedHelp,
  showKeyboardShortcuts,
  getHelpText,
  HelpDatabase,
  KeyboardShortcuts,
};
