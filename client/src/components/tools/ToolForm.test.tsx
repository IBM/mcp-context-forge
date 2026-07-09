import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { I18nProvider } from "@/i18n";
import { AuthProvider } from "@/auth/AuthContext";
import { ToolForm } from "./ToolForm";
import type { Tool } from "@/types/tool";

function createMockTool(overrides: Partial<Tool> = {}): Tool {
  return {
    id: "tool-1",
    name: "my-tool",
    originalName: "my-tool",
    customName: "my-tool",
    customNameSlug: "my-tool",
    gatewaySlug: "",
    gatewayId: null,
    description: null,
    integrationType: "REST",
    requestType: "POST",
    enabled: true,
    reachable: true,
    deprecated: false,
    tags: [],
    headers: {},
    inputSchema: { type: "object", properties: {} },
    annotations: {},
    jsonpathFilter: null,
    auth: null,
    createdAt: "2026-01-01T00:00:00",
    updatedAt: "2026-01-02T00:00:00",
    url: "https://api.example.com/endpoint",
    visibility: "public",
    ...overrides,
  };
}

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
      expect(screen.getByRole("heading", { name: /Add tool/i })).toBeInTheDocument();
      expect(screen.getByText(/Convert REST API to a tool/i)).toBeInTheDocument();
    });

    it("Cancel button calls onToggle", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /Cancel/i }));

      expect(onToggle).toHaveBeenCalledOnce();
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

    it("calls onToggle after successful tool creation if onSuccess is absent", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      // Render WITHOUT onSuccess, to hit the fallback
      render(
        <AuthProvider>
          <I18nProvider>
            <ToolForm isOpen={true} onToggle={onToggle} />
          </I18nProvider>
        </AuthProvider>,
      );

      await user.type(screen.getByLabelText(/Name/), "my-tool");
      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      await user.click(screen.getByRole("button", { name: "Add tool" }));

      await waitFor(() => {
        expect(onToggle).toHaveBeenCalledOnce();
      });
    });

    it("copies schemas to clipboard and shows copied message", async () => {
      const user = userEvent.setup();
      const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);

      renderForm();

      // Ensure manual schema mode
      await user.click(screen.getByRole("button", { name: /Add manually/i }));

      const copyInputBtn = screen.getByLabelText(/Copy input schema/i);
      await user.click(copyInputBtn);

      expect(clipboardSpy).toHaveBeenCalledWith('{\n  "type": "object",\n  "properties": {}\n}');

      const copyOutputBtn = screen.getByLabelText(/Copy output schema/i);
      await user.click(copyOutputBtn);

      expect(clipboardSpy).toHaveBeenCalledTimes(2);

      clipboardSpy.mockRestore();
    });
  });

  describe("Schema generation from OpenAPI", () => {
    it("shows the 'Generated from' caption with the returned spec_url", async () => {
      const user = userEvent.setup();
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", () =>
          HttpResponse.json({
            success: true,
            input_schema: { type: "object", properties: {} },
            output_schema: null,
            spec_url: "https://api.example.com/openapi.json",
            message: "ok",
          }),
        ),
      );
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com/endpoint");
      await user.click(screen.getByRole("button", { name: /Generate/i }));

      await waitFor(() =>
        expect(
          screen.getByText(/Generated from https:\/\/api\.example\.com\/openapi\.json/i),
        ).toBeInTheDocument(),
      );
    });

    it("confirms before overwriting an existing manually-entered schema", async () => {
      const user = userEvent.setup();
      const postSpy = vi.fn(() =>
        HttpResponse.json({
          success: true,
          input_schema: { type: "object", properties: {} },
          output_schema: null,
          spec_url: "https://api.example.com/openapi.json",
          message: "ok",
        }),
      );
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com/endpoint");
      // Seed a manual schema so the generate button must confirm first.
      await user.click(screen.getByRole("button", { name: /Add manually/i }));

      await user.click(screen.getByRole("button", { name: /Generate/i }));

      // The API is not called until the user confirms the overwrite.
      const dialog = await screen.findByRole("dialog");
      expect(postSpy).not.toHaveBeenCalled();

      await user.click(within(dialog).getByRole("button", { name: /Replace/i }));

      await waitFor(() => expect(postSpy).toHaveBeenCalledOnce());
    });

    it("does not confirm when both schema fields are empty", async () => {
      const user = userEvent.setup();
      const postSpy = vi.fn(() =>
        HttpResponse.json({
          success: true,
          input_schema: { type: "object", properties: {} },
          output_schema: null,
          spec_url: "https://api.example.com/openapi.json",
          message: "ok",
        }),
      );
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com/endpoint");
      await user.click(screen.getByRole("button", { name: /Generate/i }));

      await waitFor(() => expect(postSpy).toHaveBeenCalledOnce());
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("switches the button label to Regenerate after a successful generation", async () => {
      const user = userEvent.setup();
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", () =>
          HttpResponse.json({
            success: true,
            input_schema: { type: "object", properties: {} },
            output_schema: null,
            spec_url: "https://api.example.com/openapi.json",
            message: "ok",
          }),
        ),
      );
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com/endpoint");
      await user.click(screen.getByRole("button", { name: /^Generate$/i }));

      await waitFor(() =>
        expect(screen.getByRole("button", { name: /Regenerate/i })).toBeInTheDocument(),
      );
    });

    it("announces a generation failure via an assertive alert", async () => {
      const user = userEvent.setup();
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", () =>
          HttpResponse.json(
            { success: false, message: "OpenAPI spec server returned HTTP 502" },
            { status: 502 },
          ),
        ),
      );
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com/endpoint");
      await user.click(screen.getByRole("button", { name: /Generate/i }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveAttribute("aria-live", "assertive");
      expect(alert).toHaveTextContent(/Couldn't fetch the OpenAPI spec/i);
    });
  });

  describe("Edit mode (tool prop provided)", () => {
    beforeEach(() => {
      server.use(
        http.put("*/tools/:id", () =>
          HttpResponse.json({ id: "tool-1", name: "my-tool" }, { status: 200 }),
        ),
      );
    });

    it("shows 'Edit tool' heading instead of 'Add tool'", () => {
      renderForm({ tool: createMockTool() });
      expect(screen.getByRole("heading", { name: "Edit tool" })).toBeInTheDocument();
    });

    it("shows 'Update tool' submit button instead of 'Add tool'", () => {
      renderForm({ tool: createMockTool() });
      expect(screen.getByRole("button", { name: "Update tool" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Add tool/i })).not.toBeInTheDocument();
    });

    it("pre-populates name from tool.customName", () => {
      renderForm({ tool: createMockTool({ customName: "my-custom-tool" }) });
      expect(screen.getByLabelText(/Name/)).toHaveValue("my-custom-tool");
    });

    it("pre-populates URL from tool", () => {
      renderForm({ tool: createMockTool({ url: "https://api.example.com/v2" }) });
      expect(screen.getByLabelText(/URL/)).toHaveValue("https://api.example.com/v2");
    });

    it("hides request type radio group for MCP tools", () => {
      renderForm({
        tool: createMockTool({ integrationType: "MCP", requestType: "STREAMABLEHTTP" }),
      });
      expect(screen.queryByRole("radiogroup", { name: "Request type" })).not.toBeInTheDocument();
    });

    it("shows request type radio group for REST tools", () => {
      renderForm({ tool: createMockTool({ integrationType: "REST", requestType: "POST" }) });
      expect(screen.getByRole("radiogroup", { name: "Request type" })).toBeInTheDocument();
    });

    it("shows the Generate button when editing a REST tool", () => {
      renderForm({ tool: createMockTool({ integrationType: "REST", requestType: "POST" }) });
      expect(screen.getByRole("button", { name: /Generate/i })).toBeInTheDocument();
    });

    it("does not show the Generate button when editing an MCP tool", () => {
      renderForm({
        tool: createMockTool({ integrationType: "MCP", requestType: "STREAMABLEHTTP" }),
      });
      expect(screen.queryByRole("button", { name: /Generate/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Regenerate/i })).not.toBeInTheDocument();
    });

    it("does not show the Add manually button when editing", () => {
      renderForm({ tool: createMockTool() });
      expect(screen.queryByRole("button", { name: /Add manually/i })).not.toBeInTheDocument();
    });

    it("always shows the input and output schema fields when editing, even with no schema", () => {
      renderForm({ tool: createMockTool() });
      expect(screen.getByLabelText(/Input schema/)).toBeInTheDocument();
      expect(screen.getByLabelText(/Output schema/)).toBeInTheDocument();
    });

    it("calls onSuccess after successful tool update", async () => {
      const user = userEvent.setup();
      const onSuccess = vi.fn();
      renderForm({ tool: createMockTool(), onSuccess });

      await user.click(screen.getByRole("button", { name: "Update tool" }));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledOnce();
      });
    });

    it("opens advanced settings automatically when tool has auth configured", () => {
      renderForm({
        tool: createMockTool({
          auth: {
            authType: "bearer",
            token: "tok",
            username: "",
            password: "",
            authHeaderKey: "",
            authHeaderValue: "",
          },
        }),
      });
      const btn = screen.getByRole("button", { name: /Advanced settings/i });
      expect(btn).toHaveAttribute("aria-expanded", "true");
    });

    it("does not open advanced settings when tool has no auth", () => {
      renderForm({ tool: createMockTool({ auth: undefined }) });
      const btn = screen.getByRole("button", { name: /Advanced settings/i });
      expect(btn).toHaveAttribute("aria-expanded", "false");
    });

    it("calls onToggle when cancel is clicked", async () => {
      const user = userEvent.setup();
      const onToggle = vi.fn();
      renderForm({ onToggle });

      await user.click(screen.getByRole("button", { name: /^cancel$/i }));
      expect(onToggle).toHaveBeenCalledOnce();
    });

    it("renders with a minimal tool correctly", () => {
      const minimalTool: Tool = {
        id: "tool-min",
        name: "min-tool",
        originalName: "min-tool",
        customName: "",
        customNameSlug: "min-tool",
        gatewaySlug: "",
        integrationType: "REST",
        requestType: "GET",
        enabled: true,
        reachable: true,
        tags: [],
        createdAt: "2026-01-01T00:00:00",
        updatedAt: "2026-01-02T00:00:00",
        url: undefined as any,
        visibility: undefined as any,
        auth: {
          authType: "custom",
          authHeaders: [{ key: "X-Test", value: "test" }],
        },
      };
      renderForm({ tool: minimalTool });
      expect(screen.getByDisplayValue("min-tool")).toBeInTheDocument();
    });

    it("handles tool with multiple authHeaders and object tags", () => {
      const toolWithHeadersAndTags = createMockTool({
        tags: [{ id: "t1", label: "obj-tag", color: "red" }] as any,
        auth: {
          authType: "authheaders",
          authHeaders: [
            { key: "X-Header-1", value: "val1" },
            { key: "X-Header-2", value: "val2" },
          ],
        } as any,
      });
      renderForm({ tool: toolWithHeadersAndTags });

      // The tags should be joined by ", "
      expect(screen.getByDisplayValue("obj-tag")).toBeInTheDocument();
    });

    it("handles backward compatible authHeaderKey and authHeaderValue", () => {
      const toolWithOldHeaders = createMockTool({
        auth: {
          authType: "authheaders",
          authHeaderKey: "Old-Header",
          authHeaderValue: "old-val",
        } as any,
      });
      renderForm({ tool: toolWithOldHeaders });
      expect(screen.getByDisplayValue("Old-Header")).toBeInTheDocument();
      expect(screen.getByDisplayValue("old-val")).toBeInTheDocument();
    });

    it("displays generating state when generateSchema is in progress", async () => {
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", async () => {
          await new Promise((r) => setTimeout(r, 200));
          return HttpResponse.json({ success: true, input_schema: {}, output_schema: {} });
        }),
      );
      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");
      await user.click(screen.getByRole("button", { name: /Generate/i }));

      expect(screen.getByRole("button", { name: /Generating/i })).toBeInTheDocument();
    });

    it("displays Regenerate schema when schemaMode is generated", async () => {
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", () => {
          return HttpResponse.json({ success: true, input_schema: {}, output_schema: {} });
        }),
      );
      const user = userEvent.setup();
      renderForm();

      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");
      await user.click(screen.getByRole("button", { name: /Generate/i }));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Regenerate/i })).toBeInTheDocument();
      });
    });
  });

  describe("Form Validation and aria-invalid", () => {
    it("sets aria-invalid and aria-describedby when validation fails", async () => {
      const user = userEvent.setup({ delay: null });
      renderForm();

      // Submit without entering Name and URL
      const submitBtn = screen.getByRole("button", { name: /Add tool/i });
      await user.click(submitBtn);

      // Wait for errors to appear
      await waitFor(() => {
        const nameInput = screen.getByLabelText(/Name/);
        expect(nameInput).toHaveAttribute("aria-invalid", "true");
        expect(nameInput).toHaveAttribute("aria-describedby", "name-error");

        const urlInput = screen.getByLabelText(/URL/);
        expect(urlInput).toHaveAttribute("aria-invalid", "true");
        expect(urlInput).toHaveAttribute("aria-describedby", "url-error");
      });
    });
  });

  describe("Schema Generation UI state", () => {
    it("shows generating schema text and spinner while generating", async () => {
      const user = userEvent.setup();

      // Delay schema generation so we can observe the intermediate state
      let resolveGenerate!: (value: any) => void;
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", () => {
          return new Promise((resolve) => {
            resolveGenerate = resolve;
          });
        }),
      );

      renderForm();

      // Fill valid URL to enable Generate button
      await user.type(screen.getByLabelText(/URL/), "https://api.example.com");

      const generateBtn = screen.getByRole("button", { name: /Generate/i });
      await user.click(generateBtn);

      await waitFor(() => {
        expect(screen.getByText("Generating...")).toBeInTheDocument();
      });

      resolveGenerate(
        HttpResponse.json({
          success: true,
          input_schema: { type: "object" },
          output_schema: { type: "object" },
        }),
      );
    });
  });

  describe("Copy Output Schema", () => {
    it("copies output schema to clipboard and shows Check icon", async () => {
      const user = userEvent.setup();

      // Mock clipboard
      const originalClipboard = navigator.clipboard;
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: writeTextMock },
        configurable: true,
      });

      renderForm({
        tool: createMockTool({
          outputSchema: { type: "string" },
        }),
      });

      // Find the second copy button (Output schema)
      const copyButtons = screen.getAllByRole("button", { name: /Copy output schema/i });
      const outputCopyBtn =
        copyButtons.find((btn) => btn.getAttribute("aria-label")?.includes("Copy output schema")) ||
        copyButtons[0];

      await user.click(outputCopyBtn!);

      expect(writeTextMock).toHaveBeenCalledWith('{\n  "type": "string"\n}');

      // Wait for Check icon (aria-label="Copied!") to appear
      await waitFor(() => {
        expect(screen.getByText(/copied/i)).toBeInTheDocument();
      });

      // Restore clipboard
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      });
    });
  });
});
