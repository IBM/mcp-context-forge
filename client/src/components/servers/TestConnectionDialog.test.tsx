import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestConnectionDialog } from "./TestConnectionDialog";

describe("TestConnectionDialog", () => {
  const mockOnOpenChange = vi.fn();
  const defaultProps = {
    open: true,
    onOpenChange: mockOnOpenChange,
    serverName: "Test Server",
    serverUrl: "https://example.com",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with initial state", () => {
    render(<TestConnectionDialog {...defaultProps} />);

    expect(screen.getByRole("heading", { name: /test connection/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^test connection$/i })).toBeInTheDocument();
    expect(screen.getByText(/run a test to see the response/i)).toBeInTheDocument();
  });

  it("displays all form fields", () => {
    render(<TestConnectionDialog {...defaultProps} />);

    expect(screen.getByLabelText(/^url/i)).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: /method/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/^path/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/content type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/headers/i)).toBeInTheDocument();
  });

  it("exposes HTTP methods as radio options", () => {
    render(<TestConnectionDialog {...defaultProps} />);

    expect(screen.getByRole("radio", { name: "Get" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Post" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Patch" })).toBeInTheDocument();
  });

  it("hides the body field for GET and shows it for other methods", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    // GET is selected by default — no body field.
    expect(screen.queryByLabelText(/body/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Post" }));

    expect(screen.getByLabelText(/body/i)).toBeInTheDocument();
  });

  it("shows a pending message until the test endpoint is available", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: /^test connection$/i }));

    await waitFor(() => {
      expect(screen.getByText(/api endpoint is pending/i)).toBeInTheDocument();
    });
  });

  it("requires a URL before running", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    const urlField = screen.getByLabelText(/^url/i);
    await user.clear(urlField);

    await user.click(screen.getByRole("button", { name: /^test connection$/i }));

    await waitFor(() => {
      expect(screen.getByText(/url is required/i)).toBeInTheDocument();
    });
  });

  it("rejects an invalid URL before running", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    const urlField = screen.getByLabelText(/^url/i);
    await user.clear(urlField);
    await user.type(urlField, "not-a-url");

    await user.click(screen.getByRole("button", { name: /^test connection$/i }));

    await waitFor(() => {
      expect(screen.getByText(/url must start with http/i)).toBeInTheDocument();
    });
  });

  it("validates JSON in headers field before running", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    const headersField = screen.getByLabelText(/headers/i);
    await user.clear(headersField);
    await user.type(headersField, "invalid json");

    await user.click(screen.getByRole("button", { name: /^test connection$/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid headers json/i)).toBeInTheDocument();
    });
  });

  it("validates JSON in body field before running", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    // Body is only available for non-GET methods.
    await user.click(screen.getByRole("radio", { name: "Post" }));

    const bodyField = screen.getByLabelText(/body/i);
    await user.type(bodyField, "not json");

    await user.click(screen.getByRole("button", { name: /^test connection$/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid body json/i)).toBeInTheDocument();
    });
  });

  it("does not auto-focus the pre-filled URL field on open", () => {
    render(<TestConnectionDialog {...defaultProps} />);

    // Focus is moved into the dialog (onto the title), not onto the URL input.
    expect(screen.getByLabelText(/^url/i)).not.toHaveFocus();
  });

  it("closes dialog when close is clicked", async () => {
    const user = userEvent.setup();
    render(<TestConnectionDialog {...defaultProps} />);

    // Two "Close" buttons exist: the footer button and the dialog's built-in X.
    // The footer button is rendered first in the DOM.
    const [footerClose] = screen.getAllByRole("button", { name: /^close$/i });
    await user.click(footerClose);

    expect(mockOnOpenChange).toHaveBeenCalledWith(false);
  });
});
