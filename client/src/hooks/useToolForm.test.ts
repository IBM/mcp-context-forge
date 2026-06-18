import { describe, it, expect, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { FormEvent } from "react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useToolForm } from "./useToolForm";

describe("useToolForm", () => {
  describe("Initial State", () => {
    it("initializes with default values", () => {
      const { result } = renderHook(() => useToolForm());

      expect(result.current.name).toBe("");
      expect(result.current.url).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.requestType).toBe("POST");
      expect(result.current.advancedOpen).toBe(false);
      expect(result.current.visibility).toBe("public");
      expect(result.current.teamId).toBe("");
      expect(result.current.authType).toBe("none");
      expect(result.current.authUsername).toBe("");
      expect(result.current.authPassword).toBe("");
      expect(result.current.bearerToken).toBe("");
      expect(result.current.customHeaders).toEqual([]);
      expect(result.current.errors).toEqual({});
      expect(result.current.isValid).toBe(false);
    });
  });

  describe("generateSchema – URL protocol validation", () => {
    it("does not call the API for a javascript: URL", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ success: false }, { status: 400 }));
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("javascript:alert(1)");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      expect(postSpy).not.toHaveBeenCalled();
      expect(result.current.isGeneratingSchema).toBe(false);
    });

    it("does not call the API for an ftp: URL", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ success: false }, { status: 400 }));
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("ftp://files.example.com/spec.json");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      expect(postSpy).not.toHaveBeenCalled();
    });

    it("does not call the API for a malformed URL", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ success: false }, { status: 400 }));
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("not-a-url");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      expect(postSpy).not.toHaveBeenCalled();
    });

    it("calls the API for valid http URL", async () => {
      const postSpy = vi.fn(() =>
        HttpResponse.json({
          success: true,
          input_schema: { type: "object", properties: {} },
          output_schema: null,
          message: "ok",
        }),
      );
      server.use(http.post("*/v1/tools/generate-schemas-from-openapi", postSpy));

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("http://api.example.com/openapi.json");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      await waitFor(() => expect(postSpy).toHaveBeenCalledOnce());
    });

    it("excludes openApiSpecUrl with non-http protocol from the request payload", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            success: true,
            input_schema: null,
            output_schema: null,
            message: "ok",
          });
        }),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setOpenApiSpecUrl("ftp://badscheme.example.com/spec.json");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody?.openapi_url).toBeUndefined();
    });

    it("includes valid https openApiSpecUrl in the request payload", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            success: true,
            input_schema: null,
            output_schema: null,
            message: "ok",
          });
        }),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setOpenApiSpecUrl("https://api.example.com/openapi.json");
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody?.openapi_url).toBe("https://api.example.com/openapi.json");
    });
  });

  describe("generateSchema – custom header sanitization", () => {
    it("strips control characters from custom header key and value (multi-header path)", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            success: true,
            input_schema: null,
            output_schema: null,
            message: "ok",
          });
        }),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-Api-Key\r\nInjected: evil", value: "value\x00with\x1fnull" },
        ]);
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      const headers = capturedBody?.auth_headers as Array<{ key: string; value: string }>;
      expect(headers[0].key).toBe("X-Api-KeyInjected: evil");
      expect(headers[0].value).toBe("valuewithnull");
    });

    it("strips control characters from custom header key and value (single-header path)", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.post("*/v1/tools/generate-schemas-from-openapi", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({
            success: true,
            input_schema: null,
            output_schema: null,
            message: "ok",
          });
        }),
      );

      const { result } = renderHook(() => useToolForm({ maxCustomHeaders: 1 }));

      act(() => {
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-Api-Key\r\nInjected: evil", value: "value\x00with\x1fnull" },
        ]);
      });

      await act(async () => {
        await result.current.generateSchema();
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody?.auth_header_key).toBe("X-Api-KeyInjected: evil");
      expect(capturedBody?.auth_header_value).toBe("valuewithnull");
    });
  });

  describe("getFormData – custom headers", () => {
    it("sends all non-empty custom headers as auth_headers array when maxCustomHeaders is unset", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-First", value: "value1" },
          { id: "2", key: "X-Second", value: "value2" },
        ]);
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("authheaders");
      expect(payload.tool.auth_headers).toHaveLength(2);
      expect(payload.tool.auth_headers).toEqual([
        { key: "X-First", value: "value1" },
        { key: "X-Second", value: "value2" },
      ]);
    });

    it("omits headers with empty keys from auth_headers", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-Valid", value: "v1" },
          { id: "2", key: "  ", value: "v2" },
        ]);
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_headers).toHaveLength(1);
      expect(payload.tool.auth_headers![0].key).toBe("X-Valid");
    });

    it("sanitizes custom header keys and values in getFormData (multi-header path)", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-Api-Key\r\nInjected: evil", value: "value\x00with\x1fnull" },
        ]);
      });

      const payload = result.current.getFormData();
      const headers = payload.tool.auth_headers!;

      expect(headers[0].key).toBe("X-Api-KeyInjected: evil");
      expect(headers[0].value).toBe("valuewithnull");
    });

    it("sends authHeaderKey and authHeaderValue when maxCustomHeaders is 1", () => {
      const { result } = renderHook(() => useToolForm({ maxCustomHeaders: 1 }));

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([{ id: "1", key: "X-Api-Key", value: "secret" }]);
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("authheaders");
      expect(payload.tool.auth_header_key).toBe("X-Api-Key");
      expect(payload.tool.auth_header_value).toBe("secret");
      expect(payload.tool.auth_headers).toBeUndefined();
    });

    it("sanitizes custom header key and value in getFormData (single-header path)", () => {
      const { result } = renderHook(() => useToolForm({ maxCustomHeaders: 1 }));

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("custom");
        result.current.setCustomHeaders([
          { id: "1", key: "X-Api-Key\r\nInjected: evil", value: "value\x00with\x1fnull" },
        ]);
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_header_key).toBe("X-Api-KeyInjected: evil");
      expect(payload.tool.auth_header_value).toBe("valuewithnull");
      expect(payload.tool.auth_headers).toBeUndefined();
    });
  });

  describe("isValid – extended validation", () => {
    it("is false when inputSchema is invalid JSON", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setInputSchema("{not valid json");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("is false when outputSchema is invalid JSON", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setOutputSchema("[unclosed");
      });

      expect(result.current.isValid).toBe(false);
    });

    it("truncates description exceeding 500 characters in getFormData", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setDescription("a".repeat(501));
      });

      // sanitizeString truncates before the Zod max check, so isValid stays true
      expect(result.current.isValid).toBe(true);
      const payload = result.current.getFormData();
      expect(payload.tool.description?.length).toBe(500);
    });

    it("is true with valid name, url, and valid schema JSON", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setInputSchema(JSON.stringify({ type: "object" }));
      });

      expect(result.current.isValid).toBe(true);
    });
  });

  describe("handleSubmit – error surfacing", () => {
    it("surfaces string detail from HTTPException (e.g. 409 conflict)", async () => {
      server.use(
        http.post("*/tools", () =>
          HttpResponse.json({ detail: "Tool name already exists" }, { status: 409 }),
        ),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      expect(result.current.errors.submit).toBe("Tool name already exists");
    });

    it("surfaces formatted message from Pydantic validation array detail (422)", async () => {
      server.use(
        http.post("*/tools", () =>
          HttpResponse.json(
            { detail: [{ loc: ["body", "tool", "name"], msg: "Field required" }] },
            { status: 422 },
          ),
        ),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      expect(result.current.errors.submit).toBe("name: Field required");
    });

    it("surfaces message field from 403 ORJSONResponse", async () => {
      server.use(
        http.post("*/tools", () =>
          HttpResponse.json(
            { message: "Public-only tokens cannot create team or private resources." },
            { status: 403 },
          ),
        ),
      );

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      expect(result.current.errors.submit).toBe(
        "Public-only tokens cannot create team or private resources.",
      );
    });
  });

  describe("Form Validation", () => {
    it("requires name and url", () => {
      const { result } = renderHook(() => useToolForm());

      let isValid: boolean;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid!).toBe(false);
      expect(result.current.errors.name).toBeDefined();
      expect(result.current.errors.url).toBeDefined();
    });

    it("rejects non-http/https URL", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("ftp://files.example.com");
      });

      act(() => {
        result.current.validateForm();
      });

      expect(result.current.errors.url).toBe("URL must start with http:// or https://");
    });

    it("requires teamId when visibility is team", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setVisibility("team");
      });

      act(() => {
        result.current.validateForm();
      });

      expect(result.current.errors.teamId).toBeDefined();
    });

    it("passes with valid name and https url", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
      });

      let isValid: boolean;
      act(() => {
        isValid = result.current.validateForm();
      });

      expect(isValid!).toBe(true);
      expect(result.current.errors).toEqual({});
    });
  });

  describe("Edit mode (toolId provided)", () => {
    it("initializes form state from initialValues", () => {
      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "existing-tool",
            url: "https://api.example.com",
            requestType: "GET",
            visibility: "private",
            authType: "bearer",
            bearerToken: "my-token",
          },
        }),
      );

      expect(result.current.name).toBe("existing-tool");
      expect(result.current.url).toBe("https://api.example.com");
      expect(result.current.requestType).toBe("GET");
      expect(result.current.visibility).toBe("private");
      expect(result.current.authType).toBe("bearer");
      expect(result.current.bearerToken).toBe("my-token");
    });

    it("sends PUT request when toolId is provided", async () => {
      const putSpy = vi.fn(() => HttpResponse.json({ id: "tool-1" }, { status: 200 }));
      server.use(http.put("*/tools/tool-1", putSpy));

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
          },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(putSpy).toHaveBeenCalledOnce());
    });

    it("sends a nested auth object with empty strings to clear credentials when auth type is none", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.put("*/tools/tool-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "tool-1" }, { status: 200 });
        }),
      );

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
            authType: "basic",
            authUsername: "admin",
            authPassword: "*****", // pragma: allowlist secret
          },
        }),
      );

      // User switches auth off
      act(() => {
        result.current.setAuthType("none");
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      // Nested auth object with EMPTY STRINGS (not null) clears the stored credential
      expect(capturedBody?.auth).toEqual({ authType: "", authValue: "" });
      // No flat auth_* fields that would trigger the assemble_auth path
      expect(capturedBody?.auth_type).toBeUndefined();
      expect(capturedBody?.auth_password).toBeUndefined();
    });

    it("omits auth fields on update when the secret is still masked (unchanged)", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.put("*/tools/tool-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "tool-1" }, { status: 200 });
        }),
      );

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
            authType: "basic",
            authUsername: "admin",
            authPassword: "*****", // masked value from the server // pragma: allowlist secret
          },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      // Masked secret must not be round-tripped — no auth fields at all
      expect(capturedBody?.auth_type).toBeUndefined();
      expect(capturedBody?.auth_password).toBeUndefined();
      expect(capturedBody?.auth_username).toBeUndefined();
    });

    it("sends auth fields on update when the user enters a new basic password", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.put("*/tools/tool-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "tool-1" }, { status: 200 });
        }),
      );

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
            authType: "basic",
            authUsername: "admin",
            authPassword: "*****", // pragma: allowlist secret
          },
        }),
      );

      act(() => {
        result.current.setAuthPassword("new-secret"); // pragma: allowlist secret
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody?.auth_type).toBe("basic");
      expect(capturedBody?.auth_password).toBe("new-secret"); // pragma: allowlist secret
      expect(capturedBody?.auth_username).toBe("admin");
    });

    it("sends auth fields on update when the user enters a new bearer token", async () => {
      let capturedBody: Record<string, unknown> | undefined;
      server.use(
        http.put("*/tools/tool-1", async ({ request }) => {
          capturedBody = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json({ id: "tool-1" }, { status: 200 });
        }),
      );

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
            authType: "bearer",
            bearerToken: "*****", // pragma: allowlist secret
          },
        }),
      );

      act(() => {
        result.current.setBearerToken("fresh-token"); // pragma: allowlist secret
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(capturedBody).toBeDefined());
      expect(capturedBody?.auth_type).toBe("bearer");
      expect(capturedBody?.auth_token).toBe("fresh-token"); // pragma: allowlist secret
    });

    it("does not send POST request when toolId is provided", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ id: "tool-1" }, { status: 201 }));
      const putSpy = vi.fn(() => HttpResponse.json({ id: "tool-1" }, { status: 200 }));
      server.use(http.post("*/tools", postSpy));
      server.use(http.put("*/tools/tool-1", putSpy));

      const { result } = renderHook(() =>
        useToolForm({
          toolId: "tool-1",
          initialValues: {
            name: "my-tool",
            url: "https://api.example.com",
            integrationType: "REST",
            requestType: "POST",
          },
        }),
      );

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(putSpy).toHaveBeenCalledOnce());
      expect(postSpy).not.toHaveBeenCalled();
    });

    it("sends POST request when no toolId (create mode)", async () => {
      const postSpy = vi.fn(() => HttpResponse.json({ id: "tool-new" }, { status: 201 }));
      server.use(http.post("*/tools", postSpy));

      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("new-tool");
        result.current.setUrl("https://api.example.com");
      });

      await act(async () => {
        await result.current.handleSubmit({
          preventDefault: vi.fn(),
        } as unknown as FormEvent<HTMLFormElement>);
      });

      await waitFor(() => expect(postSpy).toHaveBeenCalledOnce());
    });

    it("initializes customHeaders from initialValues", () => {
      const headers = [
        { id: "1", key: "X-Api-Key", value: "secret" },
        { id: "2", key: "X-Tenant", value: "acme" },
      ];
      const { result } = renderHook(() =>
        useToolForm({ toolId: "tool-1", initialValues: { customHeaders: headers } }),
      );

      expect(result.current.customHeaders).toEqual(headers);
    });

    it("opens advanced settings when initialValues.advancedOpen is true", () => {
      const { result } = renderHook(() =>
        useToolForm({ toolId: "tool-1", initialValues: { advancedOpen: true } }),
      );

      expect(result.current.advancedOpen).toBe(true);
    });
  });

  describe("Form Reset", () => {
    it("resets all fields to defaults", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com");
        result.current.setDescription("desc");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("tok");
        result.current.setVisibility("private");
      });

      act(() => {
        result.current.resetForm();
      });

      expect(result.current.name).toBe("");
      expect(result.current.url).toBe("");
      expect(result.current.description).toBe("");
      expect(result.current.authType).toBe("none");
      expect(result.current.bearerToken).toBe("");
      expect(result.current.visibility).toBe("public");
    });
  });
});
