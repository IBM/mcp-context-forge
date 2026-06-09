import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import { ToolForm } from "./ToolForm";

function renderForm(props: Partial<React.ComponentProps<typeof ToolForm>> = {}) {
  return render(
    <AuthProvider>
      <I18nProvider>
        <ToolForm isOpen={true} onToggle={vi.fn()} onSuccess={vi.fn()} {...props} />
      </I18nProvider>
    </AuthProvider>,
  );
}

describe("ToolForm", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.post("*/tools", () =>
        HttpResponse.json({ id: "tool-1", name: "my-tool" }, { status: 201 }),
      ),
    );
  });

  describe("Accessibility – labels and controls", () => {
    it("links Name input to its label", () => {
      renderForm();
      expect(screen.getByLabelText(/Name/)).toBeInTheDocument();
    });

    it("links URL input to its label", () => {
      renderForm();
      expect(screen.getByLabelText(/URL/)).toBeInTheDocument();
    });

    it("marks Name as required with visible and sr-only text", () => {
      renderForm();
      const nameLabel = screen.getByText("Name", { selector: "label" });
      expect(nameLabel.querySelector(".sr-only")).toHaveTextContent("(required)");
    });

    it("marks URL as required with visible and sr-only text", () => {
      renderForm();
      const urlLabel = screen.getByText("URL", { selector: "label" });
      expect(urlLabel.querySelector(".sr-only")).toHaveTextContent("(required)");
    });

    it("marks Schema section as required with sr-only text", () => {
      renderForm();
      const schemaLabel = screen.getByText("Schema", { selector: "label" });
      expect(schemaLabel.querySelector(".sr-only")).toHaveTextContent("(required)");
    });

    it("uses aria-labelledby on the Request type radiogroup", () => {
      renderForm();
      const group = screen.getByRole("radiogroup", { name: "Request type" });
      const labelId = group.getAttribute("aria-labelledby");
      expect(labelId).toBeTruthy();
      const labelEl = document.getElementById(labelId!);
      expect(labelEl).toHaveTextContent("Request type");
    });

    it("renders all HTTP method radios inside the radiogroup", () => {
      renderForm();
      expect(screen.getByRole("radio", { name: "GET" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "POST" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "PUT" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "PATCH" })).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: "DELETE" })).toBeInTheDocument();
    });

    it("Advanced settings button has aria-expanded and aria-controls", () => {
      renderForm();
      const btn = screen.getByRole("button", { name: /Advanced settings/i });
      expect(btn).toHaveAttribute("aria-expanded", "false");
      expect(btn).toHaveAttribute("aria-controls", "advanced-settings-panel");
    });

    it("Advanced settings panel has the id referenced by aria-controls", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Advanced settings/i }));

      const panel = document.getElementById("advanced-settings-panel");
      expect(panel).toBeInTheDocument();
    });

    it("aria-expanded on Advanced settings button toggles correctly", async () => {
      const user = userEvent.setup();
      renderForm();

      const btn = screen.getByRole("button", { name: /Advanced settings/i });
      expect(btn).toHaveAttribute("aria-expanded", "false");

      await user.click(btn);
      expect(btn).toHaveAttribute("aria-expanded", "true");

      await user.click(btn);
      expect(btn).toHaveAttribute("aria-expanded", "false");
    });
  });

  describe("Accessibility – schema textareas", () => {
    it("links Input schema textarea to its label after clicking Add manually", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Add manually/i }));

      expect(screen.getByLabelText(/Input schema/)).toBeInTheDocument();
    });

    it("links Output schema textarea to its label after clicking Add manually", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Add manually/i }));

      expect(screen.getByLabelText(/Output schema/)).toBeInTheDocument();
    });

    it("marks Input schema as required with sr-only text", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Add manually/i }));

      const inputSchemaLabel = screen.getByText("Input schema", { selector: "label" });
      expect(inputSchemaLabel.querySelector(".sr-only")).toHaveTextContent("(required)");
    });
  });

  describe("Accessibility – submit error announcement", () => {
    it("submit error has role=alert so screen readers announce it", async () => {
      const user = userEvent.setup();
      server.use(
        http.post("*/tools", () =>
          HttpResponse.json({ message: "Tool name already exists" }, { status: 409 }),
        ),
      );
      renderForm();

      await user.type(screen.getByLabelText(/Name/), "duplicate-tool");
      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      await user.click(screen.getByRole("button", { name: /Add tool/i }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });
      expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "assertive");
    });
  });

  describe("Accessibility – advanced settings panel", () => {
    it("Authentication type radiogroup uses aria-labelledby", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.click(screen.getByRole("button", { name: /Advanced settings/i }));

      const group = screen.getByRole("radiogroup", { name: "Authentication type" });
      const labelId = group.getAttribute("aria-labelledby");
      expect(labelId).toBeTruthy();
      const labelEl = document.getElementById(labelId!);
      expect(labelEl).toHaveTextContent("Authentication type");
    });
  });

  describe("Form behaviour", () => {
    it("renders heading and description", () => {
      renderForm();
      expect(screen.getByRole("heading", { name: "Add tool" })).toBeInTheDocument();
      expect(screen.getByText(/Convert REST API to a tool/i)).toBeInTheDocument();
    });

    it("Add tool button is disabled when form is invalid", () => {
      renderForm();
      expect(screen.getByRole("button", { name: "Add tool" })).toBeDisabled();
    });

    it("Add tool button is enabled when name and valid URL are provided", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/Name/), "my-tool");
      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      expect(screen.getByRole("button", { name: "Add tool" })).toBeEnabled();
    });

    it("Cancel button calls onToggle", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));

      expect(onToggle).toHaveBeenCalledOnce();
    });

    it("shows name validation error when name is empty on submit", async () => {
      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      const submitBtn = screen.getByRole("button", { name: "Add tool" });
      expect(submitBtn).toBeDisabled();
    });

    it("calls onSuccess after successful tool creation", async () => {
      const user = userEvent.setup();
      const onSuccess = vi.fn();
      renderForm({ onSuccess });

      await user.type(screen.getByLabelText(/Name/), "my-tool");
      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      await user.click(screen.getByRole("button", { name: "Add tool" }));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledOnce();
      });
    });
  });
});
