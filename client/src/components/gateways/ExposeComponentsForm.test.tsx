import { describe, it, expect, vi, beforeEach, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ExposeComponentsForm } from "./ExposeComponentsForm";
import { RouterProvider } from "@/router";
import { I18nProvider } from "@/i18n";

// Mock data - must match the API response format with id fields
const mockTools = [
  { id: "tool1", name: "tool1", displayName: "First tool" },
  { id: "tool2", name: "tool2", displayName: "Second tool" },
  { id: "tool3", name: "tool3", displayName: "Third tool" },
];

const mockResources = [
  { id: "resource1", name: "resource1", displayName: "First resource" },
  { id: "resource2", name: "resource2", displayName: "Second resource" },
];

const mockPrompts = [
  { id: "prompt1", name: "prompt1", displayName: "First prompt" },
  { id: "prompt2", name: "prompt2", displayName: "Second prompt" },
  { id: "prompt3", name: "prompt3", displayName: "Third prompt" },
];

// MSW server setup
const server = setupServer(
  http.get("/tools", ({ request }) => {
    const url = new URL(request.url);
    const gatewayId = url.searchParams.get("gateway_id");
    if (gatewayId === "test-gateway-123") {
      return HttpResponse.json(mockTools);
    }
    return HttpResponse.json([]);
  }),
  http.get("/resources", ({ request }) => {
    const url = new URL(request.url);
    const gatewayId = url.searchParams.get("gateway_id");
    if (gatewayId === "test-gateway-123") {
      return HttpResponse.json(mockResources);
    }
    return HttpResponse.json([]);
  }),
  http.get("/prompts", ({ request }) => {
    const url = new URL(request.url);
    const gatewayId = url.searchParams.get("gateway_id");
    if (gatewayId === "test-gateway-123") {
      return HttpResponse.json(mockPrompts);
    }
    return HttpResponse.json([]);
  }),
  http.post("/servers", () => {
    return HttpResponse.json({ id: "virtual-server-456" });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

describe("ExposeComponentsForm", () => {
  const defaultProps = {
    gatewayId: "test-gateway-123",
    gatewayName: "Test Gateway",
  };

  const renderWithProviders = (ui: React.ReactElement) => {
    return render(
      <I18nProvider>
        <RouterProvider>{ui}</RouterProvider>
      </I18nProvider>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, "", "/app/gateways");
  });

  describe("Rendering", () => {
    it("should render the form with title and description", async () => {
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("Expose MCP tools, resources, and prompts")).toBeInTheDocument();
      });

      expect(
        screen.getByText(/ContextForge will create an endpoint that exposes selected components/i),
      ).toBeInTheDocument();
    });

    it("should render action buttons", async () => {
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /skip/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /expose components/i })).toBeInTheDocument();
      });
    });

    it("should show loading state while fetching data", () => {
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      // Loading component uses aria-label instead of text
      expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    });

    it("should render component sections after loading", async () => {
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
        expect(screen.getByText("2 resources")).toBeInTheDocument();
        expect(screen.getByText("3 prompt templates")).toBeInTheDocument();
      });
    });
  });

  describe("OAuth Toggle", () => {
    it("should render OAuth toggle switch", async () => {
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("Require OAuth for inbound clients")).toBeInTheDocument();
      });

      const toggle = screen.getByRole("switch");
      expect(toggle).toBeInTheDocument();
      expect(toggle).not.toBeChecked();
    });

    it("should toggle OAuth switch when clicked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("switch")).toBeInTheDocument();
      });

      const toggle = screen.getByRole("switch");
      await user.click(toggle);

      expect(toggle).toBeChecked();
    });
  });

  describe("Component Selection", () => {
    it("should allow selecting tools", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      // Wait for data to load
      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
      });

      // Expand tools section - tools section is expanded by default
      // Wait for table to appear
      await waitFor(() => {
        const displayNames = screen.queryAllByText("First tool");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      // Select first tool using aria-label
      const firstToolCheckbox = screen.getByRole("checkbox", { name: /select first tool/i });
      await user.click(firstToolCheckbox);

      expect(firstToolCheckbox).toBeChecked();
    });

    it("should allow selecting resources", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("2 resources")).toBeInTheDocument();
      });

      // Expand resources section
      const resourcesButton = screen.getByRole("button", { name: /2 resources/i });
      await user.click(resourcesButton);

      await waitFor(() => {
        const displayNames = screen.queryAllByText("First resource");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      // Select first resource using aria-label
      const firstResourceCheckbox = screen.getByRole("checkbox", {
        name: /select first resource/i,
      });
      await user.click(firstResourceCheckbox);

      expect(firstResourceCheckbox).toBeChecked();
    });

    it("should allow selecting prompts", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("3 prompt templates")).toBeInTheDocument();
      });

      // Expand prompts section
      const promptsButton = screen.getByRole("button", { name: /3 prompt templates/i });
      await user.click(promptsButton);

      await waitFor(() => {
        const displayNames = screen.queryAllByText("First prompt");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      // Select first prompt using aria-label
      const firstPromptCheckbox = screen.getByRole("checkbox", { name: /select first prompt/i });
      await user.click(firstPromptCheckbox);

      expect(firstPromptCheckbox).toBeChecked();
    });

    it("should allow selecting multiple components", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
      });

      // Tools section is expanded by default, wait for table
      await waitFor(() => {
        const displayNames = screen.queryAllByText("First tool");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      const tool1Checkbox = screen.getByRole("checkbox", { name: /select first tool/i });
      const tool2Checkbox = screen.getByRole("checkbox", { name: /select second tool/i });

      await user.click(tool1Checkbox);
      await user.click(tool2Checkbox);

      expect(tool1Checkbox).toBeChecked();
      expect(tool2Checkbox).toBeChecked();
    });
  });

  describe("Form Submission", () => {
    it("should create virtual server with selected components", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
      });

      // Tools section is expanded by default, wait for table
      await waitFor(() => {
        const displayNames = screen.queryAllByText("First tool");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      const tool1Checkbox = screen.getByRole("checkbox", { name: /select first tool/i });
      await user.click(tool1Checkbox);

      // Submit form
      const exposeButton = screen.getByRole("button", { name: /expose components/i });
      await user.click(exposeButton);

      // Should navigate after successful creation
      await waitFor(() => {
        expect(window.location.pathname).toBe("/app/gateways");
      });
    });

    it("should create virtual server with OAuth enabled", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("switch")).toBeInTheDocument();
      });

      // Enable OAuth
      const toggle = screen.getByRole("switch");
      await user.click(toggle);

      // Submit form
      const exposeButton = screen.getByRole("button", { name: /expose components/i });
      await user.click(exposeButton);

      await waitFor(() => {
        expect(window.location.pathname).toBe("/app/gateways");
      });
    });

    it("should disable submit button while creating", async () => {
      // Delay the server response to test the loading state
      server.use(
        http.post("/servers", async () => {
          await new Promise((resolve) => setTimeout(resolve, 100));
          return HttpResponse.json({ id: "virtual-server-456" });
        }),
      );

      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /expose components/i })).toBeInTheDocument();
      });

      const exposeButton = screen.getByRole("button", { name: /expose components/i });
      await user.click(exposeButton);

      // Button should be disabled during creation
      await waitFor(() => {
        expect(exposeButton).toBeDisabled();
      });
    });

    it("should show error message on creation failure", async () => {
      server.use(
        http.post("/servers", () => {
          return HttpResponse.json({ error: "Failed to create server" }, { status: 500 });
        }),
      );

      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /expose components/i })).toBeInTheDocument();
      });

      const exposeButton = screen.getByRole("button", { name: /expose components/i });
      await user.click(exposeButton);

      // Error message should appear
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });
  });

  describe("Skip Action", () => {
    it("should navigate to gateways page when skip is clicked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /skip/i })).toBeInTheDocument();
      });

      const skipButton = screen.getByRole("button", { name: /skip/i });
      await user.click(skipButton);

      expect(window.location.pathname).toBe("/app/gateways");
    });

    it("should skip without confirmation dialog when components are selected", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("3 tools")).toBeInTheDocument();
      });

      // Wait for tools table to be visible (tools section is expanded by default)
      await waitFor(() => {
        const displayNames = screen.queryAllByText("First tool");
        expect(displayNames.length).toBeGreaterThan(0);
      });

      // Select some components
      const tool1Checkbox = screen.getByRole("checkbox", { name: /select first tool/i });
      const tool2Checkbox = screen.getByRole("checkbox", { name: /select second tool/i });
      await user.click(tool1Checkbox);
      await user.click(tool2Checkbox);

      expect(tool1Checkbox).toBeChecked();
      expect(tool2Checkbox).toBeChecked();

      // Click skip button
      const skipButton = screen.getByRole("button", { name: /skip/i });
      await user.click(skipButton);

      // Should navigate immediately without showing any confirmation dialog
      expect(window.location.pathname).toBe("/app/gateways");

      // Verify no confirmation dialog appeared (no dialog role elements)
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

      // Verify no confirmation text appeared
      expect(screen.queryByText(/are you sure/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/discard/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/lose.*changes/i)).not.toBeInTheDocument();
    });
  });

  describe("OAuth Notification", () => {
    it("should display OAuth notification when provided", async () => {
      const oauthNotification = {
        type: "success" as const,
        message: "OAuth configured successfully",
      };

      renderWithProviders(
        <ExposeComponentsForm
          {...defaultProps}
          oauthNotification={oauthNotification}
          clearOAuthNotification={vi.fn()}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText("OAuth configured successfully")).toBeInTheDocument();
      });
    });

    it("should call clearOAuthNotification when notification is dismissed", async () => {
      const clearOAuthNotification = vi.fn();
      const oauthNotification = {
        type: "success" as const,
        message: "OAuth configured successfully",
      };

      const user = userEvent.setup();
      renderWithProviders(
        <ExposeComponentsForm
          {...defaultProps}
          oauthNotification={oauthNotification}
          clearOAuthNotification={clearOAuthNotification}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText("OAuth configured successfully")).toBeInTheDocument();
      });

      // Find and click the dismiss button
      const dismissButton = screen.getByRole("button", { name: /dismiss/i });
      await user.click(dismissButton);

      expect(clearOAuthNotification).toHaveBeenCalledTimes(1);
    });
  });

  describe("Empty State", () => {
    it("should handle empty tools list", async () => {
      server.use(
        http.get("/tools", () => {
          return HttpResponse.json([]);
        }),
      );

      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("0 tools")).toBeInTheDocument();
      });
    });

    it("should handle empty resources list", async () => {
      server.use(
        http.get("/resources", () => {
          return HttpResponse.json([]);
        }),
      );

      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("0 resources")).toBeInTheDocument();
      });
    });

    it("should handle empty prompts list", async () => {
      server.use(
        http.get("/prompts", () => {
          return HttpResponse.json([]);
        }),
      );

      renderWithProviders(<ExposeComponentsForm {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByText("0 prompt templates")).toBeInTheDocument();
      });
    });
  });
});
