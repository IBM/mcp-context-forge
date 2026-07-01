import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import { ResourceForm } from "./ResourceForm";

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
      const user = userEvent.setup();
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));
      expect(onToggle).toHaveBeenCalledOnce();
    });
  });

  describe("Validation", () => {
    it("shows required field errors on submit with empty fields", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(3);
      });
    });

    it("shows uri error when uri is missing", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByText(/URI is required/i)).toBeInTheDocument();
      });
    });

    it("shows content error when content is missing", async () => {
      const user = userEvent.setup();
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

      const user = userEvent.setup();
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
      const user = userEvent.setup();
      renderForm({ onSuccess });

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    });

    it("shows submitError above submit button on API failure", async () => {
      server.use(
        http.post("*/resources", () =>
          HttpResponse.json({ detail: "URI already exists" }, { status: 409 }),
        ),
      );

      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/URI/), "resource://example/path");
      await user.type(screen.getByLabelText(/Name/), "My Resource");
      await user.type(screen.getByLabelText(/Content/), "content");
      await user.click(screen.getByRole("button", { name: /Add resources/i }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
    });
  });
});
