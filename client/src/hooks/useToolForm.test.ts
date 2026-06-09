import { describe, it, expect, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
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
      expect(result.current.requestType).toBe("GET");
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

  describe("getFormData – OAuth config", () => {
    it("includes oauth_config with client_credentials grant type", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("client_credentials");
        result.current.setOAuthClientId("client-123");
        result.current.setOAuthClientSecret("secret-abc");
        result.current.setOAuthTokenUrl("https://auth.example.com/token");
        result.current.setOAuthIssuerUrl("https://auth.example.com");
        result.current.setOAuthScopes("read write");
        result.current.setOAuthStoreTokens(false);
        result.current.setOAuthAutoRefresh(false);
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("oauth");
      expect(payload.tool.oauth_config).toMatchObject({
        grant_type: "client_credentials",
        client_id: "client-123",
        client_secret: "secret-abc",
        token_url: "https://auth.example.com/token",
        issuer: "https://auth.example.com",
        scopes: ["read", "write"],
        store_tokens: false,
        auto_refresh: false,
      });
    });

    it("includes oauth_config with authorization_code grant type", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("authorization_code");
        result.current.setOAuthClientId("client-456");
        result.current.setOAuthClientSecret("secret-xyz");
        result.current.setOAuthTokenUrl("https://auth.example.com/token");
        result.current.setOAuthAuthorizationUrl("https://auth.example.com/authorize");
        result.current.setOAuthRedirectUri("https://myapp.example.com/callback");
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("oauth");
      expect(payload.tool.oauth_config).toMatchObject({
        grant_type: "authorization_code",
        client_id: "client-456",
        token_url: "https://auth.example.com/token",
        authorization_url: "https://auth.example.com/authorize",
        redirect_uri: "https://myapp.example.com/callback",
      });
    });

    it("includes oauth_config with password grant type", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("oauth");
        result.current.setOAuthGrantType("password");
        result.current.setOAuthClientId("client-789");
        result.current.setOAuthClientSecret("secret-pass");
        result.current.setOAuthTokenUrl("https://auth.example.com/token");
        result.current.setOAuthUsername("user@example.com");
        result.current.setOAuthPassword("userpass");
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("oauth");
      expect(payload.tool.oauth_config).toMatchObject({
        grant_type: "password",
        client_id: "client-789",
        token_url: "https://auth.example.com/token",
        username: "user@example.com",
        password: "userpass",
      });
    });

    it("omits oauth_config when authType is not oauth", () => {
      const { result } = renderHook(() => useToolForm());

      act(() => {
        result.current.setName("my-tool");
        result.current.setUrl("https://api.example.com/endpoint");
        result.current.setAuthType("bearer");
        result.current.setBearerToken("tok-abc");
      });

      const payload = result.current.getFormData();

      expect(payload.tool.auth_type).toBe("bearer");
      expect(payload.tool.oauth_config).toBeUndefined();
      expect(payload.tool.auth_token).toBe("tok-abc");
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
    it("strips control characters from custom header key and value", async () => {
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
