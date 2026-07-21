import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import type { ResourceRead } from "@/generated/types";
import { ResourceForm } from "./ResourceForm";

function createMockResource(
  overrides: Partial<NonNullable<ResourceRead> & { content?: string }> = {},
): NonNullable<ResourceRead> & { content?: string } {
  return {
    id: "resource-1",
    uri: "resource://example/path",
    name: "Existing Resource",
    description: "existing description",
    mimeType: "text/plain",
    size: 10,
    createdAt: "2024-01-01T00:00:00Z",
    updatedAt: "2024-01-01T00:00:00Z",
    enabled: true,
    tags: ["a", "b"],
    visibility: "public",
    content: "existing content",
    ...overrides,
  };
}

function renderForm(props: Partial<React.ComponentProps<typeof ResourceForm>> = {}) {
  return render(
    <AuthProvider>
      <I18nProvider>
        <ResourceForm isOpen={true} onToggle={vi.fn()} onSuccess={vi.fn()} {...props} />
      </I18nProvider>
    </AuthProvider>,
  );
}

describe("ResourceForm", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.post("*/resources", () =>
        HttpResponse.json({ id: "resource-1", name: "My Resource" }, { status: 201 }),
      ),
    );
  });

  describe("Rendering", () => {
    it("renders all form fields", () => {
      renderForm();
      expect(screen.getByLabelText(/URI/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Name/)).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/optional description/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/MIME Type/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Content/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Visibility/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Tags/)).toBeInTheDocument();
    });

    it("renders submit and cancel buttons", () => {
      renderForm();
      expect(screen.getByRole("button", { name: /Add resources/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
    });

    it("returns null when isOpen is false", () => {
      const { container } = renderForm({ isOpen: false });
      expect(container.firstChild).toBeNull();
    });
  });

  describe("Cancel button", () => {
    it("calls onToggle when Cancel button clicked", async () => {
      const onToggle = vi.fn();
      const user = userEvent.setup({ delay: null });
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));
      expect(onToggle).toHaveBeenCalledOnce();
    });
  });

  describe("Validation", () => {
    it("shows required field errors on submit with empty fields", async () => {
      const user = userEvent.setup({ delay: null });
      renderForm();

      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(3);
      });
    });

    it("shows uri error when uri is missing", async () => {
      const user = userEvent.setup({ delay: null });
      renderForm();

      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByText(/URI is required/i)).toBeInTheDocument();
      });
    });

    it("shows content error when content is missing", async () => {
      const user = userEvent.setup({ delay: null });
      renderForm();

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByText(/Content is required/i)).toBeInTheDocument();
      });
    });
  });

  describe("Submission", () => {
    it("disables submit button while submitting", async () => {
      server.use(
        http.post("*/resources", async () => {
          await new Promise((resolve) => setTimeout(resolve, 100));
          return HttpResponse.json({ id: "resource-1" }, { status: 201 });
        }),
      );

      const user = userEvent.setup({ delay: null });
      renderForm();

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");

      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Adding.../i })).toBeDisabled();
      });
    });

    it("calls onSuccess after successful submit", async () => {
      const onSuccess = vi.fn();
      const user = userEvent.setup({ delay: null });
      renderForm({ onSuccess });

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    });

    it("fills out optional fields correctly", async () => {
      const onSuccess = vi.fn();
      const user = userEvent.setup({ delay: null });
      renderForm({ onSuccess });

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.type(screen.getByPlaceholderText(/optional description/i), "Some description");
      await user.type(screen.getByLabelText(/Tags/), "tag1, tag2");

      // Select MIME Type
      const mimeTypeSelect = screen.getByRole("combobox", { name: /MIME Type/i });
      await user.click(mimeTypeSelect);
      const mimeTypeOption = await screen.findByRole("option", { name: "application/json" });
      await user.click(mimeTypeOption);

      // Select Visibility
      const visibilitySelect = screen.getByRole("combobox", { name: /Visibility/i });
      await user.click(visibilitySelect);
      const visibilityOption = await screen.findByRole("option", { name: /Public/i });
      await user.click(visibilityOption);

      // Wait for select portal to close so it doesn't block clicks
      await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());

      await user.click(screen.getByRole("button", { name: /Add resources/i }));
      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    });

    it("shows submitError above submit button on API failure", async () => {
      server.use(
        http.post("*/resources", () =>
          HttpResponse.json({ detail: "URI already exists" }, { status: 409 }),
        ),
      );

      const user = userEvent.setup({ delay: null });
      renderForm();

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByText(/URI already exists/i)).toBeInTheDocument();
      });
    });
  });

  describe("Edit mode (resource prop provided)", () => {
    beforeEach(() => {
      server.use(
        http.put("*/resources/resource-1", () =>
          HttpResponse.json({ id: "resource-1", name: "Existing Resource" }, { status: 200 }),
        ),
      );
    });

    it("shows 'Edit resource' heading instead of 'Add resources'", () => {
      renderForm({ resource: createMockResource() });
      expect(screen.getByRole("heading", { name: "Edit resource" })).toBeInTheDocument();
    });

    it("moves focus to the heading on mount so opening the form is announced", () => {
      renderForm({ resource: createMockResource() });
      expect(screen.getByRole("heading", { name: "Edit resource" })).toHaveFocus();
    });

    it("shows 'Update resource' submit button instead of 'Add resources'", () => {
      renderForm({ resource: createMockResource() });
      expect(screen.getByRole("button", { name: "Update resource" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Add resources/i })).not.toBeInTheDocument();
    });

    it("pre-populates name, uri, description, mimeType, tags, and content from the resource prop", () => {
      renderForm({ resource: createMockResource() });
      expect(screen.getByLabelText(/^Name/)).toHaveValue("Existing Resource");
      expect(screen.getByLabelText(/^URI/)).toHaveValue("resource://example/path");
      expect(screen.getByPlaceholderText(/optional description/i)).toHaveValue(
        "existing description",
      );
      expect(screen.getByLabelText(/Content/)).toHaveValue("existing content");
      expect(screen.getByLabelText(/Tags/)).toHaveValue("a, b");
    });

    it("calls onSuccess after a successful resource update", async () => {
      const user = userEvent.setup();
      const onSuccess = vi.fn();
      renderForm({ resource: createMockResource(), onSuccess });

      await user.click(screen.getByRole("button", { name: "Update resource" }));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledOnce();
      });
    });
  });
});
