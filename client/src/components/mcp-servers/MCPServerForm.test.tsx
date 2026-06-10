import { describe, it, expect, vi, beforeEach, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MCPServerForm } from "./MCPServerForm";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";

// Mock API responses for ExposeComponentsForm and gateway creation
const server = setupServer(
  http.get("/app/auth/me", () => {
    return HttpResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }),
  // Mock gateway creation
  http.post("/gateways", () => {
    return HttpResponse.json({ id: "test-gateway-123", name: "Test Server" });
  }),
  // Mock ExposeComponentsForm API calls
  http.get("/tools", () => {
    return HttpResponse.json([]);
  }),
  http.get("/resources", () => {
    return HttpResponse.json([]);
  }),
  http.get("/prompts", () => {
    return HttpResponse.json([]);
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

describe("MCPServerForm", () => {
  const defaultProps = {
    isOpen: true,
    onToggle: vi.fn(),
  };

  // Helper to render with router, i18n, and auth context
  const renderWithRouter = (ui: React.ReactElement) => {
    return render(
      <AuthProvider>
        <I18nProvider>
          <RouterProvider>{ui}</RouterProvider>
        </I18nProvider>
      </AuthProvider>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
    // Set initial path for router
    window.history.pushState({}, "", "/app/servers");
  });

  describe("Rendering", () => {
    it("should not render when isOpen is false", () => {
      renderWithRouter(<MCPServerForm isOpen={false} onToggle={defaultProps.onToggle} />);
      expect(screen.queryByText("Connect MCP server")).not.toBeInTheDocument();
    });

    it("should render when isOpen is true", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);
      expect(screen.getByText("Connect MCP server")).toBeInTheDocument();
    });

    it("should render all required form fields", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      expect(screen.getByLabelText("Streamable HTTP")).toBeInTheDocument();
      expect(screen.getByLabelText("SSE")).toBeInTheDocument();

      expect(screen.getByLabelText(/Name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/URL/i)).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/Add an optional description/i)).toBeInTheDocument();
      // advanced settings are not rendered by default
      expect(screen.queryByLabelText(/Visibility/i)).not.toBeInTheDocument();

      // action buttons
      expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Connect server/i })).toBeInTheDocument();
    });

    it("shows 'Save changes' submit button in edit mode", () => {
      renderWithRouter(<MCPServerForm isOpen={true} onToggle={vi.fn()} serverId="edit-123" />);
      expect(screen.getByRole("button", { name: /Save changes/i })).toBeInTheDocument();
    });

    it("should render link to server catalog", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const catalogLink = screen.getByRole("button", { name: /mcp server catalog/i });
      expect(catalogLink).toBeInTheDocument();
    });
  });

  describe("Transport Type Selection", () => {
    it("should have Streamable HTTP selected by default", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const streamableHttpRadio = screen.getByRole("radio", { name: /Streamable HTTP/i });
      expect(streamableHttpRadio).toBeChecked();
    });

    it("should allow switching to SSE transport", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const sseRadio = screen.getByRole("radio", { name: /SSE/i });
      await user.click(sseRadio);

      expect(sseRadio).toBeChecked();
    });
  });

  describe("Form Input Handling", () => {
    it("should update name field when typing", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const nameInput = screen.getByLabelText(/Name/i);
      await user.type(nameInput, "Test Server");

      expect(nameInput).toHaveValue("Test Server");
    });

    it("should update URL field when typing", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(urlInput, "http://localhost:3000");

      expect(urlInput).toHaveValue("http://localhost:3000");
    });

    it("should update description field when typing", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const descriptionInput = screen.getByPlaceholderText(/Add an optional description/i);
      await user.type(descriptionInput, "Test description");

      expect(descriptionInput).toHaveValue("Test description");
    });
  });

  describe("Advanced Settings", () => {
    it("should not show advanced settings by default", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      expect(screen.queryByText("Visibility")).not.toBeInTheDocument();
      expect(screen.queryByText("Authentication type")).not.toBeInTheDocument();
    });

    it("should toggle advanced settings when button is clicked", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(screen.getByText("Visibility")).toBeInTheDocument();
      expect(screen.getByText("Authentication type")).toBeInTheDocument();
    });

    it("should hide advanced settings when toggled again", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });

      // Open
      await user.click(advancedButton);
      expect(screen.getByText("Visibility")).toBeInTheDocument();

      // Close
      await user.click(advancedButton);
      await waitFor(() => {
        expect(screen.queryByText("Visibility")).not.toBeInTheDocument();
      });
    });

    it("should render AdvancedSettings component when expanded", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Check for advanced settings content
      expect(screen.getByText("Visibility")).toBeInTheDocument();
      expect(screen.getByText("Authentication type")).toBeInTheDocument();
      expect(screen.getByText("One-time authentication")).toBeInTheDocument();
      expect(screen.getByText("Passthrough headers")).toBeInTheDocument();
      expect(screen.getByText("CA certificate")).toBeInTheDocument();
    });
  });

  describe("Authentication Type Selection", () => {
    beforeEach(async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      // Open advanced settings
      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);
    });

    it("should have None authentication selected by default", () => {
      const noneRadio = screen.getByRole("radio", { name: /^None$/i });
      expect(noneRadio).toBeChecked();
    });

    it("should allow switching to Basic authentication", async () => {
      const user = userEvent.setup();

      const basicRadio = screen.getByRole("radio", { name: /Basic/i });
      await user.click(basicRadio);

      expect(basicRadio).toBeChecked();

      // Verify Basic auth fields are displayed
      expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    });

    it("should allow switching to Bearer Token authentication", async () => {
      const user = userEvent.setup();

      const bearerRadio = screen.getByRole("radio", { name: /Bearer token/i });
      await user.click(bearerRadio);

      expect(bearerRadio).toBeChecked();

      // Verify Bearer token field is displayed (use more specific selector)
      const bearerInput = screen.getByPlaceholderText(/Paste bearer token/i);
      expect(bearerInput).toBeInTheDocument();
    });

    it("should allow switching to Custom Headers authentication", async () => {
      const user = userEvent.setup();

      const customRadio = screen.getByRole("radio", { name: /Custom headers/i });
      await user.click(customRadio);

      expect(customRadio).toBeChecked();

      // Verify Custom headers section is displayed
      expect(
        screen.getByText(/Send one or more custom headers with every request/i),
      ).toBeInTheDocument();
    });

    it("should allow switching to OAuth 2.0 authentication", async () => {
      const user = userEvent.setup();

      const oauthRadio = screen.getByRole("radio", { name: /OAuth 2.0/i });
      await user.click(oauthRadio);

      expect(oauthRadio).toBeChecked();

      // Verify OAuth fields are displayed
      expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Client secret/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Token URL/i)).toBeInTheDocument();
    });

    it("should allow switching to Query Parameter authentication", async () => {
      const user = userEvent.setup();

      const queryRadio = screen.getByRole("radio", { name: /Query parameter/i });
      await user.click(queryRadio);

      expect(queryRadio).toBeChecked();

      // Verify Query parameter fields are displayed
      expect(screen.getByLabelText(/Query parameter name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/API key/i)).toBeInTheDocument();

      // Verify security warning is displayed
      expect(screen.getByText(/Security Warning:/i)).toBeInTheDocument();
    });

    it("should switch between authentication types correctly", async () => {
      const user = userEvent.setup();

      // Start with None
      const noneRadio = screen.getByRole("radio", { name: /^None$/i });
      expect(noneRadio).toBeChecked();

      // Switch to Basic
      const basicRadio = screen.getByRole("radio", { name: /Basic/i });
      await user.click(basicRadio);
      expect(basicRadio).toBeChecked();
      expect(noneRadio).not.toBeChecked();

      // Switch to Bearer
      const bearerRadio = screen.getByRole("radio", { name: /Bearer token/i });
      await user.click(bearerRadio);
      expect(bearerRadio).toBeChecked();
      expect(basicRadio).not.toBeChecked();

      // Switch to OAuth
      const oauthRadio = screen.getByRole("radio", { name: /OAuth 2.0/i });
      await user.click(oauthRadio);
      expect(oauthRadio).toBeChecked();
      expect(bearerRadio).not.toBeChecked();

      // Switch to Query Parameter
      const queryRadio = screen.getByRole("radio", { name: /Query parameter/i });
      await user.click(queryRadio);
      expect(queryRadio).toBeChecked();
      expect(oauthRadio).not.toBeChecked();

      // Switch to Custom Headers
      const customRadio = screen.getByRole("radio", { name: /Custom headers/i });
      await user.click(customRadio);
      expect(customRadio).toBeChecked();
      expect(queryRadio).not.toBeChecked();

      // Switch back to None
      await user.click(noneRadio);
      expect(noneRadio).toBeChecked();
      expect(customRadio).not.toBeChecked();
    });

    it("should display appropriate content for each authentication type", async () => {
      const user = userEvent.setup();

      // Test None - should show info message
      const noneRadio = screen.getByRole("radio", { name: /^None$/i });
      await user.click(noneRadio);
      expect(screen.getByText(/No credentials are required to connect/i)).toBeInTheDocument();

      // Test Basic - should show username and password fields
      const basicRadio = screen.getByRole("radio", { name: /Basic/i });
      await user.click(basicRadio);
      expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();

      // Test Bearer - should show token field
      const bearerRadio = screen.getByRole("radio", { name: /Bearer token/i });
      await user.click(bearerRadio);
      expect(screen.getByPlaceholderText(/Paste bearer token/i)).toBeInTheDocument();

      // Test Custom - should show add header button
      const customRadio = screen.getByRole("radio", { name: /Custom headers/i });
      await user.click(customRadio);
      expect(screen.getByRole("button", { name: /Add header/i })).toBeInTheDocument();

      // Test OAuth - should show OAuth fields
      const oauthRadio = screen.getByRole("radio", { name: /OAuth 2.0/i });
      await user.click(oauthRadio);
      expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Client secret/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/Token URL/i)).toBeInTheDocument();

      // Test Query Parameter - should show parameter name and API key fields
      const queryRadio = screen.getByRole("radio", { name: /Query parameter/i });
      await user.click(queryRadio);
      expect(screen.getByLabelText(/Query parameter name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/API key/i)).toBeInTheDocument();
    });

    it("should have proper accessibility attributes for authentication type radio group", () => {
      const radioGroup = screen.getByRole("radiogroup", { name: /Authentication type/i });
      expect(radioGroup).toBeInTheDocument();

      // Verify all radio buttons are in the group
      const radios = screen.getAllByRole("radio");
      const authRadios = radios.filter((radio) => radio.getAttribute("name") === "auth-type");

      expect(authRadios.length).toBe(6); // none, basic, bearer, custom, oauth, query
    });
  });

  describe("Form Submission", () => {
    it("should show ExposeComponentsForm after successful submission", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderWithRouter(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      // Fill in required fields
      const nameInput = screen.getByLabelText(/Name/i);
      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(nameInput, "Test Server");
      await user.type(urlInput, "http://localhost:3000");

      const submitButton = screen.getByRole("button", { name: /Connect server/i });
      await user.click(submitButton);

      // Should show ExposeComponentsForm instead of calling onToggle
      await waitFor(() => {
        expect(screen.getByText("Expose MCP tools, resources, and prompts")).toBeInTheDocument();
      });

      // onToggle should NOT be called immediately after submission
      expect(onToggle).not.toHaveBeenCalled();
    });

    it("should show ExposeComponentsForm with Skip and Expose buttons", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      // Fill in form
      const nameInput = screen.getByLabelText(/Name/i);
      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(nameInput, "Test Server");
      await user.type(urlInput, "http://localhost:3000");

      // Submit
      const submitButton = screen.getByRole("button", { name: /Connect server/i });
      await user.click(submitButton);

      // Should show ExposeComponentsForm with action buttons
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /skip/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /expose components/i })).toBeInTheDocument();
      });
    });

    it("should prevent default form submission", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      // Fill in required fields
      const nameInput = screen.getByLabelText(/Name/i);
      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(nameInput, "Test Server");
      await user.type(urlInput, "http://localhost:3000");

      const form = screen.getByRole("button", { name: /Connect server/i }).closest("form");
      const submitHandler = vi.fn((e) => e.preventDefault());

      if (form) {
        form.addEventListener("submit", submitHandler);
        const submitButton = screen.getByRole("button", { name: /Connect server/i });
        await user.click(submitButton);

        await waitFor(() => {
          expect(submitHandler).toHaveBeenCalled();
        });
      }
    });
  });

  describe("Cancel Button", () => {
    it("should call onToggle when cancel button is clicked", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderWithRouter(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      const cancelButton = screen.getByRole("button", { name: /Cancel/i });
      await user.click(cancelButton);

      expect(onToggle).toHaveBeenCalledTimes(1);
    });
  });

  describe("Server Catalog Navigation", () => {
    it("should navigate to server catalog when link is clicked", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderWithRouter(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      const catalogLink = screen.getByRole("button", { name: /mcp server catalog/i });
      await user.click(catalogLink);

      expect(onToggle).toHaveBeenCalledTimes(1);
      // Verify navigation by checking window location
      await waitFor(() => {
        expect(window.location.pathname).toBe("/app/server-catalog");
      });
    });
  });

  describe("Accessibility", () => {
    it("should have proper ARIA labels for transport type radio group", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const radioGroup = screen.getByRole("radiogroup", { name: /Server transport type/i });
      expect(radioGroup).toBeInTheDocument();
    });

    it("should have required indicators on required fields", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const nameLabel = screen.getByText(/Name/i).closest("label");
      const urlLabel = screen.getByText(/URL/i).closest("label");

      expect(nameLabel).toHaveTextContent("*");
      expect(urlLabel).toHaveTextContent("*");
    });

    it("should have screen reader text for required fields", () => {
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const srTexts = screen.getAllByText("(required)");
      expect(srTexts.length).toBeGreaterThan(0);
    });

    it("should have proper aria-expanded attribute on advanced settings button", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });

      expect(advancedButton).toHaveAttribute("aria-expanded", "false");

      await user.click(advancedButton);

      expect(advancedButton).toHaveAttribute("aria-expanded", "true");
    });
  });

  describe("Visual Feedback", () => {
    it("should rotate chevron icon when advanced settings are expanded", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      const chevron = advancedButton.querySelector("svg");

      expect(chevron).not.toHaveClass("rotate-180");

      await user.click(advancedButton);

      expect(chevron).toHaveClass("rotate-180");
    });
  });

  describe("Integration with Child Components", () => {
    it("should pass correct props to AdvancedSettings when expanded", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Verify AdvancedSettings is rendered with expected content
      expect(screen.getByText("Visibility")).toBeInTheDocument();
      expect(screen.getByText("Authentication type")).toBeInTheDocument();
    });
  });

  describe("Custom Headers Authentication", () => {
    // Helper: render the form with advanced settings open and Custom headers auth selected
    const renderWithCustomHeaders = async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);
      await user.click(screen.getByRole("button", { name: /Advanced settings/i }));
      await user.click(screen.getByRole("radio", { name: /Custom headers/i }));
      return user;
    };

    // Helper: click "Add header" the given number of times
    const addHeaders = async (user: ReturnType<typeof userEvent.setup>, count = 1) => {
      for (let i = 0; i < count; i++) {
        await user.click(screen.getByRole("button", { name: /Add header/i }));
      }
    };

    describe("Rendering", () => {
      it("shows the description text when Custom headers is selected", async () => {
        await renderWithCustomHeaders();
        expect(
          screen.getByText(/Send one or more custom headers with every request/i),
        ).toBeInTheDocument();
      });

      it("shows the Add header button", async () => {
        await renderWithCustomHeaders();
        expect(screen.getByRole("button", { name: /Add header/i })).toBeInTheDocument();
      });

      it("shows no header rows initially", async () => {
        await renderWithCustomHeaders();
        expect(screen.queryByRole("button", { name: /Remove/i })).not.toBeInTheDocument();
      });

      it("renders value inputs as type password to mask the value", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        const valueInput = screen.getByLabelText(/^Value/i);
        expect(valueInput).toHaveAttribute("type", "password");
      });

      it("renders key inputs as type text", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        const keyInput = screen.getByLabelText(/Header key/i);
        expect(keyInput).toHaveAttribute("type", "text");
      });
    });

    describe("Placeholder text", () => {
      it("shows the descriptive placeholder for key when there is exactly one header", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        expect(screen.getByPlaceholderText("e.g. X-API-Key...")).toBeInTheDocument();
      });

      it("shows the generic key placeholder when there are multiple headers", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user, 2);
        expect(screen.getAllByPlaceholderText("Add header key...")).toHaveLength(2);
        expect(screen.queryByPlaceholderText("e.g. X-API-Key...")).not.toBeInTheDocument();
      });

      it("shows the value placeholder on every row", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user, 2);
        expect(screen.getAllByPlaceholderText("Add header value...")).toHaveLength(2);
      });
    });

    describe("Adding headers", () => {
      it("adds a new empty row when Add header is clicked", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        expect(screen.getByLabelText(/Header key/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Remove/i })).toBeInTheDocument();
      });

      it("adds a second row when Add header is clicked again", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user, 2);
        expect(screen.getAllByLabelText(/Header key/i)).toHaveLength(2);
        expect(screen.getAllByRole("button", { name: /Remove/i })).toHaveLength(2);
      });
    });

    describe("Removing headers", () => {
      it("removes a row when Remove is clicked", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        await user.click(screen.getByRole("button", { name: /Remove/i }));
        expect(screen.queryByRole("button", { name: /Remove/i })).not.toBeInTheDocument();
      });

      it("keeps the remaining row after removing one of two", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user, 2);

        const keyInputs = screen.getAllByLabelText(/Header key/i);
        await user.type(keyInputs[0], "X-First");
        await user.type(keyInputs[1], "X-Second");

        const removeButtons = screen.getAllByRole("button", { name: /Remove/i });
        await user.click(removeButtons[0]);

        expect(screen.getAllByLabelText(/Header key/i)).toHaveLength(1);
        expect(screen.getByDisplayValue("X-Second")).toBeInTheDocument();
      });
    });

    describe("Editing header fields", () => {
      it("accepts typed input in the key field", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        await user.type(screen.getByLabelText(/Header key/i), "X-API-Key");
        expect(screen.getByDisplayValue("X-API-Key")).toBeInTheDocument();
      });

      it("accepts typed input in the value field", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        await user.type(screen.getByLabelText(/^Value/i), "secret-value");
        expect(screen.getByDisplayValue("secret-value")).toBeInTheDocument();
      });

      it("editing one row's key does not affect the other row", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user, 2);

        const keyInputs = screen.getAllByLabelText(/Header key/i);
        await user.type(keyInputs[1], "X-Second");

        expect(keyInputs[0]).toHaveValue("");
        expect(keyInputs[1]).toHaveValue("X-Second");
      });
    });

    describe("Accessibility", () => {
      it("marks the key label as required", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        const srTexts = screen.getAllByText("(required)");
        expect(srTexts.length).toBeGreaterThanOrEqual(2);
      });

      it("Add header button has type=button", async () => {
        await renderWithCustomHeaders();
        expect(screen.getByRole("button", { name: /Add header/i })).toHaveAttribute(
          "type",
          "button",
        );
      });

      it("Remove button has type=button", async () => {
        const user = await renderWithCustomHeaders();
        await addHeaders(user);
        expect(screen.getByRole("button", { name: /Remove/i })).toHaveAttribute("type", "button");
      });
    });
  });

  describe("OAuth Password Grant Validation", () => {
    // Helper: open advanced settings, switch to OAuth auth, select password grant
    const renderWithOAuthPassword = // pragma: allowlist secret
      async () => {
        const user = userEvent.setup();
        renderWithRouter(<MCPServerForm {...defaultProps} />);
        await user.click(screen.getByRole("button", { name: /Advanced settings/i }));
        await user.click(screen.getByRole("radio", { name: /OAuth 2\.0/i }));
        // Grant type defaults to client_credentials; switch to password
        await user.click(screen.getByRole("combobox", { name: /Grant type/i }));
        await user.click(screen.getByRole("option", { name: /Resource owner password/i }));
        return user;
      };

    it("shows username and password fields when password grant is selected", async () => {
      await renderWithOAuthPassword();
      expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^Password/i)).toBeInTheDocument();
    });

    it("disables the submit button when username is empty", async () => {
      const user = await renderWithOAuthPassword();
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      // Leave username empty, fill password
      await user.type(screen.getByLabelText(/^Password/i), "secret");
      expect(screen.getByRole("button", { name: /Connect server/i })).toBeDisabled();
    });

    it("disables the submit button when password is empty", async () => {
      const user = await renderWithOAuthPassword();
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      await user.type(screen.getByLabelText(/^Username/i), "service-account");
      // Leave password empty
      expect(screen.getByRole("button", { name: /Connect server/i })).toBeDisabled();
    });

    it("enables the submit button when both username and password are provided", async () => {
      const user = await renderWithOAuthPassword();
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      await user.type(screen.getByLabelText(/^Username/i), "service-account");
      await user.type(screen.getByLabelText(/^Password/i), "secret");
      expect(screen.getByRole("button", { name: /Connect server/i })).not.toBeDisabled();
    });

    it("marks username input as aria-invalid when username error is present", async () => {
      const user = await renderWithOAuthPassword();
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      // Only fill password, leave username empty
      await user.type(screen.getByLabelText(/^Password/i), "secret");

      // Temporarily type and clear username to expose the field without a value,
      // then attempt form submission via the form element directly
      const form = document.querySelector("form")!;
      fireEvent.submit(form);

      await waitFor(() => {
        expect(screen.getByLabelText(/^Username/i)).toHaveAttribute("aria-invalid", "true");
      });
    });

    it("marks password input as aria-invalid when password error is present", async () => {
      const user = await renderWithOAuthPassword();
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      await user.type(screen.getByLabelText(/^Username/i), "service-account");
      // Leave password empty, submit the form
      const form = document.querySelector("form")!;
      fireEvent.submit(form);

      await waitFor(() => {
        expect(screen.getByLabelText(/^Password/i)).toHaveAttribute("aria-invalid", "true");
      });
    });

    it("shows inline error messages for both fields when both are empty", async () => {
      await renderWithOAuthPassword();
      await userEvent.type(screen.getByLabelText(/^Name/i), "Test Server");
      await userEvent.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      fireEvent.submit(document.querySelector("form")!);

      await waitFor(() => {
        expect(screen.getByText("Username is required for password grant")).toBeInTheDocument();
        expect(screen.getByText("Password is required for password grant")).toBeInTheDocument();
      });
    });

    it("does not show password-grant errors when a different OAuth grant type is selected", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);
      await user.click(screen.getByRole("button", { name: /Advanced settings/i }));
      await user.click(screen.getByRole("radio", { name: /OAuth 2\.0/i }));
      // Leave on the default client_credentials grant
      await user.type(screen.getByLabelText(/Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      fireEvent.submit(document.querySelector("form")!);

      await waitFor(() => {
        expect(
          screen.queryByText("Username is required for password grant"),
        ).not.toBeInTheDocument();
        expect(
          screen.queryByText("Password is required for password grant"),
        ).not.toBeInTheDocument();
      });
    });

    it("does not show password-grant errors when auth type is not OAuth", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);
      await user.click(screen.getByRole("button", { name: /Advanced settings/i }));
      await user.click(screen.getByRole("radio", { name: /Basic/i }));
      await user.type(screen.getByLabelText(/^Name/i), "Test Server");
      await user.type(screen.getByLabelText(/^URL/i), "http://localhost:3000");
      fireEvent.submit(document.querySelector("form")!);

      await waitFor(() => {
        expect(
          screen.queryByText("Username is required for password grant"),
        ).not.toBeInTheDocument();
      });
    });
  });

  describe("CA Certificate Upload", () => {
    it("should render CA certificate upload section in advanced settings", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(screen.getByText("CA certificate")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Upload/i })).toBeInTheDocument();
    });

    it("should show file type information for CA certificate", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(
        screen.getByText(/Public certificate files only \(.pem, .crt, .cer, .cert\)/i),
      ).toBeInTheDocument();
    });

    it("should allow clicking upload button to trigger file selection", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      const uploadButton = screen.getByRole("button", { name: /Upload/i });
      expect(uploadButton).toBeInTheDocument();

      // Click should not throw error
      await user.click(uploadButton);
    });

    it("should handle file upload through drag and drop area", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Find the drag and drop area (contains the upload button)
      const uploadButton = screen.getByRole("button", { name: /Upload/i });
      const dropArea = uploadButton.closest("div[class*='cursor-pointer']");

      expect(dropArea).toBeInTheDocument();
    });

    it("should accept valid certificate file extensions", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Find the hidden file input
      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
      expect(fileInput).toBeInTheDocument();

      if (fileInput) {
        // Verify accepted file types
        expect(fileInput.accept).toContain(".pem");
        expect(fileInput.accept).toContain(".crt");
        expect(fileInput.accept).toContain(".cer");
        expect(fileInput.accept).toContain(".cert");

        // Verify multiple files are allowed
        expect(fileInput.multiple).toBe(true);
      }
    });

    it("should handle multiple certificate files", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
      expect(fileInput).toBeInTheDocument();

      if (fileInput) {
        // Create multiple mock files
        const file1 = new File(["cert1"], "cert1.pem", { type: "application/x-pem-file" });
        const file2 = new File(["cert2"], "cert2.crt", {
          type: "application/x-x509-ca-certificate",
        });

        // Simulate file selection
        Object.defineProperty(fileInput, "files", {
          value: [file1, file2],
          writable: false,
        });

        fireEvent.change(fileInput);

        // The component should handle multiple files
        await waitFor(() => {
          expect(fileInput.files?.length).toBe(2);
        });
      }
    });

    it("should handle CA certificate file selection without errors", async () => {
      const user = userEvent.setup();
      renderWithRouter(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;

      if (fileInput) {
        const file = new File(["cert"], "test.pem", { type: "application/x-pem-file" });

        Object.defineProperty(fileInput, "files", {
          value: [file],
          writable: false,
        });

        // File selection should not throw
        expect(() => fireEvent.change(fileInput)).not.toThrow();
      }
    });

    describe("OAuth Notifications", () => {
      it("should not display OAuth pending message by default", () => {
        renderWithRouter(<MCPServerForm {...defaultProps} />);
        expect(screen.queryByText(/Waiting for OAuth authorization/i)).not.toBeInTheDocument();
      });

      it("should not display OAuth notification by default", () => {
        renderWithRouter(<MCPServerForm {...defaultProps} />);
        expect(screen.queryByText(/OAuth authorization successful/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/OAuth authorization failed/i)).not.toBeInTheDocument();
      });

      it("should have submit button with default text when not in OAuth flow", () => {
        renderWithRouter(<MCPServerForm {...defaultProps} />);
        const submitButton = screen.getByRole("button", { name: /Connect server/i });
        expect(submitButton).toBeInTheDocument();
      });
    });
  });
});
