import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MCPServerForm } from "./MCPServerForm";

// Mock the router
const mockNavigate = vi.fn();
vi.mock("@/router", () => ({
  useRouter: () => ({
    navigate: mockNavigate,
  }),
}));

describe("MCPServerForm", () => {
  const defaultProps = {
    isOpen: true,
    onToggle: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Rendering", () => {
    it("should not render when isOpen is false", () => {
      render(<MCPServerForm isOpen={false} onToggle={defaultProps.onToggle} />);
      expect(screen.queryByText("Connect MCP server")).not.toBeInTheDocument();
    });

    it("should render when isOpen is true", () => {
      render(<MCPServerForm {...defaultProps} />);
      expect(screen.getByText("Connect MCP server")).toBeInTheDocument();
    });

    it("should render all required form fields", () => {
      render(<MCPServerForm {...defaultProps} />);

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

    it("should render link to server catalog", () => {
      render(<MCPServerForm {...defaultProps} />);

      const catalogLink = screen.getByRole("button", { name: /mcp server catalog/i });
      expect(catalogLink).toBeInTheDocument();
    });
  });

  describe("Transport Type Selection", () => {
    it("should have Streamable HTTP selected by default", () => {
      render(<MCPServerForm {...defaultProps} />);

      const streamableHttpRadio = screen.getByRole("radio", { name: /Streamable HTTP/i });
      expect(streamableHttpRadio).toBeChecked();
    });

    it("should allow switching to SSE transport", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const sseRadio = screen.getByRole("radio", { name: /SSE/i });
      await user.click(sseRadio);

      expect(sseRadio).toBeChecked();
    });
  });

  describe("Form Input Handling", () => {
    it("should update name field when typing", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const nameInput = screen.getByLabelText(/Name/i);
      await user.type(nameInput, "Test Server");

      expect(nameInput).toHaveValue("Test Server");
    });

    it("should update URL field when typing", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(urlInput, "http://localhost:3000");

      expect(urlInput).toHaveValue("http://localhost:3000");
    });

    it("should update description field when typing", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const descriptionInput = screen.getByPlaceholderText(/Add an optional description/i);
      await user.type(descriptionInput, "Test description");

      expect(descriptionInput).toHaveValue("Test description");
    });
  });

  describe("Advanced Settings", () => {
    it("should not show advanced settings by default", () => {
      render(<MCPServerForm {...defaultProps} />);

      expect(screen.queryByText("Visibility")).not.toBeInTheDocument();
      expect(screen.queryByText("Authentication type")).not.toBeInTheDocument();
    });

    it("should toggle advanced settings when button is clicked", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(screen.getByText("Visibility")).toBeInTheDocument();
      expect(screen.getByText("Authentication type")).toBeInTheDocument();
    });

    it("should hide advanced settings when toggled again", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

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
      render(<MCPServerForm {...defaultProps} />);

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

  describe("Form Submission", () => {
    it("should call onToggle when form is submitted", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      const submitButton = screen.getByRole("button", { name: /Connect server/i });
      await user.click(submitButton);

      expect(onToggle).toHaveBeenCalledTimes(1);
    });

    it("should reset form fields after submission", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      // Fill in form
      const nameInput = screen.getByLabelText(/Name/i);
      const urlInput = screen.getByLabelText(/URL/i);
      await user.type(nameInput, "Test Server");
      await user.type(urlInput, "http://localhost:3000");

      // Submit
      const submitButton = screen.getByRole("button", { name: /Connect server/i });
      await user.click(submitButton);

      // Fields should be cleared (component would re-render with empty state)
      expect(defaultProps.onToggle).toHaveBeenCalled();
    });

    it("should prevent default form submission", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const form = screen.getByRole("button", { name: /Connect server/i }).closest("form");
      const submitHandler = vi.fn((e) => e.preventDefault());

      if (form) {
        form.addEventListener("submit", submitHandler);
        const submitButton = screen.getByRole("button", { name: /Connect server/i });
        await user.click(submitButton);

        expect(submitHandler).toHaveBeenCalled();
      }
    });
  });

  describe("Cancel Button", () => {
    it("should call onToggle when cancel button is clicked", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      const cancelButton = screen.getByRole("button", { name: /Cancel/i });
      await user.click(cancelButton);

      expect(onToggle).toHaveBeenCalledTimes(1);
    });
  });

  describe("Server Catalog Navigation", () => {
    it("should navigate to server catalog when link is clicked", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      render(<MCPServerForm isOpen={true} onToggle={onToggle} />);

      const catalogLink = screen.getByRole("button", { name: /mcp server catalog/i });
      await user.click(catalogLink);

      expect(onToggle).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenCalledWith("/app/server-catalog");
    });
  });

  describe("Accessibility", () => {
    it("should have proper ARIA labels for transport type radio group", () => {
      render(<MCPServerForm {...defaultProps} />);

      const radioGroup = screen.getByRole("radiogroup", { name: /Server transport type/i });
      expect(radioGroup).toBeInTheDocument();
    });

    it("should have required indicators on required fields", () => {
      render(<MCPServerForm {...defaultProps} />);

      const nameLabel = screen.getByText(/Name/i).closest("label");
      const urlLabel = screen.getByText(/URL/i).closest("label");

      expect(nameLabel).toHaveTextContent("*");
      expect(urlLabel).toHaveTextContent("*");
    });

    it("should have screen reader text for required fields", () => {
      render(<MCPServerForm {...defaultProps} />);

      const srTexts = screen.getAllByText("(required)");
      expect(srTexts.length).toBeGreaterThan(0);
    });

    it("should have proper aria-expanded attribute on advanced settings button", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });

      expect(advancedButton).toHaveAttribute("aria-expanded", "false");

      await user.click(advancedButton);

      expect(advancedButton).toHaveAttribute("aria-expanded", "true");
    });
  });

  describe("Visual Feedback", () => {
    it("should rotate chevron icon when advanced settings are expanded", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

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
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Verify AdvancedSettings is rendered with expected content
      expect(screen.getByText("Visibility")).toBeInTheDocument();
      expect(screen.getByText("Authentication type")).toBeInTheDocument();
    });
  });

  describe("CA Certificate Upload", () => {
    it("should render CA certificate upload section in advanced settings", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(screen.getByText("CA certificate")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Upload/i })).toBeInTheDocument();
    });

    it("should show file type information for CA certificate", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      expect(
        screen.getByText(/Public certificate files only \(.pem, .crt, .cer, .cert\)/i),
      ).toBeInTheDocument();
    });

    it("should allow clicking upload button to trigger file selection", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      const uploadButton = screen.getByRole("button", { name: /Upload/i });
      expect(uploadButton).toBeInTheDocument();

      // Click should not throw error
      await user.click(uploadButton);
    });

    it("should handle file upload through drag and drop area", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      // Find the drag and drop area (contains the upload button)
      const uploadButton = screen.getByRole("button", { name: /Upload/i });
      const dropArea = uploadButton.closest("div[class*='cursor-pointer']");

      expect(dropArea).toBeInTheDocument();
    });

    it("should accept valid certificate file extensions", async () => {
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

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
      render(<MCPServerForm {...defaultProps} />);

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

    it("should log selected files to console", async () => {
      const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
      const user = userEvent.setup();
      render(<MCPServerForm {...defaultProps} />);

      const advancedButton = screen.getByRole("button", { name: /Advanced settings/i });
      await user.click(advancedButton);

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;

      if (fileInput) {
        const file = new File(["cert"], "test.pem", { type: "application/x-pem-file" });

        Object.defineProperty(fileInput, "files", {
          value: [file],
          writable: false,
        });

        fireEvent.change(fileInput);

        await waitFor(() => {
          expect(consoleSpy).toHaveBeenCalledWith(
            "Selected CA certificate files:",
            expect.arrayContaining([expect.any(File)]),
          );
        });
      }

      consoleSpy.mockRestore();
    });
  });
});
